# Jinyv Plugins

瑾瑜外围插件单一仓库。每个插件是仓库内的一个子目录，主仓库通过
`config/core.toml` 的 `[plugins].search_paths` 发现并加载。

```
Jinyv-plugins/
├── qqbot/          # QQ 适配层 + features 能力入口
├── desktop-pet/    # 桌宠 desktop-v1 服务端适配层
├── video-call/     # 视频通话适配层 + HTTP 桥
├── jinyu-memory-dsh/  # DSH JS/cordis 特殊插件源码 + dsh-wins 安装补丁
└── host-api/       # 宿主 HTTP API（/chat /remember /recall）
```

## 上游引用

| 插件 | 上游原仓库 | 说明 |
|---|---|---|
| desktop-pet | https://github.com/YVFENGXS/Jinyu-pet | 客户端独立仓库；本目录只放服务端适配层，不复制客户端源码 |
| video-call | https://github.com/YVFENGXS/jinyu-video-call | 服务独立仓库；本目录只放适配层，不复制服务源码 |
| qqbot | 主仓库旧实现已迁入 `features/` | 8 个能力模块已复制并改写导入；旧目录仅作 `legacy_entry` 回退 |
| dsh | 用户 zip（源码已纳入本仓库） | 特殊接入；源码与 dsh-wins 安装补丁在 `jinyu-memory-dsh/` |
| host-api | 无上游 | 主仓库与外部进程共用的 HTTP 写入通道 |

## 记忆核心接入

`desktop-pet` 与 `video-call` 都支持 `core_mode`：

| 模式 | 说明 |
|---|---|
| `embedded` | 与核心同进程，直接使用 `MemoryAPI`（默认） |
| `local` | 连本机宿主 API `http://127.0.0.1:8710` |
| `server` | 连配置的远程 `core_url` |

桌宠还可独立运行 `python desktop-pet/standalone.py --core-url ...`，
不要求核心进程加载本插件。

## 远程

远程已创建并推送 `main`：`https://github.com/YVFENGXS/jinyv-plugins`

```powershell
git -C E:\Jinyv-plugins push origin main
```

## 历史

原先三个子仓库的 git 历史保存在 `.repo-history/*.git`（已 gitignore，不进入本仓库提交）。
