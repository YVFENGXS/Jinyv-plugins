# jinyu-memory-dsh

瑾瑜记忆系统的 DSH 本地插件（改造版），以 JS/cordis 特殊插件方式运行，不属于
Python 插件契约。本仓库是该插件的独立源码仓库，便于后续单独推送和版本管理。

## 来源

- 源码来自用户提供的 `jinyu-memory-dsh.zip`（SHA256 `341ADA8F99B509AD3728A662E47DA5DF7620A08F15B49CB5D41F3202FA9A4E56`）。
- 只纳入运行必需源码：`package.json`、`lib/`、`cordis.patch.yml`、`tests/`。
- 不含 `node_modules`、构建产物、密钥、`.env`、数据库、日志或备份。
- 当前未配置 git 远程，也未推送。

## 目录

```
jinyu-memory-dsh/
├── package.json          # name=jinyu-memory-dsh，main=lib/index.js
├── cordis.patch.yml      # DSH bundle patch
├── lib/
│   ├── index.js          # 插件入口 apply(ctx)
│   ├── archive.js        # 事件卡/事实归档
│   ├── recall.js         # 钩子召回
│   ├── inject.js         # 每步注入
│   ├── store.js          # 本地记忆仓
│   └── token.js
├── tests/                # Node 自带 test runner 用例
└── scripts/
    ├── dsh_wins_adapter.js     # dsh-wins 插件侧适配
    └── install_dsh_plugin.py   # 可回滚安装/补丁脚本
```

## 运行要求

- Node.js >= 20（`package.json` 已声明）。
- DSH 的插件目录，默认 `$DSH_HOME/plugins/jinyu-memory-dsh`；未设置 `DSH_HOME` 时脚本回退到 `~/.dsh`。

## 安装

### 方式一：直接复制目录

```bash
mkdir -p "$DSH_HOME/plugins"
cp -a /path/to/jinyu-memory-dsh "$DSH_HOME/plugins/jinyu-memory-dsh"
```

### 方式二：用安装脚本（推荐，自动打 dsh-wins 补丁）

```bash
# 从本仓库安装到默认 DSH_HOME（--source 默认就是仓库根目录）
python scripts/install_dsh_plugin.py --force

# 指定目标目录
python scripts/install_dsh_plugin.py --source . --target "$DSH_HOME/plugins/jinyu-memory-dsh" --force

# 只给已安装目录打补丁
python scripts/install_dsh_plugin.py --patch-only --target "$DSH_HOME/plugins/jinyu-memory-dsh"

# 先检查不写文件
python scripts/install_dsh_plugin.py --source . --dry-run
```

脚本会：

1. 校验 `package.json name=jinyu-memory-dsh`、`lib/index.js`、`cordis.patch.yml`；
2. 复制插件源码到目标目录（忽略 `.git`、`node_modules`、缓存、密钥与日志）；
3. 备份 `lib/index.js` 为 `lib/index.js.jinyv-orig`；
4. 复制 `scripts/dsh_wins_adapter.js` 到 `lib/jinyv-dsh-wins.js`；
5. 在 `lib/index.js` 注入 import 与 `installDshWins(ctx, createStore)`；
6. 写入 `.jinyv-dsh-wins.json` 标记；重复执行不会重复注入。

## 回滚

```bash
python scripts/install_dsh_plugin.py --unpatch --target "$DSH_HOME/plugins/jinyu-memory-dsh"
```

回滚会恢复备份的 `lib/index.js`，并删除适配文件、标记与备份。回滚后需重启 DSH。

## dsh-wins 策略

`dsh_wins_adapter.js` 在 `session/event` 的 `turn/start`、`turn/end` 后调用
`applyDshWins`：

- 在会话 `config.json` 写入 `jinyvConflictPolicy = "dsh-wins"`；
- 当 DSH 本地卡片/事实相对 `.jinyv-bridge.json` 的导出签名发生变化时，标记
  `jinyv_authoritative`，写入 `dsh_claims`；
- 核心桥接导出遇到双端同时改动时，以 DSH 文本为准，核心旧结论进入
  `.jinyv-bridge.json` 与 `var/integrations/dsh/conflicts.jsonl` 留档，不物理删除核心记录。

## 测试

```bash
npm test
# 等价于
node --test tests/*.test.mjs
```

## 与主仓库的关系

主仓库 `Jinyv-memory` 的 `integrations/dsh.py` 负责核心侧检测、导入/导出、journal
与冲突留档；本仓库只负责 DSH 插件源码与插件侧 dsh-wins 适配，不包含 Python 核心。
