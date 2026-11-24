# 运维自动驾驶（observe-only）

从 QingyiPersonal 的运维自动驾驶里只取「观察」这一层：定时巡检、留痕、报警，
**不自动改库、不自动重放、不碰写入路径**。所有动作都只读，唯一写入是插件自己的
`ops_history.jsonl`。

## 巡检项

| 项 | 判定 |
|---|---|
| `db_present` | 库文件存在；不存在直接 fail |
| `integrity` | `PRAGMA quick_check` 必须返回 ok |
| `wal_size` | WAL 超过 64MB 记 warn |
| `counts` | turns / event_cards / durable_facts / memory_units 行数 |
| `retracted_ratio` | 事实撤回比例 > 30% 记 warn |
| `invalidated_units` | 失效记忆单元数量（治理层留痕） |
| `writer_lock` | 锁文件被占用 = 有写入者在线；未被占用记 info（可能没启动） |
| `contradictions` | 并列保留的矛盾边数量 |

## 运行

```bash
export RP_DB=../Jinyv-memory/data/rp_memory.db
export RP_OPS_TOKEN=换一个口令
python ops-autopilot/server.py --port 8713 --interval 300
# http://127.0.0.1:8713/?t=<口令>
```

- `--interval 0` 只做启动时一次巡检。
- `--history` 指定历史文件；默认 `<RP_DB>.ops.jsonl`。
- 每次巡检追加一行 JSON，最多保留最近 2000 条。

## 接口

| 路径 | 说明 |
|---|---|
| `GET /api/status` | 最近一次巡检结果，需要 `X-Gate-Token` 或 `?t=` |
| `GET /api/check` | 立即重跑一次巡检并返回 |
| `GET /api/history` | 最近 200 条巡检记录 |
| `GET /` | 状态页 |

## 边界

- 不做自动修复、不删 WAL、不重置撤回、不重放归档；发现问题只报警。
- 真正的「自动驾驶 + 批准账本」需要写权限，留给后续带审批的插件，不在这里实现。
