# -*- coding: utf-8 -*-
"""统一通道口径：同一套人格，不同媒介只调整「外壳」。

原则：
- 人设只有一份（Jinyv-memory/core/persona.py），这里不写人设；
- 只写「这个媒介怎么说话」：能不能用 markdown、要不要旁白、字幕多长；
- **不写死字数/句数**（QQ、KOOK 这类打字通道不限制条数），只有视频字幕、
  房间投屏这种物理受限的场景才给硬上限；
- 平台名归一成一个通道键，未知平台按打字通道处理。
"""
from __future__ import annotations

CHANNELS = {
    "qq": {
        "label": "QQ 打字",
        "max_tokens": 320,
        "max_chars": 0,          # 0 = 不限制
        "max_lines": 0,
        "overlay": (
            "【当前媒介：QQ 打字】\n"
            "- 像随手打字：不用 markdown、不写标题、不分点。\n"
            "- 想拆几条就拆几条，长度跟着情绪和内容走。\n"
            "- 动作和神态自然带出即可；表情包有合适的就发。"
        ),
    },
    "kook": {
        "label": "KOOK 打字",
        "max_tokens": 320,
        "max_chars": 0,
        "max_lines": 0,
        "overlay": (
            "【当前媒介：KOOK 打字】\n"
            "- 像随手打字：不用 markdown、不写标题、不分点。\n"
            "- 长度和条数跟着内容走；动作和神态自然带出。"
        ),
    },
    "desk": {
        "label": "桌宠",
        "max_tokens": 320,
        "max_chars": 0,
        "max_lines": 0,
        "overlay": (
            "【当前媒介：桌宠对话】\n"
            "- 像在旁边说话：不用 markdown、不写标题、不分点。\n"
            "- 动作可以被桌宠表演出来，自然写就行。"
        ),
    },
    "video": {
        "label": "视频通话",
        "max_tokens": 220,
        "max_chars": 60,          # 字幕一行放得下的硬上限
        "max_lines": 2,
        "overlay": (
            "【当前媒介：视频通话】\n"
            "- 你说的话会被念出来：口语化，别写 markdown、分点、括号旁白。\n"
            "- 一次别长篇大论；要停顿、改口都可以，像真的在说。\n"
            "- 不要提系统、设定或情绪数值。"
        ),
    },
    "room": {
        "label": "房间投屏",
        "max_tokens": 220,
        "max_chars": 80,
        "max_lines": 2,
        "overlay": (
            "【当前媒介：房间投屏】\n"
            "- 文字会显示在房间的屏幕上：短、口语化，不用 markdown。\n"
            "- 不要解释系统或数值。"
        ),
    },
    "proactive": {
        "label": "主动消息",
        "max_tokens": 160,
        "max_chars": 0,
        "max_lines": 0,
        "overlay": (
            "【当前媒介：主动找她/他】\n"
            "- 像随口发一句，不解释为什么发；可以只说一半、留个尾巴。\n"
            "- 不写小作文，也不用 markdown。"
        ),
    },
}

DEFAULT = "qq"

PLATFORM_MAP = {
    "qq": "qq", "onebot": "qq", "napcat": "qq", "snowluma": "qq",
    "aiocqhttp": "qq",
    "kook": "kook", "khl": "kook", "satori": "kook",
    "desktop": "desk", "pet": "desk", "desk": "desk",
    "video": "video", "call": "video", "camera": "video",
    "room": "room", "stage": "room", "house": "room",
    "proactive": "proactive",
}


def detect(raw) -> str:
    """把平台名 / 来源字符串归一成通道键；认不出按 QQ 打字处理。"""
    s = str(raw or "").strip().lower()
    if not s:
        return DEFAULT
    for key, channel in PLATFORM_MAP.items():
        if key in s:
            return channel
    return DEFAULT


def limits(channel) -> dict:
    ch = CHANNELS.get(str(channel or "").lower()) or CHANNELS[DEFAULT]
    return {"label": ch["label"], "max_tokens": ch["max_tokens"],
            "max_chars": ch["max_chars"], "max_lines": ch["max_lines"]}


def overlay(channel) -> str:
    """该媒介的说话方式叠加段；只追加，不替换人设。"""
    ch = CHANNELS.get(str(channel or "").lower()) or CHANNELS[DEFAULT]
    return ch["overlay"]


def apply(prompt: str, channel) -> str:
    """把人设 prompt 和媒介叠加段拼起来（人设在前，媒介在后）。"""
    body = (prompt or "").rstrip()
    extra = overlay(channel)
    return f"{body}\n\n{extra}" if body else extra
