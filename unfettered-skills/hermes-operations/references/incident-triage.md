# "Hermes 不见了" triage (the whole thing vanished / sessions died mid-turn)

Symptom: the owner says Hermes was uninstalled, the app disappeared, or every session died at once.
The premise is usually wrong. Triage three layers **in this order**, and reinstall only when layer 2
actually fails — reinstalling a healthy install fixes nothing and destroys the evidence.

| Layer | Question | Proof |
|---|---|---|
| 1. Process tree | did the processes die, or is the install gone? | `journalctl --user --since`, `journalctl -u systemd-oomd`, `systemd-cgls --user`, `gateway-exit-diag.log` |
| 2. Install | is the checkout/venv intact? | `hermes --version`, `hermes pm status`, `~/.hermes/logs/update_receipts/latest.json`, `~/.hermes/logs/install.log` |
| 3. Data | config / state.db / sessions still there? | `ls ~/.hermes`, `hermes config check`, sqlite open of `state.db` |

## Layer 1 — process tree

`systemd-oomd`, the kernel OOM killer, and a unit restart all look identical from the UI. Read the
killer's own verdict, not the app's last words:

```bash
sudo journalctl -u systemd-oomd --since "<window>" --no-pager | grep -B2 -A6 "Path:"
sudo journalctl --since "<window>" --no-pager | grep -iE "oom-kill|Killed process|Consumed .* memory peak"
systemd-cgls --user --no-pager | head -30          # which cgroup a surviving process lives in
```

A `tmux-spawn-<uuid>.scope` line means a tmux pane: the desktop app / CLI working session and its
children. "Failed with result 'oom-kill'" plus a multi-GB peak is a kill, not a crash.

## Layer 2 — install state

```bash
hermes --version                     # prints install dir + method; a real uninstall cannot do this
hermes pm status                     # exit_code 0 + outcome ok + warnings []
python3 -c "import json;d=json.load(open('$HOME/.hermes/logs/update_receipts/latest.json'));print(d['outcome'],d['venv_rebuild'],d['warnings'])"
tail -30 ~/.hermes/logs/install.log  # "already in sync" = the reinstall changed nothing
```

`venv_rebuild: {ok: false, reason: "already in sync"}` after a reinstall is **proof the install was never
damaged**. Say so plainly instead of thanking the reinstall.

## Layer 3 — data

`state.db`, `config.yaml`, profiles, cron jobs. If these are present and parse, nothing was uninstalled.

## Reconstructing what the agent actually did (the forensic query)

Hermes stores every turn — including each tool call's arguments — in `~/.hermes/state.db`. This answers
"what did you run earlier" without guessing, and it survives the session being gone:

```python
import sqlite3, json, os, datetime, re
db = os.path.expanduser("~/.hermes/state.db")
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)          # read-only URI: never lock the live store
cur = con.cursor()
start = datetime.datetime(2026,1,1,0,0).timestamp()
cur.execute("""SELECT id, session_id, timestamp, tool_calls FROM messages
               WHERE timestamp >= ? AND tool_calls IS NOT NULL AND tool_calls != ''
               ORDER BY timestamp""", (start,))
for mid, sid, ts, tc in cur.fetchall():
    for c in json.loads(tc):
        fn = c.get("function", {})
        if re.search(r"<keyword>", fn.get("arguments", ""), re.I):
            print(datetime.datetime.fromtimestamp(ts), sid[-6:], fn.get("name"), fn.get("arguments")[:300])
```

Narrow by timestamp window, then by keyword (`oomd`, `rm -rf`, `pm install`, `uninstall`). Grep the
tool_calls JSON, not just the message text — commands live in the arguments, not in the prose. Correlate
the hit's timestamp with `journalctl` and file mtimes to get a causal chain instead of a suspect list.

## Reporting shape

1. **Lead with whether the premise holds** ("not uninstalled — the process tree was killed"), then the
   evidence table: timestamp → event → the log line or path that proves it.
2. **State where your own change caused it**, in plain words, including the reasoning that was wrong —
   not just the command. The owner needs the causal link, not an apology.
3. **Fix the offending layer, then say what remains armed** and offer the remaining decision as a
   one-line choice, with the rollback command next to every change.
4. A post-incident note goes in the task dir (`~/claw/tasks/<date>/<task>/incident-*.md`), and the
   original report that recommended the harmful change gets an inline correction — never a second file
   that contradicts it silently.
