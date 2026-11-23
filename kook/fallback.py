# -*- coding: utf-8 -*-
"""KOOK 兜底发送口：QQ 掉线时宿主 POST /send，这里发到固定频道。"""
from __future__ import annotations

from bootstrap import log


async def upload_kook_image(cfg: dict, data_uri: str) -> str:
    """把 data:image/... 传到 KOOK 图床，返回可直接放进 <img src> 的地址。

    KOOK 不认 data URI（会渲染成空白框），所以贴纸要先换成一个真实 URL。
    """
    import base64 as _b64

    import httpx

    if not cfg["kook_token"]:
        return ""
    head, _, payload = data_uri.partition(",")
    try:
        raw = _b64.b64decode(payload)
    except Exception:                    # noqa: BLE001
        return ""
    if not raw or len(raw) > 8 * 1024 * 1024:
        return ""
    mime = "image/png"
    if head.startswith("data:") and ";" in head:
        mime = head[5:head.index(";")] or mime
    ext = {"image/jpeg": "jpg", "image/gif": "gif",
           "image/webp": "webp"}.get(mime, "png")
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                "https://www.kookapp.cn/api/v3/asset/create",
                headers={"Authorization": "Bot " + cfg["kook_token"]},
                files={"file": (f"kook-fallback.{ext}", raw, mime)})
        data = resp.json() or {}
    except Exception as exc:             # noqa: BLE001
        log(f"KOOK 图床请求失败：{type(exc).__name__}: {str(exc)[:100]}")
        return ""
    if resp.status_code == 200 and data.get("code") == 0:
        return str((data.get("data") or {}).get("url") or "")
    log(f"KOOK 图床上传失败 {resp.status_code}: {str(data)[:120]}")
    return ""


async def start_sender(cfg: dict, app):
    """宿主主动消息入口：QQ 掉线时 POST /send，转成 KOOK 消息发出去。

    文字和图片分两条发：图片坏了不影响文字送达；
    频道固定用 KOOK_FALLBACK_CHANNEL，避免主动消息散落到别的会话。
    """
    try:
        from aiohttp import web
    except ImportError:
        log("缺少 aiohttp，KOOK 兜底发送口未启动")
        return None

    def _bad(msg: str, code: int = 400):
        return web.json_response({"ok": False, "error": msg}, status=code)

    async def handle(request):
        if request.headers.get("Authorization", "") != "Bearer " + cfg["jinyu_token"]:
            return _bad("unauthorized", 401)
        if not cfg["kook_channel"]:
            return _bad("KOOK_FALLBACK_CHANNEL 未配置", 503)
        accounts = list(app.accounts.values())
        if not accounts:
            return _bad("KOOK 账号还没连接", 503)
        try:
            body = await request.json()
        except Exception:                    # noqa: BLE001
            return _bad("bad json")
        text = str(body.get("text") or "")[:4000]
        images = [u for u in (body.get("images") or []) if isinstance(u, str)][:4]
        account = accounts[0]
        sent = False
        if text:
            try:
                await account.message_create(cfg["kook_channel"], text)
                sent = True
            except Exception as exc:         # noqa: BLE001
                log(f"兜底文字发送失败：{type(exc).__name__}: {exc}")
        for src in images:                   # 逐张发，坏一张不拖累已发内容
            if src.startswith("data:"):
                src = await upload_kook_image(cfg, src)
                if not src:
                    continue
            try:
                await account.message_create(
                    cfg["kook_channel"], f'<img src="{src}"/>')
                sent = True
            except Exception as exc:         # noqa: BLE001
                log(f"兜底图片发送失败：{type(exc).__name__}: {str(exc)[:100]}")
        log(f"兜底投递 {'成功' if sent else '失败'}：{len(text)}字 图{len(images)}张")
        return web.json_response({"ok": sent})

    application = web.Application()
    application.router.add_post("/send", handle)
    runner = web.AppRunner(application)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", cfg["send_port"])
    await site.start()
    log(f"兜底发送口已就绪 http://127.0.0.1:{cfg['send_port']}/send"
        f"  频道={cfg['kook_channel'] or '未配置'}")
    return runner


# 兼容旧导入名
_upload_kook_image = upload_kook_image
