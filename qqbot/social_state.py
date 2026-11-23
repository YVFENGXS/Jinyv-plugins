# -*- coding: utf-8 -*-
"""签名 / QQ 空间 / 社交圈共用的轻量状态文件。

状态只落在插件自己的 state 文件里，不写记忆库，避免破坏「一个 RP_DB 一个写进程」。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from nonebot import logger

STATE: dict = {}
PATH: Optional[Path] = None


def load(path: Path) -> None:
    """读上次改签名/发说说的状态，避免重启后立刻又发一遍。"""
    global PATH
    PATH = path
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return
    except Exception as exc:                    # noqa: BLE001  坏文件不该拦住启动
        logger.warning(f"[jinyu] 社交状态读取失败: {exc}")
        return
    if isinstance(data, dict):
        STATE.update(data)


def save() -> None:
    if PATH is None:
        return
    try:
        tmp = PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(STATE, ensure_ascii=False), encoding="utf-8")
        tmp.replace(PATH)
    except Exception as exc:                    # noqa: BLE001
        logger.warning(f"[jinyu] 社交状态保存失败: {exc}")


def clip(text: str, limit: int, keep_lines: bool = False) -> str:
    """清掉控制符并限长；签名压成一行，说说允许换行。"""
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f]", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not keep_lines:
        text = " ".join(text.split())
    return text[:limit].strip()
