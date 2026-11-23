# -*- coding: utf-8 -*-
"""配置层：只从环境变量解析常量，不持有运行期可变状态。

可变状态（会话锁、缓存、mw 指针等）仍留在插件入口，避免多模块各持一份副本。
"""
from __future__ import annotations

import os
import re

import bili_live

# legacy 契约，勿改：SQLite owner 键，历史库与桌宠/通话侧都按这个值读写
CID = "jinyu"
COOLDOWN = float(os.environ.get("RP_COOLDOWN") or 2)
REPLY_CHUNK = 1000
BUBBLES_ON = (os.environ.get("RP_BUBBLES") or "1").strip().lower() not in {
    "0", "false", "no", "off"}
BUBBLE_MAX = max(1, int(float(os.environ.get("RP_BUBBLE_MAX") or 10)))
_BUBBLE_GAP = max(0.0, float(os.environ.get("RP_BUBBLE_DELAY") or 0.9))
BUBBLE_DELAY = (_BUBBLE_GAP * 0.6, _BUBBLE_GAP * 1.4)   # 相邻气泡的随机间隔（秒）
ADMIN = {x.strip() for x in (os.environ.get("RP_ADMIN_QQ") or "").split(",") if x.strip()}
# 多账号：默认关闭，老库的 qq-g…/qq-u… 原样续用。
# 开启后，主号（RP_PRIMARY_BOT_ID）继续用老键，其余号写 qq-g…@b<self_id>，
# 这样两个号同群也不会互相覆盖热窗、游标和账本。
MULTI_BOT = (os.environ.get("RP_MULTI_BOT") or "0").strip().lower() not in {
    "0", "false", "no", "off"}
PRIMARY_BOT = str(os.environ.get("RP_PRIMARY_BOT_ID") or "").strip()
BILI_ON = (os.environ.get("RP_BILI_ON") or "1").strip().lower() not in {
    "0", "false", "no", "off"}
BILI_ROOM = bili_live.resolve_room(os.environ.get("RP_BILI_ROOM") or "")
# 主人自己的B站账号：评论默认不点名，只放行 @主人（看到好玩的可以喊一声）
BILI_OWNER_UID = str(os.environ.get("RP_BILI_OWNER_UID") or "").strip()
BILI_OWNER_NAME = str(os.environ.get("RP_BILI_OWNER_NAME") or "").strip()
# 主动看B站：工具让模型自己搜/看视频；搜索类每天有次数上限，watch 走 RP_VIDEO_DAILY。
BILI_TOOL_ON = (os.environ.get("RP_BILI_TOOL") or "1").strip().lower() not in {
    "0", "false", "no", "off"}
BILI_LIST_DAILY = max(1, int(float(os.environ.get("RP_BILI_LIST_DAILY") or 30)))
# 自动回复B站@我的：只回主人发的，复用主人私聊记忆；频率/字数在 bili_live 里读。
BILI_AT_ON = (os.environ.get("RP_BILI_AT") or "1").strip().lower() not in {
    "0", "false", "no", "off"}
# 自己上网搜：遇到不懂的/新名词/刚发生的事，模型可调 web_search；每天有次数上限。
SEARCH_ON = (os.environ.get("RP_SEARCH") or "1").strip().lower() not in {
    "0", "false", "no", "off"}
SEARCH_DAILY = max(1, int(float(os.environ.get("RP_SEARCH_DAILY") or 30)))
# 听音乐：本地量测音频（语音/文件/直链/B站/YouTube），不上传、不猜情绪；
# 链接下载有每日上限与大小上限，具体阈值在 music.py 里。
MUSIC_ON = (os.environ.get("RP_MUSIC") or "1").strip().lower() not in {
    "0", "false", "no", "off"}
# 自主作息：整点报点 / 日计划 / 自己醒来。默认关闭，RP_AUTONOMY=1 开启。
AUTONOMY_ON = (os.environ.get("RP_AUTONOMY") or "0").strip().lower() not in {
    "0", "false", "no", "off"}
AUTONOMY_DIGEST = (os.environ.get("RP_AUTONOMY_DIGEST") or "1").strip().lower() not in {
    "0", "false", "no", "off"}
IDLE_NUDGE_MIN = float(os.environ.get("RP_IDLE_NUDGE_MINUTES") or 60)
PROACTIVE_ON = (os.environ.get("RP_PROACTIVE") or "1").strip().lower() not in {
    "0", "false", "no", "off"}
PROACTIVE_DAILY = max(1, int(float(os.environ.get("RP_PROACTIVE_DAILY") or 3)))
POKE_BACK = (os.environ.get("RP_POKE_BACK") or "1").strip().lower() not in {
    "0", "false", "no", "off"}
POKE_COOLDOWN = max(0.0, float(os.environ.get("RP_POKE_COOLDOWN") or 30))
MAX_SILENT = 2            # 允许连续沉默的轮数；超过后强制开口，避免对话彻底断死
# 长图 OCR 注入前台的上限（字符）：默认与视觉抄录上限对齐，截图/文档才读得全；
# 上下文紧张时可用 RP_IMG_NOTE_TEXT 调小。
IMG_NOTE_TEXT = max(200, int(float(os.environ.get("RP_IMG_NOTE_TEXT") or 4000)))
EPOCH_SECONDS = max(0, int(float(os.environ.get("RP_SESSION_EPOCH_HOURS") or 48) * 3600))
EPOCH_FLUSH = max(1.0, float(os.environ.get("RP_EPOCH_FLUSH_SECONDS") or 8))
# 宿主接口：浏览器/桌宠经 HTTP 进来，复用 QQ 这一进程的中间件，避免两个进程抢同一个库
HOST_TOKEN = str(os.environ.get("RP_HOST_TOKEN") or "").strip()
# 宿主接口写哪个会话必须显式配置：不猜号码，缺了就整体不启用（见 host_api.py）
HOST_SESSION = str(os.environ.get("RP_HOST_SESSION")
                   or os.environ.get("RP_SESSION") or "").strip()
HOST_MAX_PROMPT = max(1000, int(float(os.environ.get("RP_HOST_MAX_PROMPT") or 16000)))
# 房间对话单独一条会话：不能和视频通话/QQ 私聊共用热窗与会话锁，否则两边互相顶上下文。
# 用 #room 后缀（# 是既有 epoch 分隔符，lane_base 会回到同一个 qq-u 主体，
# 所以长期记忆的 audience 仍按主人私聊算，不会串到别人的车道）。
HOST_SESSION_ROOM = (str(os.environ.get("RP_HOST_SESSION_ROOM") or "").strip()
                     or (HOST_SESSION + "#room" if HOST_SESSION else ""))
# 房间身体桥：视频通话 / 3D 房间（source=room）的宿主回合才连；地址与令牌只从 bot 的 env 读，
# 源码不写死。没配 / 连不上 / 房间页不在线 → 这一轮当没有身体，纯文本照旧。
BRIDGE_URL = str(os.environ.get("RP_BRIDGE_URL") or "").strip()
BRIDGE_TOKEN = str(os.environ.get("RP_BRIDGE_TOKEN") or "").strip()
# perform 可能一次走两段路再坐下（每段约 4.5 秒），单次回执与整轮预算都要放宽
BRIDGE_TIMEOUT = max(1.0, float(os.environ.get("RP_BRIDGE_TIMEOUT") or "15"))
BRIDGE_BUDGET = max(1.0, float(os.environ.get("RP_BRIDGE_BUDGET") or "24"))
BRIDGE_MAX_CALLS = max(1, int(float(os.environ.get("RP_BRIDGE_MAX_CALLS") or "4")))
# 只读查询单独计数：不占动作预算，但也有硬上限（防止模型刷查询拖长回复）
BRIDGE_MAX_READS = max(1, int(float(os.environ.get("RP_BRIDGE_MAX_READS") or "4")))
# 长动作（走/坐/站/perform）超过这个时间先回 accepted，让模型先说话；页面任务继续跑。
STAGE_ACCEPT_MS = max(500, int(float(os.environ.get("RP_STAGE_ACCEPT_MS") or "2500")))
_STAGE_SLOW_ACTIONS = {"move_to", "sit", "stand", "perform", "play_clip", "play_gesture"}
BRIDGE_RESULT_CHARS = max(160, int(float(os.environ.get("RP_BRIDGE_RESULT_CHARS") or "600")))
BODY_INTENT_BUDGET = max(5.0, float(os.environ.get("RP_BODY_BUDGET") or "45"))
BODY_INTENT_STEPS = max(1, int(float(os.environ.get("RP_BODY_MAX_STEPS") or "3")))
BODY_INTENT_CALLS = max(1, int(float(os.environ.get("RP_BODY_MAX_CALLS") or "6")))
# 后台解码是同一家模型；超时压短，别让 QQ 回合等两分钟才回话
BODY_INTENT_LLM_TIMEOUT = max(5.0, float(os.environ.get("RP_BODY_LLM_TIMEOUT") or "30"))
# 一次视频回合之后，把「还在通话」的窗口再延续这么久，覆盖回合之间的听/说间隙；
# 窗口内 QQ 的 body_intent 直接拒绝，不排队去挤通话那条动作队列。
CALL_HOLD_SECONDS = max(0.0, float(os.environ.get("RP_CALL_HOLD") or "90"))
# 回复里的括号动作：回包之后再执行，给用户下一条指令留出抢锁窗口
BRACKET_BUDGET = max(3.0, float(os.environ.get("RP_BRACKET_BUDGET") or "12"))
BRACKET_DELAY_SECONDS = max(0.0, float(os.environ.get("RP_BRACKET_DELAY") or "0.6"))
# 跨窗口发话：QQ 私聊由本进程直接发；桌宠/通话各自有 HTTP 推送端点
DESKTOP_SAY_URL = (os.environ.get("RP_DESKTOP_SAY_URL")
                   or "http://127.0.0.1:8787/desktop/v1/say").strip()
CALL_SAY_URL = (os.environ.get("RP_CALL_SAY_URL")
                or "http://127.0.0.1:8790/call/say").strip()
WIN_TOKEN = str(os.environ.get("RP_WIN_TOKEN") or "").strip()
_WIN_LABELS = {"qq": "QQ", "desktop": "桌宠", "call": "通话"}
FACT_MERGE_HOURS = max(0.0, float(os.environ.get("RP_FACT_MERGE_HOURS") or 6))
FACT_MERGE_MIN = max(2, int(float(os.environ.get("RP_FACT_MERGE_MIN") or 20)))
CARD_MERGE_MIN = max(2, int(float(os.environ.get("RP_CARD_MERGE_MIN") or 8)))
# 合并候选先走向量召回：补进判定队列，仍过改写判定与二次复核；
# 阈值 RP_MERGE_ANN_COS 默认 0.80（0.72 时每条事实平均 2 个以上邻居，噪声太多）。
MERGE_ANN = (os.environ.get("RP_MERGE_ANN") or "0").strip().lower() not in {
    "0", "false", "no", "off"}
MERGE_ANN_COS = float(os.environ.get("RP_MERGE_ANN_COS") or 0.80)
# Dream 轻量整理：每天固定时刻收走过期临时事实 + 合并同义词条；0=关闭。
DREAM_ON = (os.environ.get("RP_DREAM") or "1").strip().lower() not in {
    "0", "false", "no", "off"}
# 模型账户余额提醒：降到 RP_BALANCE_ALERT（元，默认 1）及以下时，
# 瑾瑜会按人设主动「饿醒」私聊主人讨饭；0 = 关闭。检查间隔 RP_BALANCE_CHECK_HOURS（默认 1）。
BALANCE_ALERT = float(os.environ.get("RP_BALANCE_ALERT") or 1)
BALANCE_CHECK_HOURS = max(1.0, float(os.environ.get("RP_BALANCE_CHECK_HOURS") or 1))
DREAM_MAX_SESSIONS = max(1, int(float(os.environ.get("RP_DREAM_SESSIONS") or 8)))


def _dream_at(raw):
    """RP_DREAM_AT=HH:MM；写坏就退回 03:30，不让一个错配置把后台整理关掉。"""
    try:
        hour, minute = str(raw or "").strip().split(":", 1)
        return max(0, min(23, int(hour))), max(0, min(59, int(minute)))
    except (TypeError, ValueError):
        return 3, 30


DREAM_AT = _dream_at(os.environ.get("RP_DREAM_AT"))
SIGN_ON = (os.environ.get("RP_SIGN") or "1").strip().lower() not in {
    "0", "false", "no", "off"}
SIGN_GAP = max(0.0, float(os.environ.get("RP_SIGN_COOLDOWN_HOURS") or 24) * 3600)
QZONE_ON = (os.environ.get("RP_QZONE") or "1").strip().lower() not in {
    "0", "false", "no", "off"}
QZONE_DAILY = max(0, int(float(os.environ.get("RP_QZONE_DAILY") or 1)))
QZONE_GAP = max(0.0, float(os.environ.get("RP_QZONE_GAP_HOURS") or 6) * 3600)
_QZONE_RIGHT = int(float(os.environ.get("RP_QZONE_RIGHT") or 4))
# NapCat 允许值：1 所有人 / 4 好友 / 16 部分好友 / 64 仅自己 / 128 部分好友不可见
QZONE_RIGHT = _QZONE_RIGHT if _QZONE_RIGHT in {1, 4, 16, 64, 128} else 4
SOCIAL_AFFINITY_HOURS = max(0.0, float(
    os.environ.get("RP_SOCIAL_AFFINITY_HOURS") or 3))
# 后台复查：任务到点投递后过多久核对前台到底做了没有；0=关闭复查
REMIND_CHECK_SECONDS = max(0.0, float(
    os.environ.get("RP_REMIND_CHECK_SECONDS") or 120))
# 说出这些词的任务必须真有外部动作（调工具 / 发说说），只回一句话不算完成
_ACTION_WORDS = re.compile(
    r"说说|空间|签名|动态|qzone|表情包|贴纸|搜图|搜题|搜一下|图片|照片|视频|b站|网址",
    re.I)
NUDGE_LINES = ([
    os.environ["RP_IDLE_NUDGE_TEXT"]] if os.environ.get("RP_IDLE_NUDGE_TEXT") else [
    "你怎么这么长时间没找我说话了......",
    "主人......是不是把瑾瑜忘了......",
])

__all__ = [name for name in dir()
           if not name.startswith("_")
           and name not in {"os", "re", "bili_live"}] + [
    "_STAGE_SLOW_ACTIONS", "_ACTION_WORDS", "_QZONE_RIGHT"]
