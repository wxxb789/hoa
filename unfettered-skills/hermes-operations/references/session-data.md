# Session data: WAL, message stats, auto-prune


## Session DB / WAL cleanup

For ordinary WAL maintenance, use SQLite rather than filesystem deletion:

1. Check `state.db`, WAL, and SHM sizes and identify every open DB descriptor.
2. Run `pragma integrity_check` before and after.
3. Shrink it with `pragma wal_checkpoint(PASSIVE)` then `pragma wal_checkpoint(TRUNCATE)` — **hot is
   fine**. A WAL cannot be "compressed"; truncation is the only reclaim, and it completes with
   `busy=0` while the gateway (a 4-day-old one) and the CLI session both hold the DB open — verified
   on this install: 64 MB WAL → 350 KB, zero downtime. `hermes doctor`'s "stop the profile's gateway
   first" hint is not a precondition; only stop writers if TRUNCATE actually returns nonzero `busy`,
   and never from inside a session the gateway serves. Profile WALs are usually 0 B already — the
   bloat lives in the default home's `state.db`.
4. Re-check `hermes sessions stats`, journal mode, and sidecar state.

Why a WAL sits at a large round size (observed 64 MB): `journal_size_limit = -1` (Hermes' default) makes
an ordinary checkpoint reset only the WAL **header** — the file keeps its high-water allocation, so one
burst leaves a permanently large sidecar. Optional durable cap (persistent, reversible, one statement):
`pragma journal_size_limit = 8388608`. Do **not** reach for `VACUUM` on the main DB without reading
`pragma freelist_count` first: 933 free pages on a 234 MB DB is ~3.6 MB of reclaim for a 2x-space,
exclusive-lock rewrite — usually not worth it.

For a deleted-generation incident, use the maintenance-window recipe instead of jumping to checkpoint:

1. From an external shell, inventory served profiles, `HERMES_HOME` roots, auto-update state, and every `/proc/*/fd` descriptor for `state.db*`.
2. Freeze auto-update timer/service and stop gateway/other writers before capture; otherwise the visible DB and deleted generation can cross write boundaries.
3. If a live owner/CLI process holds deleted DB/WAL/SHM inodes, keep it alive but explicitly idle while capturing stable fd bytes and hashes; capture before the process exits because exit closes the only evidence.
4. Back up every served DB through SQLite `Connection.backup()` and verify each backup with integrity, counts, schema, and a scratch restore.
5. Treat a failing session API plus a direct `/proc/*/fd` scan as authoritative; do not infer safety from `hermes doctor`'s visible-holder count or a healthy systemd status, because a process can still own deleted `state.db`/WAL/SHM inodes.
6. Compare generations with logical table/row hashes; if newer/older order cannot be proven, preserve both and abort rather than guessing.
7. Checkpoint/reopen only the selected verified generation; keep gateway stopped on failure and restore all modified DBs from verified backups.
8. If history is needed while the DB API is unavailable, use read-only JSON/JSONL session artifacts only for bounded metadata or excerpts; omit tool payloads and credentials, and do not treat file fallback as verified history until the DB repair passes.
9. Restore auto-update only after runtime, health-check, and archive/quarantine verification passes.

Pitfall: a large `state.db` after WAL truncation is usually real session history. Do not prune/delete without explicit retention scope or a verified rollback archive. Never `rm` WAL/SHM sidecars directly.

## What a large `state.db` is actually made of

Before proposing a retention cut, measure composition. `dbstat` is read-only and part of SQLite:

```python
con = sqlite3.connect("file:<home>/state.db?mode=ro", uri=True)
con.execute("select name, sum(pgsize) from dbstat group by name order by 2 desc limit 10")
con.execute("pragma page_count").fetchone(), con.execute("pragma page_size").fetchone()
con.execute("pragma freelist_count").fetchone()
```

Observed shape on a 358 MB DB with 21k messages: `messages` 104 MB (29%) and **FTS 220 MB (61%)** —
`messages_fts_trigram_data` 107 MB, `messages_fts_trigram_content` 48 MB, `messages_fts_content` 48 MB,
`messages_fts_data` 16 MB. `freelist_count` was 0.

Rules that follow from that:

- **Retention is a poor lever on DB size relative to what it costs.** On that DB, `retention_days: 90`
  was protecting only the 7% of messages older than 90 days while the 30–90 day band held 43%. Quote the
  FTS/body split and an age histogram (`<7d / 7–30d / 30–90d / >90d`) before recommending a cut; when the
  file is mostly index, deleting rows does shrink it — and takes the history the product exists to recall.
- **`freelist_count = 0` means `VACUUM` reclaims nothing.** It is a full-file rewrite for zero bytes. Do
  not propose it as a size fix.
- **Timestamps are epoch integers**, not ISO strings: `sessions.started_at` / `sessions.last_activity_at`
  and `messages.timestamp`. Comparing them to `datetime('now','-30 days')` compares text to int and
  silently files every row under "old" — the histogram comes out 100% stale. Bind
  `strftime('%s','now','-30 days')` instead.
- Column names are not the obvious ones: `sessions` has `last_activity_at` / `started_at` (no
  `updated_at`), `messages` has `timestamp` (no `created_at`). Read `PRAGMA table_info` once rather than
  guessing and catching the error.
- If the goal is *cleaner search* rather than a smaller file, the `archived` / `auto_archived` columns are
  the intended lever — but prove `session_search` actually excludes archived rows before promising it.
- **`state_meta` is not metadata-sized.** It caches per-admission results
  (`gateway.admission.result.v1.<id>`, up to ~800 KB each); a couple of thousand such keys reach 60 MB +
  and rank above most tables in `dbstat`. Do not hand-delete those rows — they are the delivery /
  idempotency record for admissions. Point at `optimize-storage` and retention instead.

## Reclaiming a bloated session DB (maintenance window)

`VACUUM` reclaims nothing when `freelist_count = 0`. When the weight is FTS, the reclaim lever is
`hermes sessions optimize-storage`: it rebuilds the search index into the compact v23 external-content
layout (no conversation data is touched), VACUUMs at the end, and is safe to interrupt and re-run.
It refuses while any Hermes process holds `state.db` — as does `hermes sessions optimize`, whose
`--force` exists but warns that rewriting under a live writer can leave **every agent refusing turns**
until all writers stop. So size reclaim is a stopped-gateway maintenance window, never a background job:

1. Size the win first: `dbstat` by table (above), plus `hermes sessions prune --older-than N
   --max-messages K --dry-run` to count stub sessions (smoke tests, 2-message cron runs). `prune` deletes
   only ended sessions, and `--dry-run` never touches the file.
2. Back up through the SQLite backup API (`Connection.backup()`; the `sqlite3` CLI is usually absent):
   a ~600 MB copy takes seconds while writers run.
3. Run it as a **detached unit**, never from the session the gateway serves — `systemctl --user stop`
   kills the turn you are typing. `systemd-run --user --collect --unit=<name> --on-active=<N>s /bin/bash
   <script>`, and make the script `trap restore_gateway EXIT` so any failure still brings the gateway back.
   Export the Hermes bin dir inside the script (`~/.hermes/hermes-agent/.hermes/bin`): a systemd-run unit
   starts from the systemd user environment, not your shell PATH.
4. Sequence: stop gateway → `hermes sessions optimize-storage --yes` → `hermes sessions prune … --yes` →
   start gateway → verify `is-active`, `gateway_state.json` platforms, `unknown` admission count, and the
   new DB/WAL size.
5. A clean `systemctl --user stop` does **not** mint `unknown` admissions — only an unclean death (SIGKILL
   /OOM) does. A planned maintenance stop ends turns as interrupted and pauses no conversation; expect the
   `/discard` recovery path only after a killed process.

### The stopped gateway is not a free database

Both `optimize-storage` and `prune` refuse on **any** open descriptor, and the gateway is only one of them:
app-spawned `hermes serve --isolated … --ssh-session-token-file …` backends keep `state.db` open after the
gateway is down, and each refusal names the PIDs it found. Enumerate by descriptor — the disposable ones
are not all matchable by pattern — then clear them and run again:

```bash
python3 ~/.hermes/scripts/state-db-holders.py             # pid, kind, rss, age, short cmdline
python3 ~/.hermes/scripts/state-db-holders.py --reap-backends
```

Under a reconnect storm the backends are replaced within seconds (one observed window lost *every* attempt
because a fresh backend appeared while the gateway was still stopping), so the maintenance script must
**retry**, not try once: kill backends → run → on refusal sleep a few seconds → retry, 5–6 attempts. Each
refusal costs seconds because the tool bails before touching the file; only the successful run is long.
Kill by PID from an enumeration that excludes your own process and its ancestors — `pkill -f '<pattern>'`
also matches the shell running that command and terminates it (SIGTERM, exit 15); the trap then restarts
the gateway but the window is gone.

Measured on a 31k-message home: **585.3 MB → 310.0 MB (275.3 MB, 48%)**, WAL 65 MB → 5 MB, and
`prune --older-than 30 --max-messages 4` removed 133 stub sessions in the same window. Expect roughly the
FTS share `dbstat` reported, not a trim — quote that share before promising a number.

## Cross-platform message stats (who sent how many via X today)

When the owner asks "how many messages came in via Feishu/Discord/Telegram today" or "what did you handle from <platform>", DO NOT claim you lack access. The running agent session has no live per-platform inbox feed, but every processed message is persisted in `~/.hermes/state.db`, tagged by platform.

Schema facts:
- `sessions(id, source, started_at, title, ...)` — `source` ∈ `cli | cron | discord | feishu | telegram`.
- `messages(session_id -> sessions.id, role, content, timestamp REAL epoch, ...)`.
- Roles: `user` = incoming from owner, `assistant` = agent reply, `tool` = tool calls, `session_meta` = system markers.
- **"messages sent IN" == `role='user'`.** The raw per-session count is much larger (assistant+tool+meta). Always disambiguate which number the owner means and report the breakdown.
- All platforms' rows live in the DEFAULT `~/.hermes/state.db`, even though per-platform profiles exist; the per-profile `state.db` files are usually empty. Auto-discover all of them anyway.

Two pitfalls:
1. The `sqlite3` CLI binary is frequently NOT installed on the host (`command not found`, silent empty output). Use Python's stdlib `sqlite3` module instead — it always works. Open read-only: `sqlite3.connect("file:<path>?mode=ro", uri=True)` (Green action).
2. Use the owner timezone (CST/UTC+8) for the day boundary, not UTC, or "today" will be wrong by 8h.
3. A platform `state: connected` in `gateway_state.json` is **connectivity, not traffic**. `SELECT source, MAX(timestamp) FROM messages JOIN sessions ON sessions.id = messages.session_id GROUP BY source` over a 7-day window is the end-to-end evidence; a channel that carried nothing for a week is "connected, unproven" — report it that way instead of "all channels work", and offer a one-shot delivery self-test (that needs the owner's OK because it messages them).

Runnable probe: `scripts/session-source-stats.py` — aggregates by source × role × day across all discovered DBs. `--source feishu` filters one platform and lists each incoming user message with timestamp; `--days 7` widens the window. Run it rather than hand-typing SQL each time.

### Enabling `sessions.auto_prune` prunes immediately

Turning `sessions.auto_prune` on does **not** wait for a maintenance window: the next `state.db auto-maintenance` pass prunes every session whose **last activity** is older than `retention_days` and runs `VACUUM` (observed: 242 sessions in one pass at the next process start).

- Warn the owner with numbers before enabling it, or take a snapshot first (`hermes` quick snapshot / `state-snapshots/`).
- Surviving rows are selected by last activity, not by start date, so "old" sessions that were recently touched stay.
- A pre-prune quick snapshot plus the monthly JSONL exports are the recovery path; restoring without raising `retention_days` just re-prunes on the next pass.
- After the prune, run a live `session_search` probe — counts alone do not prove the search path works.
