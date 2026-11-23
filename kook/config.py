# -*- coding: utf-8 -*-
"""配置层：只从环境变量解析，不持有运行期状态。"""
from __future__ import annotations

import os

DEFAULT_SATORI_HOST = "127.0.0.1"
DEFAULT_SATORI_PORT = "5140"
# legacy 契约，勿改：JINYU_HOST / JINYU_TOKEN / JINYU_SOURCE 是对外环境变量名
DEFAULT_JINYU_HOST = "http://127.0.0.1:8080"
DEFAULT_SOURCE = "qq"  # 宿主接口只认 qq/desk/video，KOOK 先借用 qq 标签

REQUIRED = ("JINYU_TOKEN",)


def env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def mask(value: str, keep: int = 4) -> str:
    """日志里只留前几位，避免把凭据写进 journal。"""
    if not value:
        return "(空)"
    return value[:keep] + "*" * max(0, len(value) - keep)


def load_config() -> dict:
    return {
        "satori_host": env("SATORI_HOST", DEFAULT_SATORI_HOST),
        "satori_port": int(env("SATORI_PORT", DEFAULT_SATORI_PORT)),
        "satori_token": env("SATORI_TOKEN"),
        "satori_platform": env("SATORI_PLATFORM", "kook"),
        "jinyu_host": env("JINYU_HOST", DEFAULT_JINYU_HOST).rstrip("/"),
        "jinyu_token": env("JINYU_TOKEN"),
        "jinyu_source": env("JINYU_SOURCE", DEFAULT_SOURCE),
        "allow_users": [x.strip() for x in env("KOOK_ALLOW_USERS").split(",") if x.strip()],
        # QQ 掉线时宿主会 POST /send 到这里，再由本进程发到 KOOK 的固定频道
        "kook_channel": env("KOOK_FALLBACK_CHANNEL").strip(),
        "kook_token": env("KOOK_TOKEN").strip(),
        "send_port": int(env("KOOK_SEND_PORT", "8099")),
    }


def check_config(cfg: dict) -> list[str]:
    """返回缺失/非法的配置项说明；空列表表示可以启动。"""
    problems: list[str] = []
    if not cfg["jinyu_token"]:
        problems.append("JINYU_TOKEN 未设置：宿主接口 /jinyu/chat 的 Bearer 令牌（复用 RP_HOST_TOKEN）")
    if not (1 <= cfg["satori_port"] <= 65535):
        problems.append(f"SATORI_PORT 非法：{cfg['satori_port']}")
    if not cfg["jinyu_host"].startswith(("http://", "https://")):
        problems.append(f"JINYU_HOST 必须以 http:// 或 https:// 开头：{cfg['jinyu_host']}")
    if cfg["jinyu_source"] not in ("qq", "desk", "video"):
        problems.append(f"JINYU_SOURCE 只能是 qq/desk/video：{cfg['jinyu_source']}")
    return problems


def status_lines(cfg: dict, problems: list[str]) -> list[str]:
    """把配置清单和缺失项整理成日志行，由启动层决定怎么打印。"""
    lines = [
        "配置清单：",
        f"  Satori   ws://{cfg['satori_host']}:{cfg['satori_port']}/v1/events"
        f"  token={mask(cfg['satori_token'])}",
        f"  宿主接口  {cfg['jinyu_host']}/jinyu/chat  token={mask(cfg['jinyu_token'])}"
        f"  source={cfg['jinyu_source']}",
        f"  KOOK 平台 {cfg['satori_platform']}"
        f"  允许用户={cfg['allow_users'] or '不限'}",
    ]
    if problems:
        lines.append("缺少以下配置，进程不会启动：")
        lines.extend(f"  - {p}" for p in problems)
        lines.append("参考 kook/config.example.env；KOOK Bot Token 配在 Koishi 的 adapter-kook 里。")
    return lines


def print_status(cfg: dict, problems: list[str]) -> None:
    from bootstrap import log

    for line in status_lines(cfg, problems):
        log(line)
