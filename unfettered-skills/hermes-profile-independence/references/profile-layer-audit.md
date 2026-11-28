# Auditing the profile layer (read-only sweep)

For the recurring owner request "they said: what should we have done but haven't, what are the risks,
where can we gain efficiency" about the bot fleet. Run the steps in this order; every step is read-only,
and each output maps to exactly one finding. Nothing here changes state — the point is a report the owner
can price, not a tidy-up.

## 1 Four tripwires: the fast answer is usually "clean"

```bash
/usr/bin/python3 ~/.hermes/scripts/contract-drift-check.py             # no output = 0 drift
/usr/bin/python3 ~/.hermes/scripts/profile-soul-deinherit.py --check   # head block intact per home
/usr/bin/python3 ~/.hermes/scripts/profile-skill-materialize.py --check # "all homes match …"
/usr/bin/python3 ~/.hermes/scripts/profile-layer-reconcile.py --dry-run
hermes doctor                                                          # per-home gateway + model reachability
hermes cron incidents                                                  # every entry `resolved` = no live failure
```

Report the clean ones as clean, with the command as the evidence — a sweep that only lists problems
reads as if nothing was checked. Call the scripts with `/usr/bin/python3` (or the Hermes venv python):
the mise `python3` shim has no PyYAML, and a read-only audit then dies in `ModuleNotFoundError` — a false
red that looks like a finding. The check scripts self-re-exec through `lib/interp.py`; a
`ModuleNotFoundError` from one of them means that guard was bypassed, not that the check failed.

`hermes_health.py` is the wide one (`--timeout` defaults to 75 s). Run it alone, never beside
`daily-hygiene` (concurrent runs have reported spurious `<home>/skills unavailable`), and read the
per-run jsonl under `~/.hermes/logs/health/`: the event count varies with what changed, so compare
structures, not counts.

## 2 Declaration vs what is on disk

```bash
ls ~/.hermes/profiles/      # what exists
hermes profile list         # what is registered
```

A directory in the first list that is absent from the second is a **ghost home** — typically an empty
leftover from a restore drill (`drill-*`), 4.0 K, no `profile.yaml`. It never appears in `doctor` or
`profile list`, so only this comparison finds it. Ghosts matter less for their bytes than for what they
represent: this layer's most common lie is "the declaration is the reality".

## 3 Skills: separate the two verdict classes before counting drift

`skill-applyback-guard.py` (via the health job) emits verdicts that mean *upstream moved ahead*
(repairable) and verdicts that mean *a person must decide* (`live tree != lock (silent edit?)`, a writable
managed copy, two sources claiming one name, locked-but-missing). Only the first class is auto-healed
(rule 15). The same first-class verdict recurring in successive runs is not "drift is broken" — it is the
rate signal that upstream changes faster than a daily sweep, i.e. the case for a **trigger-based**
rematerialize keyed on the upstream change rather than a more frequent sweep.

## 4 Cron: two stores, one shape, one delivery trap

```bash
hermes cron list | head -40        # per-job: schedule, deliver, last run, dispatch
hermes cron incidents              # failures with type + first/last seen
```

- The root store `~/.hermes/cron/jobs.json` holds the `default` profile's jobs; **every other home has its
own** `~/.hermes/profiles/<p>/cron/jobs.json`. Any "which scripts does cron still run?" sweep that reads
only the root file reports live scripts as orphans and missing jobs as absent.
- The file shape is `{"jobs": [ ... ]}` — iterating `dict.values()` yields one item and makes every job
  look unreferenced. `json.load(f)["jobs"]`.
- A job whose `deliver` is `origin` posts into whichever session created it. That is fine for a one-shot
  the owner starts; for a recurring job it is a dead letter — an agent job that asks a question there is
  asking a session nobody is watching, and the question expires unread. Delivery for anything owner-facing
  goes to a channel.
- Two jobs with the same schedule across two homes (one carrying the seed script, one carrying the prompt)
  are a duplicate that both fire. Compare `schedule_display` across all stores before declaring a job
  unique.

## 5 Disk and data growth: measure, then propose

```bash
du -sh ~/.hermes ~/.hermes/{cache,installs,state-snapshots,checkpoints,logs}
du -sh ~/.hermes/profiles/*/ | sort -h
```

- `installs/` count is the health signal for the install-environment floor: one or two trees is healthy,
  dozens mean the reclaim is not running.
- `state.db` is usually the largest single grower. Break it down **before** proposing anything:

```bash
/usr/bin/python3 - <<'PY'
import sqlite3, os
con = sqlite3.connect(f"file:{os.path.expanduser('~/.hermes/state.db')}?mode=ro", uri=True)
for n, mb in con.execute("select name, sum(pgsize)/1e6 from dbstat group by name order by mb desc limit 12"):
    print(f"{n:36} {mb:8.1f}")
PY
```

Findings this probe has actually produced: `messages` is roughly half, FTS indexes ~15 %, and
`state_meta` carries `gateway.admission.result.v1.*` — one ~0.5–0.8 MB terminal-retirement tombstone per
admission, with **no retention code anywhere** (the module only encodes/loads them). Those blobs back
idempotent retry for a deleted session, so pruning them is a trade the owner decides, not hygiene.
Equally: a "archive sessions older than 90 days" proposal is worth nothing until you run
`select count(*) from sessions where last_activity_at < <cutoff>` — if that is 0, say so instead of
writing the option.

## 6 Idle homes: read sessions, not the roster

```bash
/usr/bin/python3 - <<'PY'
import sqlite3, os, glob, datetime
for db in sorted(glob.glob(os.path.expanduser("~/.hermes/profiles/*/state.db"))):
    p = db.split("/profiles/")[1].split("/")[0]
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    tot, last = c.execute("select count(*), max(last_activity_at) from sessions").fetchone()
    real = c.execute("select count(*), max(last_activity_at) from sessions where title is not null "
                     "and title not like '%PROBE%' and title not like '%Reply with%'").fetchone()
    fmt = lambda t: datetime.datetime.fromtimestamp(t).strftime('%m-%d %H:%M') if t else '-'
    print(f"{p:14} sessions={tot:<4} last={fmt(last)}  real={real[0]:<4} last_real={fmt(real[1])}")
PY
```

A home whose sessions are all probes (`Reply with exactly: PROBE_OK`) or whose last real session predates
the month is a retirement/merge candidate under the "no output in 30 days" rule — while its row in
`hermes profile list` still shows a healthy model and a running gateway, which is why the roster cannot
answer this question.

## 7 Report shape

Three blocks and nothing else: what is verified clean (with the command as evidence); findings ordered by
risk, each with its path/number; and the efficiency items with measured sizes. Any item whose execution is
destructive (deleting rows, retiring a home, removing a directory tree) goes to the owner as a question
with options — the sweep never ends in a cleanup it decided on its own.
