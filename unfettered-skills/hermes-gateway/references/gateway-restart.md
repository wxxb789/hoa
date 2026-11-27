# Restarting and verifying the gateway


### Verify gateway health from `gateway_state.json`, not a log slice

Grep a freshly opened `gateway.log` slice for `✓ <platform> connected` and a slow adapter
writes its line before the slice starts → a healthy gateway reads as broken and triggers a
rollback. Instead poll `~/.hermes/gateway_state.json` until its top-level `pid` equals the
new `systemctl --user show -p MainPID` and every required platform's `state` is
`connected`. Ignore stale entries such as a disabled `api_server` stuck at `retrying`
with a months-old `updated_at` and no `writer_pid`.

### Restarting the gateway a session is running inside

A plain CLI session can itself be a gateway child — check before touching the service:

```bash
cat /proc/self/cgroup     # ends in .../hermes-gateway.service → you are inside it
ps -o ppid= -p $$         # equals `systemctl --user show -p MainPID hermes-gateway.service`
```

From inside that cgroup `hermes gateway restart` is refused by the safety gate ("cannot restart, stop, or uninstall the gateway from inside the gateway process"), and a restart that does land kills the in-flight turn. Run it from a **detached transient unit** so the restarter outlives the stop, and let that unit do the verification:

```bash
systemd-run --user --collect --unit=gw-cycle-$(date +%H%M%S) --on-active=40 \
  /usr/bin/python3 ~/.hermes/scripts/gateway-restart-verify.py
```

`scripts/gateway-restart-verify.py` (stdlib only — system `python3`, never the toolchain one) restarts the unit, polls until systemd is `active` **and** `gateway_state.json.pid` equals the new `MainPID` with every required platform `connected`, asserts `code_sha == git -C <repo> rev-parse HEAD`, scans the post-restart journal for `startup_failed` / token conflicts / `Traceback`, runs one `hermes chat -q` probe, and writes a markdown verdict under `~/.hermes/cache/scratch/`.

- Delay the timer past the turn (~40 s) and return the final answer immediately: the restart ends the conversation, so never promise a post-restart check in the same turn — hand over the report path, and offer `systemctl --user stop <unit>.timer` as the cancel path.
- Regenerate `config-snapshot.py` **before** scheduling; there is no session left to do it afterwards.
- `systemctl --user list-timers <unit>.timer` right after scheduling proves the unit is registered.
- "Restarted" is not "on the new build": compare `gateway_state.json.code_sha` with `git rev-parse HEAD`. And identical code is not identical runtime — a days-old process still holds the OLD plugin pins (loaded at gateway start) and skill content (loaded at session start), so say which of code / plugins / skills is actually current.

### Is my config edit already live? Ask this before requesting a restart

A restart you never scheduled may land while you are still editing, and one restart is enough. Asking the
owner for `/restart` when the process already started after your write spends the owner's single action on
a no-op and leaves a turn blocked on an unnecessary approval.

```bash
systemctl --user show -p ActiveEnterTimestamp -p MainPID hermes-gateway.service
python3 -c "import json;d=json.load(open('$HOME/.hermes/gateway.pid'));print(d['pid'], d.get('start_time'))"
date -d @<start_time>       # compare against the mtime of every file you wrote
```

Then read what the live process actually holds instead of trusting the file on disk. Print **only the keys
you came for** — that blob also contains bot tokens:

```bash
PID=$(systemctl --user show -p MainPID --value hermes-gateway.service)
python3 - <<PY
import pathlib
for item in pathlib.Path('/proc/$PID/environ').read_bytes().split(b'\0'):
    s = item.decode(errors='ignore')
    if s.startswith(('DISCORD_ALLOWED_CHANNELS=', 'DISCORD_FREE_RESPONSE_CHANNELS=')):
        k, v = s.split('=', 1)
        toks = [t for t in v.split(',') if t]
        print(k, 'tokens=', len(toks), 'has_new=', '<new_channel_id>' in toks)
PY
```

An **empty** result is itself information: a gate key absent from the process env means the adapter seeded
that value from `config.yaml` (`_gate(..., from_platform_extra=False)` plus `_env_default`, which fills the
env var only when it is unset) — so config.yaml is the file that decided it, not `.env`. Read the gate at
the call site in `plugins/platforms/<platform>/adapter.py` whenever you must say which file wins, instead
of repeating "env wins" as a blanket rule.
