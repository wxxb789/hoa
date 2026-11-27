#!/usr/bin/env python3
"""Restart a Hermes gateway from OUTSIDE its service cgroup, then verify it came
back on the installed code with every required channel connected.

Use when the session issuing the restart is itself gateway-served (a plain
`hermes gateway restart` is refused by the safety gate, and a restart that lands
kills the turn). Schedule it detached so it outlives the stop:

    systemd-run --user --collect --unit=gw-cycle-$(date +%H%M%S) --on-active=40 \
      /usr/bin/python3 ~/.hermes/scripts/gateway-restart-verify.py

Env overrides: HERMES_GATEWAY_UNIT, HERMES_REPO, HERMES_REQUIRED_PLATFORMS
(comma separated). Stdlib only: run with the system python, not the toolchain
interpreter, which has no third-party deps but is not needed here either.
"""
import json, os, subprocess, sys, time
from datetime import datetime
from pathlib import Path

HOME = Path.home()
UNIT = os.environ.get("HERMES_GATEWAY_UNIT", "hermes-gateway.service")
REPO = Path(os.environ.get("HERMES_REPO", HOME / ".hermes/hermes-agent"))
STATE = Path(os.environ.get("HERMES_HOME", HOME / ".hermes")) / "gateway_state.json"
REQUIRED = [p.strip() for p in os.environ.get("HERMES_REQUIRED_PLATFORMS", "discord,feishu").split(",") if p.strip()]
OUT_DIR = HOME / ".hermes/cache/scratch"
REPORT = OUT_DIR / f"gw-restart-report-{datetime.now():%Y%m%d-%H%M%S}.md"

lines, failures = [], []


def say(msg):
    lines.append(msg)
    print(msg, flush=True)


def run(cmd, timeout=180):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def read_state():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def main_pid():
    _, out, _ = run(["systemctl", "--user", "show", "-p", "MainPID", UNIT], 30)
    try:
        return int(out.split("=", 1)[1])
    except Exception:
        return 0


def is_active():
    return run(["systemctl", "--user", "is-active", UNIT], 30)[1].strip()


before = read_state()
old_pid = before.get("pid")
head_sha = run(["git", "-C", str(REPO), "rev-parse", "HEAD"], 60)[1]
say("# Gateway restart + verification")
say("")
say(f"- start: {datetime.now().astimezone().isoformat(timespec='seconds')}")
say(f"- before: pid={old_pid} code_sha={str(before.get('code_sha'))[:12]}")
say(f"- installed HEAD: {head_sha[:12]}")

say("")
say("## Restart")
rc, _, err = run(["systemctl", "--user", "restart", UNIT], 180)
say(f"- systemctl --user restart {UNIT} -> rc={rc} {err[:200]}")

state, pid, deadline = {}, 0, time.time() + 240
while time.time() < deadline:
    time.sleep(4)
    state, pid = read_state(), main_pid()
    plats = state.get("platforms") or {}
    if (is_active() == "active" and pid and pid != old_pid and state.get("pid") == pid
            and all((plats.get(p) or {}).get("state") == "connected" for p in REQUIRED)):
        break

say("")
say("## Process")
say(f"- systemd: {is_active()} MainPID={pid} (was {old_pid})")
say(f"- state pid={state.get('pid')} code_version={state.get('code_version')} code_sha={str(state.get('code_sha'))[:12]}")
say(f"- served_profiles: {state.get('served_profiles')}")
if pid == old_pid:
    failures.append(f"MainPID unchanged ({pid}) — restart may not have happened")
if state.get("pid") != pid:
    failures.append(f"gateway_state pid {state.get('pid')} != MainPID {pid}")
if str(state.get("code_sha")) != head_sha:
    failures.append(f"code_sha {str(state.get('code_sha'))[:12]} != installed HEAD {head_sha[:12]}")

say("")
say("## Channels")
plats = state.get("platforms") or {}
for name in REQUIRED:
    e = plats.get(name) or {}
    say(f"- {name}: {e.get('state')} (updated {e.get('updated_at')}, err={e.get('error')})")
    if e.get("state") != "connected":
        failures.append(f"{name} not connected: {e.get('state')}")

say("")
say("## Logs since restart")
out = run(["journalctl", "--user", "-u", UNIT, "--since", "-4 min", "--no-pager"], 120)[1]
bad = [l for l in out.splitlines() if any(k in l for k in ("startup_failed", "Traceback", "token already in use", "ERROR"))]
say(f"- suspicious lines: {len(bad)}")
for l in bad[-6:]:
    say(f"  - {l[:200]}")
if bad:
    failures.append(f"{len(bad)} suspicious log line(s) after restart")

say("")
say("## Model path")
rc, out, err = run(["bash", "-lc", "cd ~ && timeout 240 hermes chat -q 'Reply with exactly: POST_RESTART_OK'"], 300)
ok = "POST_RESTART_OK" in out
say(f"- one-shot probe: {'PASS' if ok else 'FAIL'} (rc={rc})")
if not ok:
    failures.append(f"model probe failed: {(out or err)[-300:]}")

say("")
say("## Verdict")
say("- FAIL: " + "; ".join(failures) if failures else
    "- PASS: restarted onto installed code; required channels connected; model probe answered.")

OUT_DIR.mkdir(parents=True, exist_ok=True)
REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"\nreport: {REPORT}", flush=True)
sys.exit(1 if failures else 0)
