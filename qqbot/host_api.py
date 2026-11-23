# -*- coding: utf-8 -*-
"""宿主 HTTP 接口：/jinyu/chat 与 /jinyu/health。

浏览器 / 桌宠 / 通话 / 3D 房间不再直连 SQLite，统一把一轮对话交给本进程，
复用 QQ 这一份中间件与会话锁，避免两个进程抢同一个库。

运行期状态（中间件指针、会话锁、人设以外的提示词、跨窗口投递与沉默判断）
由组合根通过 configure() 注入，避免和插件入口互相 import。
"""
from __future__ import annotations

import asyncio
import hmac
import os
import re
import time

from nonebot import get_driver, logger

from config import (
    BRIDGE_BUDGET,
    CALL_HOLD_SECONDS,
    CID,
    EPOCH_FLUSH,
    EPOCH_SECONDS,
    HOST_MAX_PROMPT,
    HOST_SESSION,
    HOST_SESSION_ROOM,
    HOST_TOKEN,
)
from persona import PERSONA
import rp_skeleton
import stage as stage_mod
import stage_bracket
from richmsg import classify_image_bytes, download_image_ex

_CALL_UNTIL = 0.0
_CALL_SCENE = "通话"       # 通话窗口的类型：视频通话 / 房间，只用于回执措辞与日志
_HOST_ROUTES_READY = False

_get_mw_plain = lambda: None                             # noqa: E731  由组合根注入
_get_locks = lambda: {}                                  # noqa: E731
_get_img_note = lambda infos: ""                         # noqa: E731
_deliver_sends = None
_is_silent = lambda reply: not (reply or "").strip()     # noqa: E731
_get_hints = lambda: ("", "")                            # noqa: E731


def configure(*, get_mw_plain, get_locks, get_img_note, deliver_sends,
              is_silent, get_hints) -> None:
    """注入组合根的运行期状态与工具函数。"""
    global _get_mw_plain, _get_locks, _get_img_note, _deliver_sends, _is_silent, _get_hints
    _get_mw_plain = get_mw_plain
    _get_locks = get_locks
    _get_img_note = get_img_note
    _deliver_sends = deliver_sends
    _is_silent = is_silent
    _get_hints = get_hints


def get_call():
    """当前通话窗口状态，供舞台层读取（不反向 import 组合根）。"""
    return (_CALL_UNTIL, _CALL_SCENE)


def _host_authed(request) -> bool:
    header = str(request.headers.get("authorization") or "")
    if not HOST_TOKEN or not header.startswith("Bearer "):
        return False
    return hmac.compare_digest(header[7:].strip(), HOST_TOKEN)


async def _host_image_note(urls: list[str]) -> str:
    """宿主图片：下载 + 视觉判读，与 QQ 收到图片走同一套；单张失败只退化成提示。"""
    async def one(url: str):
        try:
            data, why = await asyncio.wait_for(
                asyncio.to_thread(download_image_ex, url), timeout=30)
            if not data:
                logger.info(f"[jinyu] 宿主图片未取到：{why}")
                return None
            return await asyncio.wait_for(classify_image_bytes(data), timeout=40)
        except Exception as exc:                    # noqa: BLE001  单张失败不影响整轮
            logger.info(f"[jinyu] 宿主图片处理失败：{type(exc).__name__}: {str(exc)[:80]}")
            return None

    infos = [i for i in await asyncio.gather(*(one(u) for u in urls)) if i]
    if not infos:
        return "（对方发来图片，但没取到或没看清内容）"
    return _get_img_note(infos)


async def chat(request):
    """宿主对话入口：调用方（浏览器/桌宠）不再直连 SQLite，统一交给本进程写入。"""
    global _CALL_UNTIL, _CALL_SCENE
    from fastapi.responses import JSONResponse
    if not _host_authed(request):
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
    mw_plain = _get_mw_plain()
    if mw_plain is None:
        return JSONResponse({"ok": False, "error": "memory not ready"}, status_code=503)
    try:
        body = await request.json()
    except Exception:                             # noqa: BLE001
        return JSONResponse({"ok": False, "error": "请求不是 JSON"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"ok": False, "error": "请求体必须是对象"}, status_code=400)
    text = str(body.get("text") or "").strip()[:HOST_MAX_PROMPT]
    prompt = str(body.get("prompt") or text).strip()[:HOST_MAX_PROMPT]
    source = str(body.get("source") or "").strip().lower()
    if source not in rp_skeleton.SOURCE_LABELS:
        source = ""
    # 渠道提示词（如桌宠的动作/表情指令）只拼在人设副本上，不落库、不影响 QQ 人设
    hint = str(body.get("hint") or "").strip()[:2000]
    # 平台侧只给图片地址；下载、体积/格式限制、视觉判读都在宿主里做
    images = [u.strip()[:500] for u in (body.get("images") or []) if isinstance(u, str)]
    images = [u for u in images if u.startswith(("http://", "https://"))][:4]
    if not text and not images:
        return JSONResponse({"ok": False, "error": "缺少 text"}, status_code=400)
    if images:
        note = await _host_image_note(images)        # 和 QQ 一样：先判读，再进正文
        text = (text + note) if text else note
        prompt = (prompt + note) if prompt else note
    # 房间用独立会话（HOST_SESSION#room）；视频/桌宠/QQ 仍共用 HOST_SESSION
    sid = (HOST_SESSION_ROOM or HOST_SESSION) if source == "room" else HOST_SESSION
    lock = _get_locks().setdefault(sid, asyncio.Lock())   # 与 QQ 私聊共用同一把会话锁
    started = time.monotonic()
    bridge = None
    mounted = False
    want_actions = True
    async with lock:
        try:
            session_sid = await asyncio.to_thread(
                mw_plain.session_identity, sid, CID, EPOCH_SECONDS, flush_timeout=EPOCH_FLUSH)
            # 视频/房间回合才连桥；连不上就是这一轮没有身体，工具不挂、纯文本照旧
            if source in ("video", "room"):
                _CALL_UNTIL = time.monotonic() + CALL_HOLD_SECONDS
                _CALL_SCENE = "房间" if source == "room" else "通话"
                want_actions = source != "room" or bool(stage_mod.ROOM_ACTION_RE.search(text))
                if source == "room" and not want_actions:
                    logger.info("[jinyu] stage tools off (no action intent)")
                # 房间即使没有动作意图也连桥：回复里的括号动作在回包后要用这条连接
                bridge = await stage_mod.open_bridge()
            persona = dict(PERSONA)
            persona["core"] = PERSONA["core"]
            if bridge is not None:
                persona["core"] += stage_mod.NOTE
            if "say_in" in getattr(mw_plain, "_tools", {}):
                persona["core"] += _get_hints()[0]
            if "web_search" in getattr(mw_plain, "_tools", {}):
                persona["core"] += _get_hints()[1]
            if hint:
                persona["core"] += "\n" + hint
            # 桌宠/通话/房间的舞台指令只回给调用方，落库剥掉，免得 QQ 历史里看到 [[act:..]]
            clean = None
            if source in ("desk", "video", "room"):
                clean = lambda r: re.sub(r"\[\[[^\]]*\]\]", "", str(r or "")).strip()  # noqa: E731
            # 房间没有跨窗口身份（room 不是 say_in 的目标窗口），留空即可
            tool_ctx = {"channel": {"desk": "desktop", "video": "call"}.get(source, ""),
                        "sends": []}
            loop = asyncio.get_running_loop()

            def run_chat(store: str | None = text, **chat_kw):
                # 桥 / 事件循环 / 预算挂在线程本地：QQ 回合没有绑定，只会拿到 stage_unavailable
                stage_mod.LOCAL.bridge = bridge
                stage_mod.LOCAL.loop = loop
                stage_mod.LOCAL.deadline = time.monotonic() + BRIDGE_BUDGET
                stage_mod.LOCAL.calls = 0
                stage_mod.LOCAL.reads = 0
                stage_mod.LOCAL.actions = 0
                try:
                    result = mw_plain.chat(
                        prompt, persona, session_sid, CID,
                        speaker="主人", store_input=store, source=source,
                        store_reply=clean, tool_context=tool_ctx, **chat_kw)
                    return result, int(getattr(stage_mod.LOCAL, "actions", 0))
                finally:
                    stage_mod.LOCAL.bridge = None
                    stage_mod.LOCAL.loop = None

            mounted = bridge is not None and want_actions and stage_mod.tools_on()
            try:
                reply, actions_done = await asyncio.to_thread(run_chat)
            finally:
                if mounted:
                    stage_mod.tools_off()
            try:
                turn_after = await asyncio.to_thread(
                    mw_plain.db.max_turn, session_sid, CID)
            except Exception:                      # noqa: BLE001 取不到轮号就按新轮回退
                turn_after = None
            if mounted and not str(reply or "").strip():
                # 动作做完后偶尔会空回复（工具消息收尾时模型不出话）：摘表后补一次，
                # 只写回复、不重复记主人这句，保证通话里一定有声音。
                try:
                    reply = await asyncio.to_thread(
                        mw_plain.chat,
                        prompt + "\n（动作已经做完，现在直接回应主人，不要沉默。）",
                        persona, session_sid, CID, speaker="主人", store_input="",
                        source=source, store_reply=clean, tool_context=tool_ctx,
                        store_user=False, reuse_turn=turn_after)
                    logger.info("[jinyu] stage speak retry "
                                + ("ok" if str(reply or "").strip() else "empty"))
                except Exception as exc:          # noqa: BLE001 补话失败就按空回复走
                    logger.warning(f"[jinyu] stage speak retry failed: {type(exc).__name__}")
            # 动作指令却一个动作工具都没调：模型多半在编「我翻过来了」。摘表重跑一次，
            # 逼它要么真调工具，要么明确说做不到。
            if mounted and actions_done == 0 and stage_mod.ROOM_ACTION_RE.search(text):
                logger.warning("[jinyu] stage no action for imperative: %r", text[:40])
                try:
                    stage_mod.tools_on()
                    try:
                        retry, retry_actions = await asyncio.to_thread(
                            run_chat, "", store_user=False, reuse_turn=turn_after)
                    finally:
                        stage_mod.tools_off()
                    if str(retry or "").strip():
                        reply = retry
                    logger.info(f"[jinyu] stage action retry actions={retry_actions}")
                except Exception as exc:          # noqa: BLE001
                    logger.warning(f"[jinyu] stage action retry failed: {type(exc).__name__}")
        except Exception as exc:                  # noqa: BLE001
            logger.exception(f"[jinyu] 宿主接口生成失败 sid={sid}: {exc}")
            if bridge is not None:
                await stage_mod.close_bridge(bridge)
            return JSONResponse({"ok": False, "error": "internal"}, status_code=500)
    reply = str(reply or "").strip()
    sends = list(tool_ctx.get("sends") or [])
    if sends and _deliver_sends is not None:
        await _deliver_sends(sends, tool_ctx["channel"])
    passed = _is_silent(reply)      # 这一轮把话说到别的窗口了，本窗口不再重复
    if passed:
        reply = ""
    # 回复定稿后再看括号动作：不阻塞回包、一条回复最多一个、失败只记日志
    press = None
    if source == "room" and not passed and bridge is not None:
        press = stage_bracket.extract(reply)
        if press is not None:
            logger.info(f"[bracket] press={press.raw!r} kind={press.kind} sid={sid}")
            if stage_mod.spawn_bracket(bridge, press, lock, sid) is not None:
                bridge = None        # 后台任务接管，做完自己关
    if bridge is not None:
        await stage_mod.close_bridge(bridge)
    logger.info(f"[jinyu] 宿主接口 source={source or '-'} sid={session_sid} "
                f"问={text[:40]!r} 答={reply[:60]!r}"
                + (f" 跨窗口={[s.get('channel') for s in sends]}" if sends else ""))
    return JSONResponse({"ok": True, "reply": reply, "pass": passed,
                         "session": session_sid, "source": source,
                         "ms": int((time.monotonic() - started) * 1000)})


async def health():
    from fastapi.responses import JSONResponse
    return JSONResponse({
        "ok": True, "name": "jinyu-host",
        "token": bool(HOST_TOKEN), "session": HOST_SESSION,
        "sources": list(rp_skeleton.SOURCE_LABELS),
        "llm": bool(os.environ.get("RP_FRONT_KEY") and os.environ.get("RP_BACK_KEY")),
    })


def install_host_routes() -> None:
    global _HOST_ROUTES_READY
    if _HOST_ROUTES_READY:
        return
    if not HOST_TOKEN or not HOST_SESSION:
        logger.info("[jinyu] 宿主接口未启用（缺 RP_HOST_TOKEN 或 RP_SESSION / RP_HOST_SESSION）")
        return
    driver = get_driver()
    app = getattr(driver, "server_app", None)    # NoneBot2 FastAPI driver
    if app is None:
        logger.warning("[jinyu] 宿主接口未注册：当前 driver 不是 FastAPI")
        return
    # FastAPI 按类型注解识别 Request；不注解会被当成必填查询参数（422）。
    # 只在确认是 FastAPI 时导入并补注解，aiohttp 部署不会因缺依赖而加载失败。
    from fastapi import Request
    chat.__annotations__["request"] = Request
    # legacy 契约，勿改：桌宠 / 通话 / room / satori 侧车都硬编码了这个路径
    app.add_api_route("/jinyu/chat", chat, methods=["POST"])
    app.add_api_route("/jinyu/health", health, methods=["GET"])
    _HOST_ROUTES_READY = True
    logger.info("[jinyu] 宿主接口就绪 /jinyu/chat（Bearer 校验，source=qq/desk/video/room）")
