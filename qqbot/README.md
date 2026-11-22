# Jinyv QQBot

完整的 QQ 接入（OneBot v11 / NapCat），作为 NoneBot2 插件运行。
记忆逻辑全部在独立仓库 **[Jinyv-memory](https://github.com/YVFENGXS/Jinyv-memory)** 的
`jinyv_memory/core/`，本目录只放平台能力。

## 能力

| 模块 | 说明 |
|---|---|
| `__init__.py` | 消息入口：私聊全收、群聊 @ 才回；富消息 / 主动话题 / 命令 / 轮换 |
| `richmsg.py` | `[[face]]` / `[[img]]` / `[[search]]` / `[[sticker]]` / `[[voice]]` 渲染与贴纸库 |
| `asr.py` | QQ 语音转文字 |
| `linkmeta.py` | 链接抓取、视频抽帧、B 站元数据、联网搜索 |
| `bili_live.py` | B 站直播、视频搜索、评论 / @ 回复 |
| `music.py` | 听歌分析 |
| `weather.py` | Open-Meteo 天气 |
| `reminder.py` | 定时提醒（SQLite，到点按人设发出） |
| `owner_gate.py` | 主人绑定与验证 |
| `mcp_client.py` | MCP 只读工具 |
| `autonomy.py` | 自主作息 / 自触发 |
| `task_supervisor.py` | 后台任务监督 |
| `stage_bracket.py` | 舞台动作标记解析 |
| `slop.py` | 出站 AI 味审计 |
| `kook_fallback.py` | KOOK 侧车降级 |
| `jinyv_stage/` | 舞台/房间工具桥（可选） |

## 安装

1. 安装记忆层（二选一）：

   ```bash
   # A. 可编辑安装
   pip install -e /path/to/Jinyv-memory

   # B. 不安装，运行时指路
   export JINYV_MEMORY_HOME=/path/to/Jinyv-memory
   ```

2. 安装依赖：

   ```bash
   pip install -r requirements.txt
   ```

3. 把本目录放进 NoneBot 的 `plugin_dirs`（例如 `src/plugins/qqbot`）。

4. 配置环境变量：复制 `env.example` 到 NoneBot 的 `.env`，至少填
   `ONEBOT_ACCESS_TOKEN`、`RP_FRONT_KEY`、`RP_BACK_KEY`。

5. NapCat 反向 WS 指向 `ws://127.0.0.1:8080/onebot/v11/ws`。

6. 需要 MCP 工具时：

   ```bash
   cp mcp.example.json mcp.json   # 按实际 venv / 缓存路径改
   ```

   `mcp.json` 是本机配置，已在 `.gitignore` 里。

## 独立部署

`deploy/qqbot.service` 与 `deploy/install_plugin.sh` 是 systemd 安装脚本，
把插件复制到 `/opt/qqbot/bot/src/plugins/qqbot/`。记忆库默认
`/opt/qqbot/data/rp_memory.db`。

## 定位 core

`__init__.py` 按以下顺序查找 `jinyv_memory/core`：

1. `$JINYV_MEMORY_HOME/jinyv_memory/core`
2. 已安装的 `jinyv_memory` 包
3. 插件目录下的 `jinyv_memory/core`（把仓库整份拷进来时）

找不到会直接报错，不会静默降级成无记忆模式。
