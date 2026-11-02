# Jinyv Video Call Adapter 插件

视频通话服务适配层独立仓库（本地 `E:\Jinyv-plugins\video-call`）。

- 服务原仓库：`https://github.com/YVFENGXS/jinyu-video-call`（保持不动）
- 本地服务克隆：`E:\rp_memory_project\jinyu-video-call`（只读检测，不修改）
- 适配器仓库远程地址：**待确认**（建议 `https://github.com/YVFENGXS/Jinyv-plugin-video-call`）

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
