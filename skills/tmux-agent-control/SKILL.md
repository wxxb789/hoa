---
name: tmux-agent-control
description: >-
  Drive a live TUI coding agent in a tmux pane: locate it by process, read its real state, wait for
  idle, then hand it one complete instruction without corrupting the session. Use when taking over
  or monitoring an interactive agent turn. Not for one-shot generation — run that headless.
metadata:
  version: "0.1.58"
  areas: "software-development,work-management"
  targets: "runtime-agnostic"
  summary: "drive a live TUI agent in tmux: find the pane, prove idle, send one complete instruction"
  summary_zh: "在 tmux 中驱动运行中的 TUI agent：定位 pane、证明空闲、一次发出完整指令"
  kind: "entry"
---

# Controlling a live TUI agent in tmux

Driving a coding agent (omp, pi, opencode, claude-code) that someone left running in a tmux pane:
read its state, wait for it to go idle, then hand it the next instruction without corrupting the
session.

## When to Use

- the operator says "watch that agent and tell it X when it finishes" / "take over the session in
  tmux"
- you must monitor a long agent turn and report its real outcome
- a multi-phase delivery (goal → simplify → review → PR → babysit → merge) runs through a driven
  agent → follow `gdd` and use this skill for the mechanics
- NOT for one-shot generation — that is headless `pi -p` / `omp -p ... @prompt.md > out.md`
  (see `omp-headless-orchestration`); never route a one-shot through tmux

## Pick the control mode first

- **Existing interactive pane** the operator may also be using → drive it in place (this skill).
- **New task, no steering needed** → headless `omp -p` with the prompt in a file, output to a file.
- **New task needing multi-turn steering** → own detached session:
  `tmux new-session -d -s agent-dev -c <repo>`, then the same protocol.

Never start a second agent in a repo that already has one mid-turn: two writers on one working
tree produce a diff nobody can attribute.

## Procedure

1. **Locate the pane by process, not by a remembered session name.**
   `ps -eo pid,ppid,etime,cmd | grep -E 'omp|pi |opencode'` → PID; `ls -l /proc/<pid>/cwd` → repo;
   `tmux list-panes -a -F "#{session_name}:#{window_index}.#{pane_index} pid=#{pane_pid} cmd=#{pane_current_command} cwd=#{pane_current_path}"` → pane.
   Session groups (`new-session -t main`, `destroy-unattached keep-group`) let the session you saw
   a minute ago disappear while the pane and PID live on in a sibling session. Cache the PID, not
   the `session:window.pane` string, and re-resolve before every send.
2. **Read state instead of guessing it.** `tmux capture-pane -p -t <target> -S -80`; `-S -200` for a
   whole turn, `-J` to join wrapped lines into contiguous text. The status line carries model, repo,
   branch, dirty count, context %, cost — quote it as evidence in your report.
3. **Decide busy vs idle mechanically.** Busy if any of: braille spinner glyphs
   (`⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏⠿⡿⣟⣯⣷⣻⢿⡷⣾⣽⣶⣇⣏`), `Subagents · N running`, `waiting on N job`.
   Idle only when none match AND two consecutive captures hash equal ~15-30s apart. One still
   frame is not idle — TUI redraw gaps look identical. A session restart or auto-compaction also
   freezes the pane for minutes: before acting on an idle snapshot, re-capture and check the
   harness's debug log for a recorded session exit or a scheduled continuation — a restarting turn
   needs a re-armed watcher, not a "done" verdict.
4. **Send safely; never type blind.**
   - Tail shows a modal/report hint (`esc`, `q quit`, `press … continue`) → send
     `tmux send-keys -t <target> Escape`, re-capture, up to 3 tries.
   - Refuse to send unless the composer prompt (`❯` in omp) is visible in the last lines; abort and
     report instead. A keystroke into an unread dialog confirms something you never saw.
   - Short instruction: `tmux send-keys -t <target> -l "<text>"`, then a separate
     `tmux send-keys -t <target> Enter`. `-l` alone does not submit.
   - Multi-line instruction (a plan or prompt file): write it to a file, then
     `tmux load-buffer -b p <file> && tmux paste-buffer -b p -t <target> -d`, capture to confirm the
     composer holds it, then send `Enter` on its own. Bracketed paste keeps newlines; embedding
     them in `send-keys -l` submits early or mangles the composer.
5. **Make the instruction complete on the first send.** An agent that already reported "done" will
   silently narrow scope to what it considers valid. Restate the full ask, name the items it
   rejected earlier, and require a per-item outcome table (id, file, change, test result) plus an
   explicit reason for anything it judges invalid rather than skipping it.
6. **Run it as a background watcher, not a foreground sleep loop.** `scripts/tmux-agent-watch.sh`
   implements steps 3-4: `TARGET=... MSG=... OUT=... bash scripts/tmux-agent-watch.sh`, launched as
   a background job with completion notification (the harness's own background-job mechanism, or
   `setsid … &` plus a polled status file when there is none). Report job id + artifact dir to the
   operator. Log every transition and snapshot the pane at idle / after-send / timeout — those files
   are the proof.
7. **Verify the outcome yourself.** When the turn ends: `git -C <repo> status --short`,
   `git diff --stat`, run the repo's own test command, and diff the agent's per-item table against
   the operator's ask. Report counts that actually moved, not the agent's summary.
   - **Read the aggregate, not the per-item column.** An agent writes "PASS" in every row while the
     suite summary says `总计 2579 / 失败 1`. Parse the totals line; a per-item PASS table and a
     green suite are different claims.
   - **Prove pre-existing failures with a worktree, not a stash.** The working tree belongs to the
     other agent, so never `git stash` in it. `git worktree add ${TMPDIR:-/tmp}/base-verify HEAD` in a
     non-interactive shell, run the failing test there, then `git worktree remove --force`. Same
     failure at HEAD = pre-existing, and you can say so with proof.

## Process lifecycle & graceful shutdown

Three states with distinct signals and actions — never conflate idle with done:

- **Working.** The footer shows `Working…`; the harness's session transcript grows (mtime < ~60s);
  the process is `R`/`S` with CPU; `omp ps` lists running workers when subagents are active.
  Action: wait, do not disturb.
- **Idle-but-alive — do NOT kill.** (a) TUI sitting at the composer `❯`: a live session the
  operator may attach — 0 CPU and no transcript growth but still theirs. (b) Provider wait: the log
  shows `provider error` then `agent.continue scheduled … automatic-retry` (a 429
  `prefill_cap_refused` clears in minutes) or `--wait-async` is awaiting background jobs — the
  harness self-recovers; give it ~15 min before switching provider. (c) Print-mode turn finishing
  its final flush — judge by exit code, not by silence.
- **Done → release.** A headless `-p` run that **exited** (notification fired; exit code captured,
  e.g. 0 = ok, 3 = max-cost) with the final report in `out` is finished — the process is already
  gone, nothing to kill. Only then reclaim storage: `omp gc --dry-run`, then
  `omp gc --apply --blobs --wal --stale` (add `--archive`/`--compress` for cold sessions). Confirm
  no live workers with `omp ps` first.

Graceful shutdown — never `kill <pid>` on harness children:

- **Daemon-supervised workers/brokers** (`__omp_worker_daemon_broker`, `browser-relay`, subagent
  workers): `omp ps` to find the name, `omp ps stop <name> [--timeout N]` (grace period, then hard
  kill) — the documented graceful path. `omp ps kill <name>` only if `stop` is refused. This
  replaces raw `kill <pid>`; a plain kill leaves orphaned brokers.
- **TUI session:** send `/exit`, wait for the shell prompt; never SIGKILL (it drops the in-flight
  turn and session state).
- **Headless `-p`:** let it exit on its own; bound the run up front with `--max-time`/`--max-cost`
  instead of killing mid-turn. If you must abort, prefer SIGTERM over SIGKILL and confirm the
  session file is intact afterward.
- **Before `--resume` (operator attach):** `omp session lease --json -- <id>` shows which running
  omp holds the session — never two writers.
- **Storage:** only `omp gc`; never delete the harness's session JSONL files by hand.

## Pitfalls

- **Judge success by exit code and log files, not by stderr.** A background job has no TTY, so the
  tmux client prints `open terminal failed: not a terminal` and every call still succeeds; silence
  the noise with `2>/dev/null` and read `watch.log` + snapshots.
- **A vanished tmux session does not mean the agent died.** Check the PID before declaring it gone;
  session groups and `destroy-unattached` move panes without killing processes.
- **The agent's own summary is not the operator's definition of done.** "All findings applied"
  means the findings it accepted; items it rejected earlier stay open until someone names them.
- **A fresh detached session captures as blank.** A new `tmux new-session -d` starts at 80x24 and
  omp/pi draw only inside the pane's geometry, so `capture-pane` returns empty lines and the TUI
  looks dead while its PID is alive. `tmux resize-window -t <target> -x 200 -y 50`, wait a beat,
  then capture.
- **Ctrl-C does not exit the TUI; it only interrupts the current turn.** To relaunch (e.g. after a
  self-update), send the quit command (`/exit` in omp), capture until the shell prompt is back, and
  only then `send-keys '<agent> …'`. Sending the launch command while the agent still owns the
  composer submits it as a prompt — the agent spends a turn reasoning about its own launch line.
- **Version: read the TUI banner, not the package manager.** omp's own updater stages a release and
  shows `vX → vY ✔ next launch`, while the version manager can still report the older version
  because of a minimum-release-age policy. Quit and relaunch to pick up the staged build; verify the
  banner before sending work. Without attaching, the harness's staged-update manifest
  (`${OMP_HOME:-$HOME/.omp}/update/auto-update.json`, `{phase, version, target}`) reports the same
  build — check it at each new work phase, and relaunch with the session resumed
  (`omp --resume <id>`) when a bump makes restarting worth it.
- **Unattended repo work needs the approval mode set at launch.** `omp --approval-mode yolo`
  (or `--auto-approve`) skips per-tool prompts; without it a background run stalls on the first
  write/exec approval nobody is watching. State the guardrails (no commit/push) in the prompt
  instead of relying on prompts.
- **A version-manager-installed CLI is not on PATH in a non-interactive shell.** Resolve it under
  the install root's version directory and call the absolute path; the running process may be a
  different version than the one on disk (`omp --help` prints its version first).
  `readlink -f /proc/<pane-pid>/exe` names the exact binary driving a pane, and
  `tr '\0' '\n' < /proc/<pid>/environ | grep '^PATH='` shows the PATH it was launched with.
- **A provider error is not a dead session; check the log before restarting.** The harness retries a
  failed model call by itself — the session log carries `agent turn ended with provider error` and
  then `agent.continue scheduled … source=automatic-retry` (a 429 `prefill_cap_refused` = provider
  cell at capacity, typically clears in minutes), while the pane still shows `Working…`. Spend the
  stall on work that needs no model (run the repo's gates, read the diff) instead of killing the
  turn. Only when the harness debug log shows no recovery after ~15 minutes, quit and relaunch with
  `omp --resume <session-id> --model <provider>/<model>` to continue on a healthy provider —
  providers and models are listed in the harness's model registry (see
  `references/harness-internals.md`).
- **Don't drive a pane the operator is typing in.** Attached and in use → open a detached session of
  your own; two writers to one composer corrupt the input line and the pending turn.
