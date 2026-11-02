# -*- coding: utf-8 -*-
"""desktop-v1 协议纯函数：信封、气泡、标记解析。"""
from __future__ import annotations

import json
import re
import time
import uuid

TAG_RE = re.compile(r"\[\[(act|mood):([^\]]+)\]\]", re.I)
MOTIONS = {"wag", "nod", "shake", "jump", "eat", "sleep", "wave"}
EXPRESSIONS = {"neutral", "happy", "sad", "angry", "shy", "sleepy", "surprised"}


def now_ms() -> int:
    return int(time.time() * 1000)


def new_id() -> str:
    return uuid.uuid4().hex


def envelope(msg_type: str, payload: dict, device_id: str | None = None,
             seq: int = 0) -> dict:
    body = {
        "v": 1,
        "id": new_id(),
        "type": msg_type,
        "ts": now_ms(),
        "seq": seq,
        "payload": payload,
    }
    if device_id:
        body["device_id"] = device_id
    return body


def parse_incoming(raw: str) -> dict | None:
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def take_tags(reply: str) -> tuple[str, list[str], list[str]]:
    actions, moods = [], []
    for kind, word in TAG_RE.findall(reply or ""):
        word = word.lower()
        if kind.lower() == "act" and word in MOTIONS and word not in actions:
            actions.append(word)
        elif kind.lower() == "mood" and word in EXPRESSIONS and word not in moods:
            moods.append(word)
    clean = TAG_RE.sub("", reply or "")
    clean = re.sub(r"\[\[[^\]]*\]\]", "", clean).strip()
    clean = re.sub(r"[ \t]{2,}", " ", clean)
    return clean, actions[:1], moods[:1]


def split_bubbles(reply: str, mood: str = "neutral") -> list[dict]:
    text = re.sub(r"\[\[[^\]]*\]\]", "", reply or "").strip()
    if not text:
        return []
    parts = [part.strip() for part in re.split(r"(?<=[。！？!?])", text) if part.strip()]
    parts = parts[:3] or [text]
    return [
        {
            "text": part,
            "emotion": mood if index == 0 else "neutral",
            "delay_ms": 0 if index == 0 else 650,
            "tts_url": None,
        }
        for index, part in enumerate(parts)
    ]


def actions_for(reply: str) -> list[str]:
    return ["eat"] if re.search(r"米饭|吃|饿|喂", reply or "") else []
