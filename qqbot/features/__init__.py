# -*- coding: utf-8 -*-
"""QQ 旧能力的插件侧适配入口（按迁移顺序排列）。

这些模块是**新写的适配层**，不是旧源码副本：
- 旧实现仍在 E:\\rp_memory_project，原文件不改；
- 通过 LegacyBridge 只读导入对应模块；
- 旧模块的第三方依赖（nonebot / httpx / mcp）缺失时，适配入口保持不可用并降级，
  不拖垮 qqbot 最小闭环。

迁移顺序（与 README/迁移表一致）：
richmsg → linkmeta → reminder → owner_gate → asr → bili_live
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..legacy_bridge import LegacyBridge

CAPABILITY_ORDER = (
    "richmsg",
    "linkmeta",
    "reminder",
    "owner_gate",
    "asr",
    "bili_live",
    "mcp_client",
    "task_supervisor",
    "legacy_entry",
)

LABELS = {
    "richmsg": "富消息 / 贴纸 / 图片",
    "linkmeta": "链接 / 视频 / 分镜",
    "reminder": "定时提醒",
    "owner_gate": "主人绑定与验证",
    "asr": "语音转文字",
    "bili_live": "B 站直播与视频",
    "mcp_client": "MCP 只读工具",
    "task_supervisor": "后台任务监督",
    "legacy_entry": "主动话题 / 命令 / 会话轮换",
}


@dataclass(frozen=True)
class Capability:
    name: str
    label: str
    order: int
    present: bool

    @property
    def available(self) -> bool:
        return self.present


class FeatureRegistry:
    """把旧能力暴露为稳定的插件侧入口，但不复制旧代码。"""

    def __init__(self, bridge: LegacyBridge):
        self.bridge = bridge
        raw = bridge.status()
        modules = raw.get("modules") or {}
        self._sources = {
            name: str((modules.get(name) or {}).get("source") or "")
            for name in CAPABILITY_ORDER
        }
        self._items = [
            Capability(
                name=name,
                label=LABELS.get(name, name),
                order=index,
                present=bool((modules.get(name) or {}).get("present")),
            )
            for index, name in enumerate(CAPABILITY_ORDER)
        ]

    def list(self) -> list[Capability]:
        return list(self._items)

    def get(self, name: str) -> Capability | None:
        return next((item for item in self._items if item.name == name), None)

    def load(self, name: str) -> Any:
        """按需导入旧能力；依赖缺失时由调用方捕获 ImportError。"""
        item = self.get(name)
        if item is None:
            raise KeyError(f"未知 QQ 能力：{name}")
        if not item.present:
            raise RuntimeError(f"旧能力不可用：{name}（未配置 legacy_source_dir）")
        return self.bridge.load(name)

    def status(self) -> list[dict[str, Any]]:
        return [
            {
                "name": item.name,
                "label": item.label,
                "order": item.order,
                "present": item.present,
                "available": item.available,
                "source": self._sources.get(item.name, ""),
            }
            for item in self._items
        ]
