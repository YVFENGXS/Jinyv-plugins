# Jinyv Video Call Adapter 插件

单一插件仓库中的视频通话适配层（本地 `E:\Jinyv-plugins\video-call`）。

- 插件仓库：`https://github.com/YVFENGXS/jinyv-plugins`
- 服务上游原仓库：`https://github.com/YVFENGXS/jinyu-video-call`（保持不动，不复制源码）
- 本地服务克隆：`E:\rp_memory_project\jinyu-video-call`（只读检测，不修改）
- 安装方式：服务仍从其上游仓库安装；本目录只提供适配层与桥接接口。

## 边界

- 不复制 Live2D 舞台、ASR/TTS、画面判读代码。
- 推荐通话服务只走宿主 API（`RP_HOST_BASE` + `RP_HOST_TOKEN`），禁止与主进程双写 SQLite。
- 本轮提供 `memory_context` / `record_turn` 与健康检查；服务联调在下一阶段。

## 配置（主仓库 `config/plugins/video-call.toml`）

```toml
repo_dir = ""  # 例如 E:/rp_memory_project/jinyu-video-call
service_url = "http://127.0.0.1:8790"
account = "video_call"
```
