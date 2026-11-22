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
"""
from __future__ import annotations

import argparse
import os
import runpy
import sys
from pathlib import Path


def _memory_home() -> Path | None:
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Jinyv 宿主 HTTP API")
    parser.add_argument("--host", default=os.environ.get("JINYV_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("JINYV_HOST_PORT", "8710")))
    parser.add_argument("--db", default=os.environ.get("RP_DB") or "")
    args = parser.parse_args(argv)

    home = _memory_home()
    if home is None:
        print("找不到 Jinyv-memory：请设置 JINYV_MEMORY_HOME 或安装 jinyv_memory",
              file=sys.stderr)
        return 2
    serve = home / "tools" / "serve.py"
    if not os.environ.get("RP_HOST_TOKEN"):
        print("缺少 RP_HOST_TOKEN（除 /health 外都要 Bearer 校验）", file=sys.stderr)
        return 2

    sys.argv = ["serve.py", "--host", args.host, "--port", str(args.port)]
    if args.db:
        sys.argv += ["--db", args.db]
    runpy.run_path(str(serve), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
