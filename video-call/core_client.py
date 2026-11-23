# -*- coding: utf-8 -*-
"""通话适配层到记忆核心的 HTTP 客户端（stdlib urllib）。

用于 core_mode = local / server：适配层不直接持有 MemoryAPI，
而是通过宿主 HTTP API 读取上下文与写入一轮通话。
"""
from __future__ import annotations

from transport import request_json


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
        return request_json(
            self.base_url, self.token, method, path,
            payload=payload, query=query, timeout=self.timeout, auth=auth,
            missing="core_url 未配置",
        )

    def health(self) -> dict:
        return self._request("GET", "/health", auth=False)

    def chat(self, text: str, *, speaker: str = "", store_reply: str = "",
             source: str = "video-call") -> dict:
        payload = {
            "text": str(text or ""),
            "account": self.account,
            "session": self.session,
            "speaker": str(speaker or ""),
            "source": str(source or ""),
        }
        if store_reply:
            payload["store_reply"] = str(store_reply)
        return self._request("POST", "/chat", payload)

    def recall(self, query: str, *, limit: int = 4, speaker: str = "") -> dict:
        return self._request("GET", "/recall", query={
            "q": str(query or ""),
            "limit": str(limit),
            "account": self.account,
            "session": self.session,
            "speaker": str(speaker or ""),
        })
