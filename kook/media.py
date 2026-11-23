# -*- coding: utf-8 -*-
"""消息元素层：从 Satori 消息里提取图片地址、剥掉图片标记。"""
from __future__ import annotations

import re
from typing import Any

MAX_IMAGES = 4                 # 一条消息最多带几张图；宿主侧同样按这个上限截断
IMG_TAG = re.compile(r"<img\b[^>]*>", re.I)
IMG_SRC = re.compile(r"""src\s*=\s*["']([^"']+)["']""", re.I)


def collect_images(node: Any, out: list[str], depth: int = 0) -> None:
    """深度优先找 <img> 元素，取 src；只认 http(s)，不做平台特判。"""
    if depth > 6 or len(out) >= MAX_IMAGES:
        return
    tag = str(getattr(node, "tag", "") or "").lower()
    src = getattr(node, "src", None)
    if tag == "img" and isinstance(src, str):
        if src.startswith(("http://", "https://")):
            out.append(src)
        return
    for child in getattr(node, "_children", None) or []:
        collect_images(child, out, depth + 1)


def extract_images(message: Any) -> list[str]:
    """从 satori 消息里取图片地址。

    优先用 MessageObject.message（元素表）；取不到时退回扫 content 里的
    <img src="..."/> 标记——KOOK 侧的 content 就是这种字符串。
    """
    urls: list[str] = []
    try:
        elements = getattr(message, "message", None)
    except Exception:                              # noqa: BLE001 解析失败就退回正则
        elements = None
    if isinstance(elements, list):
        for element in elements:
            collect_images(element, urls)
    if not urls:
        content = getattr(message, "content", None)
        if isinstance(content, str) and "<img" in content.lower():
            for tag in IMG_TAG.finditer(content):
                found = IMG_SRC.search(tag.group(0))
                if found and found.group(1).startswith(("http://", "https://")):
                    urls.append(found.group(1))
    return urls[:MAX_IMAGES]


def strip_images(text: str) -> str:
    """图片标记不该出现在给模型的正文里。"""
    return " ".join(IMG_TAG.sub(" ", text).split())


# 兼容旧私有名
_collect_images = collect_images
