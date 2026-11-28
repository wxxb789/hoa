# Reading the health signals of a working install

"Is Hermes OK?" is a read-only sweep plus a triage table, not a repair session. Everything here is safe to
run on a live gateway.

## The sweep, in the order that answers fastest

```bash
hermes --version                                   # build, install method, python
cd ~/.hermes/hermes-agent && git status --short     # empty = runtime checkout byte-clean
uptime; last -x reboot | head -3                    # host restarts explain gateway restarts
systemctl --user show hermes-gateway \
  -p ActiveState -p SubState -p NRestarts -p ExecMainStartTimestamp
hermes gateway status --deep
hermes doctor
hermes cron list --all
python3 ~/.hermes/scripts/post-update-check.py
python3 ~/.hermes/scripts/profile-layer-reconcile.py --dry-run
python3 ~/.hermes/scripts/profile-skill-materialize.py --check    # per-home allowed_skills vs tree
python3 ~/.hermes/scripts/profile-soul-deinherit.py --check       # identity head block intact
python3 ~/.hermes/scripts/contract-drift-check.py                 # silent = zero drift
hermes sessions stats; du -sh ~/.hermes/state.db*
```

Logs: count `ERROR` lines newer than the current process start instead of grepping the whole file — a
handful of shutdown-time errors from previous boots otherwise reads as a live failure.

```python
lines = open(path, errors="replace").read().splitlines()
errs = [l for l in lines if " ERROR " in l or " CRITICAL " in l]
```

Cron history: `hermes cron list --all` is 300+ lines, so filter it (`grep -E '^\s+(Name|Last run):'`) and
then grep for `fail`; a `recovered since` marker is history, not an open incident.

## Finding → cause → action

| Signal | What it actually means | Action |
|---|---|---|
| `Previous gateway life exited UNCLEANLY … suspected_oom=False`, `uptime` shorter than the age of that exit | host reboot (Azure/host maintenance), not a crash | Confirm `last -x reboot` + ordered shutdown in `journalctl -b -1`; note `NRestarts=0` and the restart timestamp, then move on |
| `profile 'x' has no resolvable home (key 'agent:x:…')` for profiles no longer on disk | stale session-store keys left by deleted profiles; ~17 lines per boot | Cosmetic. Report it as noise; removing keys touches the gateway session index — separate, gated change |
| `hermes doctor`: missing key for `image_gen` / `video_gen` / `x_search` | optional tool capability, not breakage | Say so explicitly; never present it as the install being broken |
| `hermes doctor`: npm vulnerabilities in web / ui-tui / whatsapp bridge | upstream lockfile | Nothing to do; wait for the next release |
| `hermes doctor`: `Orphan alias: x → profile 'x' no longer exists` | alias survived a profile retirement | `hermes profile alias <n> --remove` (reversible, no restart) |
| `post-update-check`: `required cron jobs present — <names>` | either a consolidation refactor or a real loss | Diff live `cron/jobs.json` against `cron/backups/jobs.json.bak-*` / `jobs.json.pre-refactor-*`, check for successor capability, then ask the owner: re-add job or drop expectation |
| a skills check reporting one `extra` entry, often `N+1` entries vs `N` elsewhere | a skill nested one level too deep (a category dir read as a stray skill), invisible to the loader | `find` the extra; move the inner dir up one level; never `--apply` drift you have not explained (it drops extras) |
| `owner-cockpit.py`: `N alert line(s)` | a count of `- ` lines in a time window | Categorize, do not score |
| `state.db` hundreds of MB, WAL a few MB, `integrity: ok` | normal size for a long-lived install | Nothing; check `sessions stats` only if pruning is on the table |
| detached HEAD on the release tag | the install tracks `stable` as a detached ref by design | Not drift |
| `cron` job failed days ago with `GatewayClientError` + `recovered since` | the gateway was down at that instant; the scheduler caught up | Historical |

## Profile-layer sweep

Per-home invariants, all read-only and cheap. Run them before answering "are the profiles OK?".

```bash
hermes profile list                                  # registered homes + model + gateway state
ls ~/.hermes/profiles/ | wc -l                       # compare with the list: the delta is ghost dirs
du -sh ~/.hermes/{installs,cache,state-snapshots,checkpoints,state.db}
ls ~/.hermes/installs | wc -l                        # more than one live tree = churn
```

| Finding | Meaning | Action |
|---|---|---|
| `profiles/` has more entries than `hermes profile list` | ghost home dirs: a recovery drill's `drill-*` scratch home is never removed by hygiene | report it; deleting an empty unregistered dir is reversible, a registered home is not |
| daily digest: `skill-tree-drift:FAIL <home>/<skill>`, usually followed by `severity=recovered` | a materialized copy lagged an upstream change to a shared/bundled skill and the daily sweep re-applied it | expected while upstream moves — this is the fallback path. The noise is fixed by event-driven rematerialization on source change, not by a shorter sweep; only a *hand-edited* managed copy is a hard stop |
| the daily health run shows an unusually short event list | the checker has a wall deadline (`hermes_health.py --timeout`, default 75s); the event count is not a score | compare with neighbouring days and name the run you are quoting; never read "few events" as "clean" |
| a profile with zero cron jobs while 19 jobs are spread over the others | an idle bot against the "no output in 30 days → stop / merge / redesign" rule | raise as an owner decision, never as a cleanup |
| `~/.hermes/cache` in the GB range | package caches (uv/pnpm); the weekly reclaim prunes only unreferenced entries | measure with the tool's own prune and quote before → after (`references/install-disk-hygiene.md`) |

**Verify a sweep's own inputs before publishing counts.** Root `cron/jobs.json` is
`{"jobs": [...]}` (parse the key — `list(dict.values())` silently reads one job), per-profile jobs live in
`~/.hermes/profiles/*/cron/jobs.json` as well, and an unbounded recursive glob over the workspace walks
hundreds of thousands of files before it times out. A count built from the wrong input set reads as a
finding and gets challenged.

## Repo/vault sync state

`~/.hermes/cache/sync-state/<repo>.ok` and `.fail` coexist; **the newest file wins**. A stale `.fail` next
to a fresh `.ok` is not an incident — compare mtimes before diagnosing, then confirm with the repo's own log
(`~/.hermes/logs/<repo>-sync.log`, `OK pushed <sha>`).

## Reporting shape

1. Verdict in one line (usable / degraded), then the healthy evidence with the command that produced it.
2. Problems in the order they should be touched, each with impact; the one needing owner intent is flagged
   as a decision, not silently fixed.
3. Numbered decisions, one line each, so the owner can answer "1. A, 2. yes".
4. Anything deliberately deferred (e.g. session-index cleanup) named as deferred with the reason.
