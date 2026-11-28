# Adding a probe to `hermes_health.py`

The daily digest is one script with three layers. A new invariant goes in all three, or it silently
never runs.

## Shape

1. **Registry entry** — `REGISTRY` near the top maps a short key to `(intent_ref, action)`:

   ```python
   'hoa': ('checker-decisions.json#ops.hoa-skill-drift',
           'Commit and PR the uncommitted hoa skills/ change; the runtime reads that worktree through symlinks.'),
   ```

   `intent_ref` names where the decision lives; `action` is what a human does about it. `finding()` reads
   this entry, so a check with no registration raises `KeyError` at report time — and `validate()` rejects
   a registration with an empty ref/action or a non-positive TTL.
2. **Probe** — a pure function returning `{'probe', 'level', 'message', ...}` with `level` in
   `OK | WARN | CRITICAL`. It must never raise: catch inside, or accept that one exception aborts the
   whole digest run.
3. **Daily adapter** — `def <name>_findings(d): ...` converts the probe to a `finding(d, check, scope,
   violation)` and returns `[]` when the probe is `OK`. The scope string is stable (one per subject, not
   per value), because the runner dedupes on the `[check, scope, violation]` id.
4. **Wire it into `main()`** — `findings.extend(<name>_findings(d))` next to the other `_findings` calls;
   the `checks(d, s, now)` registry path is for snapshot-derived checks, not shell probes.
5. **Standalone flag** — `--<name>-probe` (and a plan-style alias if the file groups them) that prints the
   JSON and exits `2 / 1 / 0` for `CRITICAL / WARN / OK`, so the probe is testable without running or
   delivering the digest.

## Thresholds and noise

- Report only on a condition that has **persisted**: a dirty worktree is normal mid-edit, so compare the
  oldest dirty path's mtime against a window (~24h) and stay silent inside it.
- Never emit a fresh finding id per message or per count; the dedupe layer keys on the id, and a
  fluctuating scope re-pings every morning until the owner filters the digest.
- Keep the message actionable in one line: what is wrong, the measured value, and the command that fixes
  it. The digest is read on a phone.

## Verify both branches

```bash
python3 ~/.hermes/scripts/hermes_health.py --<name>-probe    # clean tree → level OK, rc 0
touch <watched-file>; python3 ~/.hermes/scripts/hermes_health.py --<name>-probe   # → WARN (age permitting)
python3 ~/.hermes/scripts/hermes_health.py --no-state         # main path runs, no state/dedupe mutation
```

`--no-state` is the safe way to exercise the daily path: it prints events instead of saving dedupe state,
so a manual run does not suppress tomorrow's real alert.

## Before adding one

A probe binds an owner decision (see the skill's rule 7). If nothing changes for anyone when it fires, it
is noise: attach the invariant to an existing check or drop it. One schedule family, one job — never a
new cron entry per concern.
