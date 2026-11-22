#!/usr/bin/env bash
# 把 QQ 插件与记忆层装进已有的 NoneBot2 项目。
#   deploy/install_plugin.sh /opt/qqbot/bot [插件目录] [Jinyv-memory 目录]
# 默认插件目录 <bot>/src/plugins；记忆层默认取环境变量 JINYV_MEMORY_HOME，
# 否则要求已 pip install jinyv_memory。
set -euo pipefail

BOT_DIR="${1:?用法: install_plugin.sh <机器人项目目录> [插件目录] [Jinyv-memory 目录]}"
PLUGIN_DIR="${2:-$BOT_DIR/src/plugins}"
MEMORY_HOME="${3:-${JINYV_MEMORY_HOME:-}}"
SRC="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$PLUGIN_DIR/qqbot"

mkdir -p "$PLUGIN_DIR"
if [ -e "$DEST" ]; then
    echo "目标已存在，先备份：$DEST -> ${DEST}.bak.$(date +%s)"
    mv "$DEST" "${DEST}.bak.$(date +%s)"
fi
mkdir -p "$DEST"
cp -r "$SRC/." "$DEST/"
echo "QQ 插件已安装到 $DEST"

if [ -n "$MEMORY_HOME" ] && [ -d "$MEMORY_HOME/jinyv_memory" ]; then
    if [ -x "$BOT_DIR/.venv/bin/pip" ]; then
        "$BOT_DIR/.venv/bin/pip" install -e "$MEMORY_HOME"
        echo "记忆层已可编辑安装：$MEMORY_HOME"
    else
        echo "未找到 $BOT_DIR/.venv/bin/pip；请手动安装：pip install -e $MEMORY_HOME"
    fi
else
    echo "未提供 Jinyv-memory 目录：请确保已 pip install jinyv_memory，"
    echo "或运行时设置 JINYV_MEMORY_HOME 指向记忆仓库根目录。"
fi

echo "确认 pyproject.toml 里 [tool.nonebot] plugin_dirs 包含：$PLUGIN_DIR"
