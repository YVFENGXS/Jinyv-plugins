# -*- coding: utf-8 -*-
"""适配层：把 desktop-v1 的上行文字接到宿主 HTTP API。"""
from __future__ import annotations

from core_client import CoreClient
import protocol


class StandaloneDesktop:
    core_mode = "local"

    def __init__(self, *, core_url: str, core_token: str, token: str,
                 account: str, session: str):
        self.core_url = core_url
        self.core_token = core_token
        self.token = token
        self.account = account
        self.session_id = session
        self.connected = False
        self.core_ok = False
        self.pending_say: list[str] = []
        self.core = CoreClient(core_url, core_token, account=account,
                               session=session)

    def new_device_id(self) -> str:
        return protocol.new_id()[:12]

    def now_ms(self) -> int:
        return protocol.now_ms()

    def handle_text(self, text: str, *, speaker: str = "") -> str:
        result = self.core.chat(text, speaker=speaker, source="desktop")
        self.core_ok = bool(result.get("ok"))
        return str(result.get("reply") or "")
