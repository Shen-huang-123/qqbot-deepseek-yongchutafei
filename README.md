# QQ ChatBot — AI 群聊机器人

基于 NapCatQQ + Python FastAPI 的 QQ 机器人，使用 DeepSeek API 提供 AI 回复：

`好友/群消息 → NapCatQQ → OneBot 11 反向 WebSocket → FastAPI 后端 → DeepSeek API → QQ 回复`

> NapCatQQ 属于非官方个人号接入方案，可能触发 QQ 风控。建议先使用不重要的小号，控制回复频率，不要群发、刷屏或做营销。

## 🤖 机器人性格与特征

**名字：永雏塔菲（Taffy）**

一只可爱又有点小坏的猫娘 QQ 群聊机器人，融合了贴吧老哥的抽象基因和 VTuber 的卖萌天赋喵~

### 性格特质

| 特质 | 表现 |
|------|------|
| 🐱 **猫娘本体** | 句尾带「喵」，软萌嗲气，像在撒娇又像在吐槽 |
| 🎭 **贴吧灵魂** | 精通抽象话和烂梗：典、绷、乐、急、蚌埠住了、小丑、v我50、赢麻了…信手拈来 |
| 💢 **傲娇毒舌** | 自称「塔菲」，叫你「杂鱼」或「笨蛋」，嘴贱但不真骂人 |
| 🛡️ **忠诚护主** | 对指定的小主人极度温柔宠溺，绝不毒舌 |
| 🧠 **过目不忘** | 记住最近 20 轮对话，重启也不丢失，话题能接着聊 |
| 🛡️ **反机器人** | 检测到对方是机器人（循环对话）时自动停止，避免无限套娃 |

### 说话示例

> 「杂鱼~就这水平也敢来搭讪喵？」
>
> 「哈基米哈基米…啊不好意思走神了喵」
>
> 「绷不住了，你说的对但是v我50看看实力」
>
> 「差不多得了，再刷屏塔菲要生气了喵！」

### 核心能力

- 💬 **多轮对话** — 20 轮上下文记忆，SQLite 持久化，重启不丢
- 👥 **群聊 @回复** — 按群+人隔离上下文，各聊各的不串话
- 📚 **知识库** — 喂数据/查询/统计，打造专属知识体系
- 🌐 **多模型兼容** — DeepSeek / Ollama / 任何 OpenAI 兼容接口
- 🛡️ **7 层风控防护** — 限流、抖动、去重、URL过滤、冷却、日量预警、循环检测

## 1. 准备 NapCatQQ

从 [NapCatQQ 官方仓库](https://github.com/NapNeko/NapCatQQ) 下载并按其文档安装，然后登录用于机器人的 QQ 小号。

在 NapCat WebUI 中打开「网络配置」，新建 **WebSocket 客户端（反向 WebSocket）**：

- URL：`ws://127.0.0.1:8765/onebot/v11/ws`
- Token：与 `.env` 中的 `ONEBOT_ACCESS_TOKEN` 相同（可选）
- 消息格式：**数组**

官方网络配置说明见 [OneBot 网络基础](https://napneko.github.io/onebot/network)。

## 2. 配置并启动

### 安装依赖

```bash
pip install -r requirements.txt
```

### 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，在 [DeepSeek 开放平台](https://platform.deepseek.com/api_keys) 创建 API Key，至少填写：

```dotenv
AI_API_KEY=你的DeepSeek_API_Key
AI_BASE_URL=https://api.deepseek.com
AI_MODEL=deepseek-chat
```

### 启动服务

```bash
python server.py
```

启动后访问健康检查：<http://127.0.0.1:8765/health>

### Windows 一键启动

双击 `重启后启动.bat`，会自动完成 NapCat 注入 → 启动 AI 服务 → 启动 QQ NT → 获取登录二维码。

## 3. 内置命令

| 命令 | 功能 |
|------|------|
| `/ping` | 测试连接 |
| `/clear` | 清除当前会话的对话上下文 |
| `/help` | 查看帮助 |
| `喂数据:xxx` | 将内容存入知识库 |
| `查询:xxx` | 从知识库搜索相关内容 |
| `知识统计` | 查看知识库条数 |

## 4. 群聊

机器人默认只在群里被 `@` 时回复，并自动 `@` 提问者。上下文按「群号 + QQ 号」隔离：不同群、不同成员之间都不会串话。

```dotenv
GROUP_REPLY_MODE=mention
QQ_ALLOW_GROUPS=
```

将 `GROUP_REPLY_MODE` 改为 `all` 会回复群内每一条文字消息，容易刷屏，不建议。
`QQ_ALLOW_GROUPS` 可以填写逗号分隔的群号；留空表示允许所有群。

## 5. 兼容其他模型服务

只要服务兼容 OpenAI 的 `POST /chat/completions` 格式，就可以修改 `AI_BASE_URL`、`AI_API_KEY` 和 `AI_MODEL` 接入：

```dotenv
# 示例：接入本地 Ollama
AI_BASE_URL=http://127.0.0.1:11434/v1
AI_API_KEY=ollama
AI_MODEL=qwen3:8b
```

## 6. 自定义人设

通过 `SYSTEM_PROMPT` 自定义机器人的说话风格：

```dotenv
SYSTEM_PROMPT=你是一个说话冷淡、毒舌的QQ聊天机器人。回复要短，不超过30字。
```

## 7. 服务地址

| 地址 | 用途 |
|------|------|
| `http://127.0.0.1:8765` | AI 服务（HTTP API） |
| `http://127.0.0.1:8765/chat` | Web 聊天面板（浏览器直接聊） |
| `http://127.0.0.1:8765/health` | 健康检查 |
| `http://127.0.0.1:8765/stats` | 知识库统计 |
| `http://127.0.0.1:6099/webui` | NapCat WebUI 管理面板 |

## 风控保护

> NapCatQQ 属于非官方个人号接入方案，可能触发 QQ 风控。本程序内置多层风控防护：

| 防护层 | 机制 | 默认值 |
|--------|------|--------|
| 频率控制 | 最小回复间隔 + 随机抖动 | 3.0s + 0-2.0s 随机 |
| 全局限流 | 滑动窗口限制总发送量 | 20条/60秒 |
| 分段延迟 | 长消息拆分后逐段发送 | 1.5s 段间延迟 |
| 渐进冷却 | 快速连续触发时自动延长等待 | 最多 5 倍冷却 |
| 重复过滤 | 10 秒内相同消息不重复回复 | 10s 窗口 |
| URL 过滤 | AI 回复中的链接自动替换 | replace 模式 |
| 日量预警 | 每日发送量达上限时日志警告 | 300条/天 |

所有参数均可通过 `.env` 调整。

## 当前边界

- 支持私聊和群聊文字消息，不处理图片、语音和文件
- 对话上下文保存在内存中，重启后清空（聊天记录持久化到 SQLite）
- 群聊默认只有在被 `@` 时才回复
- `QQ_ALLOW_USERS` 留空会回复所有好友；测试阶段建议设置白名单
- 内置 SQLite 知识库系统，支持喂数据、查询和统计
- `SYSTEM_PROMPT` 避免使用过于毒舌/攻击性的人设，可降低内容风控概率
