# -*- coding: utf-8 -*-
"""desktop-v1 服务端（FastAPI 可选依赖）。

启动条件：
- 配置 serve = true
- 安装 fastapi + uvicorn + websockets
- 设置 JINYV_DESKTOP_TOKEN（或 config token）
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from .protocol import actions_for, envelope, split_bubbles, take_tags


def create_app(plugin: Any, ctx: Any):
    from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
    from fastapi.responses import JSONResponse

    app = FastAPI(title="jinyv-desktop-v1")
    token = plugin.token

    def authed(supplied: str) -> bool:
        import hmac
        return bool(token) and hmac.compare_digest(str(supplied or ""), token)

    @app.get("/desktop/v1/health")
    async def health():
        return JSONResponse({
            "ok": True, "protocol": "desktop-v1", "mode": "adapter",
            "connected": plugin.connected,
        })

    @app.post("/desktop/v1/say")
    async def say(request: Request):
        supplied = request.headers.get("authorization", "").replace("Bearer ", "").strip()
        if not authed(supplied):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        body = await request.json()
        text = str(body.get("text") or "").strip()
        if not text:
            return JSONResponse({"error": "text required"}, status_code=400)
        plugin.pending_say.append(text)
        return JSONResponse({"ok": True, "queued": True})

    @app.websocket("/desktop/v1/ws")
    async def desktop_ws(ws: WebSocket):
        supplied = ws.headers.get("authorization", "").replace("Bearer ", "").strip()
        if not authed(supplied):
            await ws.close(code=4001)
            return
        await ws.accept()
        plugin.connected = True
        device_id = "dev_" + plugin.new_device_id()
        seq = 0
        try:
            raw = await asyncio.wait_for(ws.receive_text(), timeout=10)
            hello = json.loads(raw)
            if hello.get("type") != "hello":
                await ws.close(code=4006)
                return
            payload = hello.get("payload") or {}
            device_id = str(payload.get("device_id") or device_id)
            seq += 1
            await ws.send_json(envelope("hello.ack", {
                "session": plugin.session_id,
                "primary": True,
                "server_time": plugin.now_ms(),
                "heartbeat_s": 30,
                "protocol": "desktop-v1",
            }, device_id=device_id, seq=seq))
            while True:
                raw = await ws.receive_text()
                msg = json.loads(raw)
                mtype = msg.get("type")
                if mtype in ("pong", "ack"):
                    continue
                if mtype == "event.text":
                    text = str((msg.get("payload") or {}).get("text") or "").strip()
                    if not text:
                        continue
                    reply = await asyncio.to_thread(plugin.handle_text, text)
                    clean, actions, moods = take_tags(reply)
                    mood = moods[0] if moods else "neutral"
                    seq += 1
                    await ws.send_json(envelope("pet.say", {
                        "bubbles": split_bubbles(clean, mood),
                        "emotion": mood,
                        "actions": actions + actions_for(clean),
                    }, device_id=device_id, seq=seq))
                if plugin.pending_say:
                    text = plugin.pending_say.pop(0)
                    seq += 1
                    await ws.send_json(envelope("pet.say", {
                        "bubbles": split_bubbles(text),
                        "emotion": "neutral",
                        "actions": [],
                    }, device_id=device_id, seq=seq))
        except (WebSocketDisconnect, asyncio.TimeoutError):
            pass
        finally:
            plugin.connected = False

    return app
