# -*- coding: utf-8 -*-
"""宿主 HTTP API 启动器。

真正的服务实现在 **Jinyv-memory/tools/serve.py**（同一个 `RP_DB` 只能有一个
写入进程）。本目录只负责定位记忆仓库并把参数透传过去，避免复制一份会漂移的
HTTP 实现。

用法：
    python host-api/__init__.py --port 8710 --db /opt/qqbot/data/rp_memory.db

环境变量：
    RP_HOST_TOKEN      必填，Bearer 令牌
    JINYV_MEMORY_HOME  Jinyv-memory 仓库根目录（未安装 jinyv_memory 时必填）

结构：
    config.py    命令行 / 环境变量
    bootstrap.py 定位 serve.py、透传参数
    __init__.py  组合根
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from bootstrap import _memory_home, main                         # noqa: E402,F401

if __name__ == "__main__":
    raise SystemExit(main())
