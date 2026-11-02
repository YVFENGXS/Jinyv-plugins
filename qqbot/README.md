# Jinyv QQBot 插件

QQ 插件独立仓库（本地 `E:\Jinyv-plugins\qqbot`）。主仓库只保留契约、加载器与测试；本仓库提供 qqbot 适配实现。

- 远程地址：**待确认**（建议 `https://github.com/YVFENGXS/Jinyv-qqbot`）
- 宿主契约：`jinyv_memory.contract`（主仓库）
- 入口：`plugin.toml` + `__init__.py`

## 当前实现

- 消息 → before 钩子召回 → `MemoryAPI.chat` → after 钩子 → 事件
- 工具：`qqbot.remember` / `qqbot.recall` / `qqbot.status` / `qqbot.capabilities`
- 定时任务：`qqbot.heartbeat`
- NoneBot2 可选；未安装时降级为工具/钩子

## 旧能力迁移状态

旧实现的 `richmsg / linkmeta / reminder / owner_gate / asr / bili_live / mcp_client / task_supervisor`
以及 `__init__.py` 中的主动话题/命令/轮换，当前**没有复制进本仓库**。

本仓库新增 `features/__init__.py`，按迁移顺序为每项能力提供**插件侧适配入口**：

```
richmsg → linkmeta → reminder → owner_gate → asr → bili_live
```

适配入口通过 `legacy_bridge.py` 只读调用旧包目录，不复制源码：

```toml
# config/plugins/qqbot.toml（主仓库）
legacy_source_dir = "E:/rp_memory_project/jinyu-memory/jinyu_memory"
```

- 旧模块的第三方依赖缺失时，该能力保持不可用并降级，不影响 qqbot 最小闭环。
- 真正「新建 + 改写」的物理迁移仍待逐模块评审；当前避免两份实现与单一真源漂移。
