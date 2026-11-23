# Jinyv QQBot

完整的 QQ 接入（OneBot v11 / NapCat），作为 NoneBot2 插件运行。
记忆逻辑全部在独立仓库 **[Jinyv-memory](https://github.com/YVFENGXS/Jinyv-memory)** 的
`jinyv_memory/core/`，本目录只放平台能力。

结构分四层：`bootstrap.py`（启动）→ `config.py`（配置）→ `features/`（可插拔功能）→
`__init__.py`（组合根：matcher、运行期状态、消息入口）。新功能加在 `features/` 或独立模块，
不再往入口堆。

## 能力

| 模块 | 说明 |
|---|---|
| `__init__.py` | 组合根：消息入口、运行期状态、matcher 注册；功能实现逐步下沉到子模块 |
| `bootstrap.py` | 启动层：定位 Jinyv-memory core、挂 sys.path、桥接标准日志 |
| `config.py` | 配置层：只解析环境变量为常量，不持有可变状态 |
| `social_state.py` | 签名 / 说说 / 社交圈共用的轻量状态文件 |
| `features/social_post.py` | 低频社交动作：个性签名、QQ 空间说说 |
| `tools_reminder.py` | 提醒类工具：登记 / 查询 / 修改 / 取消（调度仍在 `reminder.py`） |
| `stage.py` | 舞台 / 身体桥：身体工具挂表、`body_intent` 后台解码、房间括号动作 |
| `host_api.py` | 宿主 HTTP 接口：`/jinyu/chat`、`/jinyu/health`，复用本进程中间件与会话锁 |
| `outbound.py` | 出站层：气泡拆分、富消息渲染、主动发送、已发消息编号与撤回 |
| `media.py` | 媒体层：图片判读、语音/音频/链接注记、贴纸自学习采集 |
| `bili.py` | B 站层：弹幕监听、@ 我的自动回复、账号工具与 `/bili` 指令 |
| `loops.py` | 后台循环：闲置主动、词条/事件卡合并、Dream、余额、向量回填、提醒投递 |
| `admin.py` | 管理指令层：`/memory`、`/merge`、`/social`、贴纸与语音管理等运维入口 |
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

`bootstrap.py` 按以下顺序查找 `jinyv_memory/core`：

1. `$JINYV_MEMORY_HOME/jinyv_memory/core`
2. 已安装的 `jinyv_memory` 包
3. 插件目录下的 `jinyv_memory/core`（把仓库整份拷进来时）

找不到会直接报错，不会静默降级成无记忆模式。
