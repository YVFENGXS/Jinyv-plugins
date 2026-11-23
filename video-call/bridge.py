# -*- coding: utf-8 -*-
"""视频通话服务的 HTTP 桥接（stdlib urllib，零第三方依赖）。

只调用上游 call_server 的公开端点：
- GET  /health
- POST /call/turn  {"text","session","view"} -> 回复
- POST /call/say   {"text","session","source"} -> 跨窗口发话
"""
from __future__ import annotations

from transport import request_json


class CallBridge:
    def __init__(self, base_url: str, token: str = "", timeout: float = 5.0):
        self.base_url = str(base_url or "").rstrip("/")
        self.token = str(token or "").strip()
        self.timeout = float(timeout)

    def _request(self, method: str, path: str, payload: dict | None = None,
                 auth: bool = True) -> dict:
        return request_json(
            self.base_url, self.token, method, path,
            payload=payload, timeout=self.timeout, auth=auth,
            missing="service_url 未配置",
        )

    def health(self) -> dict:
        return self._request("GET", "/health", auth=False)

    def turn(self, text: str, *, session: str = "", view: str = "") -> dict:
        return self._request("POST", "/call/turn", {
            "text": str(text or ""),
            "session": str(session or ""),
            "view": str(view or ""),
        })

    def say(self, text: str, *, session: str = "", source: str = "jinyv") -> dict:
        return self._request("POST", "/call/say", {
            "text": str(text or ""),
            "session": str(session or ""),
            "source": str(source or "jinyv"),
        })
