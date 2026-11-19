# -*- coding: utf-8 -*-
"""视频通话服务适配层。

边界：
- 服务源码在独立仓库 YVFENGXS/jinyu-video-call，主仓库不复制其 Live2D 舞台、
  ASR/TTS 或画面判读代码。
- 本插件负责：lane 绑定、服务发现、健康检查、跨窗口发话桥（后续阶段实现）。
- 记忆写入统一走 MemoryAPI；通话服务通过宿主 API 或本插件桥接。
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any

from jinyv_memory.contract import Health, PluginContext, ToolSpec, TurnContext

from .bridge import CallBridge
from .core_client import CoreClient

CORE_MODES = ("embedded", "local", "server")


def create_plugin() -> "VideoCallPlugin":
    return VideoCallPlugin()


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError):
        return False


class VideoCallPlugin:
    REPO = "https://github.com/YVFENGXS/jinyu-video-call"

    def setup(self, ctx: PluginContext) -> None:
        self.ctx = ctx
        self.account = str(ctx.config.get("account") or "video_call")
        self.service_url = str(ctx.config.get("service_url") or "")
        self.token = ctx.config.secret("token", env_var="JINYV_VIDEO_CALL_TOKEN")
        self.bridge = CallBridge(self.service_url, self.token)
        self.core_mode = str(ctx.config.get("core_mode") or "embedded").lower()
        if self.core_mode not in CORE_MODES:
            ctx.logger.warning("未知 core_mode=%s，回退 embedded", self.core_mode)
            self.core_mode = "embedded"
        default_core = "http://127.0.0.1:8710" if self.core_mode == "local" else ""
        self.core_url = str(ctx.config.get("core_url") or default_core)
        self.core_token = ctx.config.secret("core_token", env_var="JINYV_HOST_API_TOKEN")
        self.core_ok = self.core_mode == "embedded"
        self.session_id = ctx.accounts.get(self.account).session_id
        self.core = CoreClient(self.core_url, self.core_token, account=self.account,
                               session=self.session_id)
        self.repo_dir = ""
        self.serve = bool(ctx.config.get("serve", False))
        ctx.tools.register(ToolSpec(
            name="video_call.status",
            description="查看视频通话服务与适配层状态。",
            parameters={"type": "object", "properties": {}},
            handler=self._tool_status,
        ), ctx.plugin_id)
        ctx.tools.register(ToolSpec(
            name="video_call.say",
            description="把一句话推到通话页播放（跨窗口发话）。",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            handler=self._tool_say,
        ), ctx.plugin_id)
        ctx.tools.register(ToolSpec(
            name="video_call.turn",
            description="把一句话发给通话服务，返回通话回复并写入共享记忆。",
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "session": {"type": "string"},
                },
                "required": ["text"],
            },
            handler=self._tool_turn,
        ), ctx.plugin_id)

    def start(self, ctx: PluginContext) -> None:
        if self.core_mode != "embedded":
            if not self.core_url:
                ctx.degrade(f"core_mode={self.core_mode} 但未配置 core_url")
                return
            if not self.core_token:
                ctx.degrade("缺少 core_token / JINYV_HOST_API_TOKEN")
                return
            probe = self.core.health()
            self.core_ok = bool(probe.get("ok"))
            if self.core_ok:
                ctx.logger.info("通话适配层已连接记忆核心 %s（%s）",
                                self.core_url, self.core_mode)
            else:
                ctx.logger.warning("记忆核心暂不可达 %s: %s", self.core_url,
                                   probe.get("error") or probe.get("status"))
        self.repo_dir = str(ctx.config.get("repo_dir") or os.environ.get("JINYV_VIDEO_CALL_DIR") or "")
        if self.serve:
            if not self.repo_dir:
                ctx.degrade(f"serve=true 需要服务目录；请独立安装 {self.REPO}")
                return
            if not Path(self.repo_dir).exists():
                ctx.degrade(f"服务目录不存在：{self.repo_dir}")
                return
            if not _has_module("fastapi"):
                ctx.degrade("fastapi 未安装，无法在本进程拉起通话服务")
                return
        elif not self.service_url:
            ctx.degrade("未配置 service_url 或 repo_dir；请指向本地或远程通话服务")
            return
        elif self.repo_dir and not Path(self.repo_dir).exists():
            ctx.logger.warning("服务目录不存在，仅使用 service_url=%s", self.service_url)
        ctx.logger.info("视频通话适配层就绪：service_url=%s repo_dir=%s",
                        self.service_url, self.repo_dir)

    def health(self, ctx: PluginContext) -> Health:
        if ctx.degraded_reason:
            return Health.degraded(ctx.degraded_reason, service_url=self.service_url,
                                   core_mode=self.core_mode, core_url=self.core_url)
        return Health.ok(service_url=self.service_url, repo_dir=self.repo_dir,
                         account=self.account, core_mode=self.core_mode,
                         core_url=self.core_url, core_ok=self.core_ok)

    # ------------------------------------------------------------ 桥接接口
    def memory_context(self, query: str, *, speaker: str = "") -> str:
        """给通话服务拼一段可注入的记忆文本（只读，不写）。"""
        if self.core_mode != "embedded":
            result = self.core.recall(query, limit=4, speaker=speaker)
            self.core_ok = bool(result.get("ok"))
            return str(result.get("text") or "")
        lane = self.ctx.accounts.get(self.account)
        result = self.ctx.memory.recall(lane, query, limit=4, speaker=speaker)
        return result.text

    def record_turn(self, text: str, reply: str, *, speaker: str = "") -> None:
        """通话产生的一轮写入共享记忆；store_reply 保持通话原文。"""
        if self.core_mode != "embedded":
            result = self.core.chat(text, speaker=speaker, store_reply=reply,
                                    source="video-call")
            self.core_ok = bool(result.get("ok"))
            if not self.core_ok:
                self.ctx.logger.warning("通话写入记忆核心失败: %s",
                                        result.get("error") or result.get("status"))
            return
        lane = self.ctx.accounts.get(self.account)
        self.ctx.memory.chat(lane, text, speaker=speaker, source="video-call",
                             store_reply=lambda _generated: reply)

    # ------------------------------------------------------------ 工具
    def _tool_status(self, args: Any, turn: TurnContext | None) -> dict:
        return {
            "ok": True,
            "service_url": self.service_url,
            "repo_dir": self.repo_dir,
            "account": self.account,
            "core_mode": self.core_mode,
            "core_url": self.core_url,
            "core_ok": self.core_ok,
            "degraded": self.ctx.degraded_reason,
        }

    def _tool_say(self, args: Any, turn: TurnContext | None) -> dict:
        text = str((args or {}).get("text") or "").strip()
        if not text:
            return {"ok": False, "error": "text 不能为空"}
        return self.bridge.say(
            text,
            session=str((args or {}).get("session") or ""),
            source="jinyv",
        )

    def _tool_turn(self, args: Any, turn: TurnContext | None) -> dict:
        text = str((args or {}).get("text") or "").strip()
        if not text:
            return {"ok": False, "error": "text 不能为空"}
        result = self.bridge.turn(
            text,
            session=str((args or {}).get("session") or ""),
        )
        reply = str(result.get("reply") or "").strip()
        if reply:
            self.record_turn(text, reply)
        return result
