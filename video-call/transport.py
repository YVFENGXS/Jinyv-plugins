# -*- coding: utf-8 -*-
"""公共 HTTP 传输层（stdlib urllib，零第三方依赖）。"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request


def request_json(base_url: str, token: str, method: str, path: str, *,
                 payload: dict | None = None, query: dict | None = None,
                 timeout: float = 5.0, auth: bool = True,
                 missing: str = "服务地址未配置") -> dict:
    """发一个 JSON 请求；网络错误统一转成 {"ok": False, "error": ...}。"""
    if not base_url:
        return {"ok": False, "error": missing}
    url = f"{base_url}{path}"
    if query:
        url += "?" + urllib.parse.urlencode(query)
    data = None if payload is None else json.dumps(
        payload, ensure_ascii=False
    ).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    if auth and token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8") or "{}")
            body.setdefault("ok", True)
            return body
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "ignore") or "{}"
        try:
            body = json.loads(raw)
        except ValueError:
            body = {"error": raw}
        body.setdefault("ok", False)
        body.setdefault("status", exc.code)
        return body
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
