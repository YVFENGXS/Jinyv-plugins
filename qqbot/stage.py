# -*- coding: utf-8 -*-
"""舞台 / 身体桥：视频回合与 QQ 回合共用的身体工具、意图解码、括号动作。

这一层只负责「把动作交给页面」：
- 工具表是进程级的，挂表期间 QQ 回合也会看到，但线程本地没有桥就回 stage_unavailable；
- 前台 body_intent 把自然语言交给后台解码器，再走同一条桥；
- 房间回复里的括号动作在回包后异步执行，失败只记日志。

依赖通过 configure() 注入，避免和组合根互相 import。
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import re
import threading
import time

from nonebot import logger

from config import (
    BODY_INTENT_BUDGET, BODY_INTENT_CALLS, BODY_INTENT_LLM_TIMEOUT,
    BODY_INTENT_STEPS, BRACKET_BUDGET, BRACKET_DELAY_SECONDS,
    BRIDGE_MAX_CALLS, BRIDGE_MAX_READS, BRIDGE_RESULT_CHARS, BRIDGE_TIMEOUT,
    BRIDGE_TOKEN, BRIDGE_URL, STAGE_ACCEPT_MS, _STAGE_SLOW_ACTIONS,
)
from llm import from_env

try:
    from jinyv_stage import intent
    from jinyv_stage import tools
    from jinyv_stage.bridge import StageBridge
except ImportError as _stage_exc:        # 接入层缺失只降级成「没有身体」，QQ 照旧
    intent, tools, StageBridge = None, None, None
    logger.warning(f"[jinyu] jinyv_stage unavailable: {_stage_exc}")

BODY_INTENT_ON = bool(BRIDGE_URL) and intent is not None

# 线程本地：视频回合绑定桥与事件循环，QQ 回合没有绑定
LOCAL = threading.local()
_DEPTH = 0
_LOCK = threading.Lock()
_BRACKET_TASKS: set[asyncio.Task] = set()
_BODY_LLM = None

# 房间回合只有「生活指令」才连桥挂身体工具；寒暄、提问、复盘不挂，避免模型为了展示身体而乱调。
ROOM_ACTION_RE = re.compile(
    r"(去|走到|走回|走过来|过来|靠近|跟着|跟随|跟我|带我|坐下|坐到|坐在|坐上|坐回|坐一下|"
    r"坐好|躺下|躺到|躺在|躺上|躺回|躺一会儿|侧躺|平躺|"
    r"站起|起身|起来|起床|上床|休息|睡觉|开门|关门|开灯|关灯|转身|看着我|看这边|抱|"
    r"动一动|动动|拿|放下|回房间|去(客厅|厨房|卧室|浴室|阳台|餐桌|沙发|书桌|窗边|床))"
)
NOTE = ("（你现在连着一具能动的身体，说和做必须分开：主人让你走过去、坐下、躺下、起身、"
        "上床、休息、过来、一起去、看向某处、做动作、做手势、换表情、开灯或开关门时，"
        "先调用对应工具拿到回执再说话；这类生活指令不能只用一句「我这就过去」答应，"
        "必须至少真正调用一次工具（走过去用 move_to 或 perform；坐下、上床、躺下用 sit "
        "并选对应座位与 posture）；"
        "没有成功回执就不要说自己已经做了，宁可说「我这就过去」再调工具。"
        "不确定目标先 list_targets，想知道能做什么先 list_abilities"
        "（可用动作、手势基元、座位与姿态、灯、门、表情），想知道自己在哪用 get_state；"
        "多个动作要一起做时用 perform 一次编排，单步用对应工具；"
        "动作失败或基元被跳过时回执会写「这一步没有发生」，不许当成成功继续往下叙述；"
        "get_state、list_targets、get_clip_state、list_abilities 只是「看」，不是「做」，"
        "没拿到动作成功回执就不许说「我已经走到了/坐下了/躺下了」；"
        "主人说跟着我/跟我走用 follow，说停下/别跟了用 unfollow；跟随时不要反复 move_to；"
        "走到主人面前直接用 move_to 的 actor.player，页面会落到他身边，不要自己编坐标；"
        "sit 不会自己走过去：离座位站起点超过 1.5m 会回 too_far，先 move_to 该座位 id 再 sit；"
        "不要只用 perform 里的 moveTo 就声称自己坐下了，必须有 sit 的成功回执；"
        "主人说「朝向我/面向我」坐或躺时，sit 必须传 facing:\"player\"，"
        "回执里 facing.degraded=true 时只能如实说「我侧躺着转头看你」「我的脚还朝着你」，"
        "不许说「整个人转过来正对着你」；"
        "一次两三个动作就够，动作做完必须回应主人，不要只动不说、"
        "也不要用 [[pass]] 收尾（这一轮主人就在当前窗口里听着）。"
        "动作失败或超时都照常把话说下去，不要向主人报告工具错误码；"
        "但回执 ok=false 时绝不能说成已经做到，要如实说「我还没过去」「我被床头挡住了」。"
        "口型由系统随语音驱动，不用你调。）\n")

_READONLY = tuple(getattr(tools, "READONLY", ())) or (
    "list_targets", "get_state", "list_abilities", "get_clip_state", "get_layers", "get_expression")

_get_mw = lambda: None                                    # noqa: E731  由组合根注入
_get_call = lambda: (0.0, "通话")                         # noqa: E731  (until, scene)


def configure(get_mw_plain, get_call=None) -> None:
    """注入组合根的运行期状态读取器（mw_plain 与会话状态）。"""
    global _get_mw, _get_call
    _get_mw = get_mw_plain
    if get_call is not None:
        _get_call = get_call


def _json(name, result):
    """工具结果压成一行 JSON；回填有硬截断，别让一次读状态把上下文塞满。"""
    if tools is not None:
        result = tools.summarize(name, result)
    try:
        text = json.dumps(result, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(result)
    if len(text) > BRIDGE_RESULT_CHARS:
        text = text[:BRIDGE_RESULT_CHARS] + "…"
    return text


def _not_done(name, code, result=None):
    """动作没做成：回填必须把「这一步没有发生」说出来，别让模型把没做的说成做了。"""
    if tools is not None:
        payload = tools.failure_payload(name, code, result)
    else:
        payload = dict(result or {"ok": False, "code": code})
        payload["hint"] = (f"{name} 这一步没有发生（{code}）：这个动作没有执行成功；"
                           "不要说你已经做了、也不要说自己现在已经在那里，"
                           "只说打算做或还没做到；想重试就再调一次工具；"
                           "照常把话说下去，不要向主人报告工具错误。")
    text = _json(name, payload)
    if os.environ.get("RP_BRIDGE_TRACE") == "1":
        logger.info(f"[jinyu] stage not-done payload {name}: {text[:500]}")
    return text


def _handler(name):
    """同步 handler：把活交给视频回合的事件循环去等回执。"""
    readonly = name in _READONLY
    def run(args, sid, cid, ctx=None):
        bridge = getattr(LOCAL, "bridge", None)
        loop = getattr(LOCAL, "loop", None)
        if bridge is None or loop is None:
            # 非视频回合（QQ / 桌宠）调到身体工具：明说这一轮没有身体
            if readonly:
                return _json(name, {"ok": False, "code": "stage_unavailable"})
            return _not_done(name, "stage_unavailable")
        if readonly:
            if getattr(LOCAL, "reads", 0) >= BRIDGE_MAX_READS:
                return _json(name, {"ok": False, "code": "stage_budget"})
            LOCAL.reads = getattr(LOCAL, "reads", 0) + 1
        else:
            if getattr(LOCAL, "calls", 0) >= BRIDGE_MAX_CALLS:
                return _not_done(name, "stage_budget")
            LOCAL.calls = getattr(LOCAL, "calls", 0) + 1
            LOCAL.actions = getattr(LOCAL, "actions", 0) + 1
        left = float(getattr(LOCAL, "deadline", 0)) - time.monotonic()
        if left <= 0.05:
            if readonly:
                return _json(name, {"ok": False, "code": "stage_deadline"})
            return _not_done(name, "stage_deadline")
        started = time.monotonic()
        try:
            future = asyncio.run_coroutine_threadsafe(
                tools.call(bridge, name, args or {}), loop)
            soft = min(left, BRIDGE_TIMEOUT)
            if name in _STAGE_SLOW_ACTIONS:
                soft = min(soft, STAGE_ACCEPT_MS / 1000)
            try:
                result = future.result(timeout=soft)
            except concurrent.futures.TimeoutError:
                if name not in _STAGE_SLOW_ACTIONS:
                    raise
                # 动作已经开始但还没结束：先让模型说话，页面这边继续跑，不取消。
                future.add_done_callback(
                    lambda done: done.exception() if not done.cancelled() else None)
                result = {"ok": True, "code": "accepted",
                          "detail": {"method": name,
                                     "message": "动作已开始但尚未完成，可以在下一轮用 get_state 查看"}}
        except Exception as exc:                  # noqa: BLE001 工具坏了不能拖垮对话
            result = {"ok": False, "code": "stage_error",
                      "detail": {"method": name, "message": type(exc).__name__}}
        extra = ""
        detail = result.get("detail")
        if isinstance(detail, dict):
            if isinstance(detail.get("playerGapMm"), (int, float)):
                extra += f" gap={int(detail['playerGapMm'])}mm"
            facing = detail.get("facing")
            if isinstance(facing, dict) and facing.get("playerSide"):
                extra += (f" side={facing.get('playerSide')} method={facing.get('method')}"
                          f" degraded={str(bool(facing.get('degraded'))).lower()}")
        logger.info(f"[jinyu] stage tool {name} {result.get('code') or 'ok'} "
                    f"{int((time.monotonic() - started) * 1000)}ms{extra}")
        if readonly:
            return _json(name, result)
        if result.get("ok"):
            if result.get("code") == "accepted":
                result = dict(result)
                result["hint"] = (
                    "动作已经开始但还没完成：只能回答「我这就过去 / 正在弄」，"
                    "不许说「已经走到了 / 已经躺好了」；下一轮可以用 get_state 查看"
                )
                return _json(name, result)
            # 基元被通道占用/冷却/说话打断时 started=false：这一步同样没有发生
            hint = tools.success_hint(name, result) if tools is not None else None
            result = dict(result)
            # 动作工具把「该说话了 + 做成的是哪一步」塞回执里：
            # 只写「动作已完成」时，模型会把 stand 说成「走到床边了」
            result["hint"] = hint or f"动作已完成（{name}），请回应主人，不要沉默"
            return _json(name, result)
        # 与上面对称：没有成功回执就说没发生（含 stage_unavailable / client_timeout /
        # stage_deadline / stage_budget，以及 too_far / not_seated 这类页面业务失败）
        return _not_done(name, str(result.get("code") or "unknown"), result)
    return run


def tools_on() -> bool:
    """把身体工具挂进 mw_plain 的工具表；引用计数，返回是否真的挂上。"""
    global _DEPTH
    mw = _get_mw()
    if tools is None or mw is None:
        return False
    with _LOCK:
        if _DEPTH == 0:
            for item in tools.openai_tools():
                fn = item["function"]
                mw.register_tool(fn["name"], fn["description"], fn["parameters"],
                                 _handler(fn["name"]),
                                 readonly=fn["name"] in _READONLY)
            logger.info(f"[jinyu] stage tools on {len(tools.TOOL_NAMES)}")
        _DEPTH += 1
    return True


def tools_off() -> None:
    """回合结束摘表；还有别的视频回合在跑就先留着（schema 一致，按线程取桥）。"""
    global _DEPTH
    if _DEPTH <= 0:
        return
    mw = _get_mw()
    with _LOCK:
        _DEPTH -= 1
        if _DEPTH or mw is None:
            return
        for name in tools.TOOL_NAMES:
            mw._tools.pop(name, None)      # 中间件只有 register，没有 unregister


async def open_bridge():
    """连房间身体桥。没配、连不上、房间页不在线都返回 None：这一轮当没有身体。"""
    if tools is None or not BRIDGE_URL:
        return None
    bridge = StageBridge(BRIDGE_URL, token=BRIDGE_TOKEN or None, timeout=BRIDGE_TIMEOUT)
    try:
        await asyncio.wait_for(bridge.connect(), timeout=BRIDGE_TIMEOUT + 2)
    except Exception as exc:                      # noqa: BLE001
        logger.info(f"[jinyu] stage bridge unavailable: {type(exc).__name__}")
        await close_bridge(bridge)
        return None
    if not bridge.room_connected:
        logger.info("[jinyu] stage bridge has no room page, fallback to text")
        await close_bridge(bridge)
        return None
    return bridge


async def close_bridge(bridge) -> None:
    try:
        await bridge.close()
    except Exception:                             # noqa: BLE001
        pass


def _decoder():
    """后台解码器：独立实例，超时比后台归纳短；没配 key 返回 None。"""
    global _BODY_LLM
    if _BODY_LLM is None:
        try:
            llm = from_env("back")
        except ValueError:
            return None
        try:
            llm.timeout = BODY_INTENT_LLM_TIMEOUT
        except Exception:                          # noqa: BLE001
            pass
        _BODY_LLM = llm
    return _BODY_LLM


def _payload(result) -> str:
    try:
        return json.dumps(result, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(result)


def body_intent(args, sid, cid, ctx=None) -> str:
    """前台工具：一句自然语言 → 后台决定工具与参数 → 真执行 → 可读回执。"""
    intent_text = " ".join(str((args or {}).get("intent") or "").split())
    if not intent_text:
        return _payload(intent.failure(
            "invalid_argument", "front", "意图是空的，没有可执行的动作", intent_text))
    if not BODY_INTENT_ON:
        return _payload(intent.failure(
            "stage_unavailable", "bridge", "没有配置身体桥（RP_BRIDGE_URL）", intent_text))
    bridge = getattr(LOCAL, "bridge", None)
    loop = getattr(LOCAL, "loop", None)
    call_until, call_scene = _get_call()
    # 视频/房间回合自己就在现场，放行；其它回合在窗口期内直接拒绝，不排队、不打到页面
    if not (bridge is not None and loop is not None) and time.monotonic() < call_until:
        logger.info(f"[body] front intent={intent_text[:60]!r} -> blocked "
                    f"layer=host code=call_in_progress")
        return _payload(intent.failure(
            "call_in_progress", "host", f"主人正在和你{call_scene}，这次没有动身体", intent_text))
    llm = _decoder()
    if llm is None:
        return _payload(intent.failure(
            "back_unavailable", "back", "后台决策模型没配好（RP_BACK_KEY）", intent_text))
    if not intent.acquire():
        return _payload(intent.failure(
            "body_busy", "host", "上一段身体动作还没结束，这次没执行", intent_text))
    started = time.monotonic()
    result = None
    try:
        budget = BODY_INTENT_BUDGET
        round_deadline = float(getattr(LOCAL, "deadline", 0) or 0)
        if bridge is not None and round_deadline:  # 视频回合共用这一轮的时间预算
            budget = min(budget, max(0.0, round_deadline - started))
        if budget <= 1.0:
            result = intent.failure(
                "stage_deadline", "host", intent.explain("stage_deadline"), intent_text)
        elif bridge is not None and loop is not None:
            # 视频回合已经连好桥：直接复用，不另开连接、不换一套调用路径
            deadline = time.monotonic() + budget
            future = asyncio.run_coroutine_threadsafe(
                intent.act(bridge, llm, intent_text,
                           max_steps=BODY_INTENT_STEPS,
                           max_calls=BODY_INTENT_CALLS,
                           deadline=deadline), loop)
            try:
                result = future.result(timeout=budget + 5)
            except concurrent.futures.TimeoutError:
                future.cancel()
                result = intent.failure(
                    "client_timeout", "bridge",
                    "身体没有在预算内回执，动作可能没有做完", intent_text)
        else:
            # QQ / 桌宠回合：按需连一次桥，做完就关
            result = asyncio.run(intent.standalone(
                intent_text, llm, url=BRIDGE_URL, token=BRIDGE_TOKEN or None,
                timeout=BRIDGE_TIMEOUT, deadline=time.monotonic() + budget,
                max_steps=BODY_INTENT_STEPS, max_calls=BODY_INTENT_CALLS))
    except Exception as exc:                       # noqa: BLE001 链路异常也要可读回填
        logger.warning(f"[body] 意图执行异常 {type(exc).__name__}: {exc}")
        result = intent.failure(
            "stage_error", "bridge", f"身体动作链路异常（{type(exc).__name__}）", intent_text)
    finally:
        intent.release()
    result = result or intent.failure("internal", "page", "身体没有返回结果", intent_text)
    # body_intent 自己走完整条动作链，不经过 _handler；这里补记动作数，
    # 否则宿主接口会以为零动作而重跑，造成同一轮重复 sit。
    if getattr(LOCAL, "bridge", None) is not None and result.get("ok"):
        steps = len(result.get("did") or [])
        LOCAL.actions = int(getattr(LOCAL, "actions", 0) or 0) + max(1, steps)
    logger.info(
        f"[body] front intent={intent_text[:60]!r} -> ok={bool(result.get('ok'))} "
        f"layer={result.get('layer') or '-'} code={result.get('code') or 'ok'} "
        f"steps={len(result.get('did') or [])} "
        f"{int((time.monotonic() - started) * 1000)}ms")
    return _payload(result)


async def _run_bracket_action(bridge, press, lock, sid):
    started = time.monotonic()
    try:
        # 先让回复/语音回包；短延迟也给用户下一条指令留出抢会话锁的窗口
        await asyncio.sleep(BRACKET_DELAY_SECONDS)
        if lock.locked():
            logger.info(f"[bracket] drop reason=lock sid={sid} press={press.raw!r}")
            return
        llm = _decoder()
        if llm is None:
            logger.info(f"[bracket] drop reason=no_decoder press={press.raw!r}")
            return
        if not intent.acquire():
            logger.info(f"[bracket] drop reason=busy press={press.raw!r}")
            return
        try:
            result = await intent.act(
                bridge, llm, press.intent, max_steps=1, max_calls=1,
                deadline=time.monotonic() + BRACKET_BUDGET, origin="bracket")
        finally:
            intent.release()
        logger.info(f"[bracket] done ok={result.get('ok')} code={result.get('code')} "
                    f"steps={len(result.get('did') or [])} "
                    f"{int((time.monotonic() - started) * 1000)}ms press={press.raw!r}")
    except Exception as exc:                      # noqa: BLE001 只管记日志，不影响回复
        logger.warning(f"[bracket] failed {type(exc).__name__}: {exc}")
    finally:
        await close_bridge(bridge)


def spawn_bracket(bridge, press, lock, sid):
    try:
        task = asyncio.create_task(_run_bracket_action(bridge, press, lock, sid))
    except RuntimeError:                          # 事件循环已经关了，这一轮放弃
        return None
    _BRACKET_TASKS.add(task)
    task.add_done_callback(_BRACKET_TASKS.discard)
    return task
