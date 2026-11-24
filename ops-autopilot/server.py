# -*- coding: utf-8 -*-
"""运维自动驾驶（observe-only）：定时只读巡检 RP_DB，报警但不改库。

用法：
    python server.py [--port 8713] [--db data/rp_memory.db] [--token 口令]
                     [--interval 300] [--history data/ops_history.jsonl]
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG = {"port": 8713, "db": "", "token": "", "history": "", "interval": 300}
STATE = {"latest": None, "at": ""}
_LOCK = threading.Lock()
MAX_HISTORY = 2000


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def resolve_db() -> str:
    return CONFIG["db"] or os.environ.get("RP_DB") or os.path.join("data", "rp_memory.db")


def history_path() -> str:
    return CONFIG["history"] or os.environ.get("RP_OPS_HISTORY") or \
        resolve_db() + ".ops.jsonl"


def _connect(path: str):
    con = sqlite3.connect("file:%s?mode=ro" % os.path.abspath(path), uri=True,
                          timeout=3.0)
    con.execute("PRAGMA busy_timeout=3000")
    return con


def _count(con, table: str) -> int:
    try:
        return int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    except sqlite3.Error:
        return -1


def check() -> dict:
    path = resolve_db()
    items = []

    def add(name, level, detail):
        items.append({"name": name, "level": level, "detail": detail})

    if not os.path.exists(path):
        add("db_present", "fail", "库文件不存在：%s" % path)
        return {"at": now(), "db": path, "items": items, "level": "fail"}

    add("db_present", "ok", path)
    try:
        con = _connect(path)
    except sqlite3.Error as exc:
        add("open", "fail", str(exc)[:160])
        return {"at": now(), "db": path, "items": items, "level": "fail"}

    try:
        try:
            result = con.execute("PRAGMA quick_check").fetchone()[0]
            add("integrity", "ok" if result == "ok" else "fail", str(result))
        except sqlite3.Error as exc:
            add("integrity", "fail", str(exc)[:160])

        wal = path + "-wal"
        size = os.path.getsize(wal) if os.path.exists(wal) else 0
        add("wal_size", "warn" if size > 64 * 1024 * 1024 else "ok",
            "%.1f MB" % (size / 1048576.0))

        counts = {t: _count(con, t) for t in
                  ("turns", "event_cards", "durable_facts", "memory_units")}
        add("counts", "ok" if min(counts.values()) >= 0 else "warn",
            ", ".join("%s=%s" % (k, v) for k, v in counts.items()))

        try:
            total = con.execute("SELECT COUNT(*) FROM durable_facts").fetchone()[0]
            gone = con.execute(
                "SELECT COUNT(*) FROM durable_facts"
                " WHERE IFNULL(retracted_at,'')<>''").fetchone()[0]
            ratio = (gone / total) if total else 0.0
            add("retracted_ratio", "warn" if ratio > 0.3 else "ok",
                "%d/%d = %.1f%%" % (gone, total, ratio * 100))
        except sqlite3.Error:
            add("retracted_ratio", "info", "表不可用")

        for name, sql in (("invalidated_units",
                           "SELECT COUNT(*) FROM memory_units"
                           " WHERE IFNULL(invalidated_by,'')<>''"),
                          ("contradictions",
                           "SELECT COUNT(*) FROM memory_contradictions")):
            try:
                add(name, "info", con.execute(sql).fetchone()[0])
            except sqlite3.Error:
                add(name, "info", "表不存在（旧库）")
    finally:
        con.close()

    lock_file = os.path.realpath(path) + ".writer.lock"
    if not os.path.exists(lock_file):
        add("writer_lock", "info", "锁文件不存在（写入者未启动过）")
    else:
        handle = open(lock_file, "a+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            add("writer_lock", "ok", "写入者在线")
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            add("writer_lock", "warn", "没有进程持有写锁")
        finally:
            handle.close()

    worst = "ok"
    for item in items:
        if item["level"] == "fail":
            worst = "fail"
            break
        if item["level"] == "warn":
            worst = "warn"
    return {"at": now(), "db": path, "items": items, "level": worst}


def remember(result: dict) -> None:
    with _LOCK:
        STATE["latest"] = result
        STATE["at"] = result["at"]
    try:
        path = history_path()
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(result, ensure_ascii=False) + "\n")
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
        if len(lines) > MAX_HISTORY:
            with open(path, "w", encoding="utf-8") as fh:
                fh.writelines(lines[-MAX_HISTORY:])
    except OSError:
        pass


def loop(interval: int) -> None:
    while True:
        remember(check())
        if interval <= 0:
            return
        time.sleep(interval)


def recent(limit=200):
    try:
        with open(history_path(), encoding="utf-8") as fh:
            return [json.loads(x) for x in fh.readlines()[-limit:] if x.strip()]
    except (OSError, ValueError):
        return []


class Handler(BaseHTTPRequestHandler):
    server_version = "jinyv-ops/0.1"

    def _authed(self):
        token = CONFIG["token"]
        if not token:
            return True
        q = parse_qs(urlparse(self.path).query)
        return (q.get("t") or [""])[0] == token or self.headers.get("X-Gate-Token") == token

    def _send(self, obj, code=200, mime="application/json; charset=utf-8"):
        body = obj if isinstance(obj, bytes) else \
            json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            if not self._authed():
                return self._send({"error": "口令不对"}, 403)
            if parsed.path == "/api/status":
                return self._send(STATE["latest"] or {"error": "尚未巡检"})
            if parsed.path == "/api/check":
                result = check()
                remember(result)
                return self._send(result)
            if parsed.path == "/api/history":
                return self._send({"items": recent(), "file": history_path()})
            return self._send({"error": "not found"}, 404)

        rel = parsed.path.strip("/") or "index.html"
        if ".." in rel:
            return self._send({"error": "bad path"}, 404)
        fp = os.path.join(BASE, "static", rel)
        if not os.path.isfile(fp):
            return self._send({"error": "not found"}, 404)
        mime = {".html": "text/html; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".js": "application/javascript; charset=utf-8"}.get(
                    os.path.splitext(fp)[1], "application/octet-stream")
        self._send(open(fp, "rb").read(), mime=mime)

    def log_message(self, fmt, *args):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--db", default=None)
    ap.add_argument("--token", default=None)
    ap.add_argument("--interval", type=int, default=None)
    ap.add_argument("--history", default=None)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    if args.db:
        CONFIG["db"] = args.db
    if args.history:
        CONFIG["history"] = args.history
    if args.interval is not None:
        CONFIG["interval"] = args.interval
    else:
        CONFIG["interval"] = int(os.environ.get("RP_OPS_INTERVAL") or CONFIG["interval"])
    CONFIG["port"] = args.port or int(os.environ.get("RP_OPS_PORT") or CONFIG["port"])
    CONFIG["token"] = args.token or os.environ.get("RP_OPS_TOKEN") or ""
    if not CONFIG["token"]:
        CONFIG["token"] = secrets.token_urlsafe(12)
        print("开发模式：本次口令 t=%s" % CONFIG["token"])

    threading.Thread(target=loop, args=(CONFIG["interval"],), daemon=True).start()
    srv = ThreadingHTTPServer((args.host, CONFIG["port"]), Handler)
    print("运维巡检：http://%s:%d/?t=%s  库：%s  间隔：%ss" %
          (args.host, CONFIG["port"], CONFIG["token"], resolve_db(), CONFIG["interval"]))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
