# -*- coding: utf-8 -*-
"""管理指令层：/memory、/merge、/social、贴纸/语音管理等人力运维入口。

指令本身绕过模型，直接读写记忆与贴纸库；报告函数也被自主作息工具复用，
所以它们通过 configure() 读取模型指针与会话辅助，不反向 import 组合根。
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timezone

from nonebot import logger
from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    Message,
    MessageEvent,
    MessageSegment,
)

import autonomy as autonomy_mod
from config import ADMIN, AUTONOMY_ON, CID, EPOCH_FLUSH, EPOCH_SECONDS
from media import _img_at_switch, img_at_only
from persona import PERSONA
import persona as persona_mod
import promise as promise_mod
import retention as retention_mod
from richmsg import (
    DOWNLOAD_LIMIT,
    add_tags,
    delete_sticker,
    download_image,
    fix_sticker,
    image_search,
    image_segment,
    list_stickers,
    list_tags,
    pick_sticker,
    remove_tag,
    rich_enabled,
    save_and_tag,
    sticker_dir,
    tts_audio,
    url_is_public,
)
import status as status_mod

_PERSONA_TAG = re.compile(r"(?<![A-Za-z0-9_])([A-Z][A-Z0-9_]{3,})(?![A-Za-z0-9_])")


def sticker_message(path):
    if not path:
        return None
    seg = image_segment(path)
    return Message(seg) if seg else None


_get_mw = lambda: None                                    # noqa: E731  由组合根注入
_get_sid = lambda event: ""                               # noqa: E731
_get_social_on = lambda: False                            # noqa: E731
_base_sid = lambda sid: sid                               # noqa: E731
_social_switch = None
_social_report = None
_locks: dict = {}
_last_media: dict = {}
SOCIAL_SID = "qq-social"


def configure(*, get_mw, get_sid, get_social_on, base_sid, social_sid,
              social_switch, social_report, locks, last_media) -> None:
    """注入组合根的运行期指针与会话辅助。"""
    global _get_mw, _get_sid, _get_social_on, _base_sid, SOCIAL_SID
    global _social_switch, _social_report, _locks, _last_media
    _get_mw = get_mw
    _get_sid = get_sid
    _get_social_on = get_social_on
    _base_sid = base_sid
    SOCIAL_SID = social_sid
    _social_switch = social_switch
    _social_report = social_report
    _locks = locks
    _last_media = last_media


def _persona_report(event: MessageEvent) -> str:
    """当前会话实际生效的人设：词条、正文、禁忌与附加规则（只读）。"""
    core = str(PERSONA.get("core") or "")
    tags: list[str] = []
    # 词条还包括 persona.py 头部的【PERSONA_LOAD】清单（如 CETACEA_LOLI）
    for tag in _PERSONA_TAG.findall((persona_mod.__doc__ or "") + core):
        if tag != "PERSONA_LOAD" and tag not in tags:   # 头部标签不是人设词条
            tags.append(tag)
    extra = []
    if rich_enabled():
        extra.append("富消息说明（图片/贴纸/语音/搜图标记）")
    if _get_social_on():
        extra.append("社交圈模式（全局一份记忆、按人记词条与好感度）")
    elif isinstance(event, GroupMessageEvent):
        extra.append("群聊模式（说话人前缀、按昵称互动）")
    parts = [
        f"【当前会话】{_get_sid(event)}｜角色={PERSONA.get('name') or '?'}"
        f"｜{'群聊' if isinstance(event, GroupMessageEvent) else '私聊'}",
        f"【角色词条】{' / '.join(tags) or '无'}",
        "【人设正文】\n" + core,
    ]
    if PERSONA.get("taboo_words"):
        parts.append("【禁忌词】" + "、".join(map(str, PERSONA["taboo_words"])))
    if PERSONA.get("forbidden_punct"):
        parts.append("【禁用标点】" + "".join(map(str, PERSONA["forbidden_punct"])))
    parts.append(f"【风格】{PERSONA.get('style') or '默认'}")
    parts.append("【附加规则】" + ("、".join(extra) if extra else "无"))
    return "\n".join(parts)


def _owner_label(base: str) -> str:
    """qq-u123456 -> 私聊 123456；qq-g789 -> 群 789；qq-social -> 社交圈（全局）。"""
    b = _base_sid(base)
    if b == SOCIAL_SID:
        return "社交圈（全局）"
    if b.startswith("qq-g"):
        return f"群 {b[4:]}"
    if b.startswith("qq-u"):
        return f"私聊 {b[4:]}"
    if b.startswith("bili-l"):
        return f"B站直播间 {b[6:]}"
    return b or "未知会话"


def _fact_line(row, with_owner=False) -> str:
    try:
        tag_list = json.loads(row["tags"] or "[]")
    except (TypeError, ValueError):
        tag_list = []
    owner = ""
    if with_owner:
        owner = f"[{_owner_label(str(row['session_id']).split('#')[0])}] "
    line = (f"#{row['id']} {owner}[{row['category'] or '未分类'} "
            f"{float(row['importance'] or 0):.2f}]")
    if tag_list:
        line += " " + "/".join(map(str, tag_list))
    speaker = str(row["speaker"] or "") if "speaker" in row.keys() else ""
    if speaker:
        line += f"（{speaker}）"
    return line + " → " + str(row["fact"])


def _card_when(card) -> str:
    """事件卡 UTC 时间 → 本地「月-日」；坏值给空串。"""
    try:
        return datetime.strptime(str(card.get("created_at") or "")[:19],
                                 "%Y-%m-%d %H:%M:%S") \
            .replace(tzinfo=timezone.utc).astimezone().strftime("%m-%d")
    except (TypeError, ValueError):
        return ""


def _short_id(eid) -> str:
    return str(eid or "")[:8]


def _card_line(card, with_owner=False) -> str:
    owner = (f"[{_owner_label(str(card['session_id']).split('#')[0])}] "
             if with_owner else "")
    body = str(card.get("summary") or "").replace("\n", " ")
    shown = body[:60] + ("…" if len(body) > 60 else "")
    return (f"#{_short_id(card.get('event_id'))} {owner}"
            f"({_card_when(card) or '—'} t{card['turn_start']}-{card['turn_end']}) {shown}")


def _cards_report(cid: str, sid: str, page: int, keyword: str) -> str:
    """事件卡列表：只列当前 epoch，合并/编辑都落在这一层。"""
    size = 8
    mw = _get_mw()
    rows, total = mw.db.card_page(sid, cid, (page - 1) * size, size, keyword)
    pages = max(1, (total + size - 1) // size)
    title = (f"搜索「{keyword}」" if keyword
             else _owner_label(str(sid).split("#")[0]))
    head = f"【事件卡】{title}｜{total} 张｜第 {min(page, pages)}/{pages} 页"
    if not rows:
        return head + "\n没有匹配的事件卡。"
    out = head + "\n" + "\n".join(_card_line(c) for c in rows)
    if not keyword and page < pages:
        out += f"\n下一页：/memory cards {page + 1}"
    return (out + "\n查看：/memory card 编号（行首 # 后 8 位）"
            "\n改：/memory card edit 编号 新正文｜删：/memory card del 编号"
            "\n补：/memory card add 正文｜全部会话：/memory cards all")


def _card_ref_problem(cards, ref: str) -> str:
    if not cards:
        return f"没找到事件卡 {ref}（编号见 /memory cards 行首 #）。"
    return ("编号前缀不唯一，请多写几位：\n"
            + "\n".join(f"- {c['event_id']}" for c in cards))


def _card_detail(cid: str, ref: str) -> str:
    mw = _get_mw()
    cards = mw.db.find_cards(ref, cid)
    if len(cards) != 1:
        return _card_ref_problem(cards, ref)
    c = cards[0]
    hooks = "、".join(str(h) for h in (c.get("entity_hooks") or [])) or "无"
    pinned = "是（会跨会话注入）" if mw.db.is_pinned(c["event_id"]) else "否"
    return (f"【事件卡】{c['event_id']}\n"
            f"会话：{_owner_label(str(c['session_id']).split('#')[0])}\n"
            f"时间：{_card_when(c) or '—'}｜轮次 t{c['turn_start']}-{c['turn_end']}｜"
            f"重要度 {float(c.get('importance') or 0.5):.2f}\n"
            f"边界：{c.get('knowledge_boundary') or 'both'}｜置顶：{pinned}\n"
            f"正文：{c['summary']}\n"
            f"钩子：{hooks}\n"
            f"改：/memory card edit {_short_id(c['event_id'])} 新正文")


def _card_edit(cid: str, ref: str, text: str) -> str:
    mw = _get_mw()
    text = text.strip()
    if not text:
        return "用法：/memory card edit 编号 新正文"
    cards = mw.db.find_cards(ref, cid)
    if len(cards) != 1:
        return _card_ref_problem(cards, ref)
    old, ok = mw.db.update_card(cards[0]["event_id"], cid, text[:200])
    if not ok:
        return f"没找到事件卡 {ref}，可能已经删过了。"
    return (f"已修改事件卡 #{_short_id(cards[0]['event_id'])}（向量会按新正文重算）\n"
            f"原：{str(old)[:60]}\n新：{text[:100]}")


def _card_delete(cid: str, ref: str) -> str:
    mw = _get_mw()
    cards = mw.db.find_cards(ref, cid)
    if len(cards) != 1:
        return _card_ref_problem(cards, ref)
    body, ok = mw.db.delete_card(cards[0]["event_id"], cid)
    if not ok:
        return f"没找到事件卡 {ref}，可能已经删过了。"
    return (f"已删除事件卡 #{_short_id(cards[0]['event_id'])}「{str(body)[:50]}」\n"
            "置顶与向量一起清理。")


def _card_add(cid: str, sid: str, text: str) -> str:
    mw = _get_mw()
    text = text.strip()
    if not text:
        return "用法：/memory card add 正文（把一件该记住的事补进事件卡）"
    turn = mw.db.next_turn(sid, cid)
    eid = mw.db.add_card(sid, cid, text[:200], turn)
    return (f"已补一张事件卡 #{_short_id(eid)}（t{turn}，钩子已自动提取）\n"
            f"正文：{text[:100]}\n查看：/memory card {_short_id(eid)}")


def _fact_edit(cid: str, ref: str, text: str) -> str:
    mw = _get_mw()
    raw = str(ref or "").lstrip("#")
    if not raw.isdigit():
        return f"「{ref}」不是编号，例如 /memory edit 142 新正文"
    text = text.strip()
    if not text:
        return "用法：/memory edit 142 新正文"
    old, n = mw.db.update_fact(int(raw), cid, text[:160])
    if not old and not n:
        return f"没找到 #{raw}，可能已经删过了。"
    if not n:
        return (f"#{raw} 改成这句会和另一条词条重复，未修改：\n"
                f"原句：{old}\n想改的：{text[:100]}")
    return (f"已修改 #{raw}（含 epoch 副本 {n} 条）\n"
            f"原：{old[:60]}\n新：{text[:100]}")


def _fact_add(cid: str, sid: str, text: str) -> str:
    mw = _get_mw()
    text = text.strip()
    if not text:
        return "用法：/memory add 正文（补一条长期有效的设定/事实）"
    turn = mw.db.next_turn(sid, cid)
    fid = mw.db.add_fact(sid, cid, text[:160], turn)
    if not fid:
        return "这条已经存在（同会话同说话人），没有重复添加。"
    return (f"已新增词条 #{fid}（t{turn}）\n{text[:100]}\n"
            f"删除：/memory del {fid}｜修改：/memory edit {fid} 新正文")


def _log_detail(row) -> str:
    card = row.get("kind") == "card"
    kind = "事件卡" if card else "词条"
    lines = [f"【合并记录 #{row['id']}】{kind}｜"
             f"{_owner_label(str(row.get('session_id') or '').split('#')[0])}",
             f"时间：{row.get('created_at') or '—'}",
             f"合并后：{row.get('merged') or ''}",
             "来源："]
    for s in row.get("sources") or []:
        if card:
            mark = "（保留）" if s.get("event_id") == row.get("keep_id") else ""
            body = str(s.get("summary") or "").replace("\n", " ")
            lines.append(f"- {_short_id(s.get('event_id'))} {s.get('date') or '—'} "
                         f"t{s.get('turn_start')}-{s.get('turn_end')}{mark} {body[:80]}")
        else:
            mark = "（保留）" if str(s.get("id")) == str(row.get("keep_id")) else ""
            body = str(s.get("fact") or "").replace("\n", " ")
            lines.append(f"- #{s.get('id')} {s.get('date') or '—'} "
                         f"t{s.get('turn_end')}{mark} {body[:80]}")
    if card:
        lines.append(f"查看保留卡：/memory card {_short_id(row.get('keep_id'))}")
    else:
        lines.append(f"查看/修改保留词条：/memory edit {row.get('keep_id')} 新正文")
    return "\n".join(lines)


def _log_report(cid: str, arg: str) -> str:
    """合并记录：列表 + 单条详情；合并掉的原卡原文都存在这里。"""
    mw = _get_mw()
    arg = str(arg or "").strip()
    if arg:
        raw = arg.lstrip("#")
        if not raw.isdigit():
            return "用法：/memory log（列表）｜/memory log 12（看第 12 条详情）"
        row = mw.db.get_merge_log(int(raw), cid)
        if not row:
            return f"没有合并记录 #{raw}。"
        return _log_detail(row)
    rows, total = mw.db.merge_logs(cid, offset=0, limit=10)
    if not rows:
        return "【合并记录】还没有合并过任何东西。"
    lines = []
    for r in rows:
        kind = "事件卡" if r.get("kind") == "card" else "词条"
        n = len(r.get("sources") or []) if isinstance(r.get("sources"), list) else 0
        if isinstance(r.get("sources"), str):
            try:
                n = len(json.loads(r["sources"] or "[]"))
            except (TypeError, ValueError):
                n = 0
        merged = str(r.get("merged") or "").replace("\n", " ")
        shown = merged[:40] + ("…" if len(merged) > 40 else "")
        lines.append(f"#{r['id']} {kind}｜"
                     f"{_owner_label(str(r.get('session_id') or '').split('#')[0])}｜"
                     f"{str(r.get('created_at') or '')[5:16]}｜{n} 条并成「{shown}」")
    return (f"【合并记录】共 {total} 条｜最近 {len(rows)} 条\n"
            + "\n".join(lines)
            + "\n详情：/memory log 编号（看被合并的原文）")


def _memory_page(cid: str, base: str, page: int, keyword: str, nav: str) -> str:
    """第二层：某个会话的词条分页；nav 为空表示全局搜索。"""
    mw = _get_mw()
    size = 10
    rows, total = mw.db.dump_facts(cid, base, keyword, (page - 1) * size, size)
    pages = max(1, (total + size - 1) // size)
    title = _owner_label(base) if nav else f"全局搜索「{keyword}」"
    head = f"【记忆词条】{title}｜{total} 条｜第 {min(page, pages)}/{pages} 页"
    if not rows:
        return head + "\n没有匹配的词条。"
    out = head + "\n" + "\n".join(_fact_line(r, with_owner=not nav) for r in rows)
    if nav and page < pages:
        out += f"\n下一页：{nav} {page + 1}"
    return out + ("\n删除：/memory del 编号｜修改：/memory edit 编号 新正文"
                  "（编号见行首 #）")


def _memory_report(arg: str, sid: str) -> str:
    """管理员 /memory：词条与事件卡的查看、搜索、增删改，以及合并记录。

    /memory                    全局会话列表
    /memory 1                  第 1 个会话的词条
    /memory 1 2                第 1 个会话的第 2 页
    /memory 1 猫               在第 1 个会话里搜「猫」
    /memory 猫                 全局搜「猫」
    /memory del 142            删除词条 #142（连同跨 epoch 副本）
    /memory edit 142 新正文    修改词条 #142
    /memory add 正文           新增一条长期词条
    /memory cards [页|词]      当前会话的事件卡
    /memory cards all          所有会话的事件卡数量
    /memory card <编号>        查看某张事件卡（编号可只写前缀）
    /memory card edit <编号> 新正文
    /memory card del <编号>
    /memory card add 正文
    /memory log [编号]         合并记录列表 / 详情
    """
    mw = _get_mw()
    cid, parts = CID, arg.split()
    head = parts[0].lower() if parts else ""
    if head in ("del", "删除", "删"):
        return _memory_delete(parts[1:])
    if head in ("edit", "改", "修改"):
        if len(parts) < 3:
            return "用法：/memory edit 142 新正文"
        return _fact_edit(cid, parts[1], " ".join(parts[2:]))
    if head in ("add", "新增", "补"):
        return _fact_add(cid, sid, " ".join(parts[1:]))
    if head in ("log", "记录", "合并记录"):
        return _log_report(cid, " ".join(parts[1:]))
    if head in ("cards", "卡片", "事件卡"):
        rest = parts[1:]
        if rest and rest[0].lower() in ("all", "全部", "会话"):
            owners = mw.db.card_owners(cid)
            if not owners:
                return "【事件卡】还没有任何事件卡。"
            total = sum(int(o["n"]) for o in owners)
            lines = [f"{i}. {_owner_label(o['base'])} · {o['n']} 张"
                     for i, o in enumerate(owners, 1)]
            return (f"【事件卡】{len(owners)} 个会话｜合计 {total} 张\n"
                    + "\n".join(lines)
                    + "\n查看当前会话：/memory cards")
        page = int(rest[0]) if rest and rest[0].isdigit() else 1
        keyword = "" if (not rest or rest[0].isdigit()) else " ".join(rest)
        return _cards_report(cid, sid, max(1, page), keyword)
    if head in ("card", "卡"):
        rest = parts[1:]
        if not rest:
            return ("用法：/memory card 编号｜edit 编号 新正文｜del 编号｜add 正文")
        sub = rest[0].lower()
        if sub in ("add", "新增", "补"):
            return _card_add(cid, sid, " ".join(rest[1:]))
        if sub in ("del", "删除", "删"):
            return _card_delete(cid, rest[1] if len(rest) > 1 else "")
        if sub in ("edit", "改", "修改"):
            if len(rest) < 3:
                return "用法：/memory card edit 编号 新正文"
            return _card_edit(cid, rest[1], " ".join(rest[2:]))
        return _card_detail(cid, rest[0])
    if not parts:
        owners = mw.db.fact_owners(cid)
        if not owners:
            return ("【记忆词条】还没有保存过任何长期事实。\n"
                    "事件卡：/memory cards｜合并记录：/memory log")
        total = sum(int(o["n"]) for o in owners)
        lines = [f"{i}. {_owner_label(o['base'])} · {o['n']} 条"
                 for i, o in enumerate(owners, 1)]
        return (f"【记忆词条】{len(owners)} 个会话｜合计 {total} 条\n"
                + "\n".join(lines)
                + "\n查看：/memory 1｜翻页：/memory 1 2｜全局搜索：/memory 猫"
                + "\n删除：/memory del 142｜修改：/memory edit 142 新正文"
                + "｜新增：/memory add 正文"
                + "\n事件卡：/memory cards｜合并记录：/memory log")
    if parts[0].isdigit():
        idx = int(parts[0])
        owners = mw.db.fact_owners(cid)
        if not 1 <= idx <= len(owners):
            return f"没有第 {idx} 个会话，先发 /memory 看列表。"
        rest = parts[1:]
        page = int(rest[0]) if rest and rest[0].isdigit() else 1
        keyword = "" if rest and rest[0].isdigit() else " ".join(rest)
        return _memory_page(cid, owners[idx - 1]["base"], max(1, page),
                            keyword, f"/memory {idx}")
    return _memory_page(cid, "", 1, " ".join(parts), "")


def _memory_delete(parts: list) -> str:
    """按编号删词条；同一句话跨 epoch 的副本一起删，避免轮换后又冒出来。"""
    mw = _get_mw()
    if not parts:
        return "用法：/memory del 142（编号见词条行首 #）"
    raw = parts[0].lstrip("#")
    if not raw.isdigit():
        return f"「{parts[0]}」不是编号，例如 /memory del 142"
    fact, n, base = mw.db.del_fact(int(raw))
    if not n:
        return f"没找到 #{raw}，可能已经删过了。"
    return (f"已删除 #{raw}「{str(fact)[:40]}」\n"
            f"所属 {_owner_label(base)}｜共清理 {n} 条（含 epoch 副本）")


def _merge_card_receipt(base: str, groups: list, applied: bool, start=0) -> list:
    """合并回执：每组标明保留哪张、每张来源卡的时间/轮次/原文。"""
    lines = []
    for i, g in enumerate(groups, 1):
        srcs = g.get("sources") or []
        tag = (f"（记录 #{g['log_id']}）"
               if applied and g.get("log_id") else "")
        lines.append(f"{start + i}) {_owner_label(base)}｜{len(srcs)} 张 → 保留 "
                     f"{_short_id(g.get('keep_id'))}{tag}")
        lines.append(f"   合并后：{g.get('summary') or ''}")
        for s in srcs[:6]:
            body = str(s.get("summary") or "").replace("\n", " ")
            shown = body[:50] + ("…" if len(body) > 50 else "")
            mark = "（保留）" if s.get("event_id") == g.get("keep_id") else ""
            lines.append(f"   - {_short_id(s.get('event_id'))} {s.get('date') or '—'} "
                         f"t{s.get('turn_start')}-{s.get('turn_end')}{mark} {shown}")
        if len(srcs) > 6:
            lines.append(f"   …其余 {len(srcs) - 6} 张见 /memory log "
                         f"{g.get('log_id') or ''}")
    return lines


def _merge_fact_receipt(base: str, groups: list, applied: bool, start=0) -> list:
    lines = []
    for i, g in enumerate(groups, 1):
        srcs = g.get("sources") or []
        tag = (f"（记录 #{g['log_id']}）"
               if applied and g.get("log_id") else "")
        lines.append(f"{start + i}) {_owner_label(base)}｜{len(srcs)} 条 → 保留 "
                     f"#{g.get('keep_id')}{tag}")
        lines.append(f"   合并后：{g.get('fact') or ''}")
        for s in srcs[:5]:
            body = str(s.get("fact") or "").replace("\n", " ")
            shown = body[:50] + ("…" if len(body) > 50 else "")
            mark = "（保留）" if str(s.get("id")) == str(g.get("keep_id")) else ""
            lines.append(f"   - #{s.get('id')} {s.get('date') or '—'} "
                         f"t{s.get('turn_end')}{mark} {shown}")
        if len(srcs) > 5:
            lines.append(f"   …其余 {len(srcs) - 5} 条见 /memory log "
                         f"{g.get('log_id') or ''}")
    return lines


async def _send_long(text: str, matcher, limit: int = 1200) -> None:
    """按行切成多条发送：合并回执动辄上千字，单条太长会被平台吞。"""
    parts, buf = [], ""
    for line in str(text).split("\n"):
        if buf and len(buf) + 1 + len(line) > limit:
            parts.append(buf)
            buf = line
        else:
            buf = f"{buf}\n{line}" if buf else line
    if buf:
        parts.append(buf)
    for p in parts:
        await matcher.send(p)


async def handle(event: MessageEvent, text: str, matcher) -> bool:
    """管理员自测/管理命令，绕过模型。"""
    mw = _get_mw()
    if not ADMIN or str(event.user_id) not in ADMIN:
        return False
    if not text.startswith("/"):
        return False
    cmd, _, arg = text[1:].partition(" ")
    arg = arg.strip()
    if cmd == "new":
        sid = _get_sid(event)
        lock = _locks.setdefault(sid, asyncio.Lock())
        async with lock:                   # 与正常回复串行，避免边聊边轮换
            new_sid = await asyncio.to_thread(
                mw.session_identity, sid, CID, EPOCH_SECONDS,
                force=True, flush_timeout=EPOCH_FLUSH)
        await matcher.finish(f"已开新会话（{new_sid}），长期事实和 strict 承诺已继承。")
        return True
    if cmd in ("persona", "人设"):
        await matcher.finish(_persona_report(event))
        return True
    if cmd in ("memory", "词条", "记忆"):
        base = _get_sid(event).split("#")[0]
        await matcher.finish(_memory_report(arg, mw.db.latest_sid(base, CID)))
        return True
    if cmd in ("plan", "计划"):
        if not (AUTONOMY_ON and autonomy_mod.ready()):
            await matcher.finish("自主作息没开（RP_AUTONOMY=0）。")
        report = await asyncio.to_thread(autonomy_mod.plan_text, arg)
        await matcher.finish(report or "这一天的计划还没生成。")
        return True
    if cmd in ("diary", "日记"):
        if not (AUTONOMY_ON and autonomy_mod.ready()):
            await matcher.finish("自主作息没开（RP_AUTONOMY=0）。")
        n = int(arg) if arg.isdigit() else 6
        report = await asyncio.to_thread(autonomy_mod.diary_text, n)
        await matcher.finish(report)
        return True
    if cmd in ("autonomy", "自主", "作息"):
        off = arg.lower() in ("off", "关", "pause", "暂停")
        on = arg.lower() in ("on", "开", "resume", "恢复")
        if on:
            if not AUTONOMY_ON:
                await matcher.finish("自主作息总开关没开（RP_AUTONOMY=0），"
                                     "先在 .env 设 1 再重启。")
                return True
            if not autonomy_mod.ready():
                await matcher.finish("自主作息还没初始化，先看启动日志。")
                return True
            autonomy_mod.pause(False)
            await matcher.finish("自主作息已恢复：报点、醒来、日计划按原计划继续。")
            return True
        if off:
            if not autonomy_mod.ready():
                await matcher.finish("自主作息没开（RP_AUTONOMY=0）。")
                return True
            autonomy_mod.pause(True)
            await matcher.finish("自主作息已暂停：醒来、报点、日计划都停，"
                                 "状态已写入 autonomy.db；/autonomy on 恢复。")
            return True
        if not (AUTONOMY_ON and autonomy_mod.ready()):
            await matcher.finish("自主作息没开（RP_AUTONOMY=0）。")
        report = await asyncio.to_thread(autonomy_mod.status)
        await matcher.finish(report)
        return True
    if cmd in ("compress", "压缩"):
        if arg in ("on", "开"):
            await matcher.finish("压缩开关由 .env 的 RP_COMPRESSION_ENABLED 控制，改完重启生效。")
        if arg in ("prune", "清理"):
            result = await asyncio.to_thread(
                retention_mod.prune, mw.db, CID)
            await matcher.finish(f"原文保留清理：软归档 {result['archived']} 轮，"
                                 f"无洞 pin {result['pinned']} 条。")
        report = await asyncio.to_thread(status_mod.report_text, mw.db, CID)
        await matcher.finish(report)
        return True
    if cmd == "voice" and arg:
        audio = await tts_audio(arg)
        if not audio:
            await matcher.finish("语音合成失败，看日志。")
        await matcher.send(Message(MessageSegment.record(audio.resolve().as_uri())))
        return True
    if cmd == "img" and arg:
        if not arg.startswith(("http://", "https://")):
            await matcher.finish("只支持 http/https 图片直链。")
        loop = asyncio.get_running_loop()
        if not await loop.run_in_executor(None, url_is_public, arg):
            await matcher.finish("这个地址不是公网图片直链。")
        await matcher.send(Message(MessageSegment.image(arg)))
        return True
    if cmd == "find" and arg:
        url = await asyncio.get_running_loop().run_in_executor(None, image_search, arg)
        if not url:
            await matcher.finish("搜图没拿到结果，换个词试试。")
        await matcher.send(Message(MessageSegment.image(url)))
        return True
    if cmd == "sticker":
        msg = sticker_message(pick_sticker(arg, allow_empty_random=True))
        if msg is None:
            await matcher.finish("贴纸库是空的，把 gif/png 放进 RP_STICKER_DIR 再试。")
        await matcher.send(msg)
        return True
    if cmd == "save":
        url = _last_media.get(_get_sid(event))
        if not url:
            await matcher.finish("这个会话里还没出现过图片，先发一张再 /save 标签1 标签2。")
        tags = [t for t in arg.replace("，", " ").split() if t]
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(None, download_image, url)
        if not data:
            await matcher.finish("下载原图失败，这张图可能已过期。")
        # 管理员手动收藏：跳过每日自动配额，也不消耗自动收藏额度
        path = await loop.run_in_executor(None, save_and_tag, data, tags, True)
        if path is None:
            await matcher.finish(
                f"入库失败（文件格式不支持或超过 {DOWNLOAD_LIMIT // (1024 * 1024)}MB）。")
        await matcher.finish(f"已收藏 {path.name}，标签：{' '.join(tags) or '（视觉自动打标）'}")
        return True
    if cmd == "tags":
        counts = list_tags()
        if not counts:
            await matcher.finish("贴纸库还是空的。")
        items = sorted(counts.items(), key=lambda kv: -kv[1])[:60]
        await matcher.finish("贴纸标签：" + "、".join(f"{t}({n})" for t, n in items))
        return True
    if cmd == "list":
        parts = arg.split()
        page = 1
        if parts and parts[-1].isdigit():     # /list 开心 2 → 第 2 页
            page = max(1, int(parts.pop()))
        kw = " ".join(parts)
        items = list_stickers(kw)
        if not items:
            await matcher.finish("没有匹配的贴纸（可加标签过滤，如 /list 开心）。")
        per = 30
        pages = (len(items) + per - 1) // per
        page = min(page, pages)
        chunk = items[(page - 1) * per:page * per]
        head = (f"共 {len(items)} 张" + (f"，按“{kw}”过滤" if kw else "")
                + f"｜第 {page}/{pages} 页")
        lines = [f"{n}  [{'、'.join(t) or '无标签'}]" for n, t in chunk]
        nav = []
        if page > 1:
            nav.append(f"/list {kw} {page - 1}".replace("  ", " "))
        if page < pages:
            nav.append(f"/list {kw} {page + 1}".replace("  ", " "))
        tail = ("\n翻页：" + "｜".join(nav)) if nav else ""
        await matcher.finish(head + "\n" + "\n".join(lines) + tail
                             + "\n删除 /del 文件名；预览 /show 文件名；改判读 /fix 文件名 角色=…")
        return True
    if cmd == "show":
        items = list_stickers(arg)
        if not items:
            await matcher.finish("没有匹配的贴纸。")
        name, tags = items[0]
        msg = sticker_message(sticker_dir() / name)
        if msg is None:
            await matcher.finish("文件读不出来，可能太大或已损坏。")
        await matcher.send(msg)
        await matcher.finish(f"{name}  [{'、'.join(tags) or '无标签'}]"
                             + (f"（共 {len(items)} 个匹配）" if len(items) > 1 else ""))
        return True
    if cmd == "del":
        if not arg:
            await matcher.finish("用法：/del 文件名（文件名用 /list 查）。")
        exact = delete_sticker(arg)
        if exact:
            await matcher.finish(f"已删除 {arg}")
        items = list_stickers(arg)
        if not items:
            await matcher.finish("没找到这个文件，用 /list 查确切文件名。")
        if len(items) == 1:
            name, tags = items[0]
            delete_sticker(name)
            await matcher.finish(f"已删除 {name}  [{'、'.join(tags) or '无标签'}]")
        lines = [n for n, _ in items[:10]]
        await matcher.finish(f"“{arg}”匹配到 {len(items)} 张，请用文件名精确删除：\n"
                             + "\n".join(lines))
        return True
    if cmd == "tag":
        parts = arg.split()
        if len(parts) < 2:
            await matcher.finish("用法：/tag 文件名 标签1 标签2（给贴纸加标签）")
        name, tags = parts[0], parts[1:]
        if not add_tags(name, tags):
            await matcher.finish("失败：文件不存在（用 /list 查）或没给标签。")
        await matcher.finish(f"已给 {name} 加标签：{'、'.join(tags)}")
        return True
    if cmd == "untag":
        parts = arg.split()
        if len(parts) != 2:
            await matcher.finish("用法：/untag 文件名 标签（删掉一个标签，文件保留）")
        if not remove_tag(parts[0], parts[1]):
            await matcher.finish("失败：文件名或标签不存在（用 /list 查）。")
        await matcher.finish(f"已从 {parts[0]} 移除标签“{parts[1]}”")
        return True
    if cmd in ("fix", "改tag", "纠错"):
        # 纠正视觉误判：/fix 文件名或标签 角色=xxx / 标签=a,b / 描述=xxx
        # 这些词会进贴纸的 tags.json 和 meta.json，后台以后挑贴纸/描述都用新值。
        fields = {"角色": "character", "character": "character",
                  "描述": "desc", "desc": "desc",
                  "标签": "tags", "tags": "tags"}
        opts, target = {}, ""
        for part in arg.split():
            if "=" in part:
                k, v = part.split("=", 1)
                opts[k.strip()] = v.strip()
            elif not target:
                target = part
        bad = [k for k in opts if k not in fields]
        if not target or not opts or bad:
            await matcher.finish(
                "用法：/fix 文件名或标签 角色=正确角色｜角色=（表示认不出是谁）\n"
                "　　　/fix 文件名 标签=开心,无语 描述=画面内容\n"
                "先用 /list 初音 查文件名，/show 文件名 看图和现有标签。")
        name = os.path.basename(target)
        if (sticker_dir() / name).is_file():
            items = [(name, [])]
        else:
            items = list_stickers(target)
        if not items:
            await matcher.finish(f"没找到“{target}”，先用 /list 查确切文件名。")
        if len(items) > 1:
            await matcher.finish(f"“{target}”匹配到 {len(items)} 张，请用文件名精确指定：\n"
                                 + "\n".join(n for n, _ in items[:10]))
        name = items[0][0]
        kw = {}
        for k, v in opts.items():
            field = fields[k]
            if field == "tags":
                kw["tags"] = [t for t in re.split(r"[,，、\s]+", v) if t]
            else:
                kw[field] = v
        res = fix_sticker(name, **kw)
        if not res:
            await matcher.finish("修正失败：文件不存在。")
        done = []
        if "character" in kw:
            done.append("角色=" + (kw["character"] or "（空）"))
        if "desc" in kw:
            done.append("描述已更新")
        if "tags" in kw:
            done.append("标签已重设")
        await matcher.finish(f"已修正 {name}：{'、'.join(done)}\n"
                             f"当前标签：{'、'.join(res[1]) or '无'}\n"
                             "同一张图再发会直接用新结果；已写进长期记忆的旧说法用 /memory del 清。")
        return True
    if cmd in ("social", "社交圈"):
        act = (arg.split() or [""])[0].lower()
        if act in ("on", "开", "开启"):
            try:
                await asyncio.to_thread(_social_switch, True)
            except Exception as exc:                # noqa: BLE001  建库失败不能切半截
                logger.exception(f"[jinyu] 社交圈开启失败: {exc}")
                await matcher.finish(f"社交圈开启失败：{exc}")
            await matcher.finish(
                "社交圈模式已开启：所有群和私聊共用一份记忆（独立记忆库，"
                "不与原来的记忆合并），按人记录词条和好感度。")
        if act in ("off", "关", "关闭"):
            await asyncio.to_thread(_social_switch, False)
            await matcher.finish("社交圈模式已关闭：回到每个群/私聊各自分离的记忆。")
        await matcher.finish(await asyncio.to_thread(_social_report))
        return True
    if cmd in ("imgat", "群图"):
        act = (arg.split() or [""])[0].lower()
        if act in ("on", "开", "开启", "只at", "只@"):
            await asyncio.to_thread(_img_at_switch, True)
            await matcher.finish(
                "已开启：群聊只分析被 @ 消息里的图片；没被 @ 的图不下载、不判读、"
                "不进表情包库（省视觉 token）。私聊不受影响。")
        if act in ("off", "关", "关闭", "全部"):
            await asyncio.to_thread(_img_at_switch, False)
            await matcher.finish("已关闭：群聊里所有图片都会下载/判读（恢复旧行为）。")
        await matcher.finish(
            f"群聊图片仅 @ 时分析：{'开启' if img_at_only() else '关闭'}\n"
            "切换：/imgat on｜/imgat off（别名 /群图）")
        return True
    if cmd in ("merge", "合并"):
        words = {w.lower() for w in arg.split()}
        do_all = bool(words & {"all", "全部"})
        do_go = bool(words & {"go", "执行"})
        do_cards = bool(words & {"cards", "card", "卡片", "事件卡"})
        do_promises = bool(words & {"promises", "promise", "承诺"})
        if mw is None:
            await matcher.finish("记忆体还没就绪，稍后再试。")
        if do_promises:
            sid = _get_sid(event)
            lg = mw._ledger(sid, CID)
            groups = promise_mod.duplicates(lg)
            if not groups:
                await matcher.finish("没有发现明显重复的承诺。")
            if not do_go:
                lines = [
                    f"{n}. " + " ／ ".join(
                        f"[{p.get('id')}] {str(p.get('text') or '')[:45]}"
                        for p in g)
                    for n, g in enumerate(groups[:8], 1)]
                await matcher.finish(
                    f"试跑：发现 {len(groups)} 组可能重复的承诺（不会改动）\n"
                    + "\n".join(lines)
                    + "\n确认后发 /merge promises go；只想留某条，"
                      "也可以直接让瑾瑜用 manage_promises merge 指定顺序。")
            merged = 0
            for g in groups[:8]:
                ids = [p.get("id") for p in g if p.get("id")]
                if len(ids) < 2:
                    continue
                promise_mod.manage(lg, "merge", ids, turn=mw.db.max_turn(sid, CID))
                merged += len(ids) - 1
            mw.db.save_ledger(sid, CID, lg)
            await matcher.finish(
                f"已合并 {merged} 条重复承诺到各组第一条；其余进 dormant，"
                "原文保留、仍可召回。")
        if do_cards:
            if do_all:
                targets = [(str(o["base"]), mw.db.latest_sid(o["base"], CID))
                           for o in mw.db.card_owners(CID) if int(o["n"] or 0) >= 2]
            else:
                base = _get_sid(event).split("#")[0]
                targets = [(base, mw.db.latest_sid(base, CID))]
            if not targets:
                await matcher.finish("没有可合并的事件卡（至少 2 张）。")
            await matcher.send(
                f"开始{'合并' if do_go else '试跑'}事件卡 {len(targets)} 个会话，请稍等…")
            lines, groups_n, removed_n, extra_n, shown_n = [], 0, 0, 0, 0
            for base, sid in targets[:8]:
                try:
                    groups = await asyncio.to_thread(mw.merge_cards, sid, CID, do_go)
                except Exception as exc:            # noqa: BLE001  单个会话失败不影响其余
                    lines.append(f"{_owner_label(base)}：失败 {type(exc).__name__}")
                    continue
                for g in groups:
                    groups_n += 1
                    removed_n += int(g.get("removed") or 0)
                    if shown_n >= 12:               # 回执最多展开 12 组，其余看记录
                        extra_n += 1
                        continue
                    lines += _merge_card_receipt(base, [g], do_go, groups_n - 1)
                    shown_n += 1
            if not lines:
                await matcher.finish("没发现重复事件卡。")
            head = (f"事件卡合并完成：{groups_n} 组，删除 {removed_n} 张重复卡"
                    if do_go else f"试跑：{groups_n} 组可能重复的事件卡，未写库")
            tail = ""
            if extra_n:
                tail += (f"\n还有 {extra_n} 组未展开"
                         + ("，已写入合并记录，用 /memory log 查看。" if do_go else "。"))
            if do_go:
                tail += "\n查看来源：/memory log｜改合并结果：/memory cards"
            else:
                tail += "\n确认无误后发 /merge cards go（全部会话：/merge cards all go）"
            if do_all and len(targets) > 8:
                tail += f"\n本次只处理前 8 个会话（共 {len(targets)} 个），可再发一次继续。"
            await _send_long(head + "\n" + "\n".join(lines) + tail, matcher)
            return True
        if do_all:
            bases = [o["base"] for o in mw.db.fact_owners(CID)
                     if int(o["n"] or 0) >= 2]
        else:
            bases = [_get_sid(event).split("#")[0]]
        if not bases:
            await matcher.finish("没有可合并的会话（事实不足 2 条）。")
        await matcher.send(f"开始{'合并' if do_go else '试跑'} {len(bases)} 个会话，请稍等…")
        lines, groups_n, removed_n, extra_n, shown_n = [], 0, 0, 0, 0
        card_note = ""
        if do_all:                               # 全部会话时顺带并掉重复事件卡
            cards_n = 0
            for o in mw.db.card_owners(CID):
                if int(o["n"] or 0) < 2:
                    continue
                try:
                    sid = mw.db.latest_sid(o["base"], CID)
                    cards_n += len(await asyncio.to_thread(mw.merge_cards, sid, CID, do_go))
                except Exception as exc:            # noqa: BLE001
                    logger.warning(f"[jinyu] 事件卡合并失败 base={o['base']}: {exc}")
            if cards_n:
                card_note = f"（顺带合并事件卡 {cards_n} 组）"
        for base in bases[:8]:
            try:
                groups = await asyncio.to_thread(mw.merge_facts, base, CID, do_go)
            except Exception as exc:                # noqa: BLE001  单个会话失败不影响其余
                lines.append(f"{_owner_label(base)}：失败 {type(exc).__name__}")
                continue
            for g in groups:
                groups_n += 1
                removed_n += int(g.get("removed") or 0)
                if shown_n >= 10:
                    extra_n += 1
                    continue
                lines += _merge_fact_receipt(base, [g], do_go, groups_n - 1)
                shown_n += 1
        if not lines:
            await matcher.finish(f"没发现重复词条。{card_note}")
        head = (f"合并完成：{groups_n} 组，删除 {removed_n} 条重复（含各 epoch 副本）"
                if do_go else f"试跑：{groups_n} 组可能重复，未写库")
        tail = ""
        if extra_n:
            tail += (f"\n还有 {extra_n} 组未展开"
                     + ("，已写入合并记录，用 /memory log 查看。" if do_go else "。"))
        if do_go:
            tail += "\n查看来源：/memory log｜改合并结果：/memory edit 编号 新正文"
        else:
            tail += "\n确认无误后发 /merge go（全部会话：/merge all go）"
        if do_all and len(bases) > 8:
            tail += f"\n本次只处理前 8 个会话（共 {len(bases)} 个），可再发一次继续。"
        await _send_long(head + card_note + "\n" + "\n".join(lines) + tail, matcher)
        return True
    if cmd == "testrich":
        await matcher.send("【自测】文本 OK")
        await matcher.send(Message(MessageSegment.face(14)))
        msg = sticker_message(pick_sticker(arg, allow_empty_random=True))
        if msg is not None:
            await matcher.send(msg)
        else:
            await matcher.send("（贴纸库为空，跳过贴纸）")
        audio = await tts_audio(arg or "瑾瑜的自测语音，主人在吗")
        if audio:
            await matcher.send(Message(MessageSegment.record(audio.resolve().as_uri())))
        else:
            await matcher.send("（语音合成失败）")
        return True
    return False
