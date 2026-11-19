# -*- coding: utf-8 -*-
"""视频通话服务的 HTTP 桥接（stdlib urllib，零第三方依赖）。

只调用上游 call_server 的公开端点：
- GET  /health
- POST /call/turn  {"text","session","view"} -> 回复
- POST /call/say   {"text","session","source"} -> 跨窗口发话
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request


class CallBridge:
    def __init__(self, base_url: str, token: str = "", timeout: float = 5.0):
        self.base_url = str(base_url or "").rstrip("/")
        self.token = str(token or "").strip()
        self.timeout = float(timeout)

    def _request(self, method: str, path: str, payload: dict | None = None,
                 auth: bool = True) -> dict:
        if not self.base_url:
            return {"ok": False, "error": "service_url 未配置"}
        data = None if payload is None else json.dumps(
            payload, ensure_ascii=False
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=data, method=method,
            headers={"Content-Type": "application/json"},
        )
        if auth and self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "ignore") or "{}"
            try:
                data = json.loads(body)
            except ValueError:
                data = {"error": body}
            data.setdefault("ok", False)
            data.setdefault("status", exc.code)
            return data
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

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
