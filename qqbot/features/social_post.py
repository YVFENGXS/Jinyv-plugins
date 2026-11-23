# -*- coding: utf-8 -*-
"""低频社交动作：个性签名 / QQ 空间说说。

从消息里摘出 [[sign:..]] / [[qzone:..]] 标记，默认不在聊天文字里出现；
只有管理员触发、受冷却与每日额度限制，失败静默。
"""
from __future__ import annotations

import re
import time
from datetime import date

from nonebot import get_bot, logger

import social_state
from config import ADMIN, QZONE_DAILY, QZONE_GAP, QZONE_ON, QZONE_RIGHT, SIGN_GAP, SIGN_ON

_SOCIAL_RE = re.compile(
    r"\[\[\s*(sign|qzone|签名|空间|说说)\s*[:：](.*?)\]\]", re.S | re.I)


def take_social(reply: str):
    """把 [[sign:..]] / [[qzone:..]] 从回复里摘掉，返回 (剩余文字, [(类型, 内容)])。"""
    posts = []

    def _grab(m):
        kind = m.group(1).lower()
        body = social_state.clip(m.group(2), 500, keep_lines=True)
        if body:
            posts.append(("sign" if kind in ("sign", "签名") else "qzone", body))
        return ""

    return _SOCIAL_RE.sub(_grab, reply or ""), posts


def post_hint() -> str:
    """给前台模型的签名/空间使用说明；两个功能都关掉时不追加。"""
    lines = []
    if SIGN_ON:
        lines.append(
            "- [[sign:一句新的个性签名]]：只有和主人聊到情绪激动、情真意切，"
            "或者你真心想留下点什么时才改；一天最多一次，平时绝对不要用")
    if QZONE_ON:
        lines.append(
            "- [[qzone:一条说说内容]]：只有你自己遇到特别有趣的事、或者想记录"
            "此刻的生活时才发；一天最多一条，没有这种冲动就不发")
    if not lines:
        return ""
    return ("\n\n【签名与QQ空间——极少数才用】\n" + "\n".join(lines)
            + "\n这两个标记会自动执行，不会出现在聊天文字里；不要为了用而用。")


async def change_sign(body: str, event) -> bool:
    """改签名：只认管理员触发，且受冷却与内容去重限制。"""
    if not SIGN_ON or event is None:
        return False
    if str(getattr(event, "user_id", "")) not in ADMIN:
        logger.info("[jinyu] 签名改动被忽略：不是管理员触发")
        return False
    text = social_state.clip(body, 100)
    if not text or text == social_state.STATE.get("sign_text"):
        return False
    now = time.time()
    if now - float(social_state.STATE.get("sign_at") or 0.0) < SIGN_GAP:
        logger.info("[jinyu] 签名改动被忽略：还在冷却期")
        return False
    bot = get_bot()
    await bot.call_api("set_self_longnick", longNick=text)
    social_state.STATE.update({"sign_at": now, "sign_text": text})
    social_state.save()
    logger.info(f"[jinyu] 个性签名已更新：{text}")
    return True


async def post_qzone(body: str) -> bool:
    """发说说：每日条数与最小间隔双限，失败由调用方静默。"""
    if not QZONE_ON or QZONE_DAILY <= 0:
        return False
    text = social_state.clip(body, 500, keep_lines=True)
    if not text or text == social_state.STATE.get("qzone_text"):
        return False
    now = time.time()
    today = date.today().isoformat()
    if social_state.STATE.get("qzone_day") != today:
        social_state.STATE.update({"qzone_day": today, "qzone_count": 0})
    if int(social_state.STATE.get("qzone_count") or 0) >= QZONE_DAILY:
        logger.info("[jinyu] 说说被忽略：今天的额度已用完")
        return False
    if now - float(social_state.STATE.get("qzone_at") or 0.0) < QZONE_GAP:
        logger.info("[jinyu] 说说被忽略：还没到最小间隔")
        return False
    bot = get_bot()
    await bot.call_api("send_qzone_msg", content=text, images=[],
                       ugc_right=QZONE_RIGHT)
    social_state.STATE.update({
        "qzone_at": now,
        "qzone_count": int(social_state.STATE.get("qzone_count") or 0) + 1,
        "qzone_text": text,
    })
    social_state.save()
    logger.info(f"[jinyu] 已发QQ空间说说（ugc_right={QZONE_RIGHT}）：{text[:60]}")
    return True


async def run_social(kind: str, body: str, event) -> bool:
    try:
        if kind == "sign":
            return bool(await change_sign(body, event))
        return bool(await post_qzone(body))
    except Exception as exc:                    # noqa: BLE001  签名/说说失败不能影响聊天
        logger.warning(f"[jinyu] {kind} 执行失败: {exc}")
        return False
