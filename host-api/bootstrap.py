# -*- coding: utf-8 -*-
"""启动层：定位 Jinyv-memory 的 tools/serve.py，把参数原样透传过去。"""
from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

from config import HostConfig, load_config


def memory_home() -> Path | None:
    candidates = []
    home = os.environ.get("JINYV_MEMORY_HOME")
    if home:
        candidates.append(Path(home))
    try:
        import jinyv_memory as pkg

        candidates.append(Path(pkg.__file__).resolve().parents[1])
    except Exception:                                    # noqa: BLE001
        pass
    here = Path(__file__).resolve()
    candidates.extend([here.parent.parent / "Jinyv-memory", here.parent.parent])
    for path in candidates:
        if (path / "tools" / "serve.py").is_file():
            return path
    return None


def run(cfg: HostConfig) -> int:
    home = memory_home()
    if home is None:
        print("找不到 Jinyv-memory：请设置 JINYV_MEMORY_HOME 或安装 jinyv_memory",
              file=sys.stderr)
        return 2
    serve = home / "tools" / "serve.py"
    if not os.environ.get("RP_HOST_TOKEN"):
        print("缺少 RP_HOST_TOKEN（除 /health 外都要 Bearer 校验）", file=sys.stderr)
        return 2

    sys.argv = ["serve.py", "--host", cfg.host, "--port", str(cfg.port)]
    if cfg.db:
        sys.argv += ["--db", cfg.db]
    runpy.run_path(str(serve), run_name="__main__")
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(load_config(argv))


# 兼容旧导入名
_memory_home = memory_home
