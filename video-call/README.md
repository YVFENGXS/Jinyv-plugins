# Video Call Adapter

视频通话的**记忆适配层**。服务源码在独立仓库
**[jinyu-video-call](https://github.com/YVFENGXS/jinyu-video-call)**，本目录不复制
Live2D 舞台、ASR/TTS 或画面判读代码。

## 边界

- 不直连 SQLite：通过宿主 HTTP API（[host-api](../host-api)）读写记忆。
- `bridge.py` 调通话服务公开端点：`/health`、`/call/turn`、`/call/say`。
- `core_client.py` 调记忆宿主：`/chat`、`/recall`。
- `transport.py` 是两个客户端共用的 JSON/HTTP 错误处理。
- `config.py` 从环境变量取连接参数，免去调用方各自拼。
- 通话产生的一轮用 `store_reply` 原样落库，避免二次生成。

## 文件

| 文件 | 作用 |
|---|---|
| `bridge.py` | 通话服务客户端 |
| `core_client.py` | 记忆宿主客户端 |
| `transport.py` | 共用 HTTP/JSON 传输层 |
| `config.py` | 环境变量 → 连接参数 |

## 用法

```python
from bridge import CallBridge
from core_client import CoreClient
import config

core = CoreClient("http://127.0.0.1:8710", token=os.environ["RP_HOST_TOKEN"],
                  session="qq-u123")
call = CallBridge("http://127.0.0.1:8790")

# 或者直接用环境变量：
cfg = config.core_config()
core = CoreClient(cfg["base_url"], token=cfg["token"], session=cfg["session"])
```

启动记忆宿主：

```bash
export RP_HOST_TOKEN=<随机串>
python host-api/__init__.py --port 8710 --db /opt/qqbot/data/rp_memory.db
```

本目录是库，不是可独立运行的 NoneBot 插件。
