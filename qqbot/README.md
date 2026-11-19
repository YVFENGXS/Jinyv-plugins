# Jinyv QQBot 插件

单一插件仓库中的 QQ 子目录（本地 `E:\Jinyv-plugins\qqbot`）。主仓库只保留契约、加载器与测试。

- 仓库地址：`https://github.com/YVFENGXS/jinyv-plugins`
- 宿主契约：`jinyv_memory.contract`（主仓库）
- 入口：`plugin.toml` + `__init__.py`

## 当前实现

- 消息 → before 钩子召回 → `MemoryAPI.chat` → after 钩子 → 事件
- 工具：`qqbot.remember` / `qqbot.recall` / `qqbot.status` / `qqbot.capabilities`
- 定时任务：`qqbot.heartbeat`
- NoneBot2 可选；未安装时降级为工具/钩子

## 能力实现

以下 8 个模块已复制到 `features/`，内部导入已改为包内相对导入：

```
richmsg.py  linkmeta.py  bili_live.py  reminder.py
owner_gate.py  asr.py  mcp_client.py  task_supervisor.py
```

- `linkmeta → .richmsg`、`linkmeta → .bili_live`、`asr → .richmsg` 已改写。
- 不再依赖 `E:\rp_memory_project`；`legacy_source_dir` 仅作为旧入口回退。
- 可选依赖见 `requirements.txt`（nonebot2 / nonebot-adapter-onebot / httpx）。
  缺依赖时对应能力不可用，不影响最小消息闭环。
- `reminder` 与 `owner_gate` 已有 unittest 覆盖（建表、排提醒、认领、绑定验证）。

旧 `__init__.py` 中的主动话题/命令/轮换（`legacy_entry`）尚未复制；
如需启用，把 `legacy_source_dir` 指向旧包目录作为回退。
