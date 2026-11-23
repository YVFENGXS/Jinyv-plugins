# -*- coding: utf-8 -*-
"""配置层：命令行参数 + 环境变量。"""
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class DesktopConfig:
    host: str
    port: int
    token: str
    core_url: str
    core_token: str
    account: str
    session: str


def load_config(argv: list[str] | None = None) -> DesktopConfig:
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
    return DesktopConfig(
        host=args.host, port=args.port, token=args.token,
        core_url=args.core_url, core_token=args.core_token,
        account=args.account, session=args.session,
    )


def check_config(cfg: DesktopConfig) -> list[str]:
    problems = []
    if not cfg.token:
        problems.append("缺少 --token / JINYV_DESKTOP_TOKEN")
    if not cfg.core_url:
        problems.append("缺少 --core-url / JINYV_DESKTOP_CORE_URL")
    return problems
