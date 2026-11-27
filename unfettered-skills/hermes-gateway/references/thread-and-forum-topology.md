# Threads and forums as the unit of work

Trigger: "频道不够用了"、"一个频道一个任务"、"记不得哪个频道在跑什么"、要不要给每个项目开频道、
要不要开 auto-thread、要不要用论坛频道。

先量化再设计：`references/channel-usage-audit.md`。本文件只管**拓扑怎么建**。

## 机制：thread 才是 session 边界

Session key（`gateway/session.py: build_session_key`）：

```
agent:<ns>:<platform>:<chat_type>[:<chat_id>][:<thread_id>]
```

`thread_id` 进 key ⇒ **一个 thread = 一个独立 session**：独立上下文、独立压缩、独立 `/reset`、
独立模型覆盖、独立标题。频道则相反：**一个频道 = 一个永不结束的 session**。

所以并发能力来自 thread，不来自频道数量；加频道只是把上下文再切一份，不放宽任何上限。

thread 名（auto-thread 从消息首行取，截 100 字符）= 任务名 ⇒ **首行就是任务标题**。
让 owner 首行写 `[type] slug`（`[dev] funnysharp 0036` / `[fix] dreaming cron`），侧边栏即任务索引。

## 帖里存了什么 vs 每次 run 加载什么

owner 会问的三个问题固定是这个形状：① 每个帖是不是记录了全部上下文？② 每次 run 是不是都加载全部？
③ 帖能有 subthread 吗？答案都不能靠聊天记录推断，要开 `state.db` 与 `config.yaml` 说话。

- **存**：帖 = 一个 session，全部消息（含 `tool_calls`、tool 结果）落 `~/.hermes/state.db` 的
  `sessions` + `messages`，`sessions.thread_id` 就是帖 ID。但**「存」≠「每轮都喂」**；一个帖还会横跨多个
  session（每次重开产生新行，`parent_session_id` 串链）。
- **每轮加载的是三层，不是全量**：
  1. 固定层 —— `SOUL.md` + 项目 `AGENTS.md` + `MEMORY.md`/`USER.md` + skills 索引。与帖无关、每轮注入，
     走 prompt cache（哪一层放什么见 `hermes-context-file-loading`）。
  2. 本 session 历史 —— 到**上下文窗口 50%** 触发压缩：`compression: threshold 0.5 / target_ratio 0.2 /
     protect_last_n 20 / protect_first_n 3`（`config.yaml`）⇒ 保留最近 20 条 + 最早 3 条原文，中间落成摘要
     （`messages.compacted=1`）。长帖里"全部上下文"其实已被摘要替换。
  3. 平台消息回填 —— 帖内因重启/漏读没进 transcript 的消息，adapter 扫回最近
     `history_backfill_limit` 条（本机 config 为 20；未配置时默认 50）拼成 `[Recent channel messages]` 前置。
     **这是平台文本，不含旧 session 的工具轨迹**，所以别用"有回填"证明上下文没丢。
- **会话轮换仍在跑，但靠插件**：内核已不再按定时器轮换会话；本机由 `hermes-session-reset-policy` 插件
  （`~/.hermes/plugins/`，须列在 `config.yaml plugins.enabled`）把 `session_reset`
  （`mode: daily|idle|both`、`at_hour`、`idle_minutes`）重新挂到 `/new reset` 通道 ⇒ 一个帖在每日
  `at_hour` 或空闲超 `idle_minutes` 后换新 session；旧 transcript 留在 `state.db` 可
  `session_search` 取，**新 session 不继承**。所以"帖内历史会不会无限涨"的答案是：涨到压缩阈值→摘要→被
  轮换截断。
- **subthread：Discord 原生没有嵌套 thread。** forum 帖本身就是 thread，帖内不能再开 thread（只有这一层，
  且 forum 内只能是 public thread）。要真父子语义只有 Kanban 卡的 `parent_id`（父卡 + N 子卡，帖 : 卡 =
  1 : 0..N）；帖与帖之间只能靠命名/tag 关联，是约定不是层级。给 owner 的建议框架：帖继续当跨天任务
  容器，子任务落 Kanban 卡，帖内只留结论。

验证（`sqlite3` CLI 不一定装，用 `python3` 的 `sqlite3` 模块读同一文件）：

```python
import sqlite3, os
con = sqlite3.connect(os.path.expanduser("~/.hermes/state.db"))
# 同一个帖（thread_id）下的 session 链：ended_at 非空 = 经历过一次 session_reset
print(con.execute("SELECT id,message_count,input_tokens,ended_at,end_reason FROM sessions"
                  " WHERE thread_id=? ORDER BY started_at DESC LIMIT 5", ("<post_thread_id>",)).fetchall())
print(con.execute("SELECT count(*) FROM messages WHERE compacted=1").fetchone())   # 压缩规模
```

回答这类问题时带上一条本会话的实测行（`thread_id` → `session_id`、`message_count`、`input_tokens`），
比解释机制更有说服力；同时点明"同 profile 其他帖完全看不见这个帖"才是 owner 真正关心的隔离性。

## 选型表

| 需求 | 用 |
|---|---|
| 权限/可见性不同、需要独立 home channel | 单独 channel |
| 一次性派活、当天收尾 | text channel + `auto_thread`（+ `free_response_auto_thread`） |
| 跨天、要状态、要翻旧账、要多任务并列可见 | forum 频道，一帖一任务 |
| 只读播报（cron 输出） | channel + `no_thread_channels` + 不在 `allowed_channels` |
| 某一类工作要换 bot/换上下文 | `gateway.profile_routes`，不是新开频道 |

## Forum channel（type 15）事实

- 帖子就是一个 thread；**标题 1–100 字符，正文 2000 字符**。
- `available_tags` 是**频道级**配置（≤20 个，需要 `MANAGE_CHANNELS`）；每个帖子 `applied_tags` ≤5，
  可在建帖时给，也可 `PATCH /channels/<post_thread_id>` 改。状态（wip/blocked/review/done）用标签，
  不要建 `#todo` `#doing` `#done` 三个频道。
- **不需要 Community**：`features: []`、`premium_tier: 0` 的普通服务器也能建 type 15 并带 tags。
- **发送侧是坑**：往 forum **父频道**发消息 = 每发一次新建一个帖子（adapter `_send_to_forum`）。
  所以 cron / 主动播报**绝不能**指向 forum 父频道，否则每次运行都长出一个新帖；只有锚定在
  thread id 上的会话才安全。
- **接收侧是免费的**：人在 forum 里建的帖子进 dispatch 时是 `chat_type="thread"` +
  `parent_chat_id=<forum>`，而 `allowed_channels` / `free_response_channels` / `channel_prompts` /
  auto-skill 都靠 `parent_id` 匹配 key——把 forum 的 ID 放进 allowlist 即可，不必枚举每个帖子。
- 帖子闲置会自动归档；归档后收到消息会重新激活，session 不受影响（但侧边栏看不到，靠搜索）。
  **主动关帖见下一节**：只打 tag 不等于关。

## 关帖前：这个 thread 还在背什么

关帖不等于改 tag / 归档。一个活了几天的任务帖会攒下**只服务于它**的挂件；archive 之前先清，否则
它们继续往一个已关闭的 thread 里投递，或者把帖子重新顶开。

1. **先查这条 thread 到底做过什么——别只读聊天记录。** thread 是 session 边界，但一个帖子会横跨多个
   session（每次重开/续写产生一个新的 session，`parent_session_id` 串成链），帖内 `read` 只给最近几条。
   直接读 `state.db`：

```python
import sqlite3, os
con = sqlite3.connect(os.path.expanduser("~/.hermes/state.db")); cur = con.cursor()
cur.execute("SELECT id,parent_session_id,title,started_at,message_count FROM sessions"
            " WHERE thread_id=? ORDER BY started_at", ("<post_thread_id>",)).fetchall()
# 再逐 session 取 role='user' 的消息，按 repo / 项目关键词归类成工作流
```

   （`sqlite3` CLI 不一定装；用 `python3` 的 `sqlite3` 模块读同一个文件即可。）归类之后才能回答
   「这帖里有没有不属于本任务的东西」。**判断标准是「在这里被执行的」，不是「在这里被看到的」**：
   工具输出里顺带出现的别的项目的进程列表、状态扫描、另一个 lane 的 OMP run 目录，都属于观察，
   不需要搬；只有真正在这个 thread 里派发/执行的非本任务工作才要迁到它自己的帖子。

2. **清掉以这个 thread 为投递目标的 cron。** deliver 指向单个 thread 的 job 属于 thread-scoped
   machinery：`hermes-cron` 规则 30 —— 跨 root + 所有 profile store 全扫，`remove` 而不是 `pause`。

3. **清残留：** 该 job 的 `~/.hermes/cache/` 状态文件、任务留下的 `~/repos/` worktree 快照目录。
   （删仓库目录算 Red 时先列出来问一句，别顺手删。）

4. **确认没有属于别的任务的结论还挂在这里**：查 `state.db` 的 `delivery_obligations`（`state != 'delivered'`）
   与未终态的 `async_delegations`，两者都清空才说明这个帖子可以安全关上。

做完再走下一节的 archive / lock。

## 关帖：让它真的关上

- 状态用 tag 表达，**关帖 = archive**。但归档很脆：**任何消息都会把归档的帖子重新激活**，包括 agent
  自己的回复，以及运行时把终端/工具活动镜像进帖子的那些消息。只把 tag 改成 `done` 而不管归档，下一次
  发言就把它顶开，owner 会以为你没关（他会重复要求同一次关闭）。
- 要它保持关上必须 **lock**：`locked: true` 后只有持 `MANAGE_THREADS` 的人能重开。调用顺序是
  `archived:false` → `locked:true` → `archived:true`；对已归档的帖子直接改 lock 会被拒：
  `50083 Thread is archived`。
- `auto_archive_duration` 单位为分钟（`60`/`1440`/`4320`/`10080`）。设 `60` 做兜底：即使之后有杂散
  消息把帖子顶开，一小时内自己关回去。
- 收尾说明必须在 **lock 之前**发进帖内——锁定后帖子收不到新消息；kind 是「先帖内给结论，再锁」。

```bash
TID=<post thread id>
PATCH(){ curl -s -X PATCH "https://discord.com/api/v10/channels/$TID" \
  -H "Authorization: Bot $DISCORD_BOT_TOKEN" -H 'Content-Type: application/json' -d "$1"; }
PATCH '{"archived":false}'; PATCH '{"locked":true}'; PATCH '{"archived":true,"auto_archive_duration":60}'
# 读回确认，不要假设
curl -s "https://discord.com/api/v10/channels/$TID" -H "Authorization: Bot $DISCORD_BOT_TOKEN" \
  | python3 -c 'import sys,json;m=json.load(sys.stdin)["thread_metadata"];print(m["archived"],m["locked"],m["auto_archive_duration"])'
```

不要用「发一条消息顺便看看它是不是关了」来验证关帖：那条消息本身就是重开动作。

## 落地前的验证探针

先证明这台机器/这个服务器能建 forum，再围绕它写设计（token 从 `~/.hermes/.env` 读，
**绝不打印**）：

```python
# POST /guilds/<guild>/channels  {name, type: 15, parent_id, available_tags:[{name, emoji_name}]}
# → 断言返回 type == 15，打印 available_tags 的 name/id；随后 DELETE /channels/<id> 复原
```

再验接收侧（只有 owner 能做）：请他建一个帖子，确认 sessions 里出现 `thread_id=<post_id>` 的行、
`chat_id` 也是 post id、且回复落在帖内而不是频道里。这两条过了再谈配置切换。

## 反模式，要当面说出来

**"channel = 任务槽"** 的症状是三个：槽位有限（于是不断开新频道）、上下文互染（新任务继承旧任务的
几 M token）、无法归档（只能 `/reset` 阉割）。修法是 thread/post-per-task，不是更多频道。

对 owner 的一句话框架（他听得懂且能自己判断）：

> channel = 稳定的上下文/权限边界；thread = 一次执行；forum 帖 = 一个持久工作项。

社区共识与命名法（状态前缀 + slug + 单一索引）见 `references/channel-topology-research.md`。

## Pitfalls

- 连发多条顶层消息会各开一个 thread；补充信息用**回复**，否则任务碎片化。
- 打开 thread 后，旧频道 session 不再续写；旧历史仍在 `state.db`，用 `session_search` 取。
- 删频道是 Red：先改名 `zz-*` 观察一段，再删。配置类改动可逆，删频道不可逆——但不可逆的只有 **Discord 侧消息**
  （机器侧 transcript 仍在本 profile 的 `state.db` 里，删频道不影响 `session_search`），所以别把「历史会丢」当成不删的理由。
  删除前跑 `references/channel-usage-audit.md` → **退役前四问**（最后一条消息时间 / cron 投递 / `config.yaml`+`.env` 引用 /
  各 profile 会话数），报告里给分级选项让 owner 按号回，删除动作留他或他明确一句授权后再动。
- 别让 agent 自动建频道。允许它建 thread / 论坛帖，不建频道。
