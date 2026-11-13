---
name: git-auto-sync-pipelines
description: >-
  Design a scheduled commit/push pipeline for a repo the owner edits by hand: ordered preflight
  gates, a scope allowlist and size cap, a staged secret scan, rebase-then-push, heartbeat and
  deduped alerts. Use when a notes or research repo must sync on a schedule, or when an existing
  auto-sync needs a safety review. Not for a repo with a review/PR workflow, and not for a one-off
  commit you can make yourself.
metadata:
  version: "0.1.54"
  areas: "software-development,work-management"
  targets: "runtime-agnostic"
  summary: "scheduled commit/push for hand-edited repos: ordered gates, allowlist and size caps, staged secret scan, heartbeat and deduped alerts"
  summary_zh: "手改仓库的定时提交推送：固定门序、白名单与体积上限、暂存区密钥扫描、心跳与去重告警"
  kind: "entry"
---

# Git auto-sync pipelines

## When to Use

- A repo is edited by hand (notes vault, research repo) and must be committed and pushed on a schedule.
- An existing auto-sync needs a safety review: branch guard, secret scan, alert noise, silent stalls.
- Someone asks to "sync these two repos every N hours" without a PR workflow.

Scheduled "validate → commit → rebase → push the target branch" for a repo the owner edits by hand.
Reference implementation shape: one shared library (`<sync-root>/lib/git-sync-common.sh`) plus one
wrapper per repo, run by a single scheduler entry that loops the wrappers and prints only what they
printed. A separate watchdog is usually retired into the daily health sweep: "has not succeeded
recently" is one step of that sweep, because a periodic watchdog cannot outlive the scheduler it is
watching.

## Gate order (never reorder)

1. `flock` — one run at a time; silent skip on contention.
2. pre-staged index → **refuse**. Staging is the human's signal, not the automation's.
3. no-op check → exit silently (still stamp the success heartbeat).
4. branch must equal the target branch. `git push origin HEAD:<target>` from a feature branch
   publishes that branch's commits to the target — this is the single highest-severity failure mode.
5. in-progress git operation markers (`rebase-merge`, `rebase-apply`, `MERGE_HEAD`,
   `CHERRY_PICK_HEAD`, `BISECT_LOG`) → skip; a conflict path that runs `rebase --abort` would
   otherwise destroy the owner's manual rebase.
6. scope + size gate → repo-defined validation → `git add -A` → **staged secret scan** → commit.
7. rebase onto `origin/<branch>`, then push (never force), then re-fetch and assert HEAD == remote.

## Rules that matter more than the happy path

- **Exit 0 on failure when the message is the alert.** A no-agent scheduler sends an extra error
  notice on non-zero exit, so the wrapper's `fail()` returns 0 after printing — one message, not two.
- **Dedupe alerts by failure signature** (hash of the message, `SYNC_DEDUPE_HOURS` window, default 24)
  or a permanently failing gate becomes 12 messages/day.
- **Heartbeat + watchdog**: every successful run (including no-ops) writes a timestamp; a second
  scheduled job alerts when the newest heartbeat is older than `SYNC_WATCHDOG_HOURS`. Without it, a
  stale lock or a crashed script means "silently not syncing", which looks identical to "nothing to
  sync".
- **Scope whitelist, not `git add -A` alone**: tracked paths are always allowed; new files only under
  declared roots (`SYNC_NEW_FILE_ROOTS`). Otherwise any stray export lands in history, which is
  irreversible.
- **Size cap** (`SYNC_SIZE_BLOCK_MB`, default 20; `SYNC_SIZE_WARN_MB`, default 5). Binary bloat in
  git is one-way.
- `SYNC_PUSH=0` turns a run commit-only: set it on secondary machines so exactly one machine pushes.
- **Target branch is configuration, not a constant.** Resolve it per repo (`SYNC_TARGET_BRANCH`,
  default: the repo's remote HEAD); never copy `main` from one machine into another repo's pipeline.

## Secret scan specifics

- `gitleaks git --staged --redact --no-banner` exits 1 on findings and keeps secrets out of stdout.
  Substitute the scanner the operator's install provides; the contract is staged-only, exit 1 on a
  finding, no secret echoed.
- A secret scanner usually carries a built-in allowlist: an AWS documentation placeholder such as
  `AKIAIOSFODNN7EXAMPLE` is NOT reported. Verify the scan with a realistic token (`ghp_` plus 36
  characters), not a documentation placeholder.
- On a finding: `git reset -q` (unstage) before failing, or the pre-staged guard blocks every later
  run and the sync wedges until a human intervenes.

## Repo-specific validation stays in the repo

Read the repo's own contract for the validation set (its harness README, `AGENTS.md`, or equivalent)
and run exactly that (`SYNC_VALIDATE_CMD`). If the repo forbids unattended commits/pushes, add a
narrow mechanical-sync exception clause to its contract in the same change instead of silently
violating it.

## Pitfalls

- **Capture `git rebase` output.** Conflict hints go to stderr and, uncaptured, reach stdout — which
  the scheduler delivers verbatim, so the noise re-fires every run and defeats alert dedupe. Capture
  to a variable, keep only the `CONFLICT` line in the alert, abort silently.
- A stuck conflict is a human decision: abort, keep the local commit, alert once a day. Never
  `--force`, never `rebase --skip`.
- Validation scripts that write dated reports will pollute every commit; delete only today's
  untracked copies (never `git clean` the whole directory — it takes human files too).
- A validator that always exits 0 (report-only lint) is not a gate; say so instead of implying safety.
- Background/no-tty runs of such scripts can emit `open terminal failed: not a terminal`; run tests in
  the foreground.

## Configuration

| Key | Env | Default |
|---|---|---|
| `sync_root` | `SYNC_ROOT` | none — directory holding the library and wrappers |
| `repos` | `SYNC_REPOS` | none — newline/space list of repo paths, or a config file |
| `target_branch` | `SYNC_TARGET_BRANCH` | the repo's remote HEAD branch |
| `new_file_roots` | `SYNC_NEW_FILE_ROOTS` | none — allowlist of roots; tracked paths always pass |
| `validate_command` | `SYNC_VALIDATE_CMD` | the repo's own contract command; none if absent |
| `secret_scanner` | `SYNC_SECRET_SCANNER` | `gitleaks` if installed, else require an explicit value |
| `size_block_mb` | `SYNC_SIZE_BLOCK_MB` | `20` |
| `size_warn_mb` | `SYNC_SIZE_WARN_MB` | `5` |
| `dedupe_hours` | `SYNC_DEDUPE_HOURS` | `24` |
| `watchdog_hours` | `SYNC_WATCHDOG_HOURS` | none — required by the heartbeat job |
| `heartbeat_file` | `SYNC_HEARTBEAT_FILE` | `${XDG_STATE_HOME:-$HOME/.local/state}/<sync-name>/heartbeat` |
| `push` | `SYNC_PUSH` | `1` |
| `alert_channel` | `SYNC_ALERT_CHANNEL` | the scheduler's own notification path |

Resolution order and the config-file path are defined once in
[skill-porting-and-publishing § Configuration](../skill-porting-and-publishing/SKILL.md#configuration-is-a-gate-not-advice);
this skill does not restate them. The repo list and target branch belong in the operator's config,
not in the library script.
