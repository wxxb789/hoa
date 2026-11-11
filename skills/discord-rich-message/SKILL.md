---
name: discord-rich-message
description: >-
  Send structured tables and reports into Discord within its real limits: Components V2 payloads,
  monospace aligned tables, and the attachment fallback. Use when a plain Discord message would show
  raw pipes or truncate. Discord only — other platforms have their own rich-message systems.
metadata:
  version: "0.1.31"
  areas: "software-development,work-management"
  targets: "runtime-agnostic"
  summary: "structured Discord messages within platform limits: Components V2, aligned code-block tables, attachment fallback"
  summary_zh: "在平台限制内发送结构化 Discord 消息：Components V2、等宽对齐表格、附件兜底"
  kind: "entry"
---

# Discord Rich Message (Components V2)

## Platform scope — HARD BOUNDARY

**Discord ONLY.** Components V2 (`flags: 32768`) is a Discord-private message
protocol. It does **not** exist on other platforms.

- ❌ Feishu (飞书) → has its own **interactive card** / markdown-module system. Use that, never this.
- ❌ Slack → Block Kit. ❌ Telegram → its own entities/HTML. ❌ Email → real HTML/Markdown.
- ✅ Only emit this payload when the target is a **Discord channel id**.

If a task spans multiple platforms, render Discord with this skill and render each
other platform with its own native mechanism. Never copy the V2 payload across platforms.

## Why this exists

Discord's plain message body renders only a **subset** of Markdown. It does **not** render:
- tables (`| a | b |`) → shows raw pipes
- horizontal rules `---`
- inline links `[text](url)` (anti-phishing; intentional, won't change)
- `####`+ headings, deep nested lists

So for any **structured / tabular** output to Discord, do NOT send a Markdown table.
Send a **Components V2** message (verified to render cleanly, including an accent
bar + divider + monospace aligned table), or attach a file when the content
outgrows the text budget.

## Discord's limits (the constraints the sender must enforce)

| Constraint | Value | Consequence |
|---|---|---|
| Plain message `content` | 2000 characters | Split or switch to Components V2 |
| Combined text across V2 components | 4000 characters | Split into several messages, or attach a file |
| Total components per message | 40 | One Container + a few Text Displays is the common shape |
| `content` / `embeds` fields with V2 | Not allowed | Text must live in `type 10` Text Display blocks |
| Attachments with V2 | Not shown by default | Upload via multipart `files[n]` and expose each with a `type 13` File component (or a Media Gallery for images) |
| Upload size | The guild tier's cap (25 MiB default) | Compress or link externally above it |
| Markdown tables | Never rendered | Put the aligned table inside a fenced code block |

The 2000-character limit applies to the legacy `content` field only; a V2 message
has no `content`, so the binding limit there is 4000 characters of combined text.
Count Unicode code points after your alignment padding, not bytes.

## The sender contract

Use a sender wrapper that implements this contract; write one when the host has
none. In the examples below, `discord-send` stands for such a wrapper. The wire format is a single
`POST /channels/{channel_id}/messages` with
`Authorization: Bot $DISCORD_BOT_TOKEN` (or a webhook URL). The wrapper should:

- require `--channel <id>` explicitly — no implicit default, so a report never lands in the wrong
  channel;
- accept `--table-tsv`, `--table-json`, or `--table-md` (a Markdown table file or stdin →
  auto-converted), plus `--text` for a plain body and `--file <path>` for the attachment flow;
- set `flags: 32768` itself, build the Container, and validate the two text budgets before sending;
- print `OK message_id=... channel=...` on success; on failure print `API_ERROR {...}` to stderr and
  exit non-zero (2 usage, 3 API, 4 no token) so a caller can branch;
- offer `--dry-run` to print the payload without sending.

Design decisions worth keeping:
- **Width-aware alignment**: CJK/fullwidth/emoji counted as width 2, so 中英混排
  tables stay aligned inside the code block.
- **Explicit channel**: required, as above.
- **Token hygiene**: read the token from the environment or a secret store; never
  log it, and redact it in curl reproductions.

## Resolving a channel id

Never hard-code ids from one server; they differ per guild and change when a
channel is recreated. Resolve a name → id from the guild's channel list once per
task, then use the id:

```bash
curl -s -H "Authorization: Bot ${DISCORD_BOT_TOKEN}" \
  "https://discord.com/api/v10/guilds/${DISCORD_GUILD_ID}/channels" \
  | python3 -c 'import sys,json
for c in json.load(sys.stdin): print(c.get("name"), "->", c.get("id"))'
```

If a send returns 404 `Unknown Channel`, re-list rather than reusing the stale id.

## Usage shapes

```bash
# 1) TSV table (first row = header). \n between rows, \t between cells.
discord-send --channel <id> --title "本周指标" \
  --table-tsv $'指标\t本周\t上周\t变化\n启动耗时\t1.2s\t1.8s\t↓33%\n错误率\t0.4%\t0.9%\t↓56%'

# 2) Convert an existing Markdown table file (or stdin with '-')
discord-send --channel <id> --title "Report" --table-md report.md
cat report.md | discord-send --channel <id> --title "Report" --table-md -

# 3) JSON rows
discord-send --channel <id> --title T --table-json '[["a","b"],["1","2"]]'

# 4) Plain text inside the V2 container (bold/italic/inline-code work; tables/links don't)
discord-send --channel <id> --text "**deploy done** see logs"

# 5) Attachment flow: long report as a file, exposed through a File component
discord-send --channel <id> --text "Full report attached" --file report.html

# Inspect payload without sending:
discord-send --channel <id> --title T --table-tsv $'a\tb\n1\t2' --dry-run
```

## Components V2 payload shape (reference)

```json
{
  "flags": 32768,
  "components": [
    { "type": 17, "accent_color": 5814783, "components": [
      { "type": 10, "content": "**Title**" },
      { "type": 14, "divider": true, "spacing": 1 },
      { "type": 10, "content": "```\naligned table here\n```" }
    ]}
  ]
}
```
- `type 17` = Container (accent bar). `type 10` = Text Display. `type 14` = Separator.
- `type 13` = File, which exposes one uploaded attachment (`{"type": 13, "file": {"url": "attachment://report.html"}}`).
- `flags: 32768` = `1<<15` = IS_COMPONENTS_V2. **Required**, else Discord rejects/ignores components.
- When V2 flag is set, you CANNOT also send a plain `content` field — content must live in `type 10` blocks.
- Attachments are sent in the same multipart request (`files[0]` plus an `attachments` array), not as a URL by default.

## Pitfalls

- **Omitting `flags: 32768`** → components silently ignored / 400. The sender sets it for you.
- **CJK misalignment** if you hand-roll padding with `len()`; always count fullwidth as 2.
- **Length limits**: plain `content` ≤ 2000 characters; V2 combined text ≤ 4000; ≤ 40 components.
  The sender validates and tells you to split — split at row boundaries, not mid-table.
- **Wrong channel**: `--channel` is required on purpose. Re-list ids if you get a 404.
- **Old/embedded clients** may degrade V2 rendering; the monospace code block still reads fine as fallback.
- **Attachments are hidden unless exposed**: uploading a file is not enough under V2; add a File or
  Media Gallery component or the file will not appear.
- **Token hygiene**: never echo `DISCORD_BOT_TOKEN`; the sender reads it internally. When debugging
  with curl, redact it.

## Verify

After sending, the API returns a `message_id`. To confirm rendering, ask the user to
look at the channel (the agent cannot see Discord visually). Keep one self-test message
or delete test messages with:
```bash
curl -s -X DELETE -H "Authorization: Bot ${DISCORD_BOT_TOKEN}" \
  "https://discord.com/api/v10/channels/<id>/messages/<message_id>"
```
