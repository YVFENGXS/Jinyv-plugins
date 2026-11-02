# Jinyv Desktop Pet Adapter 插件

单一插件仓库中的桌宠服务端适配层（本地 `E:\Jinyv-plugins\desktop-pet`）。

- 插件仓库：`https://github.com/YVFENGXS/jinyv-plugins`
- 客户端上游原仓库：`https://github.com/YVFENGXS/Jinyu-pet`（保持不动，不复制源码）
- 本地客户端克隆：`E:\rp_memory_project\rp-desktop-pet`（只读检测，不修改）
- 协议真源：主仓库 `docs/protocol/desktop-v1.md`
- 安装方式：客户端仍从其上游仓库安装；本目录只提供服务端适配层。

## 边界

- 不复制 Electron / WebGL / Live2D 资产；只提供 desktop-v1 服务端入口。
- 不直连 SQLite：`embedded` 走 `MemoryAPI`，`local`/`server` 走宿主 HTTP API。
- 提供 `/desktop/v1/health`、`/desktop/v1/say`、`/desktop/v1/ws`。
- 可独立进程运行 `standalone.py`，连本机或远程记忆核心。

## 配置（主仓库 `config/plugins/desktop-pet.toml`）

```toml
client_dir = ""  # 例如 E:/rp_memory_project/rp-desktop-pet
account = "desktop"
serve = false
core_mode = "embedded"  # embedded | local | server
core_url = ""           # local 默认 http://127.0.0.1:8710；server 必填
```

独立运行：

```bash
JINYV_DESKTOP_TOKEN=... JINYV_HOST_API_TOKEN=... \
python standalone.py --core-url http://127.0.0.1:8710
```
