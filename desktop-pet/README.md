# Desktop Pet Adapter

桌宠的**服务端适配层**。客户端源码在独立仓库
**[Jinyu-pet](https://github.com/YVFENGXS/Jinyu-pet)**，本目录不复制 Electron /
WebGL / Live2D 资产。

## 边界

- 不直连 SQLite：一律通过宿主 HTTP API（[host-api](../host-api)）读写记忆。
- 提供 `/desktop/v1/health`、`/desktop/v1/presence`、`/desktop/v1/say`、`/desktop/v1/ws`。
- 上行文字 → 宿主 `/chat`；下行气泡 / 动作标记走 desktop-v1 协议。
- 可独立进程运行，不要求与 QQ 插件同进程。

## 运行

先启动记忆宿主：

```bash
export RP_HOST_TOKEN=<随机串>
python host-api/__init__.py --port 8710 --db /opt/qqbot/data/rp_memory.db
```

再启动适配层：

```bash
export JINYV_DESKTOP_TOKEN=<桌宠令牌>
export JINYV_HOST_API_TOKEN="$RP_HOST_TOKEN"
python standalone.py --core-url http://127.0.0.1:8710 --port 8787
```

依赖：`fastapi`、`uvicorn`、`websockets`。

环境变量同时认新名和旧名：`JINYV_DESKTOP_*` 与 `RP_DESKTOP_*` / `RP_HOST_*`。
如果 `RP_HOST_BASE` 指向 QQ 插件的 `http://127.0.0.1:8080`，适配层会自动带上
`/jinyu` 前缀（对应 `/jinyu/chat`、`/jinyu/health`）；指向独立 host-api 时保持 `/chat`。

协议文档：[docs/desktop-v1.md](docs/desktop-v1.md)。

`/desktop/v1/health` 与 `/desktop/v1/presence` 都会返回当前 WS 连接数；客户端
重连后以最新 `hello.ack` 的 `server_time` 为准，不依赖本地时钟。

## 文件

| 文件 | 作用 |
|---|---|
| `standalone.py` | 组合根 / 独立启动入口 |
| `bootstrap.py` | 启动层：健康检查 + uvicorn |
| `config.py` | 命令行参数与环境变量 |
| `adapter.py` | desktop-v1 适配对象（上行文字 → 宿主 `/chat`） |
| `server.py` | FastAPI 路由与 WebSocket |
| `protocol.py` | desktop-v1 信封 / 气泡拆分 / 动作提取 |
| `core_client.py` | 宿主 HTTP 客户端（stdlib urllib） |
| `install_desktop_adapter.sh` | 服务器 systemd 安装脚本 |
