# -*- coding: utf-8 -*-
"""提醒类工具：把模型意图转成 reminder 模块的登记 / 查询 / 修改 / 取消。

只做参数规整与回执措辞，调度与持久化仍在 reminder.py。
"""
from __future__ import annotations

from nonebot import logger

import reminder


def reminder_uid(sid: str, ctx=None) -> int:
    """当前会话对应的 QQ 号：工具里拿不到 ctx 时从 qq-u<uid> 会话号兜底。"""
    ctx = ctx or {}
    uid = int(ctx.get("user_id") or 0)
    if not uid and str(sid).startswith("qq-u"):
        try:
            uid = int(str(sid)[4:])
        except ValueError:
            uid = 0
    return uid


def tool_set_reminder(args, sid, cid, ctx=None) -> str:
    """工具 set_reminder：由模型判断「该不该提醒」，正则只留兜底。"""
    ctx = ctx or {}
    uid = reminder_uid(sid, ctx)
    gid = int(ctx.get("group_id") or 0)
    if not reminder.ready() or not uid:
        return "当前场景无法登记提醒。"
    plan = reminder.schedule_text(str((args or {}).get("when") or ""),
                                  str((args or {}).get("what") or ""),
                                  sid, uid, gid)
    if not plan.get("ok"):
        return str(plan.get("error") or "提醒登记失败。")
    if ctx is not None:                     # 标记这轮已由工具处理，正则不再兜底
        ctx["reminded"] = True
    label = plan.get("repeat_label") or ""
    logger.info(f"[jinyu] 工具登记提醒 sid={sid} 用户={uid} 当={plan['when']} "
                f"重复={label or '无'} 内容={plan.get('content')!r}")
    head = f"已登记（{label}）" if label else "已登记"
    return f"{head}：{plan.get('content') or '到点提醒'}，将在 {plan['when']} 提醒。"


def tool_list_reminders(args, sid, cid, ctx=None) -> str:
    """列出待办提醒：模型自查名额、拿编号去改或删。"""
    uid = reminder_uid(sid, ctx)
    if not reminder.ready() or not uid:
        return "当前场景看不到提醒。"
    rows = reminder.list_pending(uid)
    if not rows:
        return f"现在没有待办提醒（0/{reminder.MAX_PENDING}）。"
    lines = []
    for r in rows:
        tag = reminder.repeat_label(r.get("repeat"))
        what = str(r.get("text") or "（提醒一下）")[:40]
        lines.append(f"#{r['id']} {reminder.fmt_when(r['due_ts'])}"
                     + (f"【{tag}】" if tag else "") + f" {what}")
    return f"待办提醒 {len(rows)}/{reminder.MAX_PENDING}：\n" + "\n".join(lines)


def tool_edit_reminder(args, sid, cid, ctx=None) -> str:
    """改一条待办的内容或时间；编号来自 list_reminders。"""
    uid = reminder_uid(sid, ctx)
    if not reminder.ready() or not uid:
        return "当前场景改不了提醒。"
    try:
        rid = int((args or {}).get("id") or 0)
    except (TypeError, ValueError):
        rid = 0
    if not rid:
        return "id 要填数字，先用 list_reminders 查编号。"
    res = reminder.update(uid, rid,
                          when=str((args or {}).get("when") or ""),
                          text=str((args or {}).get("what") or ""))
    if not res.get("ok"):
        return str(res.get("error") or "没改成。")
    tag = reminder.repeat_label(res.get("repeat"))
    return (f"已改 #{rid}：{res.get('text') or '（提醒一下）'}"
            f"｜{res.get('when')}" + (f"（{tag}）" if tag else ""))


def tool_cancel_reminder(args, sid, cid, ctx=None) -> str:
    """取消一条或全部待办，立刻释放名额。"""
    uid = reminder_uid(sid, ctx)
    if not reminder.ready() or not uid:
        return "当前场景取消不了提醒。"
    if bool((args or {}).get("all")):
        return reminder.cancel(uid, "all")
    try:
        rid = int((args or {}).get("id") or 0)
    except (TypeError, ValueError):
        rid = 0
    if not rid:
        return "id 要填数字，先用 list_reminders 查编号；清空就传 all=true。"
    return reminder.cancel(uid, str(rid))
