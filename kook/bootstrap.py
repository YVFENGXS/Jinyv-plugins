# -*- coding: utf-8 -*-
"""启动层：插件目录上 sys.path、侧车日志、watchdog 事件戳。"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

EVENT_STAMP = os.environ.get("KOOK_EVENT_STAMP") or "/tmp/sidecar_last_event"


def log(msg: str) -> None:
    print(time.strftime("[%H:%M:%S]"), "[kook-sidecar]", msg, flush=True)


def mark_event() -> None:
    """记下最近一条入站消息的时间，watchdog 靠它判断网关是不是「假在线」。"""
    try:
        with open(EVENT_STAMP, "w", encoding="utf-8") as fh:
            fh.write(str(int(time.time())))
    except OSError:
        pass
