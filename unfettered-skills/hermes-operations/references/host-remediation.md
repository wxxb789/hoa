# Host remediation (turning a review into applied, reversible changes)

Companion to `host-resource-review.md`. That file ends with a ranked list; this one is the write side:
order, commands, the pitfalls that only appear at write time, and the rollback that must ship with each
item. Read-only until the owner approves a specific item list.

## Order of operations

1. **Self-healing cleanup first** — package caches, rolling generations, log caps. Reversible by
   construction (they regenerate), needs no backup, and it produces the free space a swapfile will eat.
2. **The safety valve** — swap and the runtime's cgroup cap. This prevents a *class* of failure rather
   than saving a number.
3. **Kill selection policy** — systemd-oomd + slice limits.
4. **Structural rewrites** — repackaging a cache-launched service, adding an idle-session reaper.

If the pass has to be abandoned half-way, this order leaves the box protected before it is tidy.

## Swap: size from evidence, not from "more is safer"

```bash
sudo fallocate -l 8G /swapfile          # ext4 accepts it; fall back to dd if swapon rejects the file
sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw,pri=-2 0 0' | sudo tee -a /etc/fstab
printf 'vm.swappiness = 10\n' | sudo tee /etc/sysctl.d/99-<host>.conf && sudo sysctl -p /etc/sysctl.d/99-<host>.conf
```

Sizing rule: **≈1:1 of RAM is the ceiling, not a target to grow past.** Justify the existing size with
`vmstat` `si/so ≈ 0` and `/proc/pressure/memory` `full avg10` well under 1% — that means swap is parking
cold pages, which is exactly the job. Enlarging past 1:1 does not absorb a bigger spike better; it
converts a clean OOM kill into a thrashing box, and on 2 vCPU thrashing is a 5–10x slowdown with no error
message. Fail-fast beats fail-slow.

Say what would change the answer, or the size stays a matter of taste:

- `full avg10 > 10%` sustained, or
- `si + so > 100 pages/s` for more than ~10 minutes, or
- steady-state swap occupancy > 50% of the file (not during a build or a cleanup).

Then the lever is RAM, not the file.

Default `vm.swappiness = 60` makes the kernel evict cold pages it has no reason to touch; set 10 when
swap exists only as a safety valve. Keep the swapfile on the root volume: a swapfile on a cloud
"Temporary Storage" disk vanishes at rebuild while fstab still points at it.

## journald: restart before vacuum, or the vacuum is a no-op

Drop-in `/etc/systemd/journald.conf.d/99-size-limit.conf`: `SystemMaxUse=1G`, `SystemMaxFileSize=128M`,
`RuntimeMaxUse=256M`. Then `systemctl restart systemd-journald` and only afterwards
`journalctl --vacuum-size=1G`.

**`--vacuum` on its own can print `freed 0B` while the directory is still multi-GB** — the cap is a
config value journald has not re-read yet. Restart, then vacuum, then prove it with
`journalctl --disk-usage`. Restarting journald is safe; it costs nothing but recent in-flight lines.

## Filesystem and writeback

- `discard` in fstab **plus** `fstrim.timer` is redundant: inline TRIM on every unlink adds latency
  spikes on large deletes. Drop `discard`, keep the weekly timer, and apply it without a reboot with
  `mount -o remount,nodiscard /` — confirm with `findmnt -no OPTIONS /` that it actually went away.
- `vm.dirty_ratio = 20` on a 7–8 GB host means ~1.5 GB of dirty pages before writeback starts; a burst
  write then stalls readers and shows up as `io full` in `/proc/pressure/io`. Prefer absolute limits:
  `vm.dirty_bytes=268435456` + `vm.dirty_background_bytes=67108864`. Setting the `_bytes` form
  auto-zeroes the ratio form — that is expected, not a regression.

## Capping the runtime without restarting it

- `MemoryHigh` (throttle + reclaim) before `MemoryMax` (kill). Put the line a few multiples above steady
  state and just under the unit's observed peak; `systemctl show -p MemoryPeak` or the `Memory: peak:`
  line in `systemctl status` is the number to use, not the current value.
- Apply live: a drop-in for boot, plus `systemctl --user set-property <unit> MemoryHigh=3.5G` for the
  running cgroup. Verify with `systemctl --user show <unit> -p MemoryHigh -p MemoryCurrent`.
- **Never `systemctl restart user@<uid>.service` to pick up a unit property.** It tears down every process
  in the user manager — gateway, desktop sessions, the shell you are typing in. `set-property` on the
  running cgroup + a drop-in for the next boot is the whole recipe.

## systemd-oomd: the install IS the change — know what the package arms

Ubuntu's `systemd` ships
`/usr/lib/systemd/system/user@.service.d/10-oomd-user-service-defaults.conf` containing
`ManagedOOMMemoryPressure=kill` + `ManagedOOMMemoryPressureLimit=50%`. That drop-in is inert only while no
oomd is running, so `apt-get install -y systemd-oomd` arms "kill the whole user session at 50% pressure"
for every login. Raising the limit afterwards moves the threshold; it does not remove the policy.

Look before and after:

```bash
dpkg -L systemd-oomd | grep '\.d/'                      # what the package ships
systemctl show user@<uid>.service -p DropInPaths \
  -p ManagedOOMMemoryPressure -p ManagedOOMMemoryPressureLimit
sudo oomctl | sed -n '/Monitored CGroups/,$p'           # what is actually armed
```

Safe shape: give oomd the **swap** valve only (`SwapUsedLimit=90%`, a real stall), and bound the process
that can actually grow with `MemoryHigh` on its own unit.

If the owner does want a memory-pressure kill, **the marked cgroup IS the victim pool**, and the choice
of level is the whole design. Dump the tree before picking one:

```bash
systemd-cgls /user.slice/user-<uid>.slice --no-pager
```

On a desktop-app host it looks like this:

```
user-1000.slice
├─ session-*.scope          ← UI backends live HERE, as siblings
└─ <user>@example.com
   └─ app.slice/hermes-gateway.service
```

- Marking `user@<uid>.service` gives oomd **exactly one candidate — the gateway** — because nothing else
  of size lives in that subtree. The kill lands on the interface, not on the memory hog. This is the
  failure that looks like protection.
- Marking the **slice** is the level that contains the actual consumers, so it is the right granularity
  *once the interface is `omit`ted*. It is still a heuristic: oomd kills the **fattest cgroup**, which
  can be a tmux pane carrying the desktop app (observed: 16 processes, 3.6 G peak) while the real
  consumer sat in another cgroup of the same slice. Accept that, or leave oomd on the swap valve only.
- Either way verify the pool after the change: `oomctl` must list the path you meant, and nothing you
  need. An empty `Memory Pressure Monitored CGroups:` means nothing is armed, not that it is safe.

Disarm, reversible, no restart:

```bash
sudo systemctl set-property user@<uid>.service ManagedOOMMemoryPressure=auto   # /etc wins over /usr/lib
sudo oomctl | sed -n '/Monitored CGroups/,$p'          # "Memory Pressure Monitored CGroups:" now empty
```

Remaining pitfalls:

- `systemctl show` prints `ManagedOOMMemoryPressureLimit` as **bytes** (80% × 4 GiB); `oomctl` prints the
  real percentage under `Memory Pressure Limit`. Trust `oomctl` and do not "correct" the value.
- `set-property` persists to `/etc/systemd/system.control/<unit>.d/50-ManagedOOM*.conf` — it survives
  reboot. That file is what to diff when a property you disarmed comes back.
- Keep `ManagedOOMSwap=kill` when disarming the pressure kill: swap at 90% is a genuine stall, and it is
  the only valve left if `MemoryHigh` throttling is not enough.
- oomd only acts on cgroups that carry the property — marking the slice is the step that makes it real,
  which is exactly why marking a *slice* is the wrong granularity.
- Never `systemctl restart user@<uid>.service` to apply a property (see above).

## Reaping idle UI sessions

Each desktop/dashboard window is a full agent process that never exits on its own. The idle test must
require **all three** conditions:

1. wall-clock age > threshold (hours, not minutes),
2. `cpu_time / age < 1%` — a session streaming a turn keeps burning CPU,
3. **zero children** — a running tool call appears as a child of the agent process.

Age alone reaps a session mid-answer; CPU alone never fires on a session waiting for input.

Pitfall: `/proc/<pid>/task/<pid>/children` is a **file** containing a space-separated pid list, not a
directory. `os.listdir` on it raises, and a bare `except OSError: return 0` silently turns the
"has children" guard into a constant zero — the guard you believe is protecting a running tool call does
nothing. Read the file and split it.

Ship it as a systemd **user** timer, threshold in `Environment=`, one log line per reap (`pid / rss /
age / cpu`), and SIGTERM rather than SIGKILL so the process can persist before exiting.

`systemctl --user enable --now` on a timer whose `OnBootSec` has **already elapsed** fires the service
immediately — the install itself performs the first reap against live sessions. Either run the script's
`--dry-run` once before enabling, or accept that the first pass is a real rehearsal and say so when
reporting it.

This reaper owns *UI agent* sessions. The next section owns the `serve --isolated` backends the desktop
app spawns; they are different processes with different idle signals — do not merge the two tests.

## App-spawned backends: reap, or hand them to systemd — there is no restart

The desktop app does not connect to one server; it spawns one backend per SSH session:

```
hermes serve --isolated --host 127.0.0.1 --port 0 \
  --ssh-session-token-file ~/.hermes/desktop-ssh/<session>/<nonce>.token --ssh-owner-nonce <nonce>
```

Those are children of the app, not units: `systemctl` cannot restart them, and each reconnect attempt
leaves the previous backend running. Observed after one OOM kill: 15 backends, 3368 MB RSS (≈190 MB each,
634 MB for the live one), 13 of them silent since the reconnect storm. That leak is what pushes an 8 GB
host into pressure — the kill is the symptom, so cleaning it is part of the incident, not a follow-up.

Supervision map — say it plainly when the owner asks "why didn't it restart":

| component | owner | after SIGKILL |
|---|---|---|
| `hermes-gateway.service` | systemd user unit, `Restart=always`, `RestartSec=5` | back in seconds, unassisted |
| `serve --isolated` backend | the desktop app | only on the app's next connect, and the old one stays |
| machine-level `hermes serve --port 9119` | a systemd unit you create | back in seconds — the only shape where "killed" self-heals |

Safe reap — all four guards, or it breaks a live window:

1. cmdline has ` serve ` **and** `--isolated` (never the machine-level server),
2. the per-session log under `~/.hermes/desktop-ssh/<session>/` is silent for N minutes,
3. **no children** — a running tool call is a child of the backend,
4. **never the freshest session** among the candidates — that is the window the owner is looking at,
   even when it has been quiet past the threshold.

Guard 4 is the easy one to omit and the one that matters: without it a window left idle over lunch is
reaped the moment it crosses the threshold. Ship as a systemd user timer (10-minute tick, SIGTERM then
SIGKILL after ~15 s, one log line per pid with rss and idle minutes). Live script:
`~/.hermes/scripts/desktop-ssh-reaper.py` (`--dry-run`); its knobs are `Environment=` on
`hermes-desktop-ssh-reaper.service` — `REAPER_IDLE_MINUTES`, `REAPER_MAX_KILLS`, `REAPER_KEEP_FRESHEST`,
`REAPER_MIN_SURVIVORS`, `REAPER_MAX_BACKENDS`.

**Idle minutes alone cannot bound a storm.** A client that reconnects through a rotating cloud-NAT pool
re-spawns a burst (10 backends in one second, ~570 SSH logins in 30 min observed) faster than any idle
threshold expires them, so a reaper tuned only on idle tidies a leak it can never catch up to. Two knobs
are required: `REAPER_MAX_KILLS` above the burst size, and `REAPER_MAX_BACKENDS` as a hard count cap
(freshest N immune, excess reaped oldest-idle-first). Tune both with the script's `--dry-run`: its
candidate list filters on the `session-*.scope` cgroup, which makes it authoritative where `pgrep` is not.
The backend count matters beyond memory — every live backend holds `state.db`, which blocks
`hermes sessions optimize-storage` even with the gateway stopped.

Prove the session you are typing in survived: `free -m` before/after plus
`curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:<live port>/`.

### Inspecting those processes without flooding the context

The Hermes launcher's cmdline is the **entire bootstrap script** (~6 KB per process). `ps -eo cmd`,
`hermes serve --status`, and any `pgrep` loop that prints `$cmdline` dump 90–100 KB for a dozen backends —
enough to burn the context window in one call.

- Print `comm`, `pid`, `rss`, and `cut -c1-120` of the cmdline; never the whole line.
- `pgrep -fc <pattern>` counts **itself** when the pattern matches the command line — subtract one or
  filter on `/proc/<pid>/comm`. `pkill -f <pattern>` is worse: it terminates the shell running the command
  (exit 15), because that shell's own cmdline contains the pattern, so a cleanup loop dies half-way and
  reads as a crash. Kill by PID from a `/proc` enumeration that excludes `os.getpid()` **and its ancestor
  chain**; reusable form: `scripts/state-db-holders.py --reap-backends`.
- Correlate a backend to its session with the `desktop-ssh/<session>` fragment only; the token and nonce
  after it are noise for everything except launching.

### Protecting the interface from the killer

Two killers, two knobs — and only one of them works from a user unit.

| knob | steers | effect |
|---|---|---|
| `ManagedOOMPreference=omit` | systemd-oomd | removes the cgroup from the candidate list |
| `ManagedOOMPreference=avoid` | systemd-oomd | keeps it, but only as a last resort |
| `OOMScoreAdjust` | the kernel OOM killer | **negative values do not apply in a user unit** |

```ini
# ~/.config/systemd/user/hermes-gateway.service.d/20-oom-protection.conf
[Service]
ManagedOOMPreference=omit
```

- **`omit` needs the cgroup xattr, and oomd honours it under memory pressure only when the unit's cgroup
  owner equals the marked ancestor's owner.** Both are the login UID here, so it is honoured; against a
  root-owned ancestor such as `-.slice` it would be ignored silently.
- **`OOMScoreAdjust=-300` is a no-op in a user unit.** Lowering `oom_score_adj` needs
  `CAP_SYS_RESOURCE`, which the user manager does not have; `user@.service` carries `OOMScoreAdjust=100`
  and children inherit it. The unit reads `-300` while the process reads `100`. Never present that line
  as kernel-OOM protection — either accept the gap or move the service to the system manager (which has
  the privilege, at the cost of re-doing HOME/XDG for it).
- `systemctl set-property` rejects `OOMScoreAdjust` outright ("Cannot set property …"), so a drop-in is
  the only path — which is exactly why the no-op is easy to miss.
- Prove the xattr landed rather than trusting `systemctl show`:
  `python3 -c "import os; p='/sys/fs/cgroup/…/<unit>'; print({n: os.getxattr(p,n) for n in os.listxattr(p)})"`
  → `{'user.oomd_omit': b'1'}` (`user.oomd_avoid` for `avoid`).
- **`sudo systemctl --user …` fails with `Failed to connect to bus: No medium found`** — sudo drops
  `XDG_RUNTIME_DIR`. Run user-unit commands as the owner with no sudo; inside an `&&` chain the failure
  is swallowed and the next line still reports success (a "sent SIGKILL" that killed nothing).

### "Will it actually come back?" — kill it and time it

`Restart=always` in a unit file is a claim. One SIGKILL is the proof, and it costs a few seconds:

```bash
old=$(systemctl --user show hermes-gateway -p MainPID --value); t0=$(date +%s%3N)
systemctl --user kill -s SIGKILL hermes-gateway
until new=$(systemctl --user show hermes-gateway -p MainPID --value); \
      [ -n "$new" ] && [ "$new" != 0 ] && [ "$new" != "$old" ]; do sleep 0.2; done
echo "recovered in $(( $(date +%s%3N) - t0 )) ms"
```

Expect `Main process exited, code=killed, status=9/KILL` → `Scheduled restart job, restart counter is at
N` → `Started`, and `NRestarts` +1. Observed 8.3 s (5 s `RestartSec` + startup); `RestartSec=2` is
usually safe to cut that further. `StartLimitIntervalSec=0` means it never gives up — right for an
interface, wrong for a crash loop, so a process that can fail repeatedly wants `RestartSteps` +
`RestartMaxDelaySec` for backoff. **Re-probe the listener by the new PID**: an ephemeral port (`--port 0`)
changes on restart, and a stale-port `curl` returning `000` reads as "still down".

## Python env slimming (the venv that carries CUDA on a CPU-only host)

```bash
pipx install <pkg> --force \
  --pip-args="--index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple"
pipx runpip <pkg> list | grep -iE '^(nvidia|triton|cuda)'
pipx runpip <pkg> uninstall -y <those packages>
```

- **`pipx reinstall` does not accept `--pip-args`** (only `install` does). It dies in argparse, exits 0-ish
  in a pipeline, and leaves the venv untouched — which reads as "no change" rather than "not run".
- The `+cpu` wheel wins because a local version identifier sorts above the plain one; the
  `--extra-index-url` keeps ordinary dependencies resolvable.
- **`--force` reuses the existing venv**, so the old CUDA dependency tree survives it. Measure, then
  uninstall the orphans explicitly: one observed case went 7.2 GB → 6.6 GB from the reinstall alone, and
  → 1.2 GB only after removing `nvidia-*` / `triton` / `cuda-*`.
- Verify with `python -c "import torch; print(torch.__version__, torch.version.cuda)"` — expect `+cpu` and
  `None`, then load the real model, not just the import.
- **Probe a venv's interpreter with `env -u PYTHONPATH -u PYTHONHOME`.** A shell inside Hermes exports its
  own site-packages; that path leaks into the venv and produces a false
  `No module named 'numpy._core._multiarray_umath'`. The venv is fine, the test is not — never conclude a
  venv is broken from an in-Hermes probe.
- Before optimizing a package, prove the runtime imports it: `grep -rn "<import>" --include=*.py <runtime>/`
  in the installed source. A CLI on PATH is not evidence — a 7 GB `whisper` install sat beside a runtime
  that only ever imported `faster_whisper`.

## A service launched out of a package cache

`bunx <pkg>@latest` runs the binary from the bunx cache, which means (a) clearing the cache breaks the
service until reinstall and (b) every restart may silently change version.

Fix, in this order: `bun add -g <pkg>` → repoint the unit's `ExecStart` at `~/.bun/bin/<pkg>` →
`daemon-reload` + restart → prove it (listener + an HTTP probe with a real status code) → only then
`bun pm cache rm`. Clearing first breaks the running service and turns a 4 GB reclaim into an outage.

## Make the reclaim persist

A one-off cleanup regresses: caches refill, generation backups accumulate, journal regrows. Every reclaim
needs a periodic counterpart or it is undone within a quarter.

- Weekly job over an **allowlist** (cache dirs, rolling generation dirs with `keep=N`), never a predicate
  like "older than N days" over a directory it does not own.
- **Silent below a report threshold** — a job that pings every week with "freed 0 MB" is a negative asset.
- `no_agent` cron that delivers script stdout verbatim is the right shape: the script already emits final
  text, so no LLM turn is spent.
- Alerting is part of the same discipline: a watchdog that only tracks RSS cannot answer "is memory
  tight". Add PSI `full avg10`, swap-used %, and the `pswpin/pswpout` delta between runs as separate
  signals in the existing level state machine, and keep the silent-when-ok contract.

## Package caches: one name, several directories

A "cache" is rarely one path. On this host uv's downloads sit in `~/.hermes/cache/uv` (~2.5 GB),
a second `~/.cache/uv` holds a few hundred KB, and pnpm's store is a third location entirely
(`pnpm store path` → `~/.local/share/pnpm/store/v11`). Enumerate before pruning:

```bash
du -sh ~/.hermes/cache/* ~/.cache/uv ~/.cache/pnpm 2>/dev/null; pnpm store path
```

- **`uv cache prune` prunes the tree uv chooses, not the one you measured.** It prints
  `Pruning cache at: <dir>`; if that path is not yours the run reports `No unused entries found` while
the real cache is untouched. Pass `UV_CACHE_DIR=<dir>` explicitly, per directory.
- **Score by measured bytes, not by the tool's own summary.** Take `dir_size` before and after each
  prune and report the delta; a prune that prints "Removed 0 files" still can leave 1 GB gone from
  another tree, and the opposite reading ("freed nothing") hides a real reclaim.
- **A prune cannot reclaim what a venv still hardlinks.** Wheels referenced by the active venv stay
  until `uv cache clean`, which forces a full re-download on the next install — a tradeoff for an
offline window, never part of a scheduled cleanup.
- **Only `prune` verbs belong in a cron job.** `cache clean` / `store prune --force`-style nukes turn a
  routine reclaim into a rebuild-everything event on a host that may be offline later.
- **Resolve the binary through PATH *and* the mise shims** (`~/.local/share/mise/shims/<cmd>`): a cron
  unit and an interactive shell do not share the same PATH, so the job silently skips a present tool.

## Install environments: one tree per input combination, and nothing prunes them

`~/.hermes/installs/<install-hash>/environments/<input-hash>/` accumulates one tree per dependency-input
combination (`pm/runtime.py:_inputs` = `pyproject.toml` + `uv.lock` + the python path). Nothing expires
them: one host reached 37 trees / 18 GB, and the tree count grows with *normal* operations, because any
operation that runs a dependency install creates one — `hermes profile create/delete`, plugin installs,
and the first start of a **new profile** (every clone, and every restore drill: a full-fleet drill adds N
trees while it proves N homes can boot).

```bash
# enumerate, then prune: live = whatever facts.json points at
python3 - <<'PY'
import json, pathlib
for e in pathlib.Path.home().glob('.hermes/installs/*/environments'):
    blob = (e.parent/'facts.json').read_text()
    trees = sorted((p for p in e.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True)
    print(e.parent.name, 'total', len(trees), 'live', sum(t.name in blob for t in trees))
PY
```

- **One pointer, not a heuristic:** `facts.json` names the live environment(s). Keep live + the **newest
  2** unreferenced trees, delete the rest.
- **Age is not a usable criterion.** Every non-live tree can be same-day (they are created by the day's
  activity), so an "older than N days" rule reclaims **zero** exactly when the disk is filling. Use age
  only as a floor (`≥ 1 h`) so a mid-flight install is never deleted under itself.
- **Measure with `df`, not by summing subtrees.** Trees are hardlink-heavy, so `du -s` over the doomed
  set is an upper bound (observed: 16.5 GiB summed vs ~11 GiB actually freed). Count afterwards instead:
  `ls ~/.hermes/installs/*/environments | wc -l` should equal live + kept.
- Ship the prune inside the daily hygiene script, next to the package caches, and say which trees went in
  the same ZH line — an irreversible delete needs a line the owner can find later.

## Reporting

- Every change gets its rollback on the same line.
- A before → after table for exactly the numbers claimed; a reclaim total is the sum of individually
  verified items, not a round number.
- An explicit **"not doing, because"** section for anything the owner's constraint excluded (a layer they
  said not to touch, an upgrade they ruled out). Silently dropping those items reads as an oversight and
  invites a second round.
