# -*- coding: utf-8 -*-
"""记忆星图：只读 Jinyv-memory 的 RP_DB，把记忆画成主题聚类星图。

接口：
  GET /api/memories  -> {"nodes":[...], "links":[...], "source":{...}}
  GET /              -> 星图页（口令门禁 ?t=口令）

数据来源（全部只读）：
  durable_facts / event_cards / memory_units
  库不存在时返回空图，不建库、不写库。

用法：
    python server.py [--port 8712] [--db data/rp_memory.db] [--token 口令]
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sqlite3
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG = {"gate_token": "", "port": 8712, "db": ""}
MAX_NODES = 2000


def clamp(text, limit=160):
    s = " ".join(str(text or "").split())
    return s[:limit]


def as_float(value, default=0.5):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if v < 0:
        return 0.0
    if v > 1:
        return 1.0
    return v


def first_tag(raw):
    if isinstance(raw, (list, tuple)):
        return str(raw[0]) if raw else ""
    text = str(raw or "").strip()
    if not text:
        return ""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return text.split(",")[0].strip()
    if isinstance(data, list) and data:
        return str(data[0])
    if isinstance(data, dict) and data:
        return str(next(iter(data)))
    return ""


def content_text(raw):
    text = str(raw or "")
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return clamp(text)
    if isinstance(data, dict):
        for key in ("text", "summary", "content", "fact", "value"):
            if data.get(key):
                return clamp(data[key])
        return clamp(json.dumps(data, ensure_ascii=False))
    if isinstance(data, list) and data:
        return clamp(data[0])
    return clamp(text)


def load_config(path):
    if path and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for key in ("gate_token", "port", "db"):
                    if key in data:
                        CONFIG[key] = data[key]
        except Exception as exc:  # noqa: BLE001
            print("! 读配置失败：%s" % exc)


def db_path():
    return CONFIG.get("db") or os.environ.get("RP_DB") or os.path.join("data", "rp_memory.db")


def rows(sql, args=()):
    path = db_path()
    con = sqlite3.connect("file:%s?mode=ro" % os.path.abspath(path), uri=True, timeout=3)
    try:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute(sql, args).fetchall()]
    finally:
        con.close()


def collect():
    """三张表各取一段，统一成 nodes；表不存在或没数据就跳过。"""
    nodes, counts, errors = [], {}, []
    path = db_path()
    if not os.path.exists(path):
        return {"nodes": [], "links": [], "source": {"db": path, "error": "库不存在"}}

    per_table = MAX_NODES // 3 + 100
    queries = [
        (
            "facts",
            """select id, fact, tags, importance, category, created_at, supersedes_id
               from durable_facts
               where retracted_at is null or retracted_at = ''
               order by id desc limit ?""",
            lambda r: (
                "f:%s" % r["id"],
                clamp(r.get("fact")),
                first_tag(r.get("tags")) or clamp(r.get("category")) or "事实",
                as_float(r.get("importance"), 0.5),
                r.get("created_at") or "",
                r.get("supersedes_id"),
            ),
        ),
        (
            "events",
            """select event_id, summary, subject, session_id, importance, created_at, supersedes_id
               from event_cards
               where retracted_at is null or retracted_at = ''
               order by rowid desc limit ?""",
            lambda r: (
                "e:%s" % r["event_id"],
                clamp(r.get("summary")),
                clamp(r.get("subject")) or clamp(r.get("session_id")) or "事件",
                as_float(r.get("importance"), 0.5),
                r.get("created_at") or "",
                r.get("supersedes_id"),
            ),
        ),
        (
            "units",
            """select id, content_json, thread_id, bucket_key, salience, created_at, supersedes
               from memory_units
               order by rowid desc limit ?""",
            lambda r: (
                "m:%s" % r["id"],
                content_text(r.get("content_json")),
                clamp(r.get("thread_id")) or clamp(r.get("bucket_key")) or "摘要",
                as_float(r.get("salience"), 0.5),
                r.get("created_at") or "",
                r.get("supersedes"),
            ),
        ),
    ]

    rev = {}
    for name, sql, mapping in queries:
        try:
            data = rows(sql, (per_table,))
        except sqlite3.Error as exc:
            errors.append("%s: %s" % (name, str(exc)[:80]))
            counts[name] = 0
            continue
        counts[name] = len(data)
        for r in data:
            nid, summary, topic, importance, t, prev = mapping(r)
            if not summary:
                continue
            nodes.append({
                "id": nid, "summary": summary, "topic": topic,
                "importance": importance, "t": t,
            })
            if prev:
                rev[nid] = "f:%s" % prev if name == "facts" else (
                    "e:%s" % prev if name == "events" else "m:%s" % prev)

    nodes = nodes[:MAX_NODES]
    links = build_links(nodes, rev)
    return {"nodes": nodes, "links": links,
            "source": {"db": path, "counts": counts, "errors": errors}}


def build_links(nodes, rev):
    by_id = {n["id"]: n for n in nodes}
    by_topic = {}
    for n in nodes:
        by_topic.setdefault(n["topic"] or "其他", []).append(n)

    seen, links = set(), []
    for group in by_topic.values():
        order = sorted(group, key=lambda n: (n.get("t") or "", n["id"]))
        for a, b in zip(order, order[1:]):
            key = tuple(sorted((a["id"], b["id"])))
            if key not in seen:
                seen.add(key)
                links.append({"source": a["id"], "target": b["id"]})

    for nid, prev in rev.items():
        if nid in by_id and prev in by_id:
            key = tuple(sorted((nid, prev)))
            if key not in seen:
                seen.add(key)
                links.append({"source": nid, "target": prev})
    return links


class Handler(BaseHTTPRequestHandler):
    server_version = "jinyv-starmap/0.1"

    def _authed(self):
        token = CONFIG["gate_token"]
        if not token:
            return True
        query = parse_qs(urlparse(self.path).query)
        return (query.get("t") or [""])[0] == token or \
            self.headers.get("X-Gate-Token", "") == token

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/memories":
            if not self._authed():
                return self._json({"error": "口令不对"}, 403)
            return self._json(collect())

        rel = parsed.path.strip("/") or "index.html"
        if ".." in rel or rel.startswith("/"):
            self.send_response(404)
            return self.end_headers()
        fp = os.path.join(BASE, "static", rel)
        if not os.path.isfile(fp):
            self.send_response(404)
            return self.end_headers()
        mime = {".html": "text/html; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8"}.get(
                    os.path.splitext(fp)[1].lower(), "application/octet-stream")
        body = open(fp, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


def main():
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--db", default=None)
    ap.add_argument("--token", default=None)
    ap.add_argument("--config", default=None)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    load_config(args.config)
    if args.db:
        CONFIG["db"] = args.db
    elif not CONFIG.get("db"):
        CONFIG["db"] = os.environ.get("RP_DB", "")
    if args.port:
        CONFIG["port"] = args.port
    else:
        CONFIG["port"] = int(os.environ.get("RP_STARMAP_PORT") or CONFIG.get("port") or 8712)
    CONFIG["gate_token"] = args.token or os.environ.get("RP_STARMAP_TOKEN") or CONFIG["gate_token"]
    if not CONFIG["gate_token"]:
        CONFIG["gate_token"] = secrets.token_urlsafe(12)
        print("开发模式：本次口令 t=%s" % CONFIG["gate_token"])

    srv = ThreadingHTTPServer((args.host, CONFIG["port"]), Handler)
    print("记忆星图：http://%s:%d/?t=%s  库：%s" %
          (args.host, CONFIG["port"], CONFIG["gate_token"], db_path()))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
