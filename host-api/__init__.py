# -*- coding: utf-8 -*-
"""宿主 HTTP API 插件：给桌宠、通话、DSH 等外部进程一个统一写入通道。

零第三方依赖，使用 stdlib ThreadingHTTPServer。
端点：
  GET  /health
  POST /chat     {"text","session","account","speaker","source","store_reply"}
                 -> {"reply","session"}
  POST /remember {"text","speaker","importance","account","session"} -> {"ok","id"}
  GET  /recall?q=&limit=&account=&session=&speaker= -> {"cards","facts","text"}
除 /health 外都要求 Authorization: Bearer <token>。
"""
from __future__ import annotations

import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from jinyv_memory.contract import Health, PluginContext, ToolSpec

MAX_BODY = 1 << 20
MAX_TEXT = 4000


def create_plugin() -> "HostAPIPlugin":
    return HostAPIPlugin()


class HostAPIPlugin:
    def setup(self, ctx: PluginContext) -> None:
        self.ctx = ctx
        self.host = str(ctx.config.get("host") or "127.0.0.1")
        self.port_requested = int(ctx.config.get("port") or 8710)
        self.account = str(ctx.config.get("account") or ctx.accounts.default_key)
        self.token = ctx.config.secret("token", env_var="JINYV_HOST_API_TOKEN")
        self.port = 0
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        ctx.tools.register(ToolSpec(
            name="host_api.status",
            description="查看宿主 HTTP API 的监听状态。",
            parameters={"type": "object", "properties": {}},
            handler=self._tool_status,
        ), ctx.plugin_id)

    def start(self, ctx: PluginContext) -> None:
        if not self.token:
            ctx.degrade("缺少 JINYV_HOST_API_TOKEN，宿主 HTTP API 不启动")
            return
        handler = _make_handler(self)
        self._server = ThreadingHTTPServer((self.host, self.port_requested), handler)
        self.port = int(self._server.server_address[1])
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="jinyv-host-api",
            daemon=True,
        )
        self._thread.start()
        ctx.logger.info("宿主 HTTP API 已启动 http://%s:%s", self.host, self.port)

    def stop(self, ctx: PluginContext) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None

    def health(self, ctx: PluginContext) -> Health:
        if ctx.degraded_reason:
            return Health.degraded(ctx.degraded_reason, port=self.port)
        return Health.ok(host=self.host, port=self.port, account=self.account)

    def _tool_status(self, args: Any, turn: Any) -> dict:
        return {
            "ok": bool(self._server),
            "host": self.host,
            "port": self.port,
            "account": self.account,
        }

    # ------------------------------------------------------------ 业务
    def _lane(self, session: str = "", account: str = ""):
        lane = self.ctx.accounts.get(account or self.account)
        return lane.with_session(session) if session else lane

    def handle_chat(self, payload: dict) -> tuple[int, dict]:
        text = str(payload.get("text") or "").strip()
        if not text:
            return 400, {"error": "text required"}
        if len(text) > MAX_TEXT:
            return 413, {"error": "text too long"}
        session = str(payload.get("session") or "").strip()
        lane = self._lane(session, str(payload.get("account") or ""))
        speaker = str(payload.get("speaker") or "")[:80]
        source = str(payload.get("source") or "host-api")[:40]
        store_reply = str(payload.get("store_reply") or "").strip()
        reply = self.ctx.memory.chat(
            lane, text, speaker=speaker, source=source,
            store_reply=(lambda _generated: store_reply) if store_reply else None,
        )
        return 200, {"reply": reply, "session": lane.session_id}

    def handle_remember(self, payload: dict) -> tuple[int, dict]:
        text = str(payload.get("text") or "").strip()
        if not text:
            return 400, {"error": "text required"}
        speaker = str(payload.get("speaker") or "")[:80]
        try:
            importance = max(0.0, min(1.0, float(payload.get("importance") or 0.7)))
        except (TypeError, ValueError):
            importance = 0.7
        lane = self._lane(str(payload.get("session") or "").strip(),
                          str(payload.get("account") or ""))
        fact_id = self.ctx.memory.remember(lane, text, speaker=speaker,
                                           importance=importance)
        return 200, {"ok": bool(fact_id), "id": fact_id}

    def handle_recall(self, params: dict) -> tuple[int, dict]:
        query = str((params.get("q") or [""])[0])[:MAX_TEXT]
        try:
            limit = max(1, min(50, int((params.get("limit") or ["6"])[0])))
        except ValueError:
            limit = 6
        account = str((params.get("account") or [""])[0])
        session = str((params.get("session") or [""])[0]).strip()
        speaker = str((params.get("speaker") or [""])[0])[:80]
        result = self.ctx.memory.recall(self._lane(session, account), query,
                                        limit=limit, speaker=speaker)
        return 200, result.to_dict()


def _make_handler(plugin: HostAPIPlugin):
    class Handler(BaseHTTPRequestHandler):
        server_version = "jinyv-host/1"

        def _json(self, code: int, data: dict) -> None:
            raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _auth(self) -> bool:
            header = str(self.headers.get("Authorization") or "")
            if not header.startswith("Bearer "):
                self._json(401, {"error": "unauthorized"})
                return False
            supplied = header[7:].strip()
            if not hmac.compare_digest(supplied, plugin.token):
                self._json(401, {"error": "unauthorized"})
                return False
            return True

        def _body(self) -> dict:
            try:
                size = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                size = 0
            if size <= 0 or size > MAX_BODY:
                return {}
            try:
                data = json.loads(self.rfile.read(size).decode("utf-8", "ignore") or "{}")
            except ValueError:
                return {}
            return data if isinstance(data, dict) else {}

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                self._json(200, {"ok": True, "name": "jinyv-host"})
                return
            if parsed.path == "/recall":
                if not self._auth():
                    return
                try:
                    code, data = plugin.handle_recall(parse_qs(parsed.query))
                except Exception:
                    code, data = 500, {"error": "internal"}
                self._json(code, data)
                return
            self._json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path not in ("/chat", "/remember"):
                self._json(404, {"error": "not found"})
                return
            if not self._auth():
                return
            payload = self._body()
            try:
                if path == "/chat":
                    code, data = plugin.handle_chat(payload)
                else:
                    code, data = plugin.handle_remember(payload)
            except Exception:
                code, data = 500, {"error": "internal"}
            self._json(code, data)

        def log_message(self, fmt: str, *args) -> None:
            plugin.ctx.logger.info("%s %s", self.address_string(), fmt % args)

    return Handler
