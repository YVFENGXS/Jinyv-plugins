# -*- coding: utf-8 -*-
"""媒体层：图片判读、语音/音频/链接注记、贴纸自学习采集。

这一层只处理「一条消息里带了什么媒体」，不碰记忆与会话：
- `capture` 是优先级最高的旁路处理器，只收集图片/表情包，绝不回复；
- `_wait_media` 让主回复流程等本条消息的视觉判读结果；
- `_voice_notes` / `_audio_file_note` / `_link_notes` 把媒体变成可注入前台的文字。

`_sid`、`_target`、最近图片缓存、视频引用由组合根通过 configure() 注入，
避免和插件入口互相 import。
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from nonebot import get_bot, logger, on_message
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent

from asr import (
    enabled as asr_enabled,
    fetch_voice,
    transcribe as asr_transcribe,
)
from config import ADMIN, IMG_NOTE_TEXT
from linkmeta import (
    card_info,
    card_note,
    enabled as link_enabled,
    extract_urls,
    frames_available,
    is_video_url,
    note_for as link_note_for,
    video_frames_info,
)
import music as music_mod
from richmsg import (
    autosave_enabled,
    classify_image_bytes,
    download_image_ex,
    save_and_tag,
)

_get_sid = lambda event: ""                               # noqa: E731  由组合根注入
_get_target = None
_last_media: dict = {}                                    # 由组合根注入（共享同一份 dict）
_remember_video = lambda sid, path, key: None             # noqa: E731


async def _default_target(event) -> bool:
    return False


_get_target = _default_target


def configure(*, get_sid, get_target, last_media, remember_video) -> None:
    """注入组合根的会话/目标判断与共享状态。"""
    global _get_sid, _get_target, _last_media, _remember_video
    _get_sid = get_sid
    _get_target = get_target
    _last_media = last_media
    _remember_video = remember_video


def _has_voice(event: MessageEvent) -> bool:
    return any(seg.type == "record" for seg in event.message)


async def _voice_notes(event: MessageEvent,
                       audio_paths: Optional[list] = None) -> str:
    """把消息里的语音转成文字注记；未启用或失败时降级成「没听清」。

    audio_paths 非空时，原始音频同时落到音乐缓存，供 music_analyze 复用；
    这样即使没配 ASR，模型也能「听」主人刚发的语音。
    """
    if not asr_enabled() and audio_paths is None:
        return ""
    notes = []
    for seg in event.message:
        if seg.type != "record":
            continue
        try:
            raw = await fetch_voice(get_bot(), seg.data or {})
            if raw and audio_paths is not None:
                try:
                    audio_paths.append(str(music_mod.save_bytes(raw, "qq")))
                except Exception as exc:          # noqa: BLE001  缓存失败不影响转写
                    logger.info(f"[jinyu] 语音缓存失败 user={event.user_id}: {exc}")
            text = (await asyncio.to_thread(asr_transcribe, raw)
                    if raw and asr_enabled() else "")
            if text:
                logger.info(f"[jinyu] 语音转写 {len(text)} 字 user={event.user_id}")
            elif asr_enabled():
                logger.info(f"[jinyu] 语音未转写 user={event.user_id} audio={len(raw)}B")
        except Exception as exc:                  # noqa: BLE001  转写失败不影响回复
            logger.info(f"[jinyu] 语音转写失败 user={event.user_id}: {exc}")
            text = ""
        if not asr_enabled():
            notes.append("（发来一条语音，没转成文字）")
        else:
            notes.append(f"（语音说：{text[:300]}）" if text
                         else "（发来一条语音，没听清）")
    return "".join(notes)


# QQ 文件段里哪些后缀当音频处理；mp4/mkv 等也收，交给 ffmpeg 取音轨
_FILE_AUDIO = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg",
               ".opus", ".amr", ".wma", ".mp4", ".m4v", ".mov",
               ".webm", ".mkv"}


def _is_audio_file(seg) -> bool:
    """文件段是不是音频/视频：先看文件名后缀，没后缀再看 URL。"""
    data = dict(seg.data or {})
    name = str(data.get("file") or data.get("name") or "")
    suffix = Path(name).suffix.lower()
    if suffix:
        return suffix in _FILE_AUDIO
    url = str(data.get("url") or "").split("?")[0].lower()
    return any(url.endswith(ext) for ext in _FILE_AUDIO)


async def _audio_file_note(event: MessageEvent,
                           audio_paths: Optional[list] = None) -> str:
    """把 QQ 文件段的音频/视频下载到音乐缓存，供 music_analyze 直接听。"""
    if audio_paths is None:
        return ""
    notes = []
    for seg in event.message:
        if seg.type != "file":
            continue
        data = dict(seg.data or {})
        url = str(data.get("url") or "")
        name = str(data.get("file") or data.get("name") or "")
        suffix = Path(name).suffix.lower()
        if suffix and suffix not in _FILE_AUDIO:
            continue
        if not url.startswith("http"):
            continue
        try:
            path = await asyncio.to_thread(music_mod.save_url, url)
            audio_paths.append(str(path))
            notes.append(f"（发来音频文件：{name[:50] or '未命名'}）")
        except music_mod.MusicError as exc:
            logger.info(f"[jinyu] 音频文件跳过 user={event.user_id}: {exc}")
            notes.append("（音频文件没取到，可能太大或已过期）")
        except Exception as exc:                  # noqa: BLE001  下载失败不影响回复
            logger.info(f"[jinyu] 音频文件失败 user={event.user_id}: {exc}")
            notes.append("（音频文件没取到）")
    return "".join(notes)


async def _link_notes(text: str, event: MessageEvent) -> str:
    """消息里带链接才抓；分享卡片当兜底；视频站链接直接抽帧（时长/配额兜底）。"""
    if not link_enabled():
        return ""
    cards = []
    for seg in event.message:
        if seg.type == "json":
            info = card_info((seg.data or {}).get("data"))
            if info:
                cards.append(info)
    notes = []
    urls = []
    for card in cards:
        if card.get("url"):
            if card["url"] not in urls:
                urls.append(card["url"])
        else:                                   # 小程序卡片常常没有能打开的网页地址
            note = card_note(card)
            if note:
                notes.append(note)
                logger.info(f"[jinyu] 卡片无链接，只注入摘要 "
                            f"{card.get('title') or card.get('desc')!r}")
    for url in extract_urls(text):
        if url not in urls:
            urls.append(url)
    if not urls:
        return "".join(notes)
    urls = urls[:3]
    card_by_url = {c["url"]: c for c in cards if c.get("url")}
    for url in urls:
        host = urlparse(url).hostname or ""
        try:
            note = await asyncio.wait_for(
                asyncio.to_thread(link_note_for, url, card_by_url.get(url)),
                timeout=15)
        except Exception as exc:              # noqa: BLE001  抓取失败静默降级
            logger.info(f"[jinyu] 链接抓取失败 host={host}: {exc}")
            note = ""
        if note:
            notes.append(note)
            logger.info(f"[jinyu] 链接已注入 host={host} chars={len(note)}")
        if is_video_url(url) and frames_available():
            try:
                extra, video_path, key = await asyncio.wait_for(
                    asyncio.to_thread(video_frames_info, url,
                                      str(event.user_id) in ADMIN), timeout=300)
            except Exception:                 # noqa: BLE001  抽帧失败不影响回复
                extra, video_path, key = "", None, ""
            if extra:
                notes.append(extra)
                _remember_video(_get_sid(event), video_path, key)
    return "".join(notes)


# ------------------------------------------------- 贴纸自学习（不回复，只收集）

capture = on_message(priority=1, block=False)

# 群聊图片是否只在被 @ 时分析。开着能省视觉 token，默认保持旧行为（全量分析）。
# 状态落 RP_DB 同目录 media_state.json，重启不丢。
_IMG_AT_ONLY = False
_IMG_STATE_PATH: Optional[Path] = None


def _img_state_load(path: Path) -> None:
    global _IMG_STATE_PATH, _IMG_AT_ONLY
    _IMG_STATE_PATH = path
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return
    except Exception as exc:                    # noqa: BLE001  坏文件不该拦住启动
        logger.warning(f"[jinyu] 媒体状态读取失败: {exc}")
        return
    if isinstance(data, dict):
        _IMG_AT_ONLY = bool(data.get("group_image_at_only"))


def _img_state_save() -> None:
    if _IMG_STATE_PATH is None:
        return
    try:
        tmp = _IMG_STATE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps({"group_image_at_only": _IMG_AT_ONLY},
                                  ensure_ascii=False), encoding="utf-8")
        tmp.replace(_IMG_STATE_PATH)
    except Exception as exc:                    # noqa: BLE001
        logger.warning(f"[jinyu] 媒体状态保存失败: {exc}")


def _img_at_switch(on: bool) -> None:
    global _IMG_AT_ONLY
    _IMG_AT_ONLY = bool(on)
    _img_state_save()


def img_at_only() -> bool:
    """群聊图片是否只在被 @ 时分析（供 /imgat 状态展示）。"""
    return _IMG_AT_ONLY


_CAPTION_NOISE = re.compile(r"\[(?:图片|表情|动画表情|视频|语音|文件)\]")


def _caption_from_segs(segs) -> str:
    """同条消息里附带的文字，作为视觉判断的弱线索（可能图文不符）。

    QQ 里表情包常带「[图片]」占位前缀，先剥掉；只留真正写下的字，最多 200 字。
    """
    parts = []
    for s in segs or []:
        try:
            if s.type != "text":
                continue
            t = str((s.data or {}).get("text") or "")
        except Exception:                     # noqa: BLE001 段结构异常不影响判读
            continue
        t = _CAPTION_NOISE.sub("", t)
        if t.strip():
            parts.append(t.strip())
    return re.sub(r"\s+", " ", " ".join(parts)).strip()[:200]


def _extract_image_urls(event: MessageEvent) -> list:
    """消息里所有图片/商城表情的直链（可能为空列表）。"""
    urls = []
    for seg in event.message:
        if seg.type == "image":
            u = seg.data.get("url") or seg.data.get("file") or ""
            if u.startswith("http"):
                urls.append(u)
        elif seg.type == "mface":
            u = seg.data.get("url") or ""
            if u.startswith("http"):
                urls.append(u)
    return urls


_media_tasks = set()
_media_futs = {}           # message_id -> [该条消息每张图的判读 task]（_handle 等它拿描述）


def drop_pending(message_id) -> None:
    """这条消息不会回复了：把挂起的视觉任务从全局表摘掉，避免泄漏。"""
    _media_futs.pop(str(message_id), None)


@capture.handle()
async def _capture(event: MessageEvent):
    # 群聊省 token：没被 @ 就不下载、不判读、不入表情包库；私聊始终分析。
    if isinstance(event, GroupMessageEvent) and _IMG_AT_ONLY and not event.is_tome():
        return
    urls = _extract_image_urls(event)
    if not urls:
        return
    sid = _get_sid(event)
    _last_media[sid] = urls[-1]
    is_admin = str(event.user_id) in ADMIN
    hint = _caption_from_segs(event.message)
    tasks = []
    for u in urls:                        # 一条消息里所有图都处理
        task = asyncio.create_task(_process_image(u, sid, is_admin, hint))
        _media_tasks.add(task)
        task.add_done_callback(_media_tasks.discard)
        tasks.append(task)
    if await _get_target(event):          # 只给会回复的消息挂结果，message_id 唯一不串图
        _media_futs[str(event.message_id)] = tasks


async def _process_image(url: str, sid: str, is_admin: bool,
                         hint: str = "") -> Optional[dict]:
    """下载 → 视觉判读 → 可用表情包入库 / 其余只留描述。失败只记日志。"""
    try:
        loop = asyncio.get_running_loop()
        data, why = await loop.run_in_executor(None, download_image_ex, url)
        if data is None:
            logger.info(f"[jinyu] 图片下载失败 sid={sid}：{why}")
            return None
        info = await classify_image_bytes(data, hint)
        if info.get("err"):
            logger.warning(f"[jinyu] 视觉判读失败 sid={sid}: {info['err']}")
        if info.get("kind") == "表情包":
            if info.get("blocked"):
                logger.info(f"[jinyu] 图中文字违禁，不入库 sid={sid}：{info.get('text')}")
            elif info.get("suitable") is False:
                logger.info(f"[jinyu] 后台判定不适合作为表情包，不入库 sid={sid}："
                            f"{info.get('desc')}")
            elif autosave_enabled():
                path = await loop.run_in_executor(
                    None, lambda: save_and_tag(data, [], is_admin, info))
                if path is not None:
                    logger.info(f"[jinyu] 贴纸入库 {path.name} (sid={sid}) "
                                f"tags={info.get('tags')} text={info.get('text')!r}")
        else:
            logger.info(f"[jinyu] 图片（非表情包）不入库 sid={sid}：{info.get('desc')}")
        return info
    except Exception as exc:              # noqa: BLE001
        logger.warning(f"[jinyu] 图片处理失败: {exc}")
        return None


def _img_note(infos: list) -> str:
    """后台视觉结果 → 给前台模型看的事实说明：是什么图、图上写了什么。

    图片和表情包都要说清楚——以前表情包的描述被丢掉，前台只能说"看不到图"。
    """
    parts = []
    for info in infos:
        if not info:
            continue
        label = "一个表情包" if info.get("kind") == "表情包" else "一张图片"
        bits = []
        if info.get("desc"):
            bits.append(str(info["desc"]))
        if info.get("character"):
            bits.append(f"角色是「{info['character']}」")
        text = str(info.get("text") or "").strip()
        if text:
            if len(text) > IMG_NOTE_TEXT:
                # 长图（截图/文档）整段 OCR 会灌满上下文，而且常有错字；
                # 只给开头一段，并说清这是 OCR 摘要，别让前台当成原文照念。
                text = text[:IMG_NOTE_TEXT].rstrip() + "…（后略）"
                bits.append(f"图上的字（OCR 开头部分，可能有错字，只作参考别照抄）：「{text}」")
            else:
                bits.append(f"图上的字是「{text}」")
        parts.append(f"（发来{label}：{'；'.join(bits)}）" if bits
                     else f"（发来{label}，但没看清内容）")
        if info.get("blocked") or info.get("suitable") is False:
            parts.append("（这张图不适合当表情包，别学它）")
    return "".join(parts)


async def _wait_media(event: MessageEvent) -> list:
    """等本条消息的视觉任务；超时/失败都只当"没看见"，绝不卡住回复。"""
    tasks = _media_futs.pop(str(event.message_id), None) or []
    out = []
    for task in tasks:
        try:
            info = await asyncio.wait_for(asyncio.shield(task), timeout=35)
        except Exception:                 # noqa: BLE001
            info = None
        if info:
            out.append(info)
    return out
