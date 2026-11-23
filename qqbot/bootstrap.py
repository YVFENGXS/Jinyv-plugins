# -*- coding: utf-8 -*-
"""启动层：定位 Jinyv-memory core、把插件目录挂到 sys.path、桥接标准日志。"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from nonebot import logger


def locate_core() -> Path:
    """定位 Jinyv-memory 的 core 目录（记忆中间层独立仓库）。"""
    candidates = []
    home = os.environ.get("JINYV_MEMORY_HOME")
    if home:
        candidates.append(Path(home) / "jinyv_memory" / "core")
        candidates.append(Path(home) / "core")
    try:
        import jinyv_memory as _pkg

        candidates.append(Path(_pkg.__file__).resolve().parent / "core")
    except Exception:                                    # noqa: BLE001
        pass
    here = Path(__file__).resolve().parent
    candidates.append(here / "jinyv_memory" / "core")
    candidates.append(here / "core")
    for path in candidates:
        if (path / "rp_skeleton.py").is_file():
            return path
    raise RuntimeError(
        "找不到 jinyv_memory/core：请先安装 Jinyv-memory，"
        "或设置 JINYV_MEMORY_HOME 指向该仓库根目录"
    )


CORE = locate_core()
PLUGIN = Path(__file__).resolve().parent
for _path in (CORE, PLUGIN):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))


class _StdLogBridge(logging.Handler):
    """把标准 logging 接到 NoneBot 的 loguru。

    core/rp_skeleton.py 用的是 logging.getLogger("rp_memory")，没人配 handler，
    INFO 会被直接吞掉——后台归纳只能看到告警。接过来之后「后台归纳完成」才可见。
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            logger.opt(depth=6, exception=record.exc_info).log(
                record.levelname, record.getMessage())
        except Exception:                       # noqa: BLE001  日志失败不能影响业务
            pass


def bind_core_log() -> None:
    # rp_memory 是后台归纳，jinyv_memory.richmsg 是搜图/视觉判读/贴纸入库；
    # jinyv_memory.llm 是模型适配器的调用/缓存遥测。三者都用标准 logging，
    # 不接过来 INFO 会被直接吞掉。
    for name in ("rp_memory", "jinyv_memory.richmsg", "jinyv_memory.mcp",
                 "jinyv_memory.llm", "jinyv_stage.intent"):
        lg = logging.getLogger(name)
        if not any(isinstance(h, _StdLogBridge) for h in lg.handlers):
            lg.addHandler(_StdLogBridge())
        lg.setLevel(logging.INFO)
        lg.propagate = False                    # 避免再被 root 的 handler 重复打印
