# -*- coding: utf-8 -*-
"""只读桥接到旧 jinyu-memory QQ 实现（迁移过渡期）。

设计边界：
- 旧实现仍在 E:\\rp_memory_project，原文件不改、不复制进本仓库。
- 本仓库提供新适配层；需要旧能力时，由配置 `legacy_source_dir` 指向旧包目录，
  运行时按需导入对应模块。
- 这是过渡方案，不是最终形态；物理迁移（新建 + 改写）需逐模块评审后再进行，
  避免出现两份实现和单一真源漂移。
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Any

CAPABILITIES = {
    "richmsg": "富消息 / 贴纸 / 图片",
    "asr": "语音转文字",
    "linkmeta": "链接 / 视频 / 分镜",
    "bili_live": "B 站直播与视频",
    "reminder": "定时提醒",
    "owner_gate": "主人绑定与验证",
    "mcp_client": "MCP 只读工具",
    "task_supervisor": "后台任务监督",
    # 旧 __init__.py 里还包含主动话题、轮换、命令等入口逻辑
    "legacy_entry": "主动话题 / 命令 / 会话轮换",
}


class LegacyBridge:
    def __init__(self, source_dir: str | Path | None):
        self.source_dir = Path(source_dir).resolve() if source_dir else None
        self.available = bool(self.source_dir and self.source_dir.is_dir())

    def status(self) -> dict[str, Any]:
        modules = {}
        for name, label in CAPABILITIES.items():
            if name == "legacy_entry":
                path = self.source_dir / "__init__.py" if self.source_dir else None
            else:
                path = self.source_dir / f"{name}.py" if self.source_dir else None
            modules[name] = {
                "label": label,
                "file": str(path) if path else "",
                "present": bool(path and path.exists()),
            }
        return {
            "source_dir": str(self.source_dir or ""),
            "available": self.available,
            "modules": modules,
        }

    def load(self, name: str) -> Any:
        """按需导入旧模块。调用方必须处理旧模块的第三方依赖缺失。"""
        if not self.available:
            raise RuntimeError("未配置 qqbot.legacy_source_dir")
        if name not in CAPABILITIES:
            raise KeyError(f"未知旧能力：{name}")
        directory = str(self.source_dir)
        if directory not in sys.path:
            sys.path.insert(0, directory)
        module = importlib.import_module(name)
        return module

    @staticmethod
    def has_module(module_name: str) -> bool:
        try:
            return importlib.util.find_spec(module_name) is not None
        except (ImportError, ModuleNotFoundError):
            return False
