# -*- coding: utf-8 -*-
"""桌宠服务独立启动入口（不依赖核心进程内 MemoryAPI）。

用法示例：
  python standalone.py --core-url http://127.0.0.1:8710 \
      --core-token "$JINYV_HOST_API_TOKEN" --token "$JINYV_DESKTOP_TOKEN"

启动后暴露 /desktop/v1/health、/desktop/v1/say、/desktop/v1/ws；
上行文字通过宿主 HTTP API 写入本地或远程记忆核心。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core_client import CoreClient  # noqa: E402
import protocol  # noqa: E402
from server import create_app  # noqa: E402


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="desktop-v1 standalone adapter")
    parser.add_argument("--host", default=os.environ.get("JINYV_DESKTOP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("JINYV_DESKTOP_PORT", "8787")))
    parser.add_argument("--token", default=os.environ.get("JINYV_DESKTOP_TOKEN", ""))
    parser.add_argument("--core-url", default=os.environ.get(
        "JINYV_DESKTOP_CORE_URL", "http://127.0.0.1:8710"))
    parser.add_argument("--core-token", default=os.environ.get(
        "JINYV_DESKTOP_CORE_TOKEN", os.environ.get("JINYV_HOST_API_TOKEN", "")))
    parser.add_argument("--account", default=os.environ.get("JINYV_DESKTOP_ACCOUNT", "desktop"))
    parser.add_argument("--session", default=os.environ.get("JINYV_DESKTOP_SESSION", ""))
    args = parser.parse_args(argv)

    if not args.token:
        print("缺少 --token / JINYV_DESKTOP_TOKEN", file=sys.stderr)
        return 2
    if not args.core_url:
        print("缺少 --core-url / JINYV_DESKTOP_CORE_URL", file=sys.stderr)
        return 2

    adapter = StandaloneDesktop(core_url=args.core_url, core_token=args.core_token,
                                token=args.token, account=args.account,
                                session=args.session)
    probe = adapter.core.health()
    adapter.core_ok = bool(probe.get("ok"))
    if adapter.core_ok:
        print(f"已连接记忆核心：{args.core_url}")
    else:
        print(f"记忆核心暂不可达：{args.core_url} ({probe.get('error') or probe.get('status')})",
              file=sys.stderr)

    import uvicorn

    app = create_app(adapter, None)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
