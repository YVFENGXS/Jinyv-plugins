# Jinyv Video Call Adapter 插件

单一插件仓库中的视频通话适配层（本地 `E:\Jinyv-plugins\video-call`）。

- 插件仓库：`https://github.com/YVFENGXS/jinyv-plugins`
- 服务上游原仓库：`https://github.com/YVFENGXS/jinyu-video-call`（保持不动，不复制源码）
- 本地服务克隆：`E:\rp_memory_project\jinyu-video-call`（只读检测，不修改）
- 安装方式：服务仍从其上游仓库安装；本目录只提供适配层与桥接接口。

## 边界

- 不复制 Live2D 舞台、ASR/TTS、画面判读代码。
- 不直连 SQLite：`embedded` 走 `MemoryAPI`，`local`/`server` 走宿主 HTTP API。
- 提供 `memory_context` / `record_turn`；通话回复通过 `store_reply` 原样落库。
- 通话服务自身可本地或远程：配置 `service_url` 即可，桥接走 stdlib `urllib`。

## 配置（主仓库 `config/plugins/video-call.toml`）

```toml
repo_dir = ""  # 例如 E:/rp_memory_project/jinyu-video-call
service_url = "http://127.0.0.1:8790"  # 也可填远程通话服务
account = "video_call"
core_mode = "embedded"  # embedded | local | server
core_url = ""           # local 默认 http://127.0.0.1:8710；server 必填
```
