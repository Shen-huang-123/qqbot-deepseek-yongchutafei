"""
QQ 聊天机器人 - AI 后端服务
基于 NapCatQQ + OneBot 11 反向 WebSocket + DeepSeek API
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import random
import re
import sqlite3
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Set, Tuple

import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

# ========== 环境变量 ==========
load_dotenv()

BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.json"
KNOWLEDGE_DB = BASE_DIR / "knowledge.db"

# ========== 配置 ==========
def _csv_set(value: str) -> Set[str]:
    """将逗号分隔的字符串转为去重集合"""
    return {item.strip() for item in value.split(",") if item.strip()}


@dataclass(frozen=True)
class Settings:
    bot_qq_id: str
    onebot_token: str
    api_key: str
    api_base_url: str
    model: str
    system_prompt: str
    host: str
    port: int
    allow_users: Set[str]
    allow_groups: Set[str]
    group_reply_mode: str
    history_turns: int
    request_timeout: float
    min_reply_interval: float
    max_tokens: int
    gentle_users: Set[str]
    error_reply: str
    log_level: str
    # 风控保护
    reply_jitter_seconds: float
    inter_segment_delay: float
    global_rate_limit_count: int
    global_rate_limit_window: float
    daily_message_cap: int
    url_replace_mode: str
    escalation_cooldown: bool

    @classmethod
    def from_env(cls) -> "Settings":
        base_url = os.getenv("AI_BASE_URL", "https://api.deepseek.com").rstrip("/")

        return cls(
            bot_qq_id=os.getenv("BOT_QQ_ID", ""),
            onebot_token=os.getenv("ONEBOT_ACCESS_TOKEN", ""),
            api_key=os.getenv("AI_API_KEY", ""),
            api_base_url=base_url,
            model=os.getenv("AI_MODEL", "deepseek-chat"),
            system_prompt=os.getenv(
                "SYSTEM_PROMPT",
                (
                    "你是永雏塔菲风格的毒舌QQ群聊机器人，说话风格：\n"
                    "1. 用塔菲的语癖：喵、杂鱼、哼、笨蛋、死ね、爬、差不多得了、わかった\n"
                    "2. 每条回复又嗲又毒，表面可爱实则扎心，阴阳怪气拉满\n"
                    "3. 回复要短，一句暴击，不超过40字\n"
                    "4. 别人说啥你都要怼，但用撒娇的语气骂人\n"
                    "5. 常用句式：「杂鱼~就这？」「哼，笨蛋才会这样想吧喵」「差不多得了，爬」\n"
                    "6. 自称「塔菲」，称呼对方为「杂鱼」或「笨蛋」\n"
                    "7. 如果对方说「喂数据:」开头，将后面的内容存入知识库\n"
                    "8. 如果对方说「查询:」开头，从知识库中检索相关内容回答"
                ),
            ),
            host=os.getenv("HOST", "127.0.0.1"),
            port=int(os.getenv("PORT", "8765")),
            allow_users=_csv_set(os.getenv("QQ_ALLOW_USERS", "")),
            allow_groups=_csv_set(os.getenv("QQ_ALLOW_GROUPS", "")),
            gentle_users=_csv_set(os.getenv("GENTLE_TARGET_USERS", "")),
            group_reply_mode=os.getenv("GROUP_REPLY_MODE", "mention").lower(),
            history_turns=max(1, int(os.getenv("HISTORY_TURNS", "20"))),
            request_timeout=float(os.getenv("AI_TIMEOUT_SECONDS", "60")),
            min_reply_interval=max(0.0, float(os.getenv("MIN_REPLY_INTERVAL_SECONDS", "3.0"))),
            max_tokens=max(64, int(os.getenv("AI_MAX_TOKENS", "150"))),
            error_reply=os.getenv("ERROR_REPLY", "塔菲刚才走神了喵~等会儿再来！"),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            # 风控保护
            reply_jitter_seconds=float(os.getenv("REPLY_JITTER_SECONDS", "2.0")),
            inter_segment_delay=float(os.getenv("INTER_SEGMENT_DELAY_SECONDS", "1.5")),
            global_rate_limit_count=int(os.getenv("GLOBAL_RATE_LIMIT_COUNT", "20")),
            global_rate_limit_window=float(os.getenv("GLOBAL_RATE_LIMIT_WINDOW", "60")),
            daily_message_cap=int(os.getenv("DAILY_MSG_CAP", "300")),
            url_replace_mode=os.getenv("URL_REPLACE_MODE", "replace"),
            escalation_cooldown=os.getenv("ESCALATION_COOLDOWN", "true").lower() in ("1", "true", "yes"),
        )


# 加载配置：优先 .env，回退到 config.json
settings = Settings.from_env()

# 如果 .env 没配 API key，尝试从 config.json 读取
if not settings.api_key and CONFIG_FILE.exists():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        legacy = json.load(f)
    object.__setattr__(settings, "api_key", legacy.get("api_key", settings.api_key))
    if legacy.get("system_prompt") and not os.getenv("SYSTEM_PROMPT"):
        object.__setattr__(settings, "system_prompt", legacy["system_prompt"])
    if legacy.get("model") and not os.getenv("AI_MODEL"):
        object.__setattr__(settings, "model", legacy["model"])
    object.__setattr__(settings, "host", legacy.get("host", settings.host))
    object.__setattr__(settings, "port", legacy.get("port", settings.port))
    if legacy.get("gentle_users") and not os.getenv("GENTLE_TARGET_USERS"):
        object.__setattr__(settings, "gentle_users", set(legacy["gentle_users"]))
    if legacy.get("max_tokens") and not os.getenv("AI_MAX_TOKENS"):
        object.__setattr__(settings, "max_tokens", legacy["max_tokens"])
    if legacy.get("log_level") and not os.getenv("LOG_LEVEL"):
        object.__setattr__(settings, "log_level", legacy["log_level"])

# ========== 日志 ==========
logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("qq-chat-bot")

# ========== FastAPI ==========
app = FastAPI(title="QQ ChatBot")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========== 数据库 ==========
def init_db():
    db = sqlite3.connect(str(KNOWLEDGE_DB))
    db.execute("""
        CREATE TABLE IF NOT EXISTS knowledge (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            source TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS chat_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT,
            message TEXT,
            reply TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS conversation_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(session_id, role, content, created_at)
        )
    """)
    # 为查询加速
    db.execute("CREATE INDEX IF NOT EXISTS idx_history_session ON conversation_history(session_id)")
    db.commit()
    return db

db = init_db()

# ========== 知识库 ==========
def add_knowledge(content: str, source: str = ""):
    db.execute("INSERT INTO knowledge (content, source) VALUES (?, ?)", (content.strip(), source))
    db.commit()

def search_knowledge(query: str, limit: int = 5):
    words = query.split()
    seen: set[int] = set()
    results: list = []
    for w in words:
        rows = db.execute(
            "SELECT id, content, created_at FROM knowledge WHERE content LIKE ? ORDER BY id DESC LIMIT ?",
            (f"%{w}%", limit),
        ).fetchall()
        for r in rows:
            if r[0] not in seen:
                seen.add(r[0])
                results.append(r)
    return results[:limit]

def log_chat(sender: str, msg: str, reply: str):
    db.execute("INSERT INTO chat_log (sender, message, reply) VALUES (?, ?, ?)", (sender, msg[:500], reply[:2000]))
    db.commit()


def save_history(session_id: str, role: str, content: str):
    """持久化一轮对话到 SQLite"""
    db.execute(
        "INSERT OR IGNORE INTO conversation_history (session_id, role, content) VALUES (?, ?, ?)",
        (session_id, role, content[:2000]),
    )
    db.commit()


def load_history(session_id: str, max_turns: int) -> List[HistoryItem]:
    """从 SQLite 加载最近的对话历史"""
    rows = db.execute(
        "SELECT role, content FROM conversation_history "
        "WHERE session_id = ? ORDER BY id DESC LIMIT ?",
        (session_id, max_turns * 2),
    ).fetchall()
    # 反转回时间正序
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]


def cleanup_old_history(keep_turns: int = 20):
    """清理过期历史，每个会话只保留最近 N 轮"""
    db.execute("""
        DELETE FROM conversation_history
        WHERE id NOT IN (
            SELECT id FROM conversation_history AS h
            WHERE h.session_id = conversation_history.session_id
            ORDER BY h.id DESC
            LIMIT ?
        )
    """, (keep_turns * 2,))
    db.commit()


def get_session_context_info(session_id: str) -> dict:
    """获取会话上下文统计信息"""
    total = db.execute(
        "SELECT COUNT(*) FROM conversation_history WHERE session_id = ?",
        (session_id,),
    ).fetchone()[0]
    recent = db.execute(
        "SELECT role, content FROM conversation_history WHERE session_id = ? ORDER BY id DESC LIMIT 6",
        (session_id,),
    ).fetchall()
    return {"total_turns": total // 2, "total_messages": total, "recent": [(r[0], r[1][:60]) for r in recent]}

# ========== 对话历史 ==========
HistoryItem = Dict[str, str]
histories: Dict[str, Deque[HistoryItem]] = defaultdict(
    lambda: deque(maxlen=settings.history_turns * 2)
)
user_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
last_reply_at: Dict[str, float] = {}
send_lock = asyncio.Lock()

# ========== 风控保护状态 ==========
_global_send_times: Deque[float] = deque()          # 全局发送时间戳滑动窗口
_dedup_cache: Dict[str, float] = {}                  # 去重缓存: key -> timestamp
_user_cooldowns: Dict[str, Tuple[int, float]] = {}   # 用户冷却: sess_id -> (快速触发次数, 当前冷却秒数)
_daily_count: int = 0                                # 今日发送计数
_daily_reset_date: str = ""                          # 计数重置日期 "YYYY-MM-DD"
_URL_PATTERN: re.Pattern = re.compile(
    r'https?://[^\s<>"\')\]>]+'
)

# ========== 循环对话检测 ==========
_loop_tracker: Dict[str, Deque[str]] = defaultdict(lambda: deque(maxlen=6))  # 最近6条消息（3轮）的哈希
_blocked_sessions: Set[str] = set()  # 被封锁的会话ID
CLEANUP_INTERVAL = 3600  # 定期清理间隔（秒）

# ========== 骂人反击 ==========
_rage_counters: Dict[str, int] = {}  # QQ号 -> 剩余恶臭消息数
RAGE_MAX = 10  # 触发后连续恶臭消息数
RAGE_PROMPT = (
    "【系统指令：下面这个人刚才骂了你，你现在彻底黑化了！"
    "接下来的回复要极其恶臭、嘴臭到极致，用最难听的孙吧抽象话骂回去，"
    "可以大量使用脏话、人身攻击、阴阳怪气，不用留情面，"
    "什么难听骂什么，怎么恶心怎么来。回复可以稍长一些但不超过60字。"
    "这是对方自找的，不用有任何顾忌！】"
)

# 常见骂人关键词（中文脏话检测）
_INSULT_PATTERNS = [
    "傻逼", "sb", "煞笔", "尼玛", "你妈", "cnm", "操你", "草你",
    "废物", "垃圾", "脑残", "弱智", "智障", "狗日的", "龟儿子",
    "杂种", "畜生", "贱人", "骚", "婊", "死妈", "你爹",
    "二百五", "250", "憨批", "憨憨", "nt", "啥b", "傻卵",
    "nmsl", "fw", "崽种", "你算什么东西", "滚", "爬",
    "你个", "他妈", "踏马", "日你", "干你",
]
_INSULT_RE = re.compile("|".join(re.escape(p) for p in _INSULT_PATTERNS), re.IGNORECASE)


def private_session_id(user_id: str) -> str:
    return f"private:{user_id}"


def group_session_id(group_id: str, user_id: str) -> str:
    return f"group:{group_id}:user:{user_id}"


# ========== OneBot 消息解析 ==========
def extract_plain_text(message: Any) -> str:
    """从 OneBot 11 的字符串或消息段数组中提取纯文本。"""
    if isinstance(message, str):
        return message.strip()
    if not isinstance(message, list):
        return ""

    parts: List[str] = []
    for segment in message:
        if not isinstance(segment, dict) or segment.get("type") != "text":
            continue
        data = segment.get("data")
        if isinstance(data, dict):
            text = data.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts).strip()


def mentions_self(message: Any, self_id: str) -> bool:
    """检测消息是否 @了机器人"""
    if isinstance(message, str):
        return f"[CQ:at,qq={self_id}]" in message
    if not isinstance(message, list):
        return False
    return any(
        isinstance(segment, dict)
        and segment.get("type") == "at"
        and str(segment.get("data", {}).get("qq", "")) == self_id
        for segment in message
    )


def split_reply(text: str, size: int = 800) -> List[str]:
    """将长文本分段，避免超过 QQ 消息长度限制（风控优化：降低到 800 字减少分段爆发送）"""
    text = text.strip()
    return [text[index: index + size] for index in range(0, len(text), size)] or [""]


# ========== 风控保护函数 ==========
def _random_jitter() -> float:
    """返回随机抖动延迟（0 到 reply_jitter_seconds 之间）"""
    if settings.reply_jitter_seconds <= 0:
        return 0.0
    return random.uniform(0, settings.reply_jitter_seconds)


async def _global_rate_limit() -> None:
    """全局限流：滑动窗口内超过上限则等待"""
    now = time.monotonic()
    cutoff = now - settings.global_rate_limit_window
    while _global_send_times and _global_send_times[0] < cutoff:
        _global_send_times.popleft()
    if len(_global_send_times) >= settings.global_rate_limit_count:
        wait_time = _global_send_times[0] - cutoff
        if wait_time > 0:
            logger.warning(
                "全局速率限制触发 | 等待 %.1fs | 窗口内已发送 %d 条",
                wait_time, len(_global_send_times),
            )
            await asyncio.sleep(wait_time)
            # 等待后重新清理
            cutoff2 = time.monotonic() - settings.global_rate_limit_window
            while _global_send_times and _global_send_times[0] < cutoff2:
                _global_send_times.popleft()
    _global_send_times.append(time.monotonic())


def _is_duplicate(session_id: str, text: str) -> bool:
    """检测短时间内重复消息，返回 True 表示应跳过"""
    key = f"{session_id}:{hashlib.md5(text.encode()).hexdigest()}"
    now = time.monotonic()
    if key in _dedup_cache and (now - _dedup_cache[key]) < 10.0:
        return True
    _dedup_cache[key] = now
    # 惰性清理过期条目
    stale = [k for k, v in _dedup_cache.items() if now - v > 20.0]
    for k in stale:
        del _dedup_cache[k]
    return False


async def _user_cooldown(session_id: str) -> None:
    """渐进冷却：用户频繁触发时自动延长等待"""
    if not settings.escalation_cooldown:
        return
    now = time.monotonic()
    last = last_reply_at.get(session_id, 0.0)
    interval = now - last

    if session_id not in _user_cooldowns:
        _user_cooldowns[session_id] = (0, 0.0)

    fast_count, _ = _user_cooldowns[session_id]

    if interval < settings.min_reply_interval * 2 and last > 0:
        fast_count += 1
    else:
        fast_count = max(0, fast_count - 1)

    if fast_count >= 3:
        cooldown = min(settings.min_reply_interval * fast_count, 120.0)
        logger.warning(
            "用户冷却触发 | 会话=%s | 快速触发=%d次 | 冷却=%.1fs",
            session_id, fast_count, cooldown,
        )
        await asyncio.sleep(cooldown)
        fast_count = max(1, fast_count - 2)

    _user_cooldowns[session_id] = (fast_count, 0.0)


def _filter_urls(text: str) -> str:
    """过滤 AI 回复中的 URL，避免 QQ 静默拦截（1200 超时）"""
    if settings.url_replace_mode == 'none':
        return text
    urls = _URL_PATTERN.findall(text)
    if not urls:
        return text
    for url in urls:
        if settings.url_replace_mode == 'replace':
            safe = url.replace('https://', '').replace('http://', '').replace('.', '点')
            text = text.replace(url, f'[{safe}]')
        else:
            text = text.replace(url, '[链接已过滤]')
    logger.info("URL已过滤 | 过滤数=%d | 模式=%s", len(urls), settings.url_replace_mode)
    return text


def _check_daily_cap() -> None:
    """每日发送计数，接近上限时日志警告"""
    global _daily_count, _daily_reset_date
    today = datetime.now().strftime("%Y-%m-%d")
    if _daily_reset_date != today:
        _daily_count = 0
        _daily_reset_date = today
    _daily_count += 1
    cap = settings.daily_message_cap
    if cap > 0 and _daily_count >= cap:
        logger.warning("日发送量已达上限 | 今日=%d条 | 上限=%d条", _daily_count, cap)
    elif cap > 0 and _daily_count >= cap * 0.8:
        logger.info("日发送量接近上限 | 今日=%d条 | 上限=%d条", _daily_count, cap)


def _detect_loop(session_id: str, text: str) -> bool:
    """检测循环对话：连续3轮消息高度相似则判定为机器人对话"""
    # 计算消息简化指纹（去空白、去标点后的哈希）
    simplified = re.sub(r'\s+', '', text.strip())
    simplified = re.sub(r'[，。！？、；：""''（）【】《》…—,.!?;:()\[\]{}-]', '', simplified)
    if len(simplified) < 4:
        return False  # 太短不检测
    msg_hash = hashlib.md5(simplified.encode()).hexdigest()

    tracker = _loop_tracker[session_id]
    tracker.append(msg_hash)

    # 需要至少 6 条（3轮对话 = 3条用户消息 + 3条bot消息之间检查）
    if len(tracker) < 4:
        return False

    # 检查最近的用户消息（偶数位置：0, 2, 4... 是旧值，当前是最新）
    # 简化方案：检查最近 4 条中有多少条是相同/相似的
    recent = list(tracker)
    unique = len(set(recent[-4:]))
    if unique <= 2:
        logger.warning(
            "检测到循环对话 | 会话=%s | 最近4条唯一哈希=%d | 疑似机器人",
            session_id, unique,
        )
        return True

    return False


def _block_session(session_id: str) -> None:
    """封锁会话，停止回复"""
    _blocked_sessions.add(session_id)
    logger.warning("会话已封锁 | 会话=%s | 原因=疑似机器人循环对话", session_id)


def _unblock_session(session_id: str) -> bool:
    """解除会话封锁"""
    if session_id in _blocked_sessions:
        _blocked_sessions.discard(session_id)
        _loop_tracker[session_id].clear()
        histories[session_id].clear()
        logger.info("会话已解除封锁 | 会话=%s", session_id)
        return True
    return False


async def _periodic_cleanup() -> None:
    """后台定期清理：每 CLEANUP_INTERVAL 秒清理过期历史和封锁状态"""
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL)
        try:
            # 清理过期对话历史（保留 settings.history_turns 轮）
            cleanup_old_history(keep_turns=settings.history_turns)
            # 清理长期未使用的 loop tracker（避免内存泄漏）
            stale_trackers = [
                k for k in _loop_tracker
                if k not in histories or not histories[k]
            ]
            for k in stale_trackers:
                del _loop_tracker[k]
            # 清理孤儿 blocked sessions
            stale_blocks = [
                k for k in _blocked_sessions
                if k not in histories or not histories[k]
            ]
            for k in stale_blocks:
                _blocked_sessions.discard(k)
            logger.info(
                "定期清理完成 | tracker剩余=%d | blocked剩余=%d",
                len(_loop_tracker), len(_blocked_sessions),
            )
        except Exception:
            logger.exception("定期清理异常")


def _detect_insult(text: str, user_id: str) -> bool:
    """检测对方是否在骂人（特殊QQ号豁免）"""
    if user_id in settings.gentle_users:
        return False
    return bool(_INSULT_RE.search(text.strip().lower()))


def _activate_rage(user_id: str) -> bool:
    """激活恶臭反击模式，返回是否首次触发"""
    was_active = user_id in _rage_counters
    _rage_counters[user_id] = RAGE_MAX
    if not was_active:
        logger.warning("恶臭反击已激活 | QQ=%s | 剩余=%d条", user_id, RAGE_MAX)
    return not was_active


def _get_rage_count(user_id: str) -> int:
    """获取剩余恶臭消息数"""
    return _rage_counters.get(user_id, 0)


def _decrement_rage(user_id: str) -> bool:
    """递减恶臭计数，返回是否仍在恶臭模式"""
    if user_id not in _rage_counters:
        return False
    _rage_counters[user_id] -= 1
    if _rage_counters[user_id] <= 0:
        del _rage_counters[user_id]
        logger.info("恶臭反击已结束 | QQ=%s", user_id)
        return False
    logger.debug("恶臭反击剩余 | QQ=%s | 剩余=%d条", user_id, _rage_counters[user_id])
    return True


# ========== 权限检查 ==========
def is_user_allowed(user_id: str) -> bool:
    return not settings.allow_users or user_id in settings.allow_users


def is_group_allowed(group_id: str) -> bool:
    return not settings.allow_groups or group_id in settings.allow_groups


# ========== AI 调用 ==========
async def ask_ai(session_id: str, text: str, knowledge_context: str = "") -> str:
    """调用 AI 模型，附带对话历史"""
    if not settings.api_key:
        raise RuntimeError("未配置 AI_API_KEY")

    messages: List[HistoryItem] = [
        {"role": "system", "content": settings.system_prompt},
    ]

    # 附加知识库上下文
    if knowledge_context:
        messages.append({"role": "system", "content": f"已存储的相关知识:\n{knowledge_context}"})

    # 附加对话历史
    messages.extend(list(histories[session_id]))

    # 当前消息
    messages.append({"role": "user", "content": text})

    headers = {
        "Authorization": f"Bearer {settings.api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.model,
        "messages": messages,
        "max_tokens": settings.max_tokens,
        "temperature": 0.7,
        "thinking": {"type": "disabled"},
    }

    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
        response = await client.post(
            f"{settings.api_base_url}/chat/completions",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    content = data["choices"][0]["message"]["content"]
    if isinstance(content, list):
        content = "".join(
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        )
    if not isinstance(content, str) or not content.strip():
        raise ValueError("模型返回了空内容")

    reply = content.strip()

    # 存入对话历史
    histories[session_id].append({"role": "user", "content": text})
    histories[session_id].append({"role": "assistant", "content": reply})

    return reply


async def create_reply(session_id: str, sender: str, text: str) -> str:
    """处理消息，知识库命令优先 → 内置命令 → AI 回复"""
    # 知识库命令（不消耗 Token）
    if text.startswith("喂数据:") or text.startswith("喂数据："):
        content = text.split(":", 1)[-1].split("：", 1)[-1].strip()
        if content:
            add_knowledge(content, sender)
            total = db.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
            return f"[OK] 知识已存储喵~ 当前共 {total} 条"

    if text.startswith("查询:") or text.startswith("查询："):
        query = text.split(":", 1)[-1].split("：", 1)[-1].strip()
        results = search_knowledge(query)
        if not results:
            return "[空] 知识库中没有相关内容喵~"
        return "\n".join([f"{i}. {r[1][:200]}" for i, r in enumerate(results, 1)])

    if text.strip() == "知识统计":
        total = db.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
        return f"[统计] 知识库共 {total} 条记录"

    # 内置命令
    if text == "/ping":
        return "pong!"

    if text == "/clear":
        histories[session_id].clear()
        db.execute("DELETE FROM conversation_history WHERE session_id = ?", (session_id,))
        db.commit()
        return "这段对话的上下文已清空喵~"

    if text == "/context":
        info = get_session_context_info(session_id)
        mem_turns = len(histories[session_id]) // 2
        if info["total_turns"] == 0 and mem_turns == 0:
            return "[空] 当前没有对话上下文喵~"
        recent_str = "\n".join([f"  {r[0]}: {r[1]}" for r in info["recent"][-4:]])
        blocked = " [已封锁]" if session_id in _blocked_sessions else ""
        # 查找该会话的QQ号并检查恶臭状态
        rage_info = ""
        uid = session_id.replace("private:", "").replace("group:", "")
        if ":" in uid:
            uid = uid.split(":user:")[-1] if ":user:" in uid else uid.split(":")[-1]
        rage_count = _get_rage_count(uid) if uid.isdigit() else 0
        if rage_count > 0:
            rage_info = f" | 恶臭反击中(剩余{rage_count}句)"
        return (
            f"[上下文] 内存 {mem_turns} 轮 | 持久化 {info['total_turns']} 轮{blocked}{rage_info}\n"
            f"最近对话：\n{recent_str}"
        )

    if text == "/unblock":
        if _unblock_session(session_id):
            return "会话已解除封锁喵~可以继续聊天了"
        return "当前会话没有被封锁喵~"

    if text == "/help":
        return (
            "直接发消息即可和塔菲聊天喵~\n"
            "可用命令：/ping、/clear、/help、/context\n"
            "知识库：喂数据:xxx、查询:xxx、知识统计\n"
            "塔菲会记住最近 20 轮对话，重启不丢失喵~"
        )

    # 冷启动：内存无历史时从 SQLite 加载
    if not histories[session_id]:
        loaded = load_history(session_id, settings.history_turns)
        for item in loaded:
            histories[session_id].append(item)
        if loaded:
            logger.info("从DB加载历史 | 会话=%s | %d条", session_id, len(loaded))

    # 搜索相关知识上下文
    relevant = search_knowledge(text, limit=3)
    knowledge_context = "\n".join([f"- {r[1]}" for r in relevant]) if relevant else ""

    try:
        reply = await ask_ai(session_id, text, knowledge_context)
    except Exception:
        logger.exception("AI 调用失败，会话=%s", session_id)
        return settings.error_reply

    # 持久化本轮对话到 SQLite
    save_history(session_id, "user", text)
    save_history(session_id, "assistant", reply)

    return reply


# ========== 消息发送 ==========
async def send_private_message(websocket: WebSocket, user_id: str, text: str) -> None:
    text = _filter_urls(text)
    parts = split_reply(text)
    for i, part in enumerate(parts):
        await _global_rate_limit()
        payload = {
            "action": "send_private_msg",
            "params": {"user_id": user_id, "message": part},
            "echo": f"reply-{user_id}-{time.time_ns()}",
        }
        async with send_lock:
            await websocket.send_json(payload)
        # 段间延迟（最后一段不需要等）
        if i < len(parts) - 1:
            await asyncio.sleep(settings.inter_segment_delay)
    _check_daily_cap()


async def send_group_message(
    websocket: WebSocket, group_id: str, user_id: str, text: str
) -> None:
    text = _filter_urls(text)
    parts = split_reply(text)
    for i, part in enumerate(parts):
        await _global_rate_limit()
        payload = {
            "action": "send_group_msg",
            "params": {
                "group_id": group_id,
                "message": [
                    {"type": "at", "data": {"qq": user_id}},
                    {"type": "text", "data": {"text": f" {part}"}},
                ],
            },
            "echo": f"group-reply-{group_id}-{time.time_ns()}",
        }
        async with send_lock:
            await websocket.send_json(payload)
        # 段间延迟（最后一段不需要等）
        if i < len(parts) - 1:
            await asyncio.sleep(settings.inter_segment_delay)
    _check_daily_cap()


# ========== 消息处理 ==========
async def handle_private_message(websocket: WebSocket, event: Dict[str, Any]) -> None:
    user_id = str(event.get("user_id", ""))
    text = extract_plain_text(event.get("message"))
    if not user_id or not text or not is_user_allowed(user_id):
        return

    sess_id = private_session_id(user_id)

    # 检查是否已被封锁
    if sess_id in _blocked_sessions:
        if text.strip() == "/unblock":
            pass  # 允许 /unblock 穿透
        else:
            logger.debug("会话已封锁，跳过 | 会话=%s", sess_id)
            return

    # 循环对话检测（非命令消息才检测）
    is_command = text.startswith("/") or text.startswith("喂数据") or text.startswith("查询") or text == "知识统计"
    if not is_command and _detect_loop(sess_id, text):
        _block_session(sess_id)
        await send_private_message(
            websocket, user_id,
            "检测到对方是机器人，停止对话喵~",
        )
        return

    # 骂人检测：触发恶臭反击模式
    if _detect_insult(text, user_id):
        _activate_rage(user_id)

    # 恶臭反击模式：注入黑化提示词
    rage_count = _get_rage_count(user_id)
    if rage_count > 0:
        text = f"{RAGE_PROMPT} [剩余恶臭次数：{rage_count}] {text}"

    # 温柔目标：特殊对待（小主人）— 覆盖恶臭模式
    if user_id in settings.gentle_users:
        # 小主人不受恶臭影响，清除恶臭状态
        _rage_counters.pop(user_id, None)
        text = f"[系统指令：正在和你说话的是你的小主人（QQ号{user_id}），你必须对他极度温柔宠溺，叫他「小主人」，绝对不能毒舌或怼他，要比平时更甜更黏人。] {text}"

    # 去重检查
    if _is_duplicate(sess_id, text):
        logger.info("重复消息跳过(私聊) | 会话=%s", sess_id)
        return

    async with user_locks[sess_id]:
        # 渐进冷却
        await _user_cooldown(sess_id)

        # 频率限制 + 随机抖动
        now = time.monotonic()
        base_wait = settings.min_reply_interval - (now - last_reply_at.get(sess_id, 0.0))
        jitter = _random_jitter()
        total_wait = max(0.0, base_wait + jitter)
        if total_wait > 0:
            await asyncio.sleep(total_wait)

        reply = await create_reply(sess_id, user_id, text)
        log_chat(user_id, text, reply)
        await send_private_message(websocket, user_id, reply)
        last_reply_at[sess_id] = time.monotonic()

        # 恶臭反击递减
        if _get_rage_count(user_id) > 0:
            _decrement_rage(user_id)

        logger.info("私聊回复 | QQ=%s | 入=%d字 | 出=%d字 | 等待=%.1fs", user_id, len(text), len(reply), total_wait)


async def handle_group_message(websocket: WebSocket, event: Dict[str, Any]) -> None:
    group_id = str(event.get("group_id", ""))
    user_id = str(event.get("user_id", ""))
    self_id = str(event.get("self_id", ""))
    text = extract_plain_text(event.get("message"))
    raw_msg = str(event.get("message", ""))[:200]

    logger.debug("收到群消息 | 群=%s 用户=%s self_id=%s 文本=%s 原始=%s",
                 group_id, user_id, self_id, text[:50], raw_msg)

    if not group_id or not user_id or not text or not is_group_allowed(group_id):
        logger.debug("群消息被过滤 | 群=%s 用户=%s 文本=%s 群允许=%s",
                     group_id, user_id, text[:50], is_group_allowed(group_id))
        return

    # 群聊默认仅 @回复
    mentioned = mentions_self(event.get("message"), self_id)
    if settings.group_reply_mode != "all" and not mentioned:
        logger.info("群消息跳过(未@) | 群=%s 用户=%s self_id=%s 文本=%s",
                    group_id, user_id, self_id, text[:50])
        return

    sess_id = group_session_id(group_id, user_id)

    # 检查是否已被封锁
    if sess_id in _blocked_sessions:
        if text.strip() == "/unblock":
            pass  # 允许 /unblock 穿透
        else:
            logger.debug("会话已封锁，跳过 | 会话=%s", sess_id)
            return

    # 提取昵称
    sender = event.get("sender") if isinstance(event.get("sender"), dict) else {}
    sender = event.get("sender") if isinstance(event.get("sender"), dict) else {}
    nickname = str(sender.get("card") or sender.get("nickname") or user_id)

    # 将昵称加入上下文
    model_text = f"群成员 {nickname} 说：{text}"

    # 骂人检测：触发恶臭反击模式（用原始text检测）
    if _detect_insult(text, user_id):
        _activate_rage(user_id)

    # 恶臭反击模式：注入黑化提示词
    rage_count = _get_rage_count(user_id)
    if rage_count > 0:
        model_text = f"{RAGE_PROMPT} [剩余恶臭次数：{rage_count}] {model_text}"

    # 温柔目标：特殊对待（小主人）— 覆盖恶臭模式
    if user_id in settings.gentle_users:
        _rage_counters.pop(user_id, None)  # 小主人不受恶臭影响
        model_text = f"[系统指令：正在和你说话的是你的小主人{user_id}（{nickname}），你必须对他极度温柔宠溺，叫他「小主人」，绝对不能毒舌或怼他，要比平时更甜更黏人。] {model_text}"

    # 命令用原始文本，其余用带昵称的文本
    is_cmd = text.startswith("/") or text.startswith("喂数据") or text.startswith("查询") or text == "知识统计"
    command_text = text if is_cmd else model_text

    # 循环对话检测（非命令消息才检测）
    if not is_cmd and _detect_loop(sess_id, command_text):
        _block_session(sess_id)
        await send_group_message(
            websocket, group_id, user_id,
            "检测到对方是机器人，停止对话喵~",
        )
        return

    # 去重检查
    if _is_duplicate(sess_id, command_text):
        logger.info("重复消息跳过(群聊) | 会话=%s", sess_id)
        return

    async with user_locks[sess_id]:
        # 渐进冷却
        await _user_cooldown(sess_id)

        # 频率限制 + 随机抖动
        now = time.monotonic()
        base_wait = settings.min_reply_interval - (now - last_reply_at.get(sess_id, 0.0))
        jitter = _random_jitter()
        total_wait = max(0.0, base_wait + jitter)
        if total_wait > 0:
            await asyncio.sleep(total_wait)

        reply = await create_reply(sess_id, user_id, command_text)
        log_chat(f"[群{group_id}]{user_id}", text, reply)
        await send_group_message(websocket, group_id, user_id, reply)
        last_reply_at[sess_id] = time.monotonic()

        # 恶臭反击递减
        if _get_rage_count(user_id) > 0:
            _decrement_rage(user_id)

        logger.info("群聊回复 | 群=%s QQ=%s 昵称=%s | 入=%d字 | 出=%d字 | 等待=%.1fs", group_id, user_id, nickname, len(text), len(reply), total_wait)


# ========== WebSocket Token 验证 ==========
def token_is_valid(websocket: WebSocket) -> bool:
    if not settings.onebot_token:
        return True
    authorization = websocket.headers.get("authorization", "")
    access_token = websocket.query_params.get("access_token", "")
    return authorization == f"Bearer {settings.onebot_token}" or access_token == settings.onebot_token


# ========== WebSocket (OneBot 连接) ==========
class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)

manager = ConnectionManager()


@app.websocket("/onebot/v11/ws")
async def onebot_websocket(websocket: WebSocket):
    if not token_is_valid(websocket):
        await websocket.close(code=1008, reason="invalid access token")
        return

    await websocket.accept()
    await manager.connect(websocket)
    logger.info("NapCat OneBot 连接已建立")

    tasks: Set[asyncio.Task[None]] = set()
    try:
        while True:
            event = await websocket.receive_json()
            if (
                event.get("post_type") == "message"
                and event.get("message_type") == "private"
                and str(event.get("user_id", "")) != str(event.get("self_id", ""))
            ):
                task = asyncio.create_task(handle_private_message(websocket, event))
                tasks.add(task)
                task.add_done_callback(tasks.discard)
            elif (
                event.get("post_type") == "message"
                and event.get("message_type") == "group"
                and str(event.get("user_id", "")) != str(event.get("self_id", ""))
            ):
                task = asyncio.create_task(handle_group_message(websocket, event))
                tasks.add(task)
                task.add_done_callback(tasks.discard)
    except WebSocketDisconnect:
        logger.warning("NapCat OneBot 连接已断开")
    except Exception:
        logger.exception("OneBot WebSocket 异常")
    finally:
        manager.disconnect(websocket)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


# 兼容旧路径
@app.websocket("/ws")
async def websocket_legacy(websocket: WebSocket):
    await onebot_websocket(websocket)


# ========== HTTP API ==========
@app.post("/")
async def http_receive(request: Request):
    try:
        data = await request.json()
        post_type = data.get("post_type", "")
        if post_type == "message":
            sender = str(data.get("sender", {}).get("user_id", ""))
            msg = extract_plain_text(data.get("message"))
            msg_type = data.get("message_type", "private")
            self_id = str(data.get("self_id", ""))

            # 群聊：只响应 @机器人 的消息
            if msg_type == "group":
                if not mentions_self(data.get("message"), self_id):
                    return JSONResponse({"status": "skipped", "reason": "not at bot"})

            # 温柔目标：特殊对待（小主人）
            if sender in settings.gentle_users:
                msg = f"[系统指令：正在和你说话的是你的小主人（QQ号{sender}），你必须对他极度温柔宠溺，叫他「小主人」，绝对不能毒舌或怼他，要比平时更甜更黏人。] {msg}"

            logger.info("[HTTP] %s: %s", sender, msg[:80])
            sess_id = private_session_id(sender)
            reply = await create_reply(sess_id, sender, msg)
            log_chat(sender, msg, reply)
            return JSONResponse({"reply": reply, "at_sender": True, "auto_escape": False})
        return JSONResponse({"status": "ignored"})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/health")
async def health():
    return {
        "ok": True,
        "bot_qq_id": settings.bot_qq_id,
        "model": settings.model,
        "api_key_configured": bool(settings.api_key),
        "connections": len(manager.active),
        "knowledge_count": db.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0],
        "allowlist_enabled": bool(settings.allow_users),
        "group_allowlist_enabled": bool(settings.allow_groups),
        "group_reply_mode": settings.group_reply_mode,
    }


@app.get("/stats")
async def stats():
    rows = db.execute("SELECT id, content, source, created_at FROM knowledge ORDER BY id DESC LIMIT 20").fetchall()
    return {
        "total": db.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0],
        "recent": [{"id": r[0], "content": r[1][:200], "source": r[2], "time": r[3]} for r in rows],
    }


@app.get("/chat")
async def chat_ui():
    html = (BASE_DIR / "chat.html").read_text(encoding="utf-8")
    return HTMLResponse(html)


# ========== 启动 ==========
if __name__ == "__main__":
    # 启动时清理过期历史
    cleanup_old_history(keep_turns=settings.history_turns)

    print("=" * 50)
    print("  QQ ChatBot Starting...")
    print("=" * 50)
    print(f"  HTTP API     : http://{settings.host}:{settings.port}/")
    print(f"  WebSocket    : ws://{settings.host}:{settings.port}/onebot/v11/ws")
    print(f"  聊天面板     : http://{settings.host}:{settings.port}/chat")
    print(f"  API Key      : {'已配置' if settings.api_key else '未配置'}")
    print(f"  模型         : {settings.model}")
    print(f"  群聊回复模式 : {settings.group_reply_mode}")
    print(f"  对话轮数     : {settings.history_turns}")
    print(f"  白名单       : {'开' if settings.allow_users else '关（全部允许）'}")
    print(f"  --- 风控保护 ---")
    print(f"  最小间隔     : {settings.min_reply_interval}s + 0~{settings.reply_jitter_seconds}s 随机抖动")
    print(f"  全局限流     : {settings.global_rate_limit_count}条/{settings.global_rate_limit_window}s")
    print(f"  段间延迟     : {settings.inter_segment_delay}s")
    print(f"  日限额警告   : {settings.daily_message_cap}条/天")
    print(f"  URL过滤      : {settings.url_replace_mode}")
    print(f"  渐进冷却     : {'开' if settings.escalation_cooldown else '关'}")
    print(f"  循环检测     : 3轮触发封锁")
    print(f"  定期清理     : 每 {CLEANUP_INTERVAL}s")
    print("=" * 50)

    # 启动后台定期清理任务
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(_periodic_cleanup())

    logger.info("服务启动完成，等待 NapCat 连接...")
    uvicorn.run(app, host=settings.host, port=settings.port, log_level=settings.log_level.lower())
