# -*- coding: utf-8 -*-
"""启动层：检查记忆核心、组装 FastAPI 应用并交给 uvicorn。"""
from __future__ import annotations

import sys

from adapter import StandaloneDesktop
from config import DesktopConfig, check_config, load_config


def run(cfg: DesktopConfig) -> int:
    adapter = StandaloneDesktop(
        core_url=cfg.core_url, core_token=cfg.core_token,
        token=cfg.token, account=cfg.account, session=cfg.session)
    probe = adapter.core.health()
    adapter.core_ok = bool(probe.get("ok"))
    if adapter.core_ok:
        print(f"已连接记忆核心：{cfg.core_url}")
    else:
        print(f"记忆核心暂不可达：{cfg.core_url} "
              f"({probe.get('error') or probe.get('status')})", file=sys.stderr)

    import uvicorn

    from server import create_app

    app = create_app(adapter, None)
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="info")
    return 0


def main(argv: list[str] | None = None) -> int:
    cfg = load_config(argv)
    problems = check_config(cfg)
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 2
    return run(cfg)
