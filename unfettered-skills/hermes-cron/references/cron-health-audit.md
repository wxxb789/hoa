# Cron health audit — commands, fields, delivery resolution

## Verdict sources, cheapest first

| Question | Command | What it proves |
|---|---|---|
| Is the scheduler alive? | `hermes cron status` | host gateway PID, ticker heartbeat, next run |
| Which jobs exist, in what state? | `hermes cron list --all` | schedule, deliver target, last run + status, execution id |
| Anything unhealthy right now? | `hermes cron doctor` | last-run failures and not-delivered results, with the repair command |
| Failure history | `hermes cron incidents` | durable incidents with `detected` / `resolved` / `closed` |
| Execution history | `hermes cron runs <id>` | attempts, `source=builtin` vs `source=direct`, `unknown` when the owner process died |
| What the run produced | `~/.hermes/cron/output/<id>/<ts>.md` | the agent/script output artifact |

## `jobs.json` fields that hide breakage

Read `~/.hermes/cron/jobs.json` directly — the CLI omits these:

- `last_delivery_error` / `last_delivery_unverified` — a run can be `ok` while its result never reached
  the owner. This is the field that distinguishes "ran" from "delivered".
- `failure_streak` — resets on success; separates "failed once long ago" from "failing now".
- `last_dispatch` — `scheduled_at`, `dispatched_at`, `lateness_seconds`, `kind` (on-time vs late).
- `no_agent` — script jobs deliver stdout verbatim; agent jobs deliver the model's final text.
- `repeat` — `times` (`None` = unlimited) and `completed`; sanity-check the job is actually firing.
- `state`, `paused_at`, `paused_reason` — a paused job reports no failures because it never runs.

## Delivery-target resolution

Grammar: `origin`, `local`, `<platform>`, `platform:chat_id`, `bot-chat[:profile]`.

`deliver=origin` uses the job's recorded origin. When that is null (job created without a live chat
context) it falls back to the platform home-channel chain; with no home channel configured the read
fails inside `agent/secret_scope.py` and the run records a delivery error while still reporting `ok`.

Enumerate the real targets — the same resolution cron uses (write it as a file, not an inline heredoc;
see pitfalls):

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / ".hermes/hermes-agent"))
from cron.scheduler_delivery import cron_delivery_targets
for t in cron_delivery_targets():
    print(t)  # id, name, home_target_set, home_env_var
```

`home_target_set=False` means delivery to that platform fails until its `*_HOME_CHANNEL` env var is set.
Set it with `hermes config set <PLATFORM>_HOME_CHANNEL <id>` (writes `.env`, prints the path) — and set it
**in the job-owning profile's `.env`**, because the lookup runs through that profile's secret scope: a
root-only value silently fails for a profile-owned job (root for profile-less jobs, plus every profile that
owns one). `bot-chat:<profile>` targets work with no extra config.

The reader resolves against the *current process's* scope, so the same probe run from a bare script outside
a gateway/profile context reports `home_target_set=False` even when the var is configured — read False as
"unresolved", not "unset", and re-check from the gateway side.

Change: `hermes cron edit <id> --deliver <target>`, plus `--failure-deliver <target>` when failure
notices should go elsewhere (`local` suppresses them; run state stays in `hermes cron list`).

## Finding the owner's real chat id (don't make them look it up)

The session store already records every chat this install talks to: `sessions(source, chat_id, chat_type,
user_id, origin_json)` in `~/.hermes/state.db` (platform sessions live in the root store even when a
per-platform profile exists). Query it read-only with Python's `sqlite3` (`mode=ro`), order by
`last_activity_at`, and read `origin_json` for `chat_name` / `chat_type` (`dm` / `group` / `thread`) /
`thread_id`. Ask the owner only when the choice is genuinely ambiguous (DM vs a shared channel).

## Delivery self-test (proves every hop)

`last_delivery_error: null` on a `source=direct` run proves little — the trigger path may not deliver at
all. Prove the whole chain (gateway scheduler → restart-safe worker → platform adapter → target) with a
throwaway one-shot job:

```bash
hermes cron create '1m' --name cron-delivery-selftest --no-agent \
  --script cron-delivery-selftest.py --deliver <target> --repeat 1
```

- The script (`~/.hermes/scripts/cron-delivery-selftest.py`) always prints, so a missing message means a
  broken hop, not a quiet run. Keep the script as the standing self-test; delete the job afterwards.
- Read the job's `last_run_at` / `last_status` / `last_delivery_error` **and** ask the owner to confirm the
  message arrived: successful deliveries are not journaled, so the absence of journal lines proves nothing
  either way. `hermes cron doctor` counts *active* jobs only — a completed one-shot drops out of the count,
  which is not a failure.

## Verification matrix for "did the fix land"

- **Payload works?** `hermes cron run <id>` → `Ran now: succeeded` + a fresh run record + a new output
  artifact. Confirm the record, not just the trigger line.
- **Worker path works?** Only scheduled runs (`source=builtin`) go through the restart-safe worker. A
  short-interval job proves that path continuously; a CLI-triggered run (`source=direct`) does not.
- **Delivery works?** The next run that produced output has an empty `last_delivery_error`.
- **Daily/weekly jobs:** their next scheduled fire is the only real proof; state the date in the report.

## Redundancy and noise audit

Collect a read-only baseline before proposing any merge. Keep snapshots, per-item metrics, and the
review matrix in the task directory; snapshot ownership separately from nullable job metadata.

**1. Scheduling entrances and execution history**

- Read root plus valid profile homes (`profiles/<p>/config.yaml` exists), each `cron/jobs.json`, and each
  `cron/executions.db` through SQLite `mode=ro`. Inspect table columns before querying; distinguish
  claimed, started, finished, status, source, and delivery outcome. Include zero-run active jobs.
- Inspect `systemctl --user list-timers --all --no-pager`, `systemctl list-timers --all --no-pager`,
  `crontab -l`, and `/etc/crontab` plus `/etc/cron.*`; read timer and triggered-service definitions with
  `systemctl [--user] cat <unit>`. Trace wrapper subprocesses to expose duplicate work hidden below jobs.
  Mark OS/domain exclusions explicitly rather than silently dropping inventory entries.
- Use keys `(store_profile, job_id)` and `(timer_scope, unit)`; persist every batch and verify the final
  key sets and counts against the inventory. Treat directories absent from the live job-id set as retired
  output, not active workload. Do not expose session/fact content in the report.

**2. Rates, latency, and resource cost**

- Set one aware observation time and a rolling seven-day cutoff; parse timestamps before comparison.
  Count attempts by claimed time where available so pre-start failures are not lost; distinguish builtin
  scheduled and direct/manual sources. Fixed-window runs/day = attempts / 7, including zero-run days;
  never divide by only the dates that contain runs. Report age-adjusted rate separately using actual job
  creation time, and label unavailable creation evidence rather than substituting config mtime.
- Compute current expected rate separately: interval seconds → `86400 / seconds`; cron expression →
  enumerate a declared horizon with the installed cron parser in the owning profile's configured timezone.
  Label whether rates include Hermes jobs, systemd timers, or both.
- Reconstruct schedule epochs from canonical definitions, backed-up records and applied-change evidence.
  Historical executions under a faster old cadence are not duplicate dispatches under today's cadence.
  Read `source, scheduled_instant, claimed_at` ordered by claim time per job; normalize aware instants to
  UTC, count repeated scheduled identities, and inspect successive gaps. Separate direct/manual runs and
  tick/finish-relative interval drift. If schedule history is unavailable, mark expected historical rate
  unknown rather than promoting observed/current-rate mismatch into a scheduler defect.
- Wire each metric to its actual source field and verify population keys: retained execution count is not
  admission-receipt count; schedule→claim/start lateness is not claim→start overhead. A missing field stays
  unknown, not zero. Preserve output classification/sample provenance through the review-matrix builder.
- For completed timestamp pairs, compute `finished_at - started_at` and median/p95/max, retain sample
  counts, and report `started_at - claimed_at` separately as startup/queue overhead. Wall seconds are not
  CPU seconds or peak RSS. Use accounting or safe read-only probes for those dimensions when available.
- Count failures, dispatch lateness, and identifiable model calls/token usage separately. Do not rerun a
  mutating payload to benchmark it; use retained executions or a verified read-only/dry-run entry point.
  Keep projected savings labeled as estimates until post-change executions exist.

**3. Output, gate skips, and delivery**

Classify only the result area of a retained artifact. This parsing shape applies to the current markdown
layout; inspect representative artifacts before using it on another layout:

```python
def classify_output(text):
    if '## Response\n' in text:
        response = text.split('## Response\n', 1)[1].strip()
        return 'silent_response' if response in ('', '[SILENT]') else 'non_silent_response'
    if 'Script gate returned `wakeAgent=false`' in text and '## Prompt' not in text:
        return 'gate_skip'
    if '**Status:** silent (empty output)' in text:
        return 'silent_script'
    if '(FAILED)' in text or '**Status:** error' in text:
        return 'failure_artifact'
    return 'unclassified'
```

- Report the retained sample size, time window, known-silent/non-silent counts, gate skips, and unknown
  layouts. A `[SILENT]`/`wakeAgent=false` literal quoted inside a prompt is not execution evidence.
- Non-silent artifacts measure output production, not messages. `runs/day × non-silent ratio` is at most
  an estimated output rate when the sample and cadence match; it is not total cost or proven delivery.
  Local outputs never count as external interruptions. Attribute actual sent messages using per-run
  `delivery_outcome` and resolved target when those distinguish sends from local/suppressed outcomes.
- Inspect delivery-journal attribution fields before aggregating; if job identity/content is unavailable,
  label message attribution unknown instead of assigning the journal total to jobs. Keep failures,
  suppressed healthy runs, and successful external sends separate.

**Deciding frequency from the fault**, not from habit:

| Check type | Longest tolerable outage | Sensible schedule |
|---|---|---|
| resource / OOM growth | minutes | 15–30m, state-transition alerts |
| repo sync failure / staleness | hours | 2h (sync) + daily staleness line |
| config / profile / instruction invariants | a day | daily, one aggregator |
| privacy replica sweep / retention cleanup | policy-dependent | nightly; keep independent when nightly failure would block required cleanup |
| monthly housekeeping | a month | one job per month window |

**Merge recipe**: one wrapper script calls each silent sub-check in order, concatenates only the non-empty
sections under a heading per check, and exits **0** whenever the report is the alert. A non-zero exit adds
a cron failure incident plus a duplicate failure notice on top of the report you already printed; reserve
it for a harness crash. The sub-scripts keep working standalone
(`--verbose`, `--apply`), so the merge is reversible and each check stays independently debuggable. Keep the
retired jobs' scripts on disk; remove only the job entries.

## Pitfalls

- Never judge a `script` job by the script file's mode bits: the scheduler runs it through the interpreter,
  so a `-rw-------` script still executes fine. Missing `+x` is not a failure and must not be reported as one.
  Real evidence for "is this job healthy" is `~/.hermes/cron/executions.db` — per job take the latest row and
  read `status` (`completed` / failed) plus `delivery_outcome` (`delivered`, `suppressed`, `failed`); a
  `suppressed` delivery is the silent-by-design success path, not a miss. Confirming only static properties
  (file exists, syntax compiles, deliver target parses) is a partial check — label it as such instead of
  turning it into a pass/fail verdict.
- Inspect payload side effects before a CLI trigger: `deliver: local` removes external delivery only,
  not memory writes, deletion, sync/push, or repairs. Use retained evidence or an implemented read-only
  mode for benchmarks; obtain the appropriate approval before mutation or external test delivery.
- Inline nested command substitution in a `terminal` call trips the approval scanner ("nested
  executable body could not be resolved") and executes nothing. Put multi-step logic in a script file
  under the scratch dir and run that file: it runs clean and leaves a reviewable artifact.
- `hermes cron run` reports success for the *trigger*; verify the durable run record and the output
  artifact before calling a job fixed.
- Incidents auto-resolve on the next successful run — a `resolved` incident is evidence, not noise, and
  does not need manual ack; only stale `detected` ones do (`hermes cron incidents ack <id>`).
- A gateway-startup warning `Platform 'X' is explicitly disabled by platforms.X.enabled: false … will NOT
  start its adapter` is **per profile**: one profile may deliberately not serve a platform that another
  serves (the platform stays connected through the profile that does). Read `gateway_state.json`'s
  `platforms` map (state + `writer_pid`) for the real connected state before reporting a platform down, and
  never "fix" the disabling profile without the owner's intent.
- **A checker that compares config values must normalize namespaced references.** `model.provider:
  custom:<name>` is a valid reference to `providers.<name>`; comparing the raw string reports every valid
  custom provider as undefined — daily, forever. Strip the `custom:` prefix before lookup.
- **An inactivity verdict must be age-gated.** "No sessions in 30 days → retirement candidate" is false for
  a resource created yesterday: compare against the profile's creation time (`config.yaml` mtime) and skip
  anything younger than the window, or every new profile is born a retirement candidate.
