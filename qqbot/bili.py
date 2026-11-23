# -*- coding: utf-8 -*-
"""B 站层：弹幕监听、@ 我的自动回复、账号工具与 /bili 指令。

这一层只和 B 站账号/直播间打交道，不直接读组合根：
- 聊天模型指针（mw / mw_plain）、自主作息目标会话、最近图片缓存由 configure() 注入；
- `/bili` 指令的 matcher 由调用方传入，不依赖全局 matcher。
"""
from __future__ import annotations

import asyncio
import base64
import re
import time
from pathlib import Path

from nonebot import get_bot, logger
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageSegment

import bili_live
from config import (
    ADMIN,
    BILI_AT_ON,
    BILI_LIST_DAILY,
    BILI_ON,
    BILI_OWNER_UID,
    CID,
)
from linkmeta import (
    bili_digest,
    bili_list_note,
    bili_meta_by_aid,
    bili_popular,
    bili_search,
    bili_watch_brief,
    enabled as link_enabled,
    extract_urls,
    video_meta,
)
from llm import strip_dsml
from media import _extract_image_urls
from persona import PERSONA
from richmsg import download_image_ex, pick_sticker
import rp_skeleton

_bili_tool_day = {"day": "", "n": 0}
_bili_state = {"task": None, "stop": None}   # B站弹幕监听任务（同一时间只连一条）
_AT_CTX: dict = {}

_get_mw = lambda: None                                    # noqa: E731  由组合根注入
_get_mw_plain = lambda: None                              # noqa: E731
_get_autonomy_sid = lambda: ""                            # noqa: E731
_last_media: dict = {}                                    # 由组合根注入（共享同一份 dict）


def configure(*, get_mw, get_mw_plain, get_autonomy_sid, last_media) -> None:
    """注入组合根的运行期模型指针与共享状态。"""
    global _get_mw, _get_mw_plain, _get_autonomy_sid, _last_media
    _get_mw = get_mw
    _get_mw_plain = get_mw_plain
    _get_autonomy_sid = get_autonomy_sid
    _last_media = last_media


def _bili_list_ok() -> bool:
    """搜索/热门每天次数上限：防止连续翻页把 B站接口刷成风控。"""
    day = time.strftime("%Y-%m-%d")
    if _bili_tool_day["day"] != day:
        _bili_tool_day.update(day=day, n=0)
    if _bili_tool_day["n"] >= BILI_LIST_DAILY:
        return False
    _bili_tool_day["n"] += 1
    return True


def _tool_bili(args, sid, cid, ctx=None) -> str:
    """工具 bili：去B站搜索 / 看热门 / 看一条视频（元数据 + 热评 + 画面）。"""
    if not link_enabled():
        return "链接抓取已关闭（RP_LINK=0），看不了B站。"
    action = str((args or {}).get("action") or "search").strip().lower()
    query = str((args or {}).get("query") or "").strip()
    if action in ("comment", "评论", "avatar", "头像", "name", "昵称", "emotes", "表情"):
        return ("bili 只负责 search / popular / watch；"
                "发评论、换头像、改昵称请改用 bili_account（action=comment/avatar/name）。")
    if action in ("popular", "hot", "热门", "热门视频"):
        if not _bili_list_ok():
            return "今天翻B站翻得有点多，晚点再看。"
        text = bili_list_note(bili_popular(5), "B站当前热门")
        return (text + "\n想看哪条就再用一次 watch（query 填方括号里的 BV 号）。"
                if text else "没拿到热门列表（B站接口可能风控了），晚点再看。")
    if action in ("watch", "看", "视频"):
        if not query:
            return "watch 需要 query：B站链接或 BV 号。"
        if query.startswith("http"):
            url = query
        elif "bilibili.com" in query or "b23.tv" in query:
            url = "https://" + query.split("://", 1)[-1]
        else:
            url = f"https://www.bilibili.com/video/{query}"
        unlimited = rp_skeleton.lane_principal(sid) == "owner"
        return bili_watch_brief(url, unlimited=unlimited)
    if not query:
        return "search 需要 query：想看什么关键词。"
    if not _bili_list_ok():
        return "今天翻B站翻得有点多，晚点再看。"
    text = bili_list_note(bili_search(query, 5), f"B站搜索「{query}」")
    return (text + "\n想看哪条就再用一次 watch（query 填方括号里的 BV 号）。"
            if text else "没搜到结果（可能被 B站风控拦了），换个更具体的词再试。")


def _tool_bili_account(args, sid, cid, ctx=None) -> str:
    """工具 bili_account：管理瑾瑜自己的B站账号（评论 / 表情 / 头像 / 昵称）。"""
    action = str((args or {}).get("action") or "status").strip().lower()
    if action in ("status", "me", "who", "账号", "状态"):
        return bili_live.status()
    if not bili_live.can_send():
        return "B站账号还没登录：让主人在私聊发 /bili login 扫码，再来做这个。"
    if action in ("emotes", "emoji", "表情"):
        texts = bili_live.emote_texts(24)
        return ("评论区能用的B站表情（直接写进评论正文）："
                + " ".join(texts)
                + "\n直接用 [doge] 这类写法，不要换成 QQ 表情名。")
    if rp_skeleton.lane_principal(sid) != "owner":
        return "这个B站账号是主人的，只有主人本人在私聊里才能让我发评论/换头像/改昵称。"
    if action in ("comment", "评论", "留言"):
        blocked, why = bili_live.paused()
        if blocked:
            return why
        ref = str((args or {}).get("query") or "").strip()
        text = str((args or {}).get("text") or "").strip()
        if not ref:
            return "comment 需要 query：B站视频链接或 BV 号。"
        if not text:
            return "text 必填：你想留的评论正文（可以带 [doge] 这类B站表情）。"
        url, bvid, _ = _bili_video_ref(ref)
        if not url:
            return "没认出视频地址：query 要填B站链接或 BV 号。"
        try:
            meta = video_meta(url)
        except Exception:                      # noqa: BLE001 读不到 aid 就发不了
            meta = {}
        aid = int(meta.get("aid") or 0)
        if not aid:
            return "这条视频读不到 aid，评论发不了（链接可能失效或被风控）。"
        image = str((args or {}).get("image") or "").strip()
        data = b""
        if image.startswith("sticker:") or image.startswith("贴纸:"):
            tag = image.split(":", 1)[1].strip()
            path = pick_sticker(tag) if tag else None
            if path:
                try:
                    data = Path(path).read_bytes()
                except OSError:
                    data = b""
            if not data and ctx and str(ctx.get("image") or "").startswith("http"):
                data, why = download_image_ex(str(ctx["image"]))
                if not data:
                    return f"贴纸库里没有「{tag}」，本轮搜图也没拿到：{why}"
            if not data:
                return (f"贴纸库里没有「{tag}」合适的图。可以先 search_image 找一张，"
                        "再调 comment；或者改发文字评论。")
        elif image.startswith("http"):
            data, why = download_image_ex(image)
            if not data:
                return f"图片没拿到：{why}。带图评论需要一张能下载的图。"
        elif image:
            return "image 只接受 http 图片链接、sticker:标签，或留空用本轮搜图。"
        elif ctx and str(ctx.get("image") or "").startswith("http"):
            data, why = download_image_ex(str(ctx["image"]))
            if not data:
                return f"本轮搜图没拿到：{why}。可以让主人发一张，或改发文字评论。"
        if data:
            ok, info = bili_live.post_note_comment(
                aid, text, data, str(meta.get("bvid") or bvid), title=text)
            if ok:
                return f"带图评论已发（视频笔记 {info}）"
            return info
        ok, info = bili_live.post_comment(aid, text, str(meta.get("bvid") or bvid))
        if ok:
            return f"评论已发出：{info}"
        return info
    if action in ("avatar", "头像", "换头像"):
        blocked, why = bili_live.paused()
        if blocked:
            return why
        image = str((args or {}).get("image") or "").strip()
        url = image if image.startswith("http") else (_last_media.get(sid) or "")
        if not url:
            return "没有可用的图片：先让主人发一张图，再说「换成这个头像」。"
        data, why = download_image_ex(url)
        if not data:
            return f"图片没拿到：{why}。让主人重新发一张清晰的正方形图。"
        ok, info = bili_live.set_avatar(data)
        return f"头像已换：{info}" if ok else info
    if action in ("name", "昵称", "改名"):
        blocked, why = bili_live.paused()
        if blocked:
            return why
        name = str((args or {}).get("name") or "").strip()
        if not name:
            return "name 必填：想改成什么昵称（最多 16 个字，B站扣 6 枚硬币）。"
        ok, info = bili_live.set_name(name)
        return f"昵称已改：{info}" if ok else info
    return ("bili_account 支持：status 账号状态 / emotes 可用表情 / "
            "comment 发评论 / avatar 换头像 / name 改昵称。")


def _bili_start() -> None:
    """起弹幕监听；重复调用先停旧连接，保证同一时间只有一条。"""
    if not bili_live.ready():
        return
    _bili_stop()
    stop = asyncio.Event()
    _bili_state["stop"] = stop
    _bili_state["task"] = asyncio.create_task(_bili_loop(stop))
    logger.info(f"[jinyu] B站弹幕监听启动 room={bili_live.room()}")


def _bili_stop() -> None:
    stop = _bili_state.get("stop")
    if stop is not None:
        stop.set()
    task = _bili_state.get("task")
    if task is not None and not task.done():
        task.cancel()
    _bili_state["task"] = None
    _bili_state["stop"] = None


async def _bili_loop(stop) -> None:
    """断线指数退避重连；配置/登录态在每轮重连时重新读取。"""
    backoff = 3
    while not stop.is_set():
        try:
            await bili_live.listen(_bili_on_danmu, stop)
            backoff = 3
        except asyncio.CancelledError:
            raise
        except Exception as exc:                        # noqa: BLE001 网络故障不能拖垮机器人
            logger.warning(f"[jinyu] B站弹幕连接中断 {type(exc).__name__}: {exc}"
                           f"｜{backoff}s 后重连")
            try:
                await asyncio.wait_for(stop.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(60, backoff * 2)


def _bili_video_ctx(aid) -> str:
    """@回复用：被 @ 的那条视频的标题/UP主/简介/弹幕热评；失败给空串。"""
    key = str(aid or "")
    if not key:
        return ""
    now = time.time()
    hit = _AT_CTX.get(key)
    if hit and now - hit[0] < 6 * 3600:
        return hit[1]
    ctx = ""
    try:
        meta = bili_meta_by_aid(aid)
        if meta and not meta.get("error"):
            dur = int(meta.get("duration") or 0)
            head = (f"视频：{meta.get('title')}｜{meta.get('author') or 'UP主未知'}"
                    + (f"｜{dur // 60}:{dur % 60:02d}" if dur else ""))
            desc = str(meta.get("desc") or "").strip()
            if desc:
                head += f"\n简介：{desc[:200]}"
            ctx = head
            try:
                digest = bili_digest(meta)
            except Exception:                   # noqa: BLE001 热评失败不影响标题简介
                digest = ""
            if digest:
                ctx += "\n" + digest[:500]
        elif meta.get("error"):
            logger.info(f"[jinyu] B站@视频资料被拒 aid={key}：{meta['error']}")
    except Exception as exc:                    # noqa: BLE001 资料读不到也不能不回
        logger.info(f"[jinyu] B站@视频资料读取失败 aid={key}：{exc}")
    _AT_CTX[key] = (now, ctx)
    if len(_AT_CTX) > 64:
        _AT_CTX.clear()
    return ctx


async def _bili_at_loop() -> None:
    """自动回复B站@我的：只回主人，复用主人私聊的会话与记忆。"""
    await asyncio.sleep(25)
    while True:
        try:
            mw_plain = _get_mw_plain()
            if not (BILI_AT_ON and mw_plain is not None
                    and bili_live.can_send()):
                await asyncio.sleep(60)
                continue
            ok, _why = bili_live.at_allowed()
            if not ok:
                await asyncio.sleep(40)
                continue
            items = await asyncio.to_thread(bili_live.fetch_at_me)
            owner = BILI_OWNER_UID or bili_live.my_uid()
            for it in items:
                if not owner or it.get("mid") != owner:
                    bili_live.mark_at(it["id"])   # 别人@的只记账不回
                    continue
                if not it.get("text"):
                    bili_live.mark_at(it["id"])
                    continue
                ok, why = bili_live.at_allowed()
                if not ok:                        # 额度/间隔到了就先停，游标不动，下轮再回
                    logger.info(f"[jinyu] B站@先不回复（{why}），留到下一轮")
                    break
                sid = _get_autonomy_sid() or f"qq-u{owner}"
                raw_text = re.sub(r"^@\S+\s*", "", it["text"]).strip() or it["text"]
                line = f"【B站@】{it.get('uname') or it.get('mid')}：{raw_text}"
                line += "\n（回复会直接作为B站评论发出，写短一点，300字以内，不用分条）"
                if it.get("type") == 1 and it.get("oid"):
                    ctx = await asyncio.to_thread(_bili_video_ctx, it["oid"])
                    if ctx:
                        line += ("\n（主人是在这条视频的评论区@你的，下面是你看到的视频资料；"
                                 "画面没看，别描述画面里的具体内容）\n" + ctx)
                try:
                    reply = await asyncio.to_thread(
                        mw_plain.chat, line, PERSONA, sid, CID,
                        speaker=str(it.get("uname") or ""))
                except Exception as exc:          # noqa: BLE001 单条失败不拖垮轮询
                    logger.warning(f"[jinyu] B站@生成失败 id={it['id']}: {exc}")
                    bili_live.mark_at(it["id"])   # 生成失败也记账，避免同一条反复烧模型
                    continue
                sent, info = await asyncio.to_thread(
                    bili_live.reply_at, it["oid"], it["type"],
                    it["root"], it["parent"], reply)
                bili_live.mark_at(it["id"])
                if sent:
                    logger.info(f"[jinyu] B站@已回复 id={it['id']} 内容={info!r}")
                else:
                    logger.info(f"[jinyu] B站@回复未发出 id={it['id']}：{info}")
            await asyncio.sleep(90)
        except asyncio.CancelledError:
            raise
        except Exception as exc:                  # noqa: BLE001 轮询不能死
            logger.warning(f"[jinyu] B站@轮询异常: {exc}")
            await asyncio.sleep(120)


async def _bili_on_danmu(item) -> None:
    """被点名才回复：记一条对话 + 以人设口吻发一条弹幕，节流内不生成。"""
    mw = _get_mw()
    if mw is None:
        return
    text = str(item.get("text") or "")
    who = str(item.get("uid") or "")
    if who and who == bili_live.my_uid():
        return                                          # 自己的弹幕：不自我回复
    if not bili_live.mentioned(text):
        return
    ok, why = bili_live.may_send()
    if not ok:
        logger.info(f"[jinyu] B站点名但暂不回复：{why}")
        return
    sid = f"bili-l{bili_live.room()}"
    line = f"{item.get('uname') or item.get('uid')}：{text}"
    try:
        reply = await asyncio.to_thread(mw.chat, line, PERSONA, sid, CID,
                                        speaker=str(item.get("uname") or ""))
    except Exception as exc:                            # noqa: BLE001 单条失败不影响监听
        logger.exception(f"[jinyu] B站弹幕生成失败 sid={sid}: {exc}")
        return
    sent, info = await asyncio.to_thread(bili_live.send_danmu, reply)
    if sent:
        logger.info(f"[jinyu] B站已回复 用户={item.get('uname')} 内容={info!r}")
    else:
        logger.warning(f"[jinyu] B站回复未发出：{info}")


async def _bili_notice(user_id: str, text: str) -> None:
    """登录结果回执只走私聊，避免群里贴凭据相关消息。"""
    try:
        await get_bot().send_private_msg(user_id=int(user_id), message=text)
    except Exception as exc:                            # noqa: BLE001 通知失败不影响登录
        logger.warning(f"[jinyu] B站登录结果通知失败：{exc}")


async def _bili_login_poll(user_id: str, key: str) -> None:
    """扫码后轮询 3 分钟；成功即落登录态并起监听。"""
    seen = False
    for _ in range(90):
        await asyncio.sleep(2)
        st = await asyncio.to_thread(bili_live.login_poll, key)
        if st["state"] == "scanned" and not seen:
            seen = True
            await _bili_notice(user_id, st["msg"])
        elif st["state"] == "ok":
            await _bili_notice(user_id, st["msg"] + "。被点名时会用这个号回弹幕。")
            if bili_live.ready() and BILI_ON:
                _bili_start()
            return
        elif st["state"] == "expired":
            await _bili_notice(user_id, st["msg"])
            return


_HELP_BILI = ("用法：/bili login 扫码登录｜/bili status｜"
              "/bili cmt 视频链接 [内容] 发评论（可附图或 贴纸=标签，走视频笔记）｜/bili emotes 看可用表情｜"
              "/bili avatar [图片] 换头像｜/bili name 新昵称｜"
              "/bili unlock 解除写操作暂停｜"
              "/bili room 直播间号｜/bili on|off。"
              "被点名（默认「瑾瑜」）才回弹幕；评论每日限额且不 @ 任何人；"
              "改昵称 B站扣 6 枚硬币。")


def _bili_video_ref(arg: str) -> tuple[str, str, str]:
    """把「B站链接或 BV 号 + 其余文字」拆成 (url, bvid, 评论正文)。"""
    urls = [u for u in extract_urls(arg)
            if "bilibili.com/video/" in u or "b23.tv" in u]
    url = urls[0] if urls else ""
    hit = re.search(r"(BV[0-9A-Za-z]{10})", arg, re.I)
    bvid = hit.group(1) if hit else ""
    if not url and bvid:
        url = f"https://www.bilibili.com/video/{bvid}"
    body = arg
    if urls:
        body = body.replace(urls[0], "", 1)
    if hit:
        body = body.replace(hit.group(0), "", 1)
    return url, bvid, body.strip(" 　:：")


async def _bili_comment_draft(meta: dict) -> str:
    """没给正文时，按视频资料与弹幕/热评让前台自己想一句短评。"""
    mw = _get_mw()
    if mw is None:
        return ""
    digest = ""
    try:
        digest = await asyncio.to_thread(bili_digest, meta)
    except Exception:                           # noqa: BLE001 抓不到就只按标题写
        digest = ""
    ctx = (f"标题={meta.get('title') or ''}\n作者={meta.get('author') or ''}\n"
           f"简介={meta.get('desc') or ''}\n{digest}")
    msgs = [
        {"role": "system", "content": "你在给B站视频写一条观众评论：中文，不超过60字，"
                                      "口语化，不@任何人，不写动作/标签，只输出评论正文。"},
        {"role": "user", "content": ctx[:1500]},
    ]
    try:
        draft = await asyncio.to_thread(mw.front.chat, msgs)
    except Exception as exc:                    # noqa: BLE001 生成失败让用户自己给内容
        logger.info(f"[jinyu] B站评论草稿生成失败: {exc}")
        return ""
    return bili_live.clean_comment(strip_dsml(str(draft or "")), 60)


async def _bili_comment_cmd(event, arg: str, matcher) -> None:
    """管理员发视频评论：每日限额 + 不 @ 任何人；正文可省略由模型写；附图走视频笔记。"""
    urls = _extract_image_urls(event)
    image = urls[-1] if urls else ""
    m = re.search(r"(?:贴纸=|sticker:)(\S+)", arg)
    sticker_tag = m.group(1) if m else ""
    if m:
        arg = arg.replace(m.group(0), "").strip()
    url, bvid, body = _bili_video_ref(arg)
    if not url:
        await matcher.send("用法：/bili cmt 视频链接 [内容]（可附图，附图就走视频笔记；也可写 贴纸=开心 从贴纸库选图）")
        return
    ok, why = bili_live.comment_allowed()
    if not ok:
        await matcher.send(why)
        return
    try:
        meta = await asyncio.to_thread(video_meta, url)
    except Exception:                           # noqa: BLE001 读不到就当拿不到 aid
        meta = {}
    aid = int(meta.get("aid") or 0)
    if not aid:
        await matcher.send("这条视频读不到 aid，发不了评论。")
        return
    if not body:
        body = await _bili_comment_draft(meta)
    if not body:
        await matcher.send("没想好写什么，给个方向吧：/bili cmt 链接 内容")
        return
    if image or sticker_tag:
        if image:
            data, why = await asyncio.to_thread(download_image_ex, image)
            if not data:
                await matcher.send(f"图片没拿到：{why}")
                return
        else:
            path = pick_sticker(sticker_tag)
            if not path:
                await matcher.send(f"贴纸库里没有「{sticker_tag}」合适的图。")
                return
            try:
                data = await asyncio.to_thread(Path(path).read_bytes)
            except OSError:
                await matcher.send("贴纸文件读不了，换一张或改发文字评论。")
                return
        sent, info = await asyncio.to_thread(
            bili_live.post_note_comment, aid, body, data,
            str(meta.get("bvid") or bvid))
        if sent:
            await matcher.send(f"已作为带图笔记发到评论区：{info}")
        else:
            await matcher.send(info)
        return
    sent, info = await asyncio.to_thread(
        bili_live.post_comment, aid, body, str(meta.get("bvid") or bvid))
    if sent:
        await matcher.send(f"已在评论区留言：{info}")
    else:
        await matcher.send(info)


async def _bili_command(event, text: str, matcher) -> bool:
    """管理员 /bili 指令；处理过返回 True。"""
    if str(event.user_id) not in ADMIN:
        await matcher.send("这个指令只有主人能用。")
        return True
    parts = text.split()
    cmd = (parts[1] if len(parts) > 1 else "status").lower()
    arg = " ".join(parts[2:]).strip()
    if cmd in ("cmt", "comment", "评论"):
        await _bili_comment_cmd(event, arg, matcher)
        return True
    if cmd in ("emotes", "emote", "表情"):
        texts = await asyncio.to_thread(bili_live.emote_texts, 24)
        await matcher.send("评论区可用表情（直接写进评论正文）：\n" + " ".join(texts))
        return True
    if cmd in ("avatar", "头像", "换头像"):
        urls = _extract_image_urls(event)
        url = urls[-1] if urls else (arg if arg.startswith("http") else "")
        if not url:
            await matcher.send("把图和数据发在同一条消息里：/bili avatar（附一张图）")
            return True
        data, why = await asyncio.to_thread(download_image_ex, url)
        if not data:
            await matcher.send(f"图片没拿到：{why}")
            return True
        ok, msg = await asyncio.to_thread(bili_live.set_avatar, data)
        await matcher.send(("头像已换：" + msg) if ok else msg)
        return True
    if cmd in ("name", "nick", "昵称", "改名"):
        if not arg:
            await matcher.send("用法：/bili name 新昵称（最多16字，B站扣6硬币）")
            return True
        ok, msg = await asyncio.to_thread(bili_live.set_name, arg)
        await matcher.send(("昵称已改：" + msg) if ok else msg)
        return True
    if cmd in ("login", "扫码"):
        if isinstance(event, GroupMessageEvent):
            await matcher.send("扫码登录请在私聊里发 /bili login。")
            return True
        qr = await asyncio.to_thread(bili_live.login_begin)
        if qr.get("error"):
            await matcher.send(str(qr["error"]))
            return True
        png = bili_live.qr_png(qr["url"])
        if png:
            await matcher.send(MessageSegment.image(
                "base64://" + base64.b64encode(png).decode()))
        else:
            await matcher.send("用 B站 App 打开这个链接确认登录：\n" + str(qr["url"]))
        asyncio.create_task(_bili_login_poll(str(event.user_id), str(qr["key"])))
        return True
    if cmd == "room":
        ok, msg = bili_live.set_room(arg)
        if ok and bili_live.can_send() and BILI_ON:
            _bili_start()
            msg += " 已开始监听。"
        elif ok:
            msg += " 还没登录，先 /bili login 扫码。"
        await matcher.send(msg)
        return True
    if cmd in ("on", "off"):
        bili_live.set_on(cmd == "on")
        if cmd == "on" and bili_live.can_send():
            _bili_start()
        elif cmd == "off":
            _bili_stop()
        await matcher.send(bili_live.status())
        return True
    if cmd in ("unlock", "解除", "恢复"):
        await matcher.send(bili_live.unlock())
        return True
    if cmd in ("status", "who"):
        await matcher.send(bili_live.status())
        return True
    await matcher.send(_HELP_BILI)
    return True
