# -*- coding: utf-8 -*-
"""最小生理状态：让语气先受身体影响，而不是全靠 prompt 提醒。

只保留五个量：精力、饿、渴、困、迷糊。全部 0~1，按小时回稳/累积；
状态只做两件事——翻译成一句自然语言给 prompt，以及给主动行为当闸门。

设计约束：
- 数值不进台词：`brief()` 只输出「她此刻：有点累、饿」，不输出分数；
- 取不到状态就放行（fail-open）：状态库坏了不能把嘴和手全封住；
- 多进程安全：SQLite WAL + BEGIN IMMEDIATE，QQ / KOOK / 桌宠可共用；
- 不做 100 个生理变量：够用就好，需要再加。

用法：
    from common import vitals
    vitals.tick()
    print(vitals.brief())                 # "她此刻：有点累、饿"
    ok, why = vitals.decide("active")     # 主动行为前先问身体
    vitals.event("feed", 0.4)
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

DEFAULTS = {
    "energy": 0.85,
    "hunger": 0.30,
    "thirst": 0.30,
    "sleepiness": 0.25,
    "grogginess": 0.0,
    "asleep": False,
    "activity": "",
    "updated_at": 0.0,
}

# 到达阈值才允许做；拿不到状态时一律放行
POLICY = {
    "reply":    {"asleep_ok": True,  "min_energy": 0.03, "max_groggy": 0.97},
    "active":   {"asleep_ok": False, "min_energy": 0.25, "max_groggy": 0.70},
    "qzone":    {"asleep_ok": False, "min_energy": 0.08, "max_groggy": 0.85},
    "sing":     {"asleep_ok": False, "min_energy": 0.12, "max_groggy": 0.90},
    "art":      {"asleep_ok": False, "min_energy": 0.10, "max_groggy": 0.85},
    "call":     {"asleep_ok": False, "min_energy": 0.15, "max_groggy": 0.80},
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS vitals(
  id INTEGER PRIMARY KEY CHECK(id=1),
  json TEXT NOT NULL, updated_at REAL NOT NULL);
"""


def db_path(path=None) -> str:
    if path:
        return str(path)
    env = os.environ.get("RP_VITALS_DB")
    if env:
        return env
    root = Path(__file__).resolve().parents[1]
    return str(root / "data" / "vitals.db")


def _connect(path) -> sqlite3.Connection:
    target = db_path(path)
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(SCHEMA)
    return conn


def _clamp(v, low=0.0, high=1.0) -> float:
    return max(low, min(high, float(v)))


def _load(conn: sqlite3.Connection) -> dict:
    row = conn.execute("SELECT json FROM vitals WHERE id=1").fetchone()
    state = dict(DEFAULTS)
    if row:
        try:
            state.update(json.loads(row["json"]))
        except (ValueError, TypeError):
            pass
    return state


def _save(conn: sqlite3.Connection, state: dict) -> None:
    conn.execute(
        "INSERT INTO vitals(id, json, updated_at) VALUES(1, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET json=excluded.json, updated_at=excluded.updated_at",
        (json.dumps(state, ensure_ascii=False), time.time()))
    conn.commit()


def load(path=None) -> dict:
    conn = _connect(path)
    try:
        return _load(conn)
    finally:
        conn.close()


def _advance(state: dict, hours: float) -> dict:
    """按小时推进：睡着恢复，醒着消耗；饿渴全天缓慢累积。"""
    hours = max(0.0, min(72.0, float(hours)))
    if not hours:
        return state
    asleep = bool(state.get("asleep"))
    if asleep:
        state["energy"] = _clamp(state["energy"] + 0.12 * hours)
        state["sleepiness"] = _clamp(state["sleepiness"] - 0.15 * hours)
        state["grogginess"] *= 0.5 ** (hours / 0.22)
        state["hunger"] = _clamp(state["hunger"] + 0.025 * hours)
        state["thirst"] = _clamp(state["thirst"] + 0.035 * hours)
    else:
        state["energy"] = _clamp(state["energy"] - 0.030 * hours)
        state["sleepiness"] = _clamp(state["sleepiness"] + 0.045 * hours)
        state["hunger"] = _clamp(state["hunger"] + 0.050 * hours)
        state["thirst"] = _clamp(state["thirst"] + 0.070 * hours)
        state["grogginess"] *= 0.5 ** (hours / 0.16)
    if state["energy"] < 0.25:
        state["grogginess"] = max(state["grogginess"], 0.25 + (0.25 - state["energy"]))
    if state["sleepiness"] > 0.9 and state["energy"] < 0.2:
        state["asleep"] = True
    state["updated_at"] = time.time()
    return state


def tick(path=None, now=None) -> dict:
    """把状态推进到当前时刻；返回最新状态。"""
    now = time.time() if now is None else float(now)
    conn = _connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        state = _load(conn)
        last = float(state.get("updated_at") or 0)
        if last <= 0:
            state["updated_at"] = now
        else:
            state = _advance(state, (now - last) / 3600.0)
        _save(conn, state)
        return state
    except sqlite3.OperationalError:
        return load(path)
    finally:
        conn.close()


def event(kind: str, amount: float = 0.35, path=None) -> dict:
    """吃饭 / 喝水 / 睡觉 / 醒来 / 活动。"""
    state = tick(path)
    kind = str(kind or "").strip().lower()
    if kind in ("feed", "eat", "meal"):
        state["hunger"] = _clamp(state["hunger"] - amount)
        state["energy"] = _clamp(state["energy"] + amount * 0.25)
    elif kind in ("drink", "water"):
        state["thirst"] = _clamp(state["thirst"] - amount)
    elif kind == "sleep":
        state["asleep"] = True
        state["sleepiness"] = _clamp(state["sleepiness"] - 0.2)
    elif kind in ("wake", "awake"):
        state["asleep"] = False
        state["grogginess"] = 1.0
        state["sleepiness"] = _clamp(state["sleepiness"] - 0.4)
    elif kind == "activity":
        state["activity"] = str(amount)[:30] if isinstance(amount, str) else ""
    conn = _connect(path)
    try:
        state["updated_at"] = time.time()
        _save(conn, state)
    finally:
        conn.close()
    return state


def brief(state=None, path=None) -> str:
    """一句话概括身体状态；没有可说的返回空串。数值不出现。"""
    state = load(path) if state is None else state
    if not state:
        return ""
    bits = []
    if state.get("asleep"):
        bits.append("睡着了")
    activity = str(state.get("activity") or "").strip()
    if activity and not state.get("asleep"):
        bits.append("在" + activity)
    energy = float(state.get("energy") or 1.0)
    if energy < 0.2:
        bits.append("快没力气")
    elif energy < 0.4:
        bits.append("有点累")
    hunger = float(state.get("hunger") or 0)
    if hunger > 0.75:
        bits.append("很饿")
    elif hunger > 0.55:
        bits.append("有点饿")
    if float(state.get("thirst") or 0) > 0.7:
        bits.append("渴")
    if float(state.get("sleepiness") or 0) > 0.8:
        bits.append("困得不行")
    if float(state.get("grogginess") or 0) > 0.6:
        bits.append("昏昏沉沉")
    return ("她此刻：" + "、".join(bits)) if bits else ""


def decide(behavior: str, state=None, path=None) -> tuple[bool, str]:
    """行为闸门：返回 (能不能做, 不能做的原因)。拿不到状态就放行。"""
    state = load(path) if state is None else state
    if not state:
        return True, ""
    rule = POLICY.get(str(behavior or "").strip().lower()) or {}
    if state.get("asleep") and not rule.get("asleep_ok", True):
        return False, "她睡着了"
    energy = float(state.get("energy") or 0)
    if energy < float(rule.get("min_energy", 0.0)):
        return False, f"力气不够（energy={energy:.2f}）"
    groggy = float(state.get("grogginess") or 0)
    if groggy > float(rule.get("max_groggy", 1.0)):
        return False, f"昏沉得厉害（grogginess={groggy:.2f}）"
    return True, ""
