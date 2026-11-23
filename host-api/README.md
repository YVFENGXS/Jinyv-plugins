# Host HTTP API

给桌宠、通话、DSH 等外部进程一个统一的记忆写入 / 召回通道。

服务实现不在这里复制，唯一真源是
**[Jinyv-memory/tools/serve.py](https://github.com/YVFENGXS/Jinyv-memory)**。
本目录只是启动器，负责定位记忆仓库并透传参数。

## 文件

| 文件 | 作用 |
|---|---|
| `__init__.py` | 组合根：只调用 bootstrap |
| `config.py` | 命令行参数与环境变量 |
| `bootstrap.py` | 定位 `Jinyv-memory/tools/serve.py` 并透传 |

## 启动

```bash
export RP_HOST_TOKEN=<随机串>
export RP_FRONT_KEY=sk-... RP_BACK_KEY=sk-...
python host-api/__init__.py --host 127.0.0.1 --port 8710 --db data/rp_memory.db
```

## 接口

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/health` | 存活检查（不校验令牌） |
| POST | `/chat` | `{"text","session"}` → `{"reply","session"}` |
| POST | `/remember` | `{"text","speaker","importance","session"}` → `{"ok","id"}` |
| GET | `/recall?q=&session=&limit=` | 只读召回 |

除 `/health` 外都要 `Authorization: Bearer <RP_HOST_TOKEN>`。

**同一个 `RP_DB` 只能有一个写入进程**：QQ 插件、宿主 API、桌宠服务不要同时
开写库模式。桌宠 / 通话请把 `core_url` 指到本服务。
