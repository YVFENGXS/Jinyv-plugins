# -*- coding: utf-8 -*-
"""桌宠服务端适配层（desktop-v1）。

边界：
- 客户端是独立仓库 YVFENGXS/Jinyu-pet，源码与 Electron 资产不进入主仓库。
- 本插件只负责协议入口、lane 绑定、健康检查与推送桥；记忆仍走 MemoryAPI。
- 本轮只落结构与接口；真正的 WebSocket 服务在后续阶段包装 desktop_server.py。
"""
from __future__ import annotations

import importlib.util
import os
import threading
from pathlib import Path
from typing import Any

from jinyv_memory.contract import Health, PluginContext, ToolSpec, TurnContext

from .core_client import CoreClient
from .protocol import new_id, now_ms

CORE_MODES = ("embedded", "local", "server")


def create_plugin() -> "DesktopPetPlugin":
    return DesktopPetPlugin()


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError):
        return False


class DesktopPetPlugin:
    CLIENT_REPO = "https://github.com/YVFENGXS/Jinyu-pet"

    def setup(self, ctx: PluginContext) -> None:
        self.ctx = ctx
        self.account = str(ctx.config.get("account") or "desktop")
        self.service_url = str(ctx.config.get("service_url") or "")
        self.core_mode = str(ctx.config.get("core_mode") or "embedded").lower()
        if self.core_mode not in CORE_MODES:
            ctx.logger.warning("未知 core_mode=%s，回退 embedded", self.core_mode)
            self.core_mode = "embedded"
        default_core = "http://127.0.0.1:8710" if self.core_mode == "local" else ""
        self.core_url = str(ctx.config.get("core_url") or default_core)
        self.core_token = ctx.config.secret("core_token", env_var="JINYV_HOST_API_TOKEN")
        self.core_ok = self.core_mode == "embedded"
        self.host = str(ctx.config.get("host") or "127.0.0.1")
        self.port = int(ctx.config.get("port") or 8787)
        self.token = ctx.config.secret("token", env_var="JINYV_DESKTOP_TOKEN")
        self.serve = bool(ctx.config.get("serve", False))
        self.connected = False
        self.session_id = ctx.accounts.get(self.account).session_id
        self.core = CoreClient(self.core_url, self.core_token, account=self.account,
                               session=self.session_id)
        self.pending_say: list[str] = []
        self._server = None
        self._thread: threading.Thread | None = None
        ctx.tools.register(ToolSpec(
            name="desktop.status",
            description="查看桌宠适配层与客户端连接状态。",
            parameters={"type": "object", "properties": {}},
            handler=self._tool_status,
        ), ctx.plugin_id)
        ctx.tools.register(ToolSpec(
            name="desktop.say",
            description="向已连接的桌宠设备推送一句话。",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            handler=self._tool_say,
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
                ctx.logger.info("桌宠已连接记忆核心 %s（%s）", self.core_url, self.core_mode)
            else:
                ctx.logger.warning("记忆核心暂不可达 %s: %s", self.core_url,
                                   probe.get("error") or probe.get("status"))
        missing = [name for name in ("fastapi", "uvicorn", "websockets")
                   if not _has_module(name)]
        if self.serve:
            if missing:
                ctx.degrade(f"desktop-v1 依赖缺失：{', '.join(missing)}")
                return
            if not self.token:
                ctx.degrade("缺少 JINYV_DESKTOP_TOKEN，未启动 desktop-v1 服务")
                return
            from .server import create_app

            import uvicorn

            app = create_app(self, ctx)
            config = uvicorn.Config(app, host=self.host, port=self.port,
                                    log_level="info")
            self._server = uvicorn.Server(config)
            self._thread = threading.Thread(target=self._server.run, daemon=True,
                                            name="jinyv-desktop-ws")
            self._thread.start()
            ctx.logger.info("desktop-v1 服务已启动 ws://%s:%s", self.host, self.port)
            return
        client_dir = str(ctx.config.get("client_dir")
                         or os.environ.get("JINYV_DESKTOP_PET_DIR") or "")
        if not client_dir:
            ctx.degrade(f"未配置客户端目录；客户端请独立安装 {self.CLIENT_REPO}")
            return
        if not Path(client_dir).exists():
            ctx.degrade(f"客户端目录不存在：{client_dir}")
            return
        ctx.logger.info("桌宠适配层就绪：client_dir=%s", client_dir)

    def stop(self, ctx: PluginContext) -> None:
        if self._server is not None:
            self._server.should_exit = True
            if self._thread is not None:
                self._thread.join(timeout=5)
            self._server = None
            self._thread = None
        self.connected = False

    @staticmethod
    def new_device_id() -> str:
        return new_id()[:12]

    @staticmethod
    def now_ms() -> int:
        return now_ms()

    def health(self, ctx: PluginContext) -> Health:
        if ctx.degraded_reason:
            return Health.degraded(ctx.degraded_reason, connected=self.connected,
                                   service_url=self.service_url,
                                   core_mode=self.core_mode, core_url=self.core_url)
        return Health.ok(connected=self.connected, service_url=self.service_url,
                         account=self.account, core_mode=self.core_mode,
                         core_url=self.core_url, core_ok=self.core_ok)

    # ------------------------------------------------------------ 协议入口
    def handle_hello(self, payload: dict[str, Any]) -> dict[str, Any]:
        """desktop-v1 hello 的最小处理：未来接入令牌与 capability 协商。"""
        self.connected = True
        return {
            "type": "hello.ok",
            "protocol": "desktop-v1",
            "capabilities": ["bubble.v1", "presence.report"],
            "server": "jinyv-memory",
        }

    def handle_text(self, text: str, *, speaker: str = "") -> str:
        """设备上行文字 → 核心一轮对话；与 QQ 共享同一条 lane 记忆。"""
        if self.core_mode != "embedded":
            result = self.core.chat(text, speaker=speaker, source="desktop")
            self.core_ok = bool(result.get("ok"))
            if not self.core_ok:
                self.ctx.logger.warning("桌宠写入记忆核心失败: %s",
                                        result.get("error") or result.get("status"))
            return str(result.get("reply") or "")
        lane = self.ctx.accounts.get(self.account)
        return self.ctx.memory.chat(lane, text, speaker=speaker, source="desktop")

    # ------------------------------------------------------------ 工具
    def _tool_status(self, args: Any, turn: TurnContext | None) -> dict:
        return {
            "ok": True,
            "connected": self.connected,
            "service_url": self.service_url,
            "account": self.account,
            "serve": self.serve,
            "running": bool(self._server),
            "core_mode": self.core_mode,
            "core_url": self.core_url,
            "core_ok": self.core_ok,
            "pending_say": len(self.pending_say),
            "degraded": self.ctx.degraded_reason,
        }

    def _tool_say(self, args: Any, turn: TurnContext | None) -> dict:
        text = str((args or {}).get("text") or "").strip()
        if not text:
            return {"ok": False, "error": "text 不能为空"}
        if not (self.connected or self._server is not None):
            return {"ok": False, "queued": False, "error": "desktop-v1 服务未启动或设备未连接"}
        self.pending_say.append(text)
        return {"ok": True, "queued": True}
