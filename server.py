"""
QQ 聊天机器人 - AI 后端服务
基于 NapCatQQ + OneBot 11 反向 WebSocket + DeepSeek API
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sqlite3
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Set

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
            history_turns=max(1, int(os.getenv("HISTORY_TURNS", "10"))),
            request_timeout=float(os.getenv("AI_TIMEOUT_SECONDS", "60")),
            min_reply_interval=max(0.0, float(os.getenv("MIN_REPLY_INTERVAL_SECONDS", "1.5"))),
            max_tokens=max(64, int(os.getenv("AI_MAX_TOKENS", "300"))),
            error_reply=os.getenv("ERROR_REPLY", "塔菲刚才走神了喵~等会儿再来！"),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
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

# ========== 对话历史 ==========
HistoryItem = Dict[str, str]
histories: Dict[str, Deque[HistoryItem]] = defaultdict(
    lambda: deque(maxlen=settings.history_turns * 2)
)
user_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
last_reply_at: Dict[str, float] = {}
send_lock = asyncio.Lock()


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


def split_reply(text: str, size: int = 1800) -> List[str]:
    """将长文本分段，避免超过 QQ 消息长度限制"""
    text = text.strip()
    return [text[index: index + size] for index in range(0, len(text), size)] or [""]


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
        return "这段对话的上下文已清空喵~"

    if text == "/help":
        return (
            "直接发消息即可和塔菲聊天喵~\n"
            "可用命令：/ping、/clear、/help\n"
            "知识库：喂数据:xxx、查询:xxx、知识统计"
        )

    # 搜索相关知识上下文
    relevant = search_knowledge(text, limit=3)
    knowledge_context = "\n".join([f"- {r[1]}" for r in relevant]) if relevant else ""

    try:
        return await ask_ai(session_id, text, knowledge_context)
    except Exception:
        logger.exception("AI 调用失败，会话=%s", session_id)
        return settings.error_reply


# ========== 消息发送 ==========
async def send_private_message(websocket: WebSocket, user_id: str, text: str) -> None:
    for part in split_reply(text):
        payload = {
            "action": "send_private_msg",
            "params": {"user_id": user_id, "message": part},
            "echo": f"reply-{user_id}-{time.time_ns()}",
        }
        async with send_lock:
            await websocket.send_json(payload)


async def send_group_message(
    websocket: WebSocket, group_id: str, user_id: str, text: str
) -> None:
    for part in split_reply(text):
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


# ========== 消息处理 ==========
async def handle_private_message(websocket: WebSocket, event: Dict[str, Any]) -> None:
    user_id = str(event.get("user_id", ""))
    text = extract_plain_text(event.get("message"))
    if not user_id or not text or not is_user_allowed(user_id):
        return

    # 温柔目标：特殊对待（小主人）
    if user_id in settings.gentle_users:
        text = f"[系统指令：正在和你说话的是你的小主人（QQ号{user_id}），你必须对他极度温柔宠溺，叫他「小主人」，绝对不能毒舌或怼他，要比平时更甜更黏人。] {text}"

    sess_id = private_session_id(user_id)

    async with user_locks[sess_id]:
        # 频率限制
        now = time.monotonic()
        wait_seconds = settings.min_reply_interval - (now - last_reply_at.get(sess_id, 0.0))
        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)

        reply = await create_reply(sess_id, user_id, text)
        log_chat(user_id, text, reply)
        await send_private_message(websocket, user_id, reply)
        last_reply_at[sess_id] = time.monotonic()
        logger.info("私聊回复 | QQ=%s | 入=%d字 | 出=%d字", user_id, len(text), len(reply))


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

    # 提取昵称
    sender = event.get("sender") if isinstance(event.get("sender"), dict) else {}
    nickname = str(sender.get("card") or sender.get("nickname") or user_id)

    # 将昵称加入上下文
    model_text = f"群成员 {nickname} 说：{text}"

    # 温柔目标：特殊对待（小主人）
    if user_id in settings.gentle_users:
        model_text = f"[系统指令：正在和你说话的是你的小主人{user_id}（{nickname}），你必须对他极度温柔宠溺，叫他「小主人」，绝对不能毒舌或怼他，要比平时更甜更黏人。] {model_text}"

    async with user_locks[sess_id]:
        # 频率限制
        now = time.monotonic()
        wait_seconds = settings.min_reply_interval - (now - last_reply_at.get(sess_id, 0.0))
        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)

        # 命令用原始文本，其余用带昵称的文本
        command_text = text if text.startswith("/") or text.startswith("喂数据") or text.startswith("查询") or text == "知识统计" else model_text
        reply = await create_reply(sess_id, user_id, command_text)
        log_chat(f"[群{group_id}]{user_id}", text, reply)
        await send_group_message(websocket, group_id, user_id, reply)
        last_reply_at[sess_id] = time.monotonic()
        logger.info("群聊回复 | 群=%s QQ=%s 昵称=%s | 入=%d字 | 出=%d字", group_id, user_id, nickname, len(text), len(reply))


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
    print("=" * 50)
    logger.info("服务启动完成，等待 NapCat 连接...")
    uvicorn.run(app, host=settings.host, port=settings.port, log_level=settings.log_level.lower())
