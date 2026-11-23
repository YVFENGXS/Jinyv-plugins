# -*- coding: utf-8 -*-
"""桌宠服务独立启动入口（不依赖核心进程内 MemoryAPI）。

用法示例：
  python standalone.py --core-url http://127.0.0.1:8710 \
      --core-token "$JINYV_HOST_API_TOKEN" --token "$JINYV_DESKTOP_TOKEN"

启动后暴露 /desktop/v1/health、/desktop/v1/say、/desktop/v1/ws；
上行文字通过宿主 HTTP API 写入本地或远程记忆核心。

结构：
    config.py    命令行 / 环境变量
    adapter.py   desktop-v1 适配对象
    bootstrap.py 健康检查 + uvicorn
    server.py    FastAPI 路由与 WebSocket
    standalone.py 组合根
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from adapter import StandaloneDesktop                           # noqa: E402,F401
from bootstrap import main                                       # noqa: E402
import protocol                                                  # noqa: E402,F401
from server import create_app                                    # noqa: E402,F401

if __name__ == "__main__":
    raise SystemExit(main())
