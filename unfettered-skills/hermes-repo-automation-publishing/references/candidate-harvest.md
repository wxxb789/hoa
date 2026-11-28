# Candidate harvest (`skill-harvest-unfettered.py`)

The feeder that puts this runtime's own evolved skills into hoa's `unfettered-skills/` landing zone, from
where this skill's publisher ships them. Code and policy are host-side
(`~/.hermes/scripts/skill-harvest-unfettered.py`, `~/.hermes/config/skill-harvest.toml`); the repo only
ever sees candidates.

## Wiring

- `~/.hermes/scripts/repo-sync.sh` runs the harvest **before** the repo's publishing wrapper on the same 6h
  tick: one tick both lands and publishes. Landing only into the path the publisher owns is what keeps the
  pairing safe — the harvester never commits, pushes, or touches another path.
- Non-blocking flock on `~/.hermes/cache/skill-harvest.lock`. The file carries the holder's pid and
  `--verbose` names it when a run skips; otherwise a skip is silent by design. So when a manual run prints
  nothing, check the lock before believing there was nothing to do.
- Ledger `~/.hermes/state/skill-harvest.json`, keyed by host skill name: host content hash, `zone_name`, the
  landed hash, the verdict. A skill is reconsidered only when its host content changed; a landing-zone copy
  whose hash no longer matches its record was edited by hand and is reported, never overwritten.

## Names and identifiers

- A **coupled** skill (needs the runtime, its config, gateway, memory or cron) lands as `hermes-<host>` with
  its frontmatter `name` retitled to match: the zone requires the prefix, and the gate requires `name` to
  equal its directory. The host copy keeps the name its config `disabled` list, cron `Skills:` entries and
  profile skill copies already use — renaming those instead is a config-wide edit for one published name.
- **Private identifiers** (owner handle, private repositories, host names) are substituted from the local
  `[redactions]` map, in the landed copy only. A token with no mapping parks the candidate: the map is
  written down by the operator, so it stays a substitution rather than a replacement invented at check time.

## Pitfalls (each one cost a debugging session)

- The gate prints findings on **stdout** and its `N finding(s)` summary on **stderr**. A test that reads
  stdout alone reads every real finding as a broken gate — and then aborts the whole pass.
- The throwaway validation worktree must be **reset per candidate**. Without it, each check's tree grows,
  the previous candidate's findings are blamed on the next one, and cost climbs with the batch.
- A park/report dedupe must key on the **verdict**, not only the content hash. Content-keyed dedupe hides a
  changed reason indefinitely: the skill stays parked under an obsolete cause while the real blocker never
  surfaces.
- **Never keep backups under the skills tree**: any directory holding a `SKILL.md` is taken as a candidate,
  so a `.bak-*` copy of a skill parks as a nameless twin. Backups belong outside it.
- **Do not call a lock-taking `main()` from inside a persistent kernel process.** The kernel never exits, so
  the lock fd is never released and every later run is a silent no-op.
- A run killed by a timeout or SIGKILL skips its `finally` and leaves a worktree behind; the next run's
  `prepare_worktree` clears it, so no manual cleanup is needed.
