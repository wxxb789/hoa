# Host resource review (the VM under a Hermes install)

Use when the owner asks whether the machine itself is healthy: "这台 VM 怎么样"、"跑得慢 / 内存爆了"、
"要不要加内存"、"能不能再挂一个常驻服务"。Different axis from `config-efficiency-review.md`, which is
about token/cache cost *inside* Hermes; this one is CPU / RAM / disk / exposure of the OS.

Read-only until the owner approves a change. Then: measure → attribute → rank → tier.

## Step 1 — headroom, not averages

```bash
uptime; nproc
free -h; swapon --show
vmstat 1 5
cat /proc/pressure/memory /proc/pressure/cpu /proc/pressure/io
sar -r | tail -5; sar -u | tail -5        # sysstat: hourly trend = steady state, not a sample
```

Decision points:

- `%idle > 80` → CPU is not the bottleneck. Do not propose vCPU; say so explicitly, because "2 vCPU"
  reads as small to a human and the instinct is to buy more.
- `%memused > 65` with `Swpd 0` → memory is the constraint and there is no safety valve.
- `some/full` stall in `/proc/pressure/io` during *your own* commands is measurement artifact; re-sample
  while idle before calling disk a bottleneck.

## Step 2 — OOM history, queried never inferred

```bash
journalctl -k --since "-7d" -o short-iso | grep "Out of memory: Killed process"
systemctl show <gateway-unit> -p MemoryMax -p MemoryHigh -p MemoryCurrent
```

- Bound the window to ≤7 days and restrict to `-k`. Grepping a multi-GB journal over 30 days blows the
  terminal timeout and presents as a hang, not an error.
- On a swapless host with `MemoryMax=infinity`, the kernel kills by heuristic score, not by blame: the
  process named in the log is a **victim**, not the offender. Report it that way, and check the offender's
  peak (`systemctl show -p MemoryPeak` / `ExecMainStartTimestamp`) rather than repeating the victim name
  as the cause.
- `MemoryCurrent` proves what a unit holds *now*; the unit's own `Memory: peak:` line in
  `systemctl status` proves what it held at its worst. Use peak when sizing a limit.

## Step 3 — attribute RSS per role, not per binary

Everything is named `hermes`, so `ps -eo rss,comm` lumps a 900 MB gateway with five 300 MB UI sessions.
Read the cmdline tail per PID:

```bash
for p in $(ps -eo pid,comm --no-headers | awk '$2=="hermes"{print $1}'); do
  printf "%s %sMB %s\n" "$p" "$(awk '/VmRSS/{printf "%.0f",$2/1024}' /proc/$p/status)" \
    "$(tr '\0' ' ' </proc/$p/cmdline | tail -c 120)"
done
```

Three roles to separate:

| cmdline tail | role | expected weight |
|---|---|---|
| `... gateway run` | the gateway | largest single process; peak matters |
| `--ssh-owner-nonce <hex>` | one desktop/Dashboard UI window | 250–650 MB **each**, PPID 1 |
| short-lived / no args | cron, subagent, one-shot | transient |

Each open UI window holds a full agent process with its own context, and it survives until that
process is killed. Count them before blaming the gateway: past a few days of normal use they are
usually the largest *aggregate* block on the box. If they accumulate, propose an idle reaper (script +
systemd timer) rather than assuming one exists — and say the count out loud, because the owner controls it.

## Step 3b — desktop reconnect storm: measure the rate, not the moment

`--ssh-owner-nonce` backends are spawned per SSH login, not per UI window, so a reconnect loop leaves
several of them per session and the reaper's cap is the only thing bounding the count. "Is it still
happening" is therefore a rate question: answer with a multi-day series plus the last event, never with
this minute's `ss` output.

```bash
# per-day login rate — the trend is the finding
for d in $(seq 0 4); do day=$(date -d "-$d day" +%F); printf "%s %s\n" "$day" \
  "$(journalctl -u ssh --since "$day 00:00" --until "$day 23:59:59" | grep -c Accepted)"; done
journalctl -u ssh --since today | grep Accepted | grep -oP 'from \K[0-9a-f.:]+' \
  | sort | uniq -c | sort -rn              # one client = one key, several egress IPs
ss -tn state established '( sport = :22 )' | tail -n +2 | wc -l    # current, not history
journalctl --user -u hermes-desktop-ssh-reaper.service --since today | grep -oP 'cap: \K[0-9]+(?= backends)' | sort -rn | uniq -c
journalctl --user -u hermes-desktop-ssh-reaper.service --since today | grep -c '  reap '
systemctl --user cat hermes-desktop-ssh-reaper.timer | grep -E 'On(UnitActiveSec|Calendar)'   # cadence
sar -r -f /var/log/sysstat/sa$(date +%d)    # peak %memused, correlate with the burst hours
grep -c 'Multi-profile hosting activated at startup' ~/.hermes/logs/gui.log   # backend boots, all days
```

Reading it:

- **Same key fingerprint from several IPs = one client behind an egress pool**, not several attackers.
  Name it as client-side reconnect amplification; the server-side reaper bounds the damage, it does not
  fix the cause, so the verdict is "mitigated, not solved" unless the login rate itself fell.
- `session opened` ≫ `session closed` is normal: aborted reconnect attempts never get a clean PAM close.
  The imbalance is not a leak — `ss` proves what is actually live. `who`/utmp does not: it lists pts
  entries synthesized for long-lived tmux panes, so a four-line `who` can sit on a box with zero SSH
  connections.
- **Backend spawns ≠ logins.** Count `~/.hermes/desktop-ssh/*/` nonce dirs for distinct desktop sessions
  (concurrent backends share one nonce dir); the reaper journal's `cap: N backends > M` line is the real
  concurrency, and `grep -c '  reap '` is the real churn. Thousands of logins with ten nonce dirs means
  the client retries far more often than it starts a backend.
- **The reaper's own log file can be stale or absent** — the sweep record the unit actually emits is
  journald (`journalctl --user -u hermes-desktop-ssh-reaper.service`), which can hold today's runs while
  `~/.hermes/logs/desktop-ssh-reaper.log` still ends weeks earlier. Quote the journal, and read the cadence
  from the timer unit (`OnUnitActiveSec`): a drop-in overrides `Environment=` only, so the schedule drifts
  independently and a cadence recalled from a past session is a wrong denominator.
- **Count boots, not just survivors**: every backend boot logs `Multi-profile hosting activated at startup`
  in `gui.log`, so `grep -c` gives the day's spawn total (≈ reaped + still alive) and makes the churn
  quotable as one number. Normalizing the log to message templates
  (`sed -E 's/[0-9]+/N/g' | sort | uniq -c | sort -rn`) surfaces the day's event mix — `ws accepted`,
  `client_disconnect`, `event loop stalled` — in one shot instead of grepping message by message.
- **`pgrep -fc -- '--ssh-owner-nonce'` counts its own shell** and answers 1 with zero backends alive.
  Confirm with `ps -eo pid,args | grep -- '--ssh-owner-nonce' | grep -v grep`; a count you cannot name a
  PID for is zero, and reporting it as a live leak sends the owner chasing nothing.
- **Weight is warm-up dependent** — 42–50 MB cold overnight, ~197 MB after a profile-ticking warm start.
  Quote the observed range, not a single number.
- **The user-visible damage is in `~/.hermes/logs/gui.log`**: `event loop stalled Ns (GIL pressure
  suspected)`. Each backend also ticks cron for every served profile, so the storm costs CPU/GIL as well
  as RSS — a memory-only verdict undersells it.
- **Attribute swap before blaming the storm**: `awk '/^Swap:/{print $2}' /proc/<pid>/smaps_rollup` per
  process; dev toolchains (dotnet MSBuild nodes, the coding-agent CLI) normally hold the swap.
- **A quiet window is not a fix.** If the last login was an hour ago, report "last event HH:MM:SS, quiet
  since; today 5102 by 10:21" together with the growth trend — not "fixed".

**Pitfall that costs a whole table**: parse journal fields with an anchored regex
(`grep -oP 'from \K[0-9a-f.:]+'`), never by awk column position. The syslog timestamp occupies two
fields, so `$(NF-3)` silently yields ports and produces a plausible but entirely wrong per-IP ranking.

## Step 4 — disk: find the duplicated weight

```bash
du -h --max-depth=1 ~ | sort -rh | head -20
du -h --max-depth=1 ~/.hermes | sort -rh | head -25
du -h --max-depth=1 /var/log | sort -rh
journalctl --disk-usage
lsblk -d -o NAME,ROTA,SIZE,MODEL; cat /etc/fstab; mount | grep -v tmpfs
```

Pitfalls that cost a pass each:

- **`du` on a profile's `skills/` does not measure skill content** when the entries are symlinks back to
  the root library. The weight sits in `skills/.curator_backups` (a full snapshot per curator run, one
  copy per profile) and `skills/.hub/index-cache`. Prune to the newest snapshot per location.
- **A small model can carry a multi-GB venv.** A pipx CLI whose only job is one 139 MB model can ship
  7 GB of CUDA/torch wheels. Compare model size against venv size before declaring the package needed;
  the fix is a CPU-only reinstall (`--index-url https://download.pytorch.org/whl/cpu`), not deletion.
- **Browser-automation ecosystems stack up.** puppeteer + playwright + camoufox coexist by default at
  ~1.5–3 GB each; confirm which one the tooling actually launches before pruning.
- **Package-manager caches are the cheapest win** (npm / uv / pnpm / bun, often 8–12 GB combined) — but
  check what executes *from* the cache first: a `bunx`-launched service runs out of its cache directory,
  so clearing it breaks that service until reinstall. Pin the service properly, then clear.
- **Look for a second block device before recommending cleanup of the root disk.** Cloud images often
  mount a Temporary Storage disk that is empty; `DATALOSS_WARNING_README.txt` or the label `Temporary
  Storage` means rebuildable-cache-only, never state.
- `journald` with no `SystemMaxUse` grows without bound (multi-GB is normal after a year). Capping it is
  a one-line drop-in, and it is the safest reclaim item because it costs nothing functional.

## Step 5 — exposure

```bash
ss -tulpn | grep LISTEN        # no sudo needed for your own processes
```

Every listener that is not `127.0.0.1` is a decision, not an observation. Local model/proxy bridges
routinely default to `0.0.0.0` (a Copilot-style proxy on `*:4141`), and desktop images leave CUPS on
`:631`. State the cloud-firewall caveat honestly: from inside the guest you cannot prove the port is
reachable, so report "bound to 0.0.0.0 inside the guest; NSG status unverified" — never "exposed to the
internet" as fact.

Prefer non-sudo reads first (`ss -tulpn`, `grep` on world-readable `/etc/ssh/sshd_config`). A `sudo`
command can stall the whole batch waiting on an approval prompt, which reads as a timeout rather than a
denied permission.

## Step 6 — drift that only shows up in the log

```bash
journalctl --user-unit <gateway-unit> --since "-24h" | tail -40
```

`hermes doctor` reports capability gaps; the gateway log reports *state* gaps. Recurring warnings worth
fixing rather than tolerating:

- a pinned `model.context_length` larger than the provider advertises (silently fails on long input),
- orphan profile aliases after a profile was deleted,
- a `SessionDB ... did not settle` error naming a profile directory that no longer exists — a stale
  registry handle from a long-running gateway, cleared by a restart.

## Output shape

Ranked problems, each with the evidence line that proves it, then three tiers:
**now** (reversible, ≤30 min) / **this week** (needs a script or a restart window) / **structural**
(needs the owner's decision). Every item carries the number it changes. Close with the single decision
that gates the rest — a review that ends with twenty equal-weight suggestions has not made a decision.

State the honest total: a reclaim figure is the sum of individually verified items, not a round number.

## Resource budget — the gate for "can we add another resident service?"

Express as fractions of RAM so it survives a resize:

```
resident agent processes   ≤ 20% of RAM
OS + system services       ≤ 20% of RAM
variable (builds, browsers, parallel subagents) ≤ 40% of RAM
safety margin              ≥ 20% of RAM  (or swap, once it exists)
```

Any proposal to add a long-running component must name which line it comes out of. On a small box the
correct answer to "add another always-on bot" is usually "which one are you retiring", not "buy RAM" —
offer the resize as the second option with its cost, not the first.
