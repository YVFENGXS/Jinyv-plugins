# Video Call Adapter

视频通话的**记忆适配层**。服务源码在独立仓库
**[jinyu-video-call](https://github.com/YVFENGXS/jinyu-video-call)**，本目录不复制
Live2D 舞台、ASR/TTS 或画面判读代码。

## 边界

- 不直连 SQLite：通过宿主 HTTP API（[host-api](../host-api)）读写记忆。
- `bridge.py` 调通话服务公开端点：`/health`、`/call/turn`、`/call/say`。
- `core_client.py` 调记忆宿主：`/chat`、`/recall`。
- 通话产生的一轮用 `store_reply` 原样落库，避免二次生成。

## 用法

```python
from bridge import CallBridge
from core_client import CoreClient

core = CoreClient("http://127.0.0.1:8710", token=os.environ["RP_HOST_TOKEN"],
                  session="qq-u123")
call = CallBridge("http://127.0.0.1:8790")
```

启动记忆宿主：

```bash
export RP_HOST_TOKEN=<随机串>
python host-api/__init__.py --port 8710 --db /opt/qqbot/data/rp_memory.db
```

本目录是库，不是可独立运行的 NoneBot 插件。
