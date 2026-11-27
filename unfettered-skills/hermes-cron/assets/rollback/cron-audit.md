# Cron audit rollback blocks

Restore the corresponding sections in SKILL.md and references/cron-health-audit.md from these blocks. This is a topical rollback snapshot, not a live workflow or reference.

## SKILL.md: Redundancy audit

## Redundancy audit ("too many jobs, merge them")

Do not propose merges from job names alone — measure first, then merge by **shared fail mode**, not by domain
label. Full queries: `references/cron-health-audit.md` → "Redundancy and noise audit".

1. Inventory: every job's `schedule_display`, `deliver`, `no_agent`/`script`, `repeat`, `last_status`.
2. Compute **executions/day** per job from `~/.hermes/cron/executions.db` and the **non-silent ratio** from
   `cron/output/<id>/*.md` (`Status: silent (empty output)` marks a quiet run).
3. Rank by `runs/day × non-silent ratio` = messages/day. That product is the job's cost; the biggest
   product is the headline finding, and it is usually one job, not the long tail.
4. Merge candidates: several silent checkers of the same invariants (profile/config/drift/ops-claims) →
   one daily aggregator that runs each sub-script serially and prints once. Several per-repo loops sharing
   one engine → one job over a repo list. Two jobs on the same monthly window → one.
5. Keep separate only fail modes with **different detection deadlines** (a 20-minute resource alert and a
   daily invariant digest cannot share a schedule) and anything whose failure kills the detector itself
   when co-scheduled.
6. Never count a job with `last_status: null` as redundant — it has never fired. That is unverified
   coverage; observe one real run before touching it.
7. Report the target shape as three numbers: jobs before→after, executions/day before→after, owner-facing
   messages/day before→after. Get the owner's decision on the 2–3 genuine judgment calls (alert
   semantics, merged vs separate nudges, retention of a low-value audit) before editing `jobs.json`.

## SKILL.md: Health audit opening

`hermes cron status` → `cron list --all` → `cron doctor` (`✓ Cron doctor found no issues`) →
`cron incidents` (auto-resolve after next success; stale ≠ ongoing) → `cron runs <id>`. Re-run a broken
job and confirm **both** the durable run record and the output artifact
(`~/.hermes/cron/output/<id>/*.md`). Compare `last_run_at` with when the fault was fixed; for
silent-when-healthy scripts compare artifact size, not silence.

## SKILL.md: Proof

## Proof

```bash
hermes cron status && hermes cron doctor
hermes cron runs <id>                        # builtin vs direct source
ls -lt ~/.hermes/cron/output/<id>/ | head
hermes send -t discord:<id> "delivery test"  # then read the channel back
```

## references/cron-health-audit.md: Redundancy probes

Measure cost per job before proposing any merge. Three read-only probes, cheapest first.

**1. Executions per day** (`~/.hermes/cron/executions.db`, read-only):

```python
import sqlite3, json, collections
db = "~/.hermes/cron"  # expand
names = {j["id"]: j["name"] for j in json.load(open(db + "/jobs.json"))["jobs"]}
c = sqlite3.connect(f"file:{db}/executions.db?mode=ro", uri=True)
rows = c.execute("select job_id, substr(started_at,1,10) from executions "
                 "where started_at >= date('now','-7 day')").fetchall()
per_day = collections.defaultdict(collections.Counter)
for jid, day in rows:
    per_day[jid][day] += 1
for jid, days in sorted(per_day.items(), key=lambda kv: -sum(kv[1].values())):
    print(f"{sum(days.values()) / max(len(days), 1):6.0f}/day  {names.get(jid, jid + ' (deleted)')}")
```

Job ids absent from `jobs.json` are retired jobs whose rows still sit in the table — ignore them, they are
not running jobs.

**2. Non-silent ratio** (how often a job actually speaks):

```bash
cd ~/.hermes/cron/output/<job_id>
echo "runs=$(ls *.md | wc -l) spoke=$(grep -L 'Status: silent (empty output)' *.md | wc -l)"
grep -l '<first line of the alert>' *.md | sed 's/_[0-9-]*\.md//' | sort | uniq -c
```

`cron/output/<id>/` keeps a bounded number of files, so this is a recent-window ratio, not lifetime. Read
it as "fraction of runs that interrupt the owner", and multiply by runs/day.

**3. Orphan output dirs**: directory names under `cron/output/` minus the ids in `jobs.json` are leftovers
of deleted jobs. Report them as cleanup, do not treat their contents as live runs.

Do **not** use `deliveries.db` for per-job volume on this install: its `job_json` and `content` columns came
back empty, so it yields a total count with no attribution. Use the output artifacts above instead, and read
`deliver` / `last_delivery_error` from `jobs.json` for routing.

## references/cron-health-audit.md: Trigger safety pitfall

- Re-running a job from the CLI is safe for `deliver: local` jobs; for `deliver: origin` / platform
  jobs it can post into the owner's chat — confirm before triggering a report job.
