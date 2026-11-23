# -*- coding: utf-8 -*-
"""配置层：命令行参数 + 环境变量，不持有运行期状态。"""
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class HostConfig:
    host: str
    port: int
    db: str


def load_config(argv: list[str] | None = None) -> HostConfig:
    parser = argparse.ArgumentParser(description="Jinyv 宿主 HTTP API")
    parser.add_argument("--host", default=os.environ.get("JINYV_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("JINYV_HOST_PORT", "8710")))
    parser.add_argument("--db", default=os.environ.get("RP_DB") or "")
    args = parser.parse_args(argv)
    return HostConfig(host=args.host, port=args.port, db=args.db)
