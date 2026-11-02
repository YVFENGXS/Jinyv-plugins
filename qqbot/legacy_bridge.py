# -*- coding: utf-8 -*-
"""QQ 能力加载器：优先使用插件仓库内的 features/，旧目录只作可选回退。

迁移后：
- `richmsg / linkmeta / bili_live / reminder / owner_gate / asr / mcp_client /
  task_supervisor` 已复制到 `qqbot/features/`，导入已改为包内相对导入；
- 不再依赖 `E:\\rp_memory_project`；`legacy_source_dir` 仅作为手动回退。
- 旧入口 `__init__.py` 未复制；`legacy_entry` 仍可通过回退目录加载。
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Any

LOCAL_FEATURES = Path(__file__).resolve().parent / "features"
LOCAL_LEGACY_ENTRY = Path(__file__).resolve().parent / "legacy" / "nonebot_entry.py"

CAPABILITIES = {
    "richmsg": "富消息 / 贴纸 / 图片",
    "asr": "语音转文字",
    "linkmeta": "链接 / 视频 / 分镜",
    "bili_live": "B 站直播与视频",
    "reminder": "定时提醒",
    "owner_gate": "主人绑定与验证",
    "mcp_client": "MCP 只读工具",
    "task_supervisor": "后台任务监督",
    # 旧 __init__.py 里的主动话题/轮换/命令；未复制时走回退目录
    "legacy_entry": "主动话题 / 命令 / 会话轮换",
}


class LegacyBridge:
    def __init__(self, source_dir: str | Path | None = None):
        self.source_dir = Path(source_dir).resolve() if source_dir else None
        self.available = bool(self.source_dir and self.source_dir.is_dir())
        self.local_available = LOCAL_FEATURES.is_dir()

    def _local_path(self, name: str) -> Path | None:
        if name == "legacy_entry":
            return LOCAL_LEGACY_ENTRY if LOCAL_LEGACY_ENTRY.exists() else None
        path = LOCAL_FEATURES / f"{name}.py"
        return path if path.exists() else None

    def _fallback_path(self, name: str) -> Path | None:
        if not self.source_dir:
            return None
        path = self.source_dir / ("__init__.py" if name == "legacy_entry" else f"{name}.py")
        return path if path.exists() else None

    def status(self) -> dict[str, Any]:
        modules = {}
        for name, label in CAPABILITIES.items():
            local = self._local_path(name)
            fallback = self._fallback_path(name)
            path = local or fallback
            modules[name] = {
                "label": label,
                "file": str(path) if path else "",
                "present": bool(path),
                "source": "local" if local else ("fallback" if fallback else ""),
            }
        return {
            "source_dir": str(self.source_dir or ""),
            "available": bool(self.local_available or self.available),
            "local_available": self.local_available,
            "modules": modules,
        }

    def load(self, name: str) -> Any:
        """按需导入能力；本地优先，旧目录只作回退。"""
        if name not in CAPABILITIES:
            raise KeyError(f"未知 QQ 能力：{name}")
        local = self._local_path(name)
        if local is not None:
            module_name = (
                f"{__package__}.legacy.nonebot_entry"
                if name == "legacy_entry"
                else f"{__package__}.features.{name}"
            )
            return importlib.import_module(module_name)
        if not self.available:
            raise RuntimeError(f"能力不可用：{name}（插件内无本地模块，且未配置 legacy_source_dir）")
        directory = str(self.source_dir)
        if directory not in sys.path:
            sys.path.insert(0, directory)
        return importlib.import_module(name)

    @staticmethod
    def has_module(module_name: str) -> bool:
        try:
            return importlib.util.find_spec(module_name) is not None
        except (ImportError, ModuleNotFoundError):
            return False
