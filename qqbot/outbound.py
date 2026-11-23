# -*- coding: utf-8 -*-
"""出站层：气泡拆分、富消息渲染、主动发送、已发消息编号与撤回。

这一层只关心「把一段回复发出去」，不认识会话上下文：
- `send_rich` 走当前消息 matcher，用于被动回复；
- `send_to` 指定私聊/群，用于主动消息、提醒、戳一戳；
- 已发消息登记在进程内（按 base sid），供 recall_message 按编号撤回。

matcher 是 NoneBot 在消息入口才创建的运行期对象，由组合根注入。
"""
from __future__ import annotations

import asyncio
import random
import re
import time

from nonebot import get_bot, logger
from nonebot.adapters.onebot.v11 import Message, MessageSegment

import bubbles as bubbles_mod
import kook_fallback as kook_fb
import slop as slop_mod
from config import BUBBLE_DELAY, BUBBLE_MAX, BUBBLES_ON, REPLY_CHUNK
from features import social_post
from llm import strip_dsml
from richmsg import build_messages, rich_enabled

_SENT_IMAGES: dict = {}         # sid -> 这个会话已经搜图发过的直链（去重，最多 40 条）
_SENT_MSGS: dict = {}           # sid -> 发出的消息 [{label,mid,at,preview}]，撤回按编号找
_SENT_SEQ: dict = {}            # sid -> 已发出的条数（M1、M2…）

_POKE_MARK = re.compile(r"\[\[\s*poke\s*\]\]", re.I)
_PASS_RE = re.compile(r"\[\[\s*pass\s*\]\]", re.I)
_RECALL_LEGACY = re.compile(
    r"\[\[\s*(?:recall|撤回|收回)\s*(?:[:：]\s*\d+\s*)?\]\]", re.I)
# 通话页/桌宠的舞台指令（[[表情:..]]/[[动作:..]]/[[待机]] 等）到 QQ 没有渲染器，
# 留在正文里会原样发出去；发送前统一剥掉，QQ 自己的 [[face:..]] 不受影响
_STAGE_TAG = re.compile(r"\[\[\s*(表情|动作|收起|重置|待机|转头|歪头|抬头|低头|点头)\s*[:：]?\s*[^\]]*\]\]")

_get_matcher = lambda: None                              # noqa: E731  由组合根注入


def configure(get_matcher) -> None:
    """注入当前消息 matcher（被动回复的发送通道）。"""
    global _get_matcher
    _get_matcher = get_matcher


def sent_image_list(sid) -> list:
    """这个会话已发过的搜图直链（按 base sid 存，跨 epoch 也记得）。"""
    key = str(sid or "").split("#")[0]
    return _SENT_IMAGES.setdefault(key, [])


def remember_image(sid, url) -> None:
    if not url:
        return
    sent = sent_image_list(sid)
    if url not in sent:
        sent.append(url)
    if len(sent) > 40:
        del sent[:len(sent) - 40]


def sent_store(sid) -> list:
    """这个会话发出去的消息记录（label/mid/at/preview），按基础 sid 存。"""
    return _SENT_MSGS.setdefault(str(sid or "").split("#")[0], [])


def remember_sent(sid, result, preview: str = "") -> str:
    """给每条发出的消息编号（M1、M2…），撤回时按编号找回具体那条。"""
    mid = None
    if isinstance(result, dict):
        mid = result.get("message_id")
        if mid is None and isinstance(result.get("data"), dict):
            mid = result["data"].get("message_id")
    if not mid:
        return ""
    key = str(sid or "").split("#")[0]
    seq = _SENT_SEQ.get(key, 0) + 1
    _SENT_SEQ[key] = seq
    label = f"M{seq}"
    got = sent_store(sid)
    got.append({"label": label, "mid": mid, "at": time.time(),
                "preview": re.sub(r"\s+", " ", preview or "").strip()[:40]})
    now = time.time()
    _SENT_MSGS[key] = [m for m in got if now - m["at"] <= 600][-20:]
    return label


def recent_sent(sid, seconds: float = 120) -> list:
    """2 分钟内、还能撤回的消息。"""
    now = time.time()
    return [m for m in sent_store(sid) if now - m["at"] <= seconds]


def recent_hint(sid) -> str:
    """把最近发出的消息编号给前台，撤回时按编号指定具体某条。"""
    items = recent_sent(sid)[-8:]
    if not items:
        return ""
    now = time.time()
    lines = "\n".join(
        f"- {m['label']}｜{int(now - m['at'])} 秒前｜{m['preview'] or '（无文字）'}"
        for m in items)
    return (f"\n\n【你最近发出的消息（2 分钟内可撤回）】\n{lines}\n"
            "主人要你撤回时调用 recall_message 工具，target 填上面的编号（如 M8），"
            "后台会在你这条回复发出前撤回那条。不要写 [[recall]]，"
            "也不要没调用工具就说「已经撤回」。")


async def recall_label(sid: str, label: str) -> bool:
    """按编号撤回一条自己发的消息；超过 2 分钟或找不到就放弃。"""
    got = sent_store(sid)
    target = next((m for m in got if m["label"] == label), None)
    if target is None:
        logger.info(f"[jinyu] 撤回跳过 sid={sid} 编号={label} 找不到")
        return False
    if time.time() - target["at"] > 120:
        logger.info(f"[jinyu] 撤回跳过 sid={sid} 编号={label} 已超 2 分钟")
        return False
    try:
        await get_bot().delete_msg(message_id=int(target["mid"]))
    except Exception as exc:                    # noqa: BLE001  撤回失败不影响这轮说话
        logger.opt(exception=exc).info(f"[jinyu] 撤回失败 {label}: {exc}")
        return False
    got.remove(target)
    logger.info(f"[jinyu] 已撤回 {label} sid={sid} 内容={target['preview']!r}")
    return True


def msg_preview(msg, chunk: str) -> str:
    """撤回归档用的一句话摘要：文字取正文，图片/贴纸/语音只记类型。"""
    texts = []
    has_img = has_rec = has_face = False
    try:
        for seg in msg:
            kind = getattr(seg, "type", "")
            if kind == "text":
                texts.append(str((seg.data or {}).get("text") or ""))
            elif kind == "image":
                has_img = True
            elif kind == "record":
                has_rec = True
            elif kind == "face":
                has_face = True
    except TypeError:
        pass
    if has_rec:
        return "语音"
    if has_img:
        return "贴纸" if "[sticker:" in chunk else "图片"
    if has_face:
        return "表情"
    return "".join(texts)


def split_poke(reply: str) -> str:
    """剥掉 [[poke]] 标记：回戳由事件决定，不靠回复文本里的标记。"""
    if not reply:
        return ""
    return _POKE_MARK.sub("", reply).strip() if _POKE_MARK.search(reply) else reply


def is_silent(reply: str) -> bool:
    """模型选择不回话：整条只给了 [[pass]]，或干脆是空白。"""
    return not (reply or "").strip() or bool(_PASS_RE.search(reply))


def bubbles(reply: str, limit: int | None = None) -> list:
    """把一条回复按句子拆成多条气泡（规则见 core/bubbles.split）。

    富消息标记和链接整体保留；句子首尾的（动作词）单独成泡；超过上限均分，
    不再把剩余全塞进最后一条。
    """
    return bubbles_mod.split(reply, limit or BUBBLE_MAX)


async def send_rich(reply: str, sid: str = "") -> None:
    """按标记把回复渲染成文本/图片/表情/语音分段发送。

    默认按句子拆成多条气泡依次发（RP_BUBBLES=0 则合并成一条），像真人聊天
    而不是甩一整段。富消息标记 [[img:..]] 在拆分前先占位保护，不会被切断。
    sid 用来避开这个会话已经发过的搜图，主人说「再来一张」时换一张。
    """
    matcher = _get_matcher()
    reply = strip_dsml(reply)        # 兜底：DSML 工具标记不进入正常回复
    if _STAGE_TAG.search(reply):     # 舞台指令只在通话/桌宠页面有效，QQ 这边不认
        logger.info("[jinyu] 回复里混入舞台指令，发送前已剥掉")
        reply = _STAGE_TAG.sub("", reply)
    reply = split_poke(reply)
    if _RECALL_LEGACY.search(reply):       # 旧标记不再执行，只去掉避免当正文发出去
        logger.info("[jinyu] 回复里出现旧 [[recall]] 标记，已忽略；撤回应调用 recall_message")
        reply = _RECALL_LEGACY.sub("", reply)
    if not reply.strip():
        return
    exclude = sent_image_list(sid) if sid else None
    slop_mod.log(reply, sid=sid, where="reply")     # 只记日志，不改写
    chunks = bubbles(reply) if BUBBLES_ON else [reply]
    for i, chunk in enumerate(chunks):
        if i:
            await asyncio.sleep(random.uniform(*BUBBLE_DELAY))
        if not rich_enabled():
            for j in range(0, len(chunk), REPLY_CHUNK):
                piece = chunk[j:j + REPLY_CHUNK]
                remember_sent(sid, await matcher.send(piece), piece)
            continue
        for msg in await build_messages(chunk, REPLY_CHUNK, exclude, sid):
            try:
                remember_sent(sid, await matcher.send(msg), msg_preview(msg, chunk))
            except Exception as exc:          # 单个媒体段失败不影响后续文本
                logger.opt(exception=exc).warning(f"[jinyu] 媒体段发送失败: {exc}")
    if exclude is not None and len(exclude) > 40:
        del exclude[:len(exclude) - 40]


async def send_to(reply: str, user_id: int = 0, group_id: int = 0,
                  evidence: dict | None = None) -> bool:
    """往指定私聊/群发送（主动消息、戳一戳、提醒用），返回是否全部发出。

    evidence 非空时（提醒复查用）把「真的发出去了」写进去：posts 计成功发出的
    说说/签名，sent 计文本消息；只发标记没有文字也算处理完成，避免提醒反复重试。
    """
    reply = strip_dsml(reply)        # 兜底：网关把工具调用当正文吐出来时，绝不发到 QQ
    reply = split_poke(reply)
    slop_mod.log(reply, where="proactive")      # 只记日志，不改写
    reply, posts = social_post.take_social(reply)
    posted = 0
    for kind, body in posts:        # 主动消息里也能发说说；签名无法核验身份，直接丢弃
        if evidence is None:
            asyncio.create_task(social_post.run_social(kind, body, None))
            continue
        if await social_post.run_social(kind, body, None):     # 复查要等结果，才知道发没发出去
            posted += 1
    if evidence is not None and posted:
        evidence["posts"] = int(evidence.get("posts") or 0) + posted
    if not reply.strip():
        return bool(posts)          # 只有说说/签名也算处理完成，避免提醒反复重试
    try:
        bot = get_bot()
    except Exception:                 # 账号离线 / 没连上：这一条整体改走 KOOK
        bot = None
    if not rich_enabled():
        msgs = [Message(MessageSegment.text(reply[i:i + REPLY_CHUNK]))
                for i in range(0, len(reply), REPLY_CHUNK)]
    else:
        msgs = await build_messages(reply, REPLY_CHUNK)
    if bot is None:
        logger.warning("[jinyu] QQ 不在线，主动消息改走 KOOK")
        sent = False
        for msg in msgs:
            part_text, part_imgs = kook_fb.message_parts(msg)
            if await kook_fb.send(part_text, part_imgs):
                sent = True
                if evidence is not None:
                    evidence["sent"] = True
        return sent
    ok = True
    for msg in msgs:
        try:
            if group_id:
                await bot.send_group_msg(group_id=int(group_id), message=msg)
            else:
                await bot.send_private_msg(user_id=int(user_id), message=msg)
            if evidence is not None:
                evidence["sent"] = True
        except Exception as exc:              # noqa: BLE001
            logger.opt(exception=exc).warning(
                f"[jinyu] 消息发送失败 uid={user_id} gid={group_id}: {exc}")
            part_text, part_imgs = kook_fb.message_parts(msg)
            if await kook_fb.send(part_text, part_imgs):
                if evidence is not None:
                    evidence["sent"] = True
            else:
                ok = False
    return ok
