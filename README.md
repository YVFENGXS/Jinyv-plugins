# Jinyv Plugins

瑾瑜的外围能力仓库。**记忆中间层在独立仓库
[Jinyv-memory](https://github.com/YVFENGXS/Jinyv-memory)**，这里只放平台接入。

```
Jinyv-plugins/
├── qqbot/             # 完整 QQ 接入（NoneBot2 插件；bootstrap/config/features 分层）
├── kook/              # KOOK 接入（Koishi + Satori sidecar）
├── host-api/          # 宿主 HTTP API 启动器（/chat /remember /recall）
├── desktop-pet/       # 桌宠服务端适配层（客户端在 Jinyu-pet 仓库）
├── video-call/        # 通话记忆适配层（服务在 jinyu-video-call 仓库）
└── jinyu-memory-dsh/  # DSH JS/cordis 插件源码 + 安装补丁
```

## 上游

| 目录 | 上游 | 说明 |
|---|---|---|
| qqbot | 无（本仓维护） | 依赖 Jinyv-memory core |
| kook | Koishi / Satori | 侧车只做协议转换 |
| host-api | Jinyv-memory/tools/serve.py | 只做启动器，不复制 HTTP 实现 |
| desktop-pet | [Jinyu-pet](https://github.com/YVFENGXS/Jinyu-pet) | 只放服务端适配层 |
| video-call | [jinyu-video-call](https://github.com/YVFENGXS/jinyu-video-call) | 只放记忆桥接 |
| jinyu-memory-dsh | 用户 zip | JS/cordis 特殊插件 |

房间 / 舞台渲染在 [Jinyv-room](https://github.com/YVFENGXS/Jinyv-room)，
`qqbot/jinyv_stage/` 只是可选的工具桥。

## 运行拓扑

```
QQ ───> qqbot (NoneBot2，/jinyu/chat) ────> Jinyv-memory core ──> RP_DB
KOOK ─> kook sidecar ──> /jinyu/chat ─────┘
桌宠 / 通话 ─> host-api (/chat) ──> Jinyv-memory core ────────────┘
```

**同一个 `RP_DB` 只能有一个写入进程**。当前生产由 qqbot 独占写库，
所以 KOOK sidecar 指向 qqbot 的 `/jinyu/chat`；`host-api` 是给「不由 QQ
独占」的场景准备的（`/chat` 只有 text/session，历史契约不同，暂不合并）。

## 快速开始

```bash
# 1. 记忆层
pip install -e ../Jinyv-memory        # 或 export JINYV_MEMORY_HOME=../Jinyv-memory

# 2. QQ
pip install -r qqbot/requirements.txt
cp qqbot/env.example .env             # 填 ONEBOT_ACCESS_TOKEN / RP_FRONT_KEY / RP_BACK_KEY
```

`qqbot/` 放进 NoneBot 的 `plugin_dirs` 即会自动注册消息入口。

## 历史

第一版契约式插件（`jinyv_memory.contract` + `features/` 只读桥）已废弃：
它依赖一个从未实现的宿主运行时，且 features 副本落后于线上。现在
`qqbot/` 直接使用 Jinyv-memory core，能力模块与线上逐文件同步。
