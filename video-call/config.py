# -*- coding: utf-8 -*-
"""配置层：视频通话适配所需的环境变量。"""
from __future__ import annotations

import os


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def core_config() -> dict:
    """记忆宿主（host-api）的连接参数。"""
    return {
        "base_url": _env("JINYV_CORE_URL", "http://127.0.0.1:8710"),
        "token": _env("JINYV_HOST_API_TOKEN") or _env("RP_HOST_TOKEN"),
        "account": _env("JINYV_CALL_ACCOUNT"),
        "session": _env("JINYV_CALL_SESSION") or _env("RP_SESSION"),
    }


def call_config() -> dict:
    """通话服务（jinyu-video-call）的连接参数。"""
    return {
        "base_url": _env("JINYV_CALL_URL", "http://127.0.0.1:8790"),
        "token": _env("JINYV_CALL_TOKEN"),
        "session": _env("JINYV_CALL_SESSION") or _env("RP_SESSION"),
    }
