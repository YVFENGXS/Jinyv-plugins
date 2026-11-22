# KOOK (Satori sidecar)

把 KOOK 频道消息接进记忆宿主。链路：

```
KOOK ──> Koishi（adapter-kook + plugin-server/Satori）
      ──> satori_sidecar.py ──> host-api /jinyu/chat ──> Jinyv-memory
```

本进程**不碰数据库、不做记忆、不写提示词**，只做协议转换；重启不丢数据。

## 文件

| 文件 | 作用 |
|---|---|
| `satori_sidecar.py` | Satori WebSocket 客户端 + 宿主 HTTP 转发 |
| `capabilities.py` | 能力开关与降级判断 |
| `config.example.env` | 环境变量模板 |
| `deploy/koishi/` | Koishi 启动入口、`koishi.yml`、`package.json` |

## 启动

```bash
cp kook/config.example.env kook/.env      # 填 JINYU_TOKEN 等
set -a; . kook/.env; set +a
python kook/satori_sidecar.py --check     # 只校验配置
python kook/satori_sidecar.py
```

Koishi 侧：

```bash
cd kook/deploy/koishi && npm install && node index.js
```

KOOK Bot Token 配在 Koishi 的 `adapter-kook` 里，不写进本仓库。

## 依赖

`httpx`、`websockets`（见 `satori_sidecar.py`），以及 Node 侧 Koishi 依赖。
宿主接口的实现在 [Jinyv-memory/tools/serve.py](https://github.com/YVFENGXS/Jinyv-memory)。
