# -*- coding: utf-8 -*-
"""配置层：命令行参数 + 环境变量。

兼容两套命名：
- 新：JINYV_DESKTOP_*
- 旧 systemd unit / install_desktop_adapter.sh：RP_DESKTOP_*、RP_HOST_*
"""
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


@dataclass(frozen=True)
class DesktopConfig:
    host: str
    port: int
    token: str
    core_url: str
    core_token: str
    core_prefix: str
    account: str
    session: str


def load_config(argv: list[str] | None = None) -> DesktopConfig:
    parser = argparse.ArgumentParser(description="desktop-v1 standalone adapter")
    parser.add_argument("--host", default=_env("JINYV_DESKTOP_HOST")
                        or _env("RP_DESKTOP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int,
                        default=int(_env("JINYV_DESKTOP_PORT")
                                    or _env("RP_DESKTOP_PORT", "8787")))
    parser.add_argument("--token", default=_env("JINYV_DESKTOP_TOKEN")
                        or _env("RP_DESKTOP_TOKEN"))
    parser.add_argument("--core-url", default=_env("JINYV_DESKTOP_CORE_URL")
                        or _env("RP_HOST_BASE", "http://127.0.0.1:8710"))
    parser.add_argument("--core-token", default=_env("JINYV_DESKTOP_CORE_TOKEN")
                        or _env("JINYV_HOST_API_TOKEN") or _env("RP_HOST_TOKEN"))
    parser.add_argument("--core-prefix", default=_env("JINYV_DESKTOP_CORE_PREFIX"))
    parser.add_argument("--account", default=_env("JINYV_DESKTOP_ACCOUNT", "desktop"))
    parser.add_argument("--session", default=_env("JINYV_DESKTOP_SESSION")
                        or _env("RP_SESSION"))
    args = parser.parse_args(argv)

    prefix = str(args.core_prefix or "").strip()
    # 旧部署用 RP_HOST_BASE 指向 QQ 插件的 /jinyu/*，不是 host-api 的 /chat。
    rp_base = _env("RP_HOST_BASE").rstrip("/")
    if not prefix and rp_base and str(args.core_url).rstrip("/") == rp_base:
        prefix = "/jinyu"
    if prefix and not prefix.startswith("/"):
        prefix = "/" + prefix
    prefix = prefix.rstrip("/")

    return DesktopConfig(
        host=args.host, port=args.port, token=args.token,
        core_url=args.core_url, core_token=args.core_token,
        core_prefix=prefix,
        account=args.account, session=args.session,
    )


def check_config(cfg: DesktopConfig) -> list[str]:
    problems = []
    if not cfg.token:
        problems.append("缺少 --token / JINYV_DESKTOP_TOKEN")
    if not cfg.core_url:
        problems.append("缺少 --core-url / JINYV_DESKTOP_CORE_URL")
    return problems
