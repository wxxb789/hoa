---
name: hermes-discord-tasks-forum
description: "Use when creating or updating Discord forum task posts."
version: 1.0.0
author: Zoe
license: MIT
metadata:
  hermes:
    tags: [discord, forum, tasks, async]
---

# Discord Tasks Forum（#tasks）

## When to Use

- 要建一张跨天任务帖、改帖状态标签、在帖里补结论。
- 需要列出当前 active 任务帖（简报 / 索引 / 忘了哪张在等什么）。
- 排查 Discord forum 的 API 行为（404 / 空数组 / limit 报错）。

Forum channel `#tasks` = `${HERMES_TASKS_FORUM}`（guild `zoe/home` = `${DISCORD_HOME_GUILD_ID}`，configured in `~/.hermes/.env`）。
标签：`wip`/`blocked`/`review`/`done`；标签 id 会随频道重建变化，永远通过 `discord-forum-post.py list` 或 REST 现查，不要硬编码跨会话复用。

## 已装工具

`~/.hermes/scripts/discord-forum-post.py`（读 `~/.hermes/.env` 的 `DISCORD_BOT_TOKEN`，不打印 token）：

- `create "<标题>" --body "<首帖>" [--tag wip]` → 输出 `thread_id` + `url`
- `tag <thread_id> review`（逗号分隔多标签）
- `comment <thread_id> "<text>"`
- `list`（只列 active；forum search 对本 bot 返回空，脚本走 guild 级 active threads）
- `archive <thread_id>` / `delete <thread_id>`（delete 破坏性，已实测删除成功、帖与消息一并消失）

## API 事实（踩过的坑）

- 建帖：`POST /channels/<forum_id>/threads`，body 必须有 `name`（≤100 字符）+ `message.content`；`applied_tags` 是 id 数组；返回 type 11 thread。
- `GET /channels/<forum_id>/threads/active` → **404**。用 `GET /guilds/<guild_id>/threads/active` 再按 `parent_id` 过滤。
- `GET /channels/<forum_id>/threads/search` 对本 bot 恒返回**空数组**（不报错），别拿它判断"有没有帖"。
- `threads/search` 的 `limit` 上限 25，超过返回 `50035 NUMBER_TYPE_MAX`。
- 改标签：`PATCH /channels/<thread_id>` body `{"applied_tags": [...]}`；归档同样走 PATCH `{"archived": true}`，可再 `{"archived": false}` 反悔。
- 帖子 = thread = 独立 Hermes session（session key 带 thread_id），所以帖内对话上下文与 `#work` 隔离。

## 用法约定

- 一个帖 = 一个跨天任务。标题 `[类型] slug | 执行者`，例如 `[dev] funnysharp 0040 | OMP`。
- 首帖第一行给**结论/验收标准**，不要过程；过程留帖内后续回复。
- 状态流转靠标签：`wip` → `blocked`（帖内写卡在哪、要 owner 做什么）→ `review` → `done`。
- 建完必须回报帖链接；不要静默建帖。
- 随手任务不要建帖（`#work` 的 auto-thread 足够），否则论坛退化成正想看板的反面。
- **关帖 = 先分派，再归档**（owner 2026-11-14）：正题完成、帖要 `archive` 时，帖内顺带发现的其他任务**不留在要关的帖里继续做**——按 bot 矩阵派给对的 bot（repo/CI/skill → `forge`；财务 → `gray`；长上下文生产 → `studio`），并在板上另建（或转派）一张跟踪帖，然后才归档原帖。归档前把「谁执行 / 验收标准 / 看进度命令 / 产物路径」写进新帖首帖。
- 派活给 bot 的标准形态（headless，独立于 gateway，可被断连续跑）：
  `systemd-run --user --collect --unit <name> -p WorkingDirectory=<repo> /bin/bash -lc "$HOME/.hermes/hermes-agent/.hermes/bin/hermes -p <profile> chat --query-file <prompt.md> --oneshot -Q > <log> 2>&1"`
  prompt 里必须要求**增量落盘 status**（gateway 断连会杀掉 `hermes chat` 回合，结果只留最后一轮就丢）；断连后用 `--resume <session_id>` 续，不要重发工作。

## 触发策略（owner 2026-11-08 定的 A+B 双触发）

- **自动建帖**：判定跨天即建——有外部等待（CI / review / 他人 / 额度）、跨日交付、或需反复回看。建完必须回报链接，并自动 PATCH `wip → review → done`。
- **口令建帖**：`上板` / `建帖` / `跟踪这条` 一律建，即使判定不跨天；口令高于我的判定。
- **不建**：一次会话内能收尾的随手任务（走 `#work` auto-thread）、纯讨论、纯运维播报。
- 正本在 `~/claw/AGENTS.md` 的「Discord Tasks Board」节；本 skill 只记工具与 API。

## 已接好的自动化（零 token，两层）

1. **`~/.hermes/scripts/morning-decisions.py`（每日 08:30）**：调 `discord-forum-post.py list`；有 `blocked` 的帖作为最高优先级决策行（`[任务] N 张帖在等你：…`），无则静默。
2. **`~/.hermes/scripts/tasks-watch.py` + cron `3d7bdfb194d7`（每 30 分钟，`no_agent`）**：`review` 停留 ≥12h + `wip` 最后活动 ≥48h → 提醒；同帖 24h 内一次；`blocked` 不在本脚本（给 morning 去重）；快照 `~/.hermes/cache/tasks-watch-state.json`；无触发零输出。阈值可用 `TASKS_WATCH_REVIEW_H` / `TASKS_WATCH_STALE_H` / `TASKS_WATCH_COOLDOWN_H` 覆盖（仅供测试）。

两个都是 `no_agent` 脚本：Discord API 调用免费、不起模型回合、token 为 0。
**不要**把它改成 agent 回合或加高频轮询：需要语义判断（"这条消息算不算完成"）的才需要 agent，其余保持脚本，否则每次轮询都烧一个模型回合。

## 标签查询

标签名称（`wip` · `blocked` · `review` · `done`）由 `discord-forum-post.py` 自动从频道 `available_tags` 解析为对应 tag ID，无需硬编码雪花 ID。
