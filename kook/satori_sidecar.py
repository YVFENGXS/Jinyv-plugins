#!/usr/bin/env python3
"""Satori sidecar：把 KOOK（经 Koishi/Satori）的消息转给宿主接口。

一条消息只走三步：
    Satori message-created -> POST /jinyu/chat -> Satori message.create

本进程不碰数据库、不做记忆、不做提示词，重启不丢数据。
缺凭据时启动即退出，并打印缺哪一项；加 --check 只校验配置后退出。

运行：
    python kook/satori_sidecar.py --check
    python kook/satori_sidecar.py
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import capabilities as caps                                      # noqa: E402
from bootstrap import EVENT_STAMP, log as _log, mark_event as _mark_event  # noqa: E402
from config import (DEFAULT_JINYU_HOST, DEFAULT_SATORI_HOST,       # noqa: E402,F401
                    DEFAULT_SATORI_PORT, DEFAULT_SOURCE, REQUIRED,
                    check_config, load_config, print_status)
from fallback import start_sender                                 # noqa: E402
from host_client import call_host, preflight_host                 # noqa: E402
from media import (IMG_SRC, IMG_TAG, MAX_IMAGES,                  # noqa: E402,F401
                   extract_images, strip_images)


async def run(cfg: dict) -> int:
    try:
        from satori import EventType
        from satori.client import App, WebsocketsInfo
    except ImportError:
        _log("缺少依赖 satori-python：pip install satori-python httpx")
        return 3

    app = App(
        WebsocketsInfo(
            host=cfg["satori_host"],
            port=cfg["satori_port"],
            token=cfg["satori_token"] or None,
        )
    )
    lock = asyncio.Lock()

    @app.register
    async def on_event(account, event):
        if event.type != EventType.MESSAGE_CREATED:
            return
        user_id = getattr(getattr(event, "user", None), "id", "") or ""
        if user_id and user_id == account.self_id:
            return  # 自己发的消息不回声
        _mark_event()
        if cfg["allow_users"] and user_id not in cfg["allow_users"]:
            _log(f"忽略非白名单用户 {user_id}")
            return
        text = caps.to_text(event.message, account.platform)
        images = extract_images(event.message)
        if images:
            text = strip_images(text)
        if not text and not images:
            _log("消息里没有可读文本，跳过")
            return
        _log(f"收到 {user_id}: {text[:60] or '(无文字)'} 图{len(images)}张")
        async with lock:  # 单用户场景串行，保证记忆轮次顺序
            try:
                reply = await call_host(cfg, text, images)
            except Exception as exc:  # noqa: BLE001
                _log(f"调宿主失败：{type(exc).__name__}: {exc}")
                return
            if not reply:
                _log("宿主返回空回复（可能说到别的窗口了），不发")
                return
            for chunk in caps.clamp_outbound(reply, account.platform):
                try:
                    await account.send(event, chunk)
                except Exception as exc:  # noqa: BLE001
                    _log(f"发送失败：{type(exc).__name__}: {exc}")
                    return
        _log(f"已回复 {len(reply)} 字")

    await preflight_host(cfg)
    _log("已连接到 Satori，等待消息")
    _mark_event()                    # 刚起进程算「有活动」，别被 watchdog 立刻重连
    try:
        sender = await start_sender(cfg, app)
    except Exception as exc:             # noqa: BLE001 兜底口起不来不该拦住收消息
        _log(f"兜底发送口启动失败：{type(exc).__name__}: {exc}")
        sender = None
    try:
        await app.run_async()
    finally:
        if sender is not None:
            await sender.cleanup()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Satori -> /jinyu/chat 侧车")
    parser.add_argument("--check", action="store_true", help="只校验配置，不连接")
    args = parser.parse_args()

    cfg = load_config()
    problems = check_config(cfg)
    print_status(cfg, problems)
    if problems:
        return 2
    if args.check:
        _log("配置校验通过")
        return 0
    try:
        return asyncio.run(run(cfg))
    except KeyboardInterrupt:
        _log("收到中断，退出")
        return 0


if __name__ == "__main__":
    sys.exit(main())
