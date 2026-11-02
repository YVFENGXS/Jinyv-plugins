# -*- coding: utf-8 -*-
"""桌宠到记忆核心的 HTTP 客户端（stdlib urllib）。

用于 core_mode = local / server：桌宠服务不直接持有 MemoryAPI，
而是通过宿主 HTTP API 写入与召回。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request


class CoreClient:
    def __init__(self, base_url: str, token: str = "", account: str = "",
                 session: str = "", timeout: float = 5.0):
        self.base_url = str(base_url or "").rstrip("/")
        self.token = str(token or "").strip()
        self.account = str(account or "").strip()
        self.session = str(session or "").strip()
        self.timeout = float(timeout)

    def _request(self, method: str, path: str, payload: dict | None = None,
                 query: dict | None = None, auth: bool = True) -> dict:
        if not self.base_url:
            return {"ok": False, "error": "core_url 未配置"}
        url = f"{self.base_url}{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        data = None if payload is None else json.dumps(
            payload, ensure_ascii=False
        ).encode("utf-8")
        request = urllib.request.Request(
            url, data=data, method=method,
            headers={"Content-Type": "application/json"},
        )
        if auth and self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8") or "{}")
                body.setdefault("ok", True)
                return body
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "ignore") or "{}"
            try:
                body = json.loads(raw)
            except ValueError:
                body = {"error": raw}
            body.setdefault("ok", False)
            body.setdefault("status", exc.code)
            return body
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def health(self) -> dict:
        return self._request("GET", "/health", auth=False)

    def chat(self, text: str, *, speaker: str = "", source: str = "desktop",
             store_reply: str = "") -> dict:
        payload = {
            "text": str(text or ""),
            "account": self.account,
            "session": self.session,
            "speaker": str(speaker or ""),
            "source": str(source or ""),
        }
        if store_reply:
            payload["store_reply"] = store_reply
        return self._request("POST", "/chat", payload)

    def recall(self, query: str, *, limit: int = 4, speaker: str = "") -> dict:
        return self._request("GET", "/recall", query={
            "q": str(query or ""),
            "limit": str(limit),
            "account": self.account,
            "session": self.session,
            "speaker": str(speaker or ""),
        })

    def remember(self, text: str, *, speaker: str = "",
                 importance: float = 0.7) -> dict:
        return self._request("POST", "/remember", {
            "text": str(text or ""),
            "speaker": str(speaker or ""),
            "importance": float(importance),
            "account": self.account,
            "session": self.session,
        })
