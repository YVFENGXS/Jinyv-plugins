# -*- coding: utf-8 -*-
"""共享层回归：通道口径 / 生理状态 / 待总结队列。

运行：python tests/test_common.py
"""
import os
import sys
import tempfile
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from common import channel, pending, vitals


def test_channel():
    assert channel.detect("qq") == "qq"
    assert channel.detect("kook") == "kook"
    assert channel.detect("desk") == "desk"
    assert channel.detect("video-call") == "video"
    assert channel.detect("something-else") == "qq"
    assert channel.limits("qq")["max_chars"] == 0, "打字通道不写死字数"
    assert channel.limits("video")["max_lines"] == 2
    out = channel.apply("人设正文", "qq")
    assert out.startswith("人设正文") and "当前媒介" in out
    assert "不超过 30 个字" not in channel.overlay("qq")
    assert channel.apply("", "video").startswith("【当前媒介")
    print("C1 通道口径: OK")


def test_vitals_cycle():
    path = tempfile.mktemp(suffix=".db")
    base = time.time()
    vitals.tick(path, now=base)
    vitals.event("sleep", path=path)
    state = vitals.tick(path, now=base + 8 * 3600)
    assert state["energy"] > 0.9, state
    assert state["sleepiness"] < 0.3, state

    vitals.event("wake", path=path)
    state = vitals.tick(path, now=base + 24 * 3600)
    assert state["energy"] < 0.4, state
    assert state["hunger"] > 0.5, state
    assert state["grogginess"] < 0.1, state

    vitals.event("feed", 0.5, path=path)
    vitals.event("drink", 0.5, path=path)
    state = vitals.load(path)
    assert state["hunger"] < 0.6 and state["thirst"] < 0.6, state

    text = vitals.brief(state)
    assert text.startswith("她此刻："), text
    assert "0." not in text, "数值不该进台词"
    conn = None
    os.unlink(path)
    print("C2 生理循环: OK", text)


def test_vitals_gate():
    path = tempfile.mktemp(suffix=".db")
    base = time.time()
    vitals.tick(path, now=base)
    ok, why = vitals.decide("active", path=path)
    assert ok, why
    vitals.event("sleep", path=path)
    state = vitals.load(path)
    ok, why = vitals.decide("active", state=state)
    assert not ok and "睡着" in why, (ok, why)
    ok, _ = vitals.decide("reply", state=state)
    assert ok, "睡着也要能回消息"
    os.unlink(path)
    print("C3 行为闸门: OK")


def test_pending_queue():
    path = tempfile.mktemp(suffix=".db")
    assert pending.append("视频里聊了海边", 0.7, "video", path=path) > 0
    assert pending.append("房间里喂了鱼", 0.5, "room", path=path) > 0
    assert pending.stats(path)["open"] == 2

    got = pending.claim(limit=1, ttl=600, path=path)
    assert len(got) == 1 and got[0]["source"] == "video", got
    assert pending.stats(path)["claimed"] == 1
    assert pending.claim(limit=5, ttl=600, path=path)[0]["id"] != got[0]["id"], "已认领的不该重复取"
    assert pending.ack([got[0]["id"]], path=path) == 1
    assert pending.stats(path)["done"] == 1

    # 未 ack 的认领过期后可重领；已 ack 的不再出现
    retry = pending.claim(limit=5, ttl=0, path=path)
    assert any(r["id"] == 2 for r in retry), retry
    assert all(r["id"] != got[0]["id"] for r in retry), retry
    os.unlink(path)
    print("C4 待总结队列: OK")


if __name__ == "__main__":
    test_channel()
    test_vitals_cycle()
    test_vitals_gate()
    test_pending_queue()
    print("\ncommon tests passed")
