# QQ ChatBot — AI 群聊机器人

> GitHub: https://github.com/Shen-huang-123/qqbot-deepseek-yongchutafei

## 项目概览

基于 NapCatQQ + Python FastAPI 的 QQ 机器人，使用 DeepSeek API（或其他 OpenAI 兼容接口）提供 AI 回复。支持私聊和群聊，带对话记忆、知识库和 Web 聊天面板。

## 架构

```text
QQ NT 客户端
  └─ NapCatQQ (注入式 QQ 机器人框架)
       └─ OneBot v11 反向 WebSocket → ws://127.0.0.1:8765/onebot/v11/ws
            └─ server.py (FastAPI 后端)
                 ├─ DeepSeek / OpenAI 兼容 API
                 ├─ SQLite 知识库 + 聊天记录
                 └─ chat.html (Web 聊天面板)
```

## 关键文件

| 文件 | 用途 | AI 可修改 |
|------|------|-----------|
| `server.py` | AI 后端服务核心，WebSocket + HTTP 双通道 | ✅ |
| `chat.html` | 浏览器聊天面板 (http://127.0.0.1:8765/chat) | ✅ |
| `.env` | 运行时配置（不入库，从 .env.example 复制） | ❌ |
| `.env.example` | 配置模板，不含真实密钥 | ✅ |
| `config.json` | 旧版配置文件（向后兼容，优先读 .env） | ❌ 不入库 |
| `knowledge.db` | SQLite 知识库 + 聊天记录 | ❌ 不入库 |
| `clipboard_bridge.py` | 剪贴板桥接（备用方案） | ✅ |
| `requirements.txt` | Python 依赖 | ✅ |
| `start.bat` | 简化启动脚本 | ✅ |
| `重启后启动.bat` | 一键启动（注入 NapCat → 服务 → QQ） | ✅ |

## 部署步骤

### 前置条件

1. **NapCatQQ** 已安装，路径见启动脚本
2. **QQ NT** 已安装，版本匹配 NapCat 注入要求
3. **Python 3.11+** 及依赖（见 requirements.txt）

### 首次部署

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，至少填写 AI_API_KEY

# 3. 启动服务
python server.py
```

### NapCat 配置

在 NapCat WebUI 中新建 WebSocket 客户端（反向连接）：

- **URL**: `ws://127.0.0.1:8765/onebot/v11/ws`
- **消息格式**: `array`
- **Token**: 与 `.env` 中 `ONEBOT_ACCESS_TOKEN` 一致（可选）

### 一键启动（Windows）

双击 `重启后启动.bat`，会自动完成：
1. 注入 NapCat 到 QQ NT
2. 启动 AI 服务
3. 启动 QQ NT
4. 等待二维码并复制到项目目录

## 服务地址

| 地址 | 用途 |
|------|------|
| `http://127.0.0.1:8765` | AI 服务 |
| `http://127.0.0.1:8765/chat` | Web 聊天面板 |
| `http://127.0.0.1:8765/health` | 健康检查 |
| `http://127.0.0.1:8765/stats` | 知识库统计 |
| `http://127.0.0.1:6099/webui` | NapCat WebUI |

## 核心功能

### 对话历史记忆

- 每个会话保留最近 N 轮对话上下文（`HISTORY_TURNS`，默认 10）
- 私聊会话 ID：`private:{user_id}`
- 群聊会话 ID：`group:{group_id}:user:{user_id}`（按群+人隔离，不串话）

### 内置命令

| 命令 | 功能 |
|------|------|
| `/ping` | 测试连通性 |
| `/clear` | 清除当前会话上下文 |
| `/help` | 查看帮助 |
| `喂数据:xxx` | 存入知识库 |
| `查询:xxx` | 搜索知识库 |
| `知识统计` | 查看知识库条数 |

### 群聊 @回复

- 默认 `GROUP_REPLY_MODE=mention`：仅被 @ 时回复
- 回复时自动 @提问者
- 支持 `all` 模式回复所有消息（易刷屏，不推荐）

### 白名单

- `QQ_ALLOW_USERS`：允许的好友（逗号分隔，留空=全部）
- `QQ_ALLOW_GROUPS`：允许的群号（逗号分隔，留空=全部）
- `GENTLE_TARGET_USERS`：温柔对待的特殊用户

### 其他特性

- 频率限制（`MIN_REPLY_INTERVAL_SECONDS`，默认 1.5s）
- 长消息自动分段（1800 字符/段）
- OneBot 消息数组格式兼容
- WebSocket Token 认证（可选）
- 群聊昵称识别（AI 知道是谁在说话）
- 知识库（SQLite 存储，支持喂数据/查询）
- 聊天记录持久化

## 配置说明

### 优先方式：`.env` 文件

复制 `.env.example` 为 `.env`，至少填 `AI_API_KEY`。

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `AI_API_KEY` | API Key | 必填 |
| `AI_BASE_URL` | API 地址 | `https://api.deepseek.com` |
| `AI_MODEL` | 模型名 | `deepseek-chat` |
| `AI_MAX_TOKENS` | 最大输出 Token | 300 |
| `HISTORY_TURNS` | 对话历史轮数 | 10 |
| `GROUP_REPLY_MODE` | 群聊回复模式 | `mention` |
| `PORT` | 服务端口 | 8765 |
| `SYSTEM_PROMPT` | 系统人设 | 塔菲风格毒舌 |

### 兼容其他模型服务

只要服务兼容 OpenAI 的 `POST /chat/completions` 格式，修改以下配置即可：

```dotenv
AI_BASE_URL=http://127.0.0.1:11434/v1
AI_API_KEY=ollama
AI_MODEL=qwen3:8b
```

## WebSocket API

### OneBot v11 事件

- 端点：`ws://127.0.0.1:8765/onebot/v11/ws`
- 支持 `message/private` 和 `message/group` 事件
- 响应通过 `send_private_msg` / `send_group_msg` action 回传

### HTTP API

- `POST /` — OneBot HTTP 上报兼容
- `GET /health` — 健康检查
- `GET /stats` — 知识库统计
- `GET /chat` — Web 聊天面板

## Python 环境

- Python 3.11+
- 依赖：`fastapi`, `uvicorn`, `httpx`, `websockets`, `python-dotenv`
- 可选：`pyperclip`（剪贴板桥接）

## 当前边界

- 仅回复文字消息，不处理图片、语音和文件
- 对话上下文保存在内存中，重启后清空（聊天记录持久化到 SQLite）
- AI 输出不构成医疗建议或专业意见
- NapCatQQ 属于非官方方案，可能触发 QQ 风控

## 修改指南（给 AI）

修改 `server.py` 时的注意事项：

1. **消息解析**：使用 `extract_plain_text()` 处理 OneBot 消息数组格式
2. **会话隔离**：私聊和群聊使用不同的 session_id 前缀
3. **频率限制**：通过 `last_reply_at` 字典实现，叠加 `_random_jitter()` 随机延迟
4. **配置读取**：优先 `.env`，回退到 `config.json`（向后兼容）
5. **API 调用**：通过 `ask_ai()` 函数，自动附带对话历史
6. **群聊 @检测**：使用 `mentions_self()` 函数，兼容数组和字符串格式
7. **知识库**：SQLite 数据库，表结构在 `init_db()` 中定义
8. **消息发送**：使用 `send_private_message()` / `send_group_message()`，自动分段、URL 过滤和全局限流
9. **日志**：使用 `logging.getLogger("qq-chat-bot")`，不要用 print
10. **不要硬编码密钥**：所有敏感配置从环境变量读取

## 风控防护（Anti-Fengkong）

修改消息发送逻辑时必须遵守的风控规则：

1. **`_global_rate_limit()`** — 每发送一条消息前必须调用，自动等待并记录全局发送时间
2. **`_filter_urls(text)`** — 在 send 函数中对 AI 回复调用，替换 URL 为文本占位符，避免 QQ 1200 超时拦截
3. **`_is_duplicate(session_id, text)`** — 在 handle 函数中检查，10 秒内相同内容不重复回复
4. **`_user_cooldown(session_id)`** — 在频率限制前调用，对连续快速触发用户施加递增冷却（5 倍封顶）
5. **`_random_jitter()`** — 在频率等待计算中叠加 0~jitter 秒随机延迟，破坏机器人行为特征
6. **`_check_daily_cap()`** — 每次成功发送后调用，80% 日志提醒，100% 警告
7. **分段消息必须有段间延迟** — `send_*_message` 中 for 循环必须在每段之间 `await asyncio.sleep(inter_segment_delay)`
8. **不要绕过全局速率限制** — 所有对外 WebSocket action 都必须经过 `_global_rate_limit()`
9. **新配置项必须有安全默认值** — 新增风控相关配置遵循 `.env.example` 的命名和默认值规范
10. **风控事件记录日志** — 使用 `logger.warning` 记录限流、冷却、URL 过滤等风控触发事件

### 风控参数说明

| 参数 | 默认值 | 作用 |
|------|--------|------|
| `MIN_REPLY_INTERVAL_SECONDS` | 3.0s | 基础回复间隔 |
| `REPLY_JITTER_SECONDS` | 2.0s | 随机抖动范围 |
| `INTER_SEGMENT_DELAY_SECONDS` | 1.5s | 长消息分段间延迟 |
| `GLOBAL_RATE_LIMIT_COUNT/ WINDOW` | 20条/60s | 全局滑动窗口限流 |
| `DAILY_MSG_CAP` | 300条 | 日发送量预警 |
| `URL_REPLACE_MODE` | replace | URL 替换策略 |
| `ESCALATION_COOLDOWN` | true | 渐进冷却开关 |
