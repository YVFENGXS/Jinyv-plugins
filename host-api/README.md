# Jinyv Host API 插件

零依赖宿主 HTTP API，供桌宠、视频通话、DSH 等外部进程读写共享记忆。

## 配置（主仓库 `config/plugins/host-api.toml`）

```toml
enabled = true
host = "127.0.0.1"
port = 8710
account = "owner_qq"
token = ""   # 或用环境变量 JINYV_HOST_API_TOKEN
```

## 端点

- `GET /health`
- `POST /chat` `{"text","session","account","speaker","source","store_reply"}` → `{"reply","session"}`
  - `store_reply`：用给定原文覆盖生成的回复落库（通话场景）
- `POST /remember` `{"text","speaker","importance","account","session"}` → `{"ok","id"}`
- `GET /recall?q=&limit=&account=&session=&speaker=` → 召回结果

除 `/health` 外都需要 `Authorization: Bearer <token>`。
