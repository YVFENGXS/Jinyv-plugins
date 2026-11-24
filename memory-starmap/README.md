# 记忆星图（memory-starmap）

把 Jinyv-memory 的记忆库画成星图：**点 = 一条记忆，连线 = 同主题关联**。
只读打开 `RP_DB`，不写任何表，不参与「单一写入者」的写路径。

前端为本仓库自研（原生 Canvas，无第三方代码）：按主题划分扇区、节点由内向外旋出，
支持滚轮缩放、拖拽平移、单击固定详情、图例筛选主题。
数据层直接只读 Jinyv-memory 的表结构。

## 数据映射

| 表 | 节点摘要 | 主题 | 重要度 |
|---|---|---|---|
| `durable_facts` | `fact` | `tags` 第一项 → `category` → 「事实」 | `importance` |
| `event_cards` | `summary` | `subject` → `session_id` → 「事件」 | `importance` |
| `memory_units` | `content_json` 里的 text/summary/content | `thread_id` → `bucket_key` → 「摘要」 | `salience`（截到 0–1） |

- 已撤回的行（`retracted_at` 非空）不画。
- 同主题按时间排序后**相邻连线**；`supersedes_id` 额外连一条修订边。
- 最多 2000 个节点，超出按时间取最近的。

## 运行

```bash
# 依赖：无（标准库）；只要一个可读的 RP_DB
export RP_DB=../Jinyv-memory/data/rp_memory.db
export RP_STARMAP_TOKEN=换成一个口令
python memory-starmap/server.py --port 8712
# 打开 http://127.0.0.1:8712/?t=<口令>
```

参数优先于环境变量：

```bash
python server.py --db /path/to/rp_memory.db --port 8712 --token <口令> --host 0.0.0.0
```

不传 `--token` 且没设 `RP_STARMAP_TOKEN` 时，启动会随机生成口令并打印出来。

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/memories` | `{"nodes":[{"id","summary","topic","importance","t"}],"links":[{"source","target"}],"source":{...}}`，需要 `X-Gate-Token` 或 `?t=` |
| GET | `/` `/app.js` `/style.css` | 静态页，公开（浏览器加载资源带不上口令） |

```bash
curl -H "X-Gate-Token: $RP_STARMAP_TOKEN" http://127.0.0.1:8712/api/memories | head
```

## 注意

- 库不存在时返回空图并在 `source.error` 里说明，不会自动建库。
- 只读连接使用 `file:...?mode=ro`，不会触发 WAL 写入。
- 主题是「按字段归类」的轻量聚类，不做语义聚类；宁缺勿滥，同一主题只连相邻一条。
