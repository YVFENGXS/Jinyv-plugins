# -*- coding: utf-8 -*-
"""导出离线星图：把接口数据内联进一个 HTML，手机断开网络也能打开。

用法：
    curl -H "X-Gate-Token: 口令" http://127.0.0.1:8712/api/memories > data.json
    python export.py --data data.json --out 记忆星图.html
"""
from __future__ import annotations

import argparse
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(BASE, "static")


def build(data: dict) -> str:
    with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as f:
        html = f.read()
    with open(os.path.join(STATIC, "style.css"), encoding="utf-8") as f:
        css = f.read()
    with open(os.path.join(STATIC, "app.js"), encoding="utf-8") as f:
        js = f.read()
    # 内联数据里的 </script> 会提前闭合标签，转义掉
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = html.replace('<link rel="stylesheet" href="style.css">',
                        "<style>\n%s\n</style>" % css)
    html = html.replace(
        '<script src="app.js"></script>',
        "<script>window.__STARMAP_DATA__=%s;</script>\n<script>\n%s\n</script>"
        % (payload, js))
    return html


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="接口 JSON 文件")
    ap.add_argument("--out", required=True, help="输出 HTML 路径")
    args = ap.parse_args()
    with open(args.data, encoding="utf-8") as f:
        data = json.load(f)
    html = build(data)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)
    print("已导出 %s（%.1f KB，%d 节点）"
          % (args.out, len(html.encode("utf-8")) / 1024.0, len(data.get("nodes") or [])))


if __name__ == "__main__":
    main()
