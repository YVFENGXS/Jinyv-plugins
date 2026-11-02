# Jinyv Plugins

瑾瑜外围插件单一仓库。每个插件是仓库内的一个子目录，主仓库通过
`config/core.toml` 的 `[plugins].search_paths` 发现并加载。

```
Jinyv-plugins/
├── qqbot/          # QQ 适配层 + features 能力入口
├── desktop-pet/    # 桌宠 desktop-v1 服务端适配层
├── video-call/     # 视频通话适配层 + HTTP 桥
└── host-api/       # 宿主 HTTP API（/chat /remember /recall）
```

## 上游引用

| 插件 | 上游原仓库 | 说明 |
|---|---|---|
| desktop-pet | https://github.com/YVFENGXS/Jinyu-pet | 客户端独立仓库；本目录只放服务端适配层，不复制客户端源码 |
| video-call | https://github.com/YVFENGXS/jinyu-video-call | 服务独立仓库；本目录只放适配层，不复制服务源码 |
| qqbot | 主仓库旧实现已迁入 `features/` | 8 个能力模块已复制并改写导入；旧目录仅作 `legacy_entry` 回退 |
| dsh | 用户 zip / `$DSH_HOME/plugins/jinyu-memory-dsh` | 特殊接入，不进入本仓库 |
| host-api | 无上游 | 主仓库与外部进程共用的 HTTP 写入通道 |

## 远程

目标远程：`https://github.com/YVFENGXS/jinyv-plugins`（创建后执行）：

```powershell
git -C E:\Jinyv-plugins remote add origin https://github.com/YVFENGXS/jinyv-plugins.git
git -C E:\Jinyv-plugins push -u origin main
```

## 历史

原先三个子仓库的 git 历史保存在 `.repo-history/*.git`（已 gitignore，不进入本仓库提交）。
