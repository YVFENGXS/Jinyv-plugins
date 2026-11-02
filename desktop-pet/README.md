# Jinyv Desktop Pet Adapter 插件

桌宠服务端适配层独立仓库（本地 `E:\Jinyv-plugins\desktop-pet`）。

- 客户端原仓库：`https://github.com/YVFENGXS/Jinyu-pet`（保持不动）
- 本地客户端克隆：`E:\rp_memory_project\rp-desktop-pet`（只读检测，不修改）
- 协议真源：主仓库 `docs/protocol/desktop-v1.md`
- 适配器仓库远程地址：**待确认**（建议 `https://github.com/YVFENGXS/Jinyv-plugin-desktop-pet`）

## 边界

- 不复制 Electron / WebGL / Live2D 资产；只提供 desktop-v1 服务端入口。
- 通过 `MemoryAPI` 读写共享 lane；不在插件内直连 SQLite。
- 本轮提供 `handle_hello` / `handle_text` 与健康检查；WebSocket 服务在下一阶段实现。

## 配置（主仓库 `config/plugins/desktop-pet.toml`）

```toml
client_dir = ""  # 例如 E:/rp_memory_project/rp-desktop-pet
account = "desktop"
```
