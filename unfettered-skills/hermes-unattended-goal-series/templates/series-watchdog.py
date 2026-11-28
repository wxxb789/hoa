# Template: liveness watchdog for an unattended series driver.
#
# Copy beside the series' conductor, patch the CONSTANTS block, install as a Hermes cron job:
#   cronjob_manage action=create, schedule="every 30m", no_agent=true, script=<path to this file>,
#   deliver=<owner DM or board>
# Behaviour: prints one short alert and exits; prints NOTHING when healthy (empty stdout = nothing sent),
# so the job is silent by default and costs no model turn.  Stdlib only, cross-platform paths via HOME.
#
# Keep the three conditions below and the dedupe snapshot: a stuck series that pings every tick trains the
# owner to ignore the alert that matters.

from __future__ import annotations

import datetime
import hashlib
import json
import pathlib
import re
import subprocess
import sys

# ---- CONSTANTS (patch per series) ---------------------------------------------------------------
HOME = pathlib.Path.home()
SERIES = "<series>"                                  # slug: task dir name and ledger repo column
TASK = HOME / "claw/tasks/<date>/<series>"            # conductor.py, logs/, BLOCKED.md, state file
STATE = TASK / "conductor-state.json"                 # {"goal","stage","status","updated"}
BLOCKED = TASK / "BLOCKED.md"
LOGS = TASK / "logs"
LEDGER = HOME / "claw/tasks/delivery-state.tsv"        # ts<TAB>repo<TAB>goal<TAB>stage<TAB>...
UNIT = "<series>-conductor.service"                   # systemd --user unit, or "" when launched otherwise
TOTAL_GOALS = 12                                     # how many rows with stage=done mean "series finished"
STALL_HOURS = 4.0                                    # running with no state-file advance for this long = hung
REPEAT_HOURS = 6.0                                   # re-send the identical alert at most this often
SNAP = HOME / f".hermes/cache/{SERIES}-watchdog-state.json"
# ------------------------------------------------------------------------------------------------


def now() -> datetime.datetime:
    return datetime.datetime.now()


def unit_active() -> bool:
    if not UNIT:
        return True
    try:
        out = subprocess.run(["systemctl", "--user", "is-active", UNIT],
                             capture_output=True, text=True, timeout=30)
    except Exception:
        return True  # unknown liveness never fabricates a death alert
    return out.stdout.strip() == "active"


def read_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def merged_count() -> int:
    """Rows the operator wrote for this series with stage=done (the driver's own acceptance record)."""
    if not LEDGER.exists():
        return -1
    goals = set()
    for line in LEDGER.read_text(encoding="utf-8", errors="replace").splitlines():
        cols = line.split("\t")
        if len(cols) < 4 or cols[0] == "ts":
            continue
        if cols[1] == SERIES and cols[3] == "done":
            goals.add(cols[2])
    return len(goals)


def series_finished() -> bool:
    if read_state().get("status") in {"merged-all", "finished"}:
        return True
    if merged_count() == TOTAL_GOALS:
        return True
    for log in sorted(LOGS.glob("conductor-*.log")):
        try:
            tail = log.read_text(encoding="utf-8", errors="replace")[-4000:]
        except Exception:
            continue
        if "finished all requested goals" in tail:
            return True
    return False


def blocked_alert() -> str | None:
    if not BLOCKED.exists():
        return None
    body = BLOCKED.read_text(encoding="utf-8", errors="replace").strip()
    goal = stage = reason = "?"
    for line in body.splitlines():
        low = line.lower()
        if goal == "?" and re.search(r"goal", low):
            goal = line.strip("#*  ")[:80]
        if stage == "?" and re.search(r"stage", low):
            stage = line.strip("#*  ")[:80]
        if reason == "?" and re.search(r"reason|why", low):
            reason = line.strip("#*  ")[:160]
    detail = f"{goal} / {stage} / {reason}" if any(v != "?" for v in (goal, stage, reason)) else body[:200]
    return (f"{SERIES}: driver blocked - the owner owes one decision\n"
            f"- where: {detail}\n"
            f"- detail: {BLOCKED}\n"
            f"- ask: read that file and answer in one line; the driver will not retry the same step")


def dead_alert() -> str | None:
    if unit_active() or series_finished():
        return None
    state = read_state()
    return (f"{SERIES}: driver is not running and the series is unfinished\n"
            f"- last state: goal {state.get('goal', '?')} / stage {state.get('stage', '?')} / "
            f"{state.get('status', '?')} (updated {state.get('updated', '?')})\n"
            f"- log: {LOGS}/conductor-*.log\n"
            f"- ask: resume it from the committed branch/stage, or read the log first")


def stalled_alert() -> str | None:
    if not unit_active():
        return None
    state = read_state()
    if state.get("status") != "running" or not state.get("updated"):
        return None
    try:
        updated = datetime.datetime.strptime(state["updated"], "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None
    hours = (now() - updated).total_seconds() / 3600.0
    if hours < STALL_HOURS:
        return None
    return (f"{SERIES}: stage has not advanced for {hours:.1f}h\n"
            f"- goal {state.get('goal', '?')} / stage {state.get('stage', '?')}\n"
            f"- log: {LOGS}/conductor-*.log\n"
            f"- ask: check whether the stage's agent lane is still alive (do not retry the same step)")


def main() -> int:
    message = blocked_alert() or dead_alert() or stalled_alert()
    if not message:
        return 0
    digest = hashlib.sha1(message.encode("utf-8")).hexdigest()
    snapshot: dict = {}
    if SNAP.exists():
        try:
            snapshot = json.loads(SNAP.read_text(encoding="utf-8"))
        except Exception:
            snapshot = {}
    if snapshot.get("hash") == digest and snapshot.get("sent_at"):
        try:
            sent = datetime.datetime.fromisoformat(snapshot["sent_at"])
            if (now() - sent).total_seconds() < REPEAT_HOURS * 3600:
                return 0
        except Exception:
            pass
    SNAP.parent.mkdir(parents=True, exist_ok=True)
    SNAP.write_text(json.dumps({"hash": digest, "sent_at": now().isoformat(timespec="seconds")},
                               ensure_ascii=False), encoding="utf-8")
    print(message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
