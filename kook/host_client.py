# -*- coding: utf-8 -*-
"""宿主 HTTP 客户端：把一条 KOOK 消息转成 /jinyu/chat 调用。"""
from __future__ import annotations

from bootstrap import log


async def call_host(cfg: dict, text: str, images: list[str] | None = None) -> str:
    import httpx

    payload = {"text": text, "prompt": text, "source": cfg["jinyu_source"]}
    if images:
        payload["images"] = images
    headers = {"Authorization": "Bearer " + cfg["jinyu_token"]}
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(cfg["jinyu_host"] + "/jinyu/chat", json=payload, headers=headers)
    if resp.status_code != 200:
        raise RuntimeError(f"host HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json() or {}
    reply = str(data.get("reply") or "").strip()
    if not reply:
        log(f"宿主返回空 reply，原始响应：{str(data)[:300]}")
    return reply


async def preflight_host(cfg: dict) -> None:
    """宿主接口连通性只告警不阻断：主进程可能比侧车晚起。"""
    import httpx

    url = cfg["jinyu_host"] + "/jinyu/health"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
        log(f"宿主接口预检 {url} -> {resp.status_code}")
    except Exception as exc:  # noqa: BLE001
        log(f"宿主接口暂不可达（{type(exc).__name__}: {exc}），收到消息时会重试")
