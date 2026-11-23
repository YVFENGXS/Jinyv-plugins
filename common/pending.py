# -*- coding: utf-8 -*-
"""跨端「待总结」队列：只读端把该记的内容交出去，由唯一写进程消费。

背景：同一个 `RP_DB` 只能有一个写入进程。视频 / 房间 / 桌宠这类端不该直接
写记忆库，但它们的对话需要进长期记忆。做法是写一条待处理记录，由主写进程
（qqbot）定时取走、写记忆、确认完成。

- 生产者：`append(summary, source=...)`；
- 消费者：`claim(limit=3)` → 写记忆 → `ack(ids)`；
- 认领有 TTL，消费端崩溃后条目会自动回到队列；
- SQLite WAL + BEGIN IMMEDIATE，多进程安全。
"""
from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

KEEP_DONE_DAYS = 7
MAX_ROWS = 2000

SCHEMA = """
CREATE TABLE IF NOT EXISTS pending_memories(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at REAL NOT NULL,
  source TEXT NOT NULL DEFAULT '',
  summary TEXT NOT NULL,
  importance REAL NOT NULL DEFAULT 0.5,
  claimed_at REAL NOT NULL DEFAULT 0,
  done_at REAL NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_pending_open
  ON pending_memories(done_at, claimed_at, created_at);
"""


def db_path(path=None) -> str:
    if path:
        return str(path)
    env = os.environ.get("RP_PENDING_DB")
    if env:
        return env
    root = Path(__file__).resolve().parents[1]
    return str(root / "data" / "pending.db")


def _connect(path) -> sqlite3.Connection:
    target = db_path(path)
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(SCHEMA)
    return conn


def append(summary: str, importance: float = 0.5, source: str = "", path=None) -> int:
    """投递一条待总结内容；返回 id。"""
    text = str(summary or "").strip()
    if not text:
        return 0
    conn = _connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            "INSERT INTO pending_memories(created_at, source, summary, importance)"
            " VALUES(?,?,?,?)",
            (time.time(), str(source or "")[:40], text[:1500],
             max(0.0, min(1.0, float(importance)))))
        rid = int(cur.lastrowid)
        conn.execute(
            "DELETE FROM pending_memories WHERE done_at>0 AND id <= "
            "(SELECT MAX(id) FROM pending_memories) - ?", (MAX_ROWS,))
        conn.commit()
        return rid
    finally:
        conn.close()


def claim(limit: int = 3, ttl: float = 600.0, path=None) -> list:
    """取走最多 limit 条；返回 [{id, summary, importance, source, created_at}]。"""
    now = time.time()
    conn = _connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            "SELECT * FROM pending_memories WHERE done_at=0"
            " AND (claimed_at=0 OR claimed_at<?) ORDER BY created_at LIMIT ?",
            (now - max(0.0, float(ttl)), max(1, int(limit)))).fetchall()
        ids = [int(r["id"]) for r in rows]
        if ids:
            conn.executemany("UPDATE pending_memories SET claimed_at=? WHERE id=?",
                             [(now, rid) for rid in ids])
        conn.commit()
        return [{"id": int(r["id"]), "summary": r["summary"],
                 "importance": float(r["importance"]), "source": r["source"],
                 "created_at": float(r["created_at"])} for r in rows]
    finally:
        conn.close()


def ack(ids, path=None) -> int:
    """确认已写入记忆；从队列里落成 done。"""
    ids = [int(i) for i in (ids or []) if int(i) > 0]
    if not ids:
        return 0
    conn = _connect(path)
    try:
        q = ",".join("?" * len(ids))
        cur = conn.execute(
            f"UPDATE pending_memories SET done_at=?, claimed_at=0 WHERE id IN ({q})",
            [time.time()] + ids)
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def stats(path=None) -> dict:
    conn = _connect(path)
    try:
        row = conn.execute(
            "SELECT COUNT(*) total,"
            " SUM(CASE WHEN done_at=0 AND claimed_at=0 THEN 1 ELSE 0 END) open,"
            " SUM(CASE WHEN done_at=0 AND claimed_at>0 THEN 1 ELSE 0 END) claimed,"
            " SUM(CASE WHEN done_at>0 THEN 1 ELSE 0 END) done"
            " FROM pending_memories").fetchone()
        return {k: int(row[k] or 0) for k in ("total", "open", "claimed", "done")}
    finally:
        conn.close()


def cleanup(days: int = KEEP_DONE_DAYS, path=None) -> int:
    """删掉已完成且超过保留期的条目。"""
    cut = time.time() - max(1, int(days)) * 86400
    conn = _connect(path)
    try:
        cur = conn.execute("DELETE FROM pending_memories WHERE done_at>0 AND done_at<?",
                           (cut,))
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()
