---
name: hermes-gateway
version: 2.0.0
description: "Use when managing the Hermes gateway, profiles, or channels."
author: Zoe
license: MIT
metadata:
  hermes:
    tags: [hermes, gateway, profiles, bot-mode, discord, feishu, channels]
---

# Hermes Gateway, Profiles, Channels

## When to Use

| You hear / see | Load |
|---|---|
| "重启一下 gateway"、gateway 挂了 / 卡住 | restart discipline (below) |
| bot 在某个平台不回、连上又断 | `references/messaging-channels.md` |
| 频道已路由/allowlist 但零响应、日志无痕 | `references/messaging-channels.md` |
| 频道静默：adapter connected、config 看着对，但消息被静默丢（`.env` 盖过 config） | `references/silent-channel-triage.md` |
| "对话全停了"、bot 只回「This conversation is paused」、网关莫名重启 | `references/oom-pressure-and-paused-sessions.md` |
| 这个 profile 怎么像换了个 agent | `references/profiles-and-identity.md` |
| profile 继承了别的 bot 的身份 / 技能是符号链接 / 白名单要改 | `hermes-profile-independence` |
| 加频道 / persona / bot profile、Bot Mode | `references/bot-mode-cli.md` |
| 主动消息落错 chat、home channel | `references/messaging-channels.md` |
| `Discord bot token already in use` | `references/messaging-channels.md` |
| `Maximum number of application commands reached` | `references/discord-slash-command-sync.md` |
| `session_reset … no longer applied` | `references/messaging-channels.md` |
| 设计/审计 profile 阵容（要不要拆、拆几个） | `references/profile-roster-audit.md` |
| "我需要哪些 channel"、频道冗余/缺失、上下文老是断 | `references/channel-usage-audit.md` |
| "这些旧频道能删了吗"、退役 / 清理已经改名隔离的频道 | `references/channel-usage-audit.md` → 退役前四问 + 删除动作本身 |
| "一个频道一个任务、频道不够用了"、记不清哪个频道在跑什么、要不要开论坛频道 | `references/thread-and-forum-topology.md` |
| "帖子是不是记了全部上下文"、"每次 run 都加载全部吗"、"帖能有子帖 / subthread 吗" | `references/thread-and-forum-topology.md`（帖内上下文经济一节） |
| WebUI sidecar | `references/webui-sidecar.md` |
| 多个 thread / DM 停住不回、bot 只回一句 "⏸️ This conversation is paused" | `references/paused-conversations.md` |
| 一批 thread 标题还是原样（`https://…` / `Analyze … post by …`）、像刚开了没下文 | `references/paused-conversations.md` → *Batch repair* |
| 并发上限 / 入站被回 "at the active session limit (N/M)" | admission cap bullet under restart discipline |

**Not for**: upgrade mechanics → `hermes-updates`; cron delivery targets → `hermes-cron`;
per-profile providers/models → `hermes-models`.

## Restart discipline

- A CLI session can itself be a gateway child: `cat /proc/self/cgroup` (ends in
  `…/hermes-gateway.service` → you are inside) and `ps -o ppid= -p $$` vs
  `systemctl --user show -p MainPID hermes-gateway.service`.
- From inside that cgroup `hermes gateway restart` is refused, and a restart that lands kills the
  in-flight turn. Schedule it from a detached unit and let the unit verify:
  `systemd-run --user --collect --unit=gw-cycle-$(date +%H%M%S) --on-active=40 /usr/bin/python3 ~/.hermes/scripts/gw-restart-verify.py`
- Answer immediately and hand over the verdict path; never promise a post-restart check in the same turn.

- **A `hermes chat` dispatch is a gateway child, not an independent process.** Backgrounding
  `hermes chat --query-file f --oneshot -Q` keeps the *process* alive but its turn still runs through the
  gateway, so a scheduled restart lands mid-run and the log ends with `Gateway disconnected; turn outcome
  is unknown` plus a resumable session id. Assume the work is half-done, not lost: the tool writes it
  performed are on disk and a repo auto-sync may already have committed them — reopen the tree, diff
  against the task spec, and finish the remainder yourself instead of re-dispatching the whole job. Either
  serialize a restart against long dispatches, or run the dispatch under `systemd-run`/tmux so the process
  outlives your session — but **that buys independence from the session, not from the gateway's turn
  transport**: units launched with `systemd-run --user --collect` still die mid-turn with the same
  `Gateway disconnected; turn outcome is unknown` line while the gateway process itself has been up for
  hours (its log then shows `tui_gateway.ws … WebSocketDisconnect`), because the turn runs through the
  gateway whatever hosts the process.
- **A dispatch batch dies unit by unit, and each unit holds its own session id.** Because `-Q` writes its
  log only at completion, a log holding nothing but the error plus `session_id` is the failure signature,
  and an empty log is not health. Transient `--collect` units vanish from
  `systemctl --user list-units --all` once they exit, so "unit gone + no artifact on disk" is the verdict
  to act on: audit every sibling of the batch, then resume each with a check-and-continue prompt
  (`hermes -p <profile> chat --resume local-<id> --query-file <check-prompt> --oneshot -Q`, itself launched
  detached) rather than re-dispatching the work.
- **Author the dispatch prompt for a mid-turn kill, not for a clean exit.** `-Q` prints nothing until the
  turn ends, so a prompt whose only output is the final answer loses everything when the transport drops.
  Require the agent to append to a `status.md` (or equivalent) in the task dir after each step, and to
  print artifact paths + verdict as its last line; a resumed run then reads its own file and continues
  where it stopped. Shape:
  `systemd-run --user --collect --unit <name> -p WorkingDirectory=<repo> /bin/bash -lc
  "$HOME/.hermes/hermes-agent/.hermes/bin/hermes -p <profile> chat --query-file <prompt.md> --oneshot -Q
  > <task>/logs/<name>.log 2>&1"`.
- **Look for a resume before you re-dispatch.** A sibling session may already have picked the batch up: a
  `-r2`/`-rN` unit name or log beside the original, plus a task artifact whose mtime is newer than the
  failure, is that evidence. Re-launching on top double-runs the work and races the shared tree.
- **A resumed dispatch keeps its delivery binding: the gateway posts the turn's final answer into the
  origin chat/thread by itself.** So a resume prompt whose wrap-up also says `hermes send -t <platform>:<chat>
  "<report>"` delivers the report **twice**. Author it as "make the final answer BE the report, then read
  the chat back (`messages?limit=2`) to confirm it landed; only send if the read-back does not show it".
- **Platform sends from a session shell scoped to a profile home need `env -u HERMES_HOME`.** A per-home
  `.env` carries no platform token, so `hermes send -t discord:<id>` fails with `Platform 'discord' is not
  configured … this shell is scoped to profile home …` — that is the scoped home missing credentials, not a
  disconnected platform. Run it as `env -u HERMES_HOME hermes send …` (falls back to the root home's `.env`);
  read messages back with an interpreter that has `python-dotenv`, or the read-back itself fails with
  `ModuleNotFoundError: dotenv` and looks like a second, unrelated problem.

- **The lifecycle guard scans the text of whatever the unit executes.** A command that stops or restarts
  the gateway is refused from inside the gateway (`Blocked: … cannot restart, stop, or uninstall the
  gateway from inside the gateway process`), and wrapping a shell script in `systemd-run --on-active` does
  not hide it — the referenced script is scanned too. The shape that passes is a **Python** script whose
  `subprocess.run(["systemctl", "--user", "stop|restart", "hermes-gateway.service"])` is triggered by the
  detached unit (that is exactly how `gw-restart-verify.py` works). Keep such a wrapped command free of
  `/dev/null` and other non-regular files: the same scanner rejects them before running anything.
  Regenerate `config-snapshot.py` **before** scheduling. The scheduled unit writes
  `~/.hermes/cache/scratch/gw-restart-report-<ts>.md`; read that file back and quote its verdict fields
  instead of paraphrasing health — old pid → new `MainPID`, `code_sha` vs installed HEAD,
  `served_profiles` (name the count, not "all"), each required platform `connected`, "lines from the new
  gateway pid that look wrong: 0", the model one-shot probe, and the final PASS/FAIL line. A cutover or
  config change that touches per-home `model.*` is only live on the bot side after this restart lands —
  say that explicitly and use a 60 s delay when the reply itself must be delivered first.
- Judge health from `gateway_state.json` (`pid` == new MainPID, required platforms `connected`; ignore
  stale `api_server: retrying`), not from a log slice. "Restarted" ≠ "on the new build": compare
  `code_sha` with `git rev-parse HEAD`; identical code ≠ identical runtime (plugin pins and skill content
  load at process/session start).
- **Date owner-reported errors across the restart window.** An error the owner received around a
  scheduled restart may have been minted by the OLD process (its env/config was loaded at ITS start):
  compare the attempt's timestamp with `systemctl --user show -p ActiveEnterTimestamp` before
  diagnosing the new process. An unauthorized-slash or pairing-style reply from seconds before the
  new process came up is a stale-env artifact — ask for a fresh plain-text test instead.
- **A config edit is not a live change.** `profile_routes`, adapter enables, home channels and
  `skills.disabled` are read when the process/adapter starts, so removing a route leaves the old routing
  **still live** until the next restart. When the owner says "defer/undo that", either schedule the
  restart now and say the old behaviour persists until it lands, or state plainly that the change is
  pending — never imply the revert is already in effect because `config get` shows the new value.
  **But classify the key before answering "does this need a restart?" — the turn budgets are live on the
  next turn, so a restart there is pure waste.** The gateway re-bridges `agent.max_turns` (+ `sessions.*`)
  from `config.yaml` at the start of every turn (`gateway/run.py:_current_max_iterations()` →
  `_reload_runtime_env_preserving_config_authority()`), precisely so a stale `HERMES_MAX_ITERATIONS` in the
  process env cannot win. Read site is the verdict: adapter/routing/`skills.disabled` keys are start-time;
  `agent.max_turns` and its sibling budget keys are per-turn. Do not schedule a restart, and do not ask the
  owner for one, to make a budget change take effect.
- **`max_concurrent_sessions` is the only admission gate — and it REJECTS, it does not queue.** Over the
  cap, the inbound gets an in-thread reply (`Hermes is at the active session limit (N/M) … Try again when
  another session finishes`) and is **never stored**, so nothing resumes it later; the thread simply looks
  untouched. Two properties decide the plan: the cap is read at **process start** (restart-only key, unlike
  the per-turn budget keys above), and the slot registry is **shared across gateway turns, CLI runs and
  Desktop** — so a lane of `hermes chat --resume` children holds the same N slots, and setting the cap
  while that lane runs makes the lane reject *itself*. Size it as `lane concurrency + interactive
  headroom` (roughly 2× the lane) and apply it only once the lane has drained. Rejected inbounds are not
  lost forever provided a recovery lane exists that can rebuild a thread with **no session row at all**
  (`references/paused-conversations.md` → *Batch repair*, class "never ingested").
- **Before asking the owner to restart, check whether one already happened after your write.** A restart
  you did not schedule can land while you are still editing: compare
  `systemctl --user show -p ActiveEnterTimestamp hermes-gateway.service` and `gateway.pid`'s `start_time`
  with the mtime of every file you changed. A process that started later already serves the new value, and
  asking for `/restart` spends the owner's single action on a no-op and blocks a turn waiting for an
  approval that should not exist. Prove what the live process holds by reading its environment
  selectively — recipe in `references/gateway-restart.md`.
- **A restart that lands mid-turn eats that turn's closing reply.** Its tool calls ran and their artifacts
  are on disk, but the turn is fenced `unknown_execution` (`Native session startup recovery …`) and the
  session surfaces as `Session … paused: unknown_execution`; the owner receives **nothing** — silence, not
  an error. So checkpoint long builds (artifacts on disk + a short interim message up front) instead of
  betting the deliverable on one closing report, and when the owner says "你没告诉过我 / 再问我一遍",
  verify what was actually delivered before re-asking: `references/paused-conversations.md`.

## Profiles

- Each profile is its own `HERMES_HOME`: only its own `SOUL.md`, `memories/`, `skills/`, `.env`. Nothing
  inherits from root.
- **Identity is owned per home, not generated.** `profiles/<p>/SOUL.md` is that bot's authoritative
  file and is meant to be edited; there is no root-plus-delta generator any more. The only shared part
  is the `core-invariants` block pinned at **byte 0**, verified by byte-prefix comparison. Repo-owned
  (`*-nrs`) homes compile their SOUL from the repo instead. After any home-topology move, the skill why and how: `hermes-profile-independence`.
- **Skills are real per-home copies, not symlinks.** Only `profile.yaml: allowed_skills` is
  materialized (managed copies 0444/0555; `evolvable_skills` for deliberate forks). Change the surface
  by editing that list, then `python3 ~/.hermes/scripts/profile-skill-materialize.py --apply
  [--profile <p>]`; verify with `--check` and `python3 ~/.hermes/scripts/profile-layer-reconcile.py
  --dry-run` (silent when healthy). Never hand-place a skill directory into a home — the next
  materialize deletes it. A surviving symlink in `profiles/<p>/skills/` means that home was not migrated.
- Drift symptoms: an owned skill missing in one profile, skill sets differing in both directions, cloned
  `model_aliases` pointing at retired ids, a cloned `terminal.cwd` that stops a context file from loading.
- **A profile's working directory is three anchors, not one.** `terminal.cwd` only decides where a *new*
  session opens. An existing session — the eternal Bot Chat included — resumes at the `cwd` stored in
  `profiles/<p>/state.db` (`sessions.cwd`), and the Desktop project picker reads `profiles/<p>/projects.db`
  (`project_meta.active_id` → `projects.primary_path`). `session.resume` consults the stored row before the
  profile default, so a stale row silently wins: moving a bot to a repo is `terminal.cwd` + `projects.db` +
  every stored session + each cron job's `workdir`, and fixing one leaves the old chat reading `~/claw`.
  Probe with `hermes -p <p> --in <dir> -z "run pwd and reply with only its output"`.
- **The local terminal backend ignores `terminal.cwd` for CLI one-shots.** With `terminal.backend: local`
  the config loader overwrites the cwd with `os.getcwd()`, so `hermes -p <p> -z …` runs in the caller's
  directory whatever the profile says. Always pass `--in <dir>` for one-shots and probes; scheduled jobs
  (`workdir`) and Desktop/gateway sessions (`terminal.cwd`) are unaffected.
- Multiplex: secondary profiles pin the shared platform OFF with a **top-level** `<platform>: {enabled:
  false}` (not `platforms.<platform>`). `Platform 'discord' is explicitly disabled … will NOT start its
  adapter` is the dedup working — removing the pin creates a duplicate-token conflict.
- **Renaming a bot is an in-place metadata edit, never a migration.** Change `profile.yaml`
  (`description`, `ui_meta.hermes-bots.title/section`) and update that home's own `SOUL.md` (or, for a
  repo-owned `*-nrs` bot, its role file in the repo). Do **not** create a new directory and copy
  files in: the directory name is the storage key for sessions, `memory_store.db`, cron and desktop
  identity, so a "clean" profile silently loses the history that justified keeping the bot. After the
  rename the roster shows the new title while every command still takes the old directory name
  (`hermes -p <dir>`); record that mapping in the instruction file and verify with an identity probe
  (`hermes -p <dir> -z`), never by reading the title back.
- **Deleting a profile takes two passes.** `rm -rf profiles/<p>` right after a session makes the running
  gateway recreate the home (its cron ticker still holds the boot-time reserved set, and a directory that
  exists is served again). Then the dir feeds itself: recreated → served → recreated. Correct order: delete
  → immediately ask the control socket for `rescan-profiles`
  (`gateway.control_socket.rescan_gateway_profiles(get_default_hermes_root())`, answer lists the new
  `served_profiles`) → wait ≥60s → if the directory came back, delete it again now that the served set no
  longer contains it → verify with `ls` + `gateway_state.json` `served_profiles`.
- **Deleting leaves residue that breaks naive audits.** `hermes profile delete <p> -y` moves the profile to
  `profiles/.deleted/<p>` and leaves the wrapper alias behind; an interrupted delete can also leave an empty
  `profiles/<p>/`. So: `hermes profile alias <p> --remove` for each retired name, and every script that
  iterates `profiles/*` must skip dot-directories **and** directories without `config.yaml` — otherwise a
  healthy fleet reports "profile missing config" / "unknown profile" forever. After a delete, re-run the
  drift checker and `profile-layer-reconcile.py` (skill symlink count changes).

## Profile roster: audit before proposing

- Audit evidence first: session counts **and titles** (smoke tests like `Reply with exactly: OK`,
  `PROBE_*` mean the bot never did real work), which profile owns which cron, `hosted_rooms`,
  `skills.disabled` parity across profiles, per-profile `memory_store.db` fact counts.
- A profile earns existence only by differing on ≥1 of: context, tools, permissions, model, failure mode,
  acceptance test, independence/parallelism — plus a canonical destination directory. A recurring
  routine is required only when the work has a real time trigger; task-triggered roles run on demand.
  Everything else is a skill, a routine, or nothing.
- Never make "fewer profiles" the goal; state the criterion before proposing cuts or it reads as tidying.
- Keep the front door separate from the builder: a profile that routes daily work and also does long
  repo/engineering work pollutes its own context. Tone tweaks belong in prompt overlays.
- Empty roster entries are the normal failure mode (zero routines + zero real sessions + no destination):
  report them as measured evidence, not opinion.
- A "30 days idle → retire" rule must subtract profile age: a profile materialized yesterday has zero
  sessions by definition. Compare the window against `config.yaml` mtime (creation) before calling a bot
  dead, or every new role starts life as a retirement candidate.
- A **project-local matrix** (one repo or project needs several bots) splits on write surface and
  acceptance test, never on pipeline stage: each bot owns disjoint paths plus one acceptance gate, and
  fan-out lanes stay cards/subagents. Definitions for that matrix live in the project repo and are
  materialized into profiles — `references/repo-owned-bot-definitions.md`.
- **Retiring a role ≠ merging it.** A role whose only product is *independent verification* (an auditor,
  a reviewer, a control-plane steward) exists because the generator cannot grade itself: deleting its bot
  removes the gate even if its write surface is reassigned on paper. Either keep the bot, or add the real
  substitute in the same change (a read-only pass on a different model family, invoked as a step with a
  recorded verdict) and update the role contract. Audit evidence that a verifier "has no sessions and no
  enabled routine" is not evidence it is idle when the matrix is minutes old — a role materialized today
  has zero runs by definition.
- **A public channel per bot is `gateway.profile_routes`, not a second token** — but a route can only point
  at a channel the bot can already see; and routing the install's only home channel to a specialist bot
  silently takes that platform away from the front door. Say that out loud before the owner agrees.
- Carrying out a split (new builder profile, model pin, SOUL overlay, skill trim, job attribution):
  `references/profile-roster-audit.md` → *Execute the split*.

## Channels and delivery

Two meanings the owner conflates:

1. **Per-job delivery** — no config change: `deliver='<platform>:<chat_id>'`, or create the job from the
   target chat and leave `deliver` empty.
2. **Global gateway default** — `<PLATFORM>_HOME_CHANNEL` in `.env` (per profile); needs a restart.

A third, distinct one: **one channel → a different profile** (a `#research` channel answered by the
research bot while every other channel stays on the front door). That is `gateway.profile_routes`, not a
second bot token — recipe, specificity table and Feishu caveats in
`references/channel-to-profile-routing.md`. Restart required; verify by persona, not by logs.

Convention here: system/ops cron → `#dashboard` (`discord:${HERMES_DASHBOARD_CHANNEL_ID}`, one-way, deliberately not
in `discord.allowed_channels`); personal reminders / briefs / career → DM home.

- **过程噪声按 home 在 config 层关，不要在 prompt 里叮嘱模型少说话。** `display.tool_progress`
  （`all` | `grouped` | `off`；`off` = 完全不推每条 tool call 的进度气泡）是 gateway 读取的
  per-user/per-platform 键，**不在 CLI 的 config schema 里**，所以 `hermes config set` 会警告
  `not a recognized config key`（并存下值）—— 直接编辑该 home 的 `config.yaml` 更干净。YAML 1.1 下
  裸 `off` 会被解析成布尔 `false`（归一化后仍是 "off"），写引号 `"off"` 让读的人不困惑。它是
  读配置、不是启动时读，下一轮消息起生效，不需要重启 gateway。owner 说「只要结果、不要工具调用
  过程」时改这个键；`display.interim_assistant_messages`（模型自己的中途台词）是**另一路**噪声，
  要一并安静得单独关。想在每轮都肉眼看见 tool call 时再改回 `all`——别写进 SOUL/skill 当永久规则。

### Channel topology: threads are the session boundary

- `auto_thread` defaults **true** but only fires on an **@mention**; free-response channels are skipped
  unless `free_response_auto_thread: true`. So the common setup (`require_mention: false` +
  `free_response_channels` listing every channel + no `free_response_auto_thread`) yields **exactly one
  eternal session per channel** — every later task, progress check and restart lands in it, compaction
  eats the middle, and the owner starts issuing `/reset` as manual GC.
- Corollary: do not add channels to "separate topics"; the channel is a label, the thread is the unit of
  context. Adding a channel splits context again, and a specialist bot with no sessions on that platform
  proves the split was fiction — keep routing through the front door.
- If a channel is meant to be one-way (ops feed), also put it in `no_thread_channels` and out of
  `allowed_channels`; `channel_prompts` is the lever for per-channel behaviour, not another bot.
- These keys exist in both `config.yaml` and `.env` (`DISCORD_*`) — **but which one wins is per key and
  decided at the call site, so read the gate before asserting it.** An adapter-build
  `_gate(key, env_key, from_platform_extra=False)` takes its value from `discord_cfg` (config.yaml) and
  only *fills* the env var when it is unset (`_env_default`); a message-time raw consult then reads
  whatever the process env holds. Edit both and keep them identical, then decide liveness from the process
  start time rather than from which file you believe dominates (`references/gateway-restart.md`).
- Before proposing any channel add/remove, measure actual traffic from `state.db` first:
  `references/channel-usage-audit.md`.
- **A forum channel (type 15) is the task queue.** One post = one thread = one session, and tags /
  close / archive keep the list short — that is the answer to "one channel per task", never more
  channels. Sending into the forum **parent** always creates a NEW post, so cron or any proactive
  output must never target it; only thread-anchored sessions are safe. Limits, REST probe and the
  inbound `parent_id` inheritance: `references/thread-and-forum-topology.md`.
- **帖子不能嵌套，帖内上下文也不是全量。** Discord 只有一层 thread —— forum 帖本身就是 thread，帖内不能再
  开 thread；所以"子任务"只有 Kanban 卡的 `parent_id` 是真层级（一个帖 : 0..N 张卡，卡分叉），帖与帖用
  命名/tag 关联只是约定。被问"这个帖记了全部上下文吗 / 每次 run 都加载全部吗"时拆三层答：固定层
  （`SOUL.md` + 项目 `AGENTS.md` + `MEMORY.md`/`USER.md` + skills 索引，每轮注入、与帖无关）、本 session
  历史（到上下文窗口 50% 被摘要替换）、平台消息回填片段。机制、压缩与 `session_reset` 参数、验证 SQL：
  `references/thread-and-forum-topology.md`。
- Frame the partition for the owner as: channel = stable context/permission boundary, thread = one
  execution, forum post = one durable work item. Under that framing "which channel has task X" stops
  being a memory problem — the thread/post title is the index.

## Proof

```bash
hermes gateway status --deep
python3 -c "import json;d=json.load(open('$HOME/.hermes/gateway_state.json'));print(d['pid'],d.get('code_sha'));print({k:v.get('state') for k,v in d.get('platforms',{}).items()})"
systemctl --user show -p MainPID hermes-gateway.service
md5sum ~/.hermes/SOUL.md ~/.hermes/profiles/*/SOUL.md
for p in ~/.hermes/profiles/*/; do echo "$p $(ls $p/skills | wc -l)"; done
```

## References

- `references/profiles-and-identity.md` — profiles, persona overlays, identity/skill consistency audit,
  multiplexing rollout, expected-disable warning.
- `references/profile-roster-audit.md` — roster evidence pass, justification test, routine/permission
  contracts, commercial-product comparison (Grok Bots / ChatGPT Dots / Meta Muse).
- `references/repo-owned-bot-definitions.md` — repo as source of truth for a bot matrix: `bots/` layout,
  field-to-primitive map, materializer (`--check` / `--apply`), one-way sync, drift job, pitfalls.
- `references/skill-catalogue-surgery.md` — per-profile skill trimming: the real name universe
  (`find -L … SKILL.md`), the `disabled = (root_disabled ∪ universe) − desired` formula the drift checker
  expects, the truncated-name trap, exceptions-file rebuild, verification probes.
- `references/messaging-channels.md` — home-channel semantics, Discord slash cap, token-lock false
  positive, `session_reset`.
- `references/channel-to-profile-routing.md` — one bot token, many bots: `gateway.profile_routes`,
  specificity table, Feishu group/DM caveats, persona-based verification.
- `references/channel-usage-audit.md` — how many channels are actually used and how: state.db queries
  (per-source/chat_id, owner hour histogram, empty sessions from `/reset`, compaction), channel-name
  resolution over REST, the `auto_thread` / `free_response_auto_thread` trap, report shape, and the
  **channel-retirement checklist** (last message / cron delivery / config+.env refs / per-profile sessions)
  plus the delete mechanics: guard script (pre-check gate on name/id/guild + `--dry-run`), `User-Agent`
  requirement, and the 404/`10003` read-back that proves the channels are gone.
- `references/thread-and-forum-topology.md` — thread = session boundary mechanics, forum channel as
  task queue (type 15 limits, one-call-one-thread send trap, `parent_id` allowlist inheritance), REST
  probe, naming convention, what to say to the owner instead of adding channels, plus the per-post
  **context economics** (what is stored vs what each turn loads — compression thresholds, the
  `session_reset` plugin rotation, history backfill) and the "no nested threads → Kanban parent cards"
  answer.
- `references/channel-topology-research.md` — when a channel-per-project is actually justified, the
  status-prefix naming convention, the single-index pattern, the anti-pattern list, and when to move
  the task object into an external tracker.
- `references/gateway-restart.md` — restart from inside the gateway, `gateway_state.json` verification,
  and how to tell whether your config edit is *already* live (process start vs write time, selective
  `/proc/<pid>/environ` read, per-key gate source).
- `references/silent-channel-triage.md` — channel silent but config looks right: where routed
  messages log, REST visibility probe, `.env`-overrides-`config.yaml` gate diff, fix shape.
- `references/paused-conversations.md` — conversations frozen after an unclean gateway exit: find
  `unknown`/`queued` admissions in every profile's `state.db`, `/discard` vs `/reset` recovery, and how
  to read the real kill reason out of `gateway.log` + systemd-oomd. Also the **silent** variant — a turn
  killed by a clean restart, no pause notice — with the delivery forensics for "what did the owner
  actually receive"; and the **batch** variant — dozens of threads whose title never changed — with the
  thread-vs-session triage table, the resume / rebuild recipes and the unattended lane discipline.
- `references/bot-mode-cli.md` — Bot Mode from the CLI (bot = profile + metadata).
- `references/webui-sidecar.md` — safe `nesquena/hermes-webui` sidecar.
- `references/bot-mode-and-profiles.md`, `references/discord-slash-command-sync.md` — session detail.
- `references/cases.md` — historical cases: multiplex upgrade rollout, channel/persona overlays, Discord
  token lock + WebUI sidecar.
- `scripts/gw-restart-verify.py` — restart + verify (stdlib only, system `python3`).
- `scripts/channel-usage-audit.py` — one-shot channel audit: live name/type/parent, last message
  per channel, per-profile session counts (read-only `state.db`), and the grep lines for cron/config.
- `scripts/archive-channel-transcripts.py` — pre-delete archive of a channel's local transcript
  (per session, threads included) to markdown, from one or several `state.db` stores.
