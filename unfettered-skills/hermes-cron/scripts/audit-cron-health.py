#!/usr/bin/env python3
"""Cron health dump: per job, the fields the CLI does not show.

Usage: python3 audit-cron-health.py [--json]

Reads ~/.hermes/cron/jobs.json (read-only, safe any time) and prints per job: schedule, deliver
state, last/next run, failure streak, delivery error, dispatch lateness, mode, and the newest
output artifact under ~/.hermes/cron/output/<id>/. Run this before answering "are my cron jobs
alive?" so the delivery/streak fields are not missed, then confirm with `hermes cron doctor`.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

HOME = pathlib.Path.home()
JOBS = HOME / ".hermes" / "cron" / "jobs.json"
OUT = HOME / ".hermes" / "cron" / "output"


def load_jobs() -> list[dict]:
    data = json.loads(JOBS.read_text())
    if isinstance(data, list):
        return data
    return list(data.get("jobs") or data.values())


def newest_output(job_id: str):
    d = OUT / job_id
    if not d.is_dir():
        return None
    files = sorted(d.glob("*"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def print_targets() -> None:
    """Enumerate cron delivery targets with the same resolver cron itself uses.

    Caveat: the resolver reads the *current process's* profile scope, so run from a bare
    script outside a gateway/profile context it reports home_target_set=False even when the
    var is configured. Read False as 'unresolved', not 'unset'.
    """
    sys.path.insert(0, str(HOME / ".hermes" / "hermes-agent"))
    try:
        from cron.scheduler_delivery import cron_delivery_targets
    except Exception as exc:  # source tree moved, or import chain changed upstream
        print(f"delivery targets unavailable: {exc!r}")
        return
    for t in cron_delivery_targets():
        print(f"  {t}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="dump raw job dicts instead of the summary")
    ap.add_argument("--targets", action="store_true",
                    help="also list cron delivery targets and their home-channel state")
    args = ap.parse_args()

    if args.targets:
        print("delivery targets:")
        print_targets()
        print()

    jobs = load_jobs()
    if args.json:
        print(json.dumps(jobs, indent=2, ensure_ascii=False))
        return 0

    print(f"{len(jobs)} job(s) in {JOBS}\n")
    for j in jobs:
        sched = (j.get("schedule") or {})
        sched = sched.get("display") or sched.get("expr") or sched.get("kind")
        print(f"{j.get('name')}  [{j.get('id')}]")
        print(f"    schedule       {sched}   state={j.get('state')} paused={bool(j.get('paused_at'))}")
        print(f"    deliver        {j.get('deliver')}  origin={json.dumps(j.get('origin'))}")
        print(f"    last           {j.get('last_run_at')}  ->  {j.get('last_status')}")
        print(f"    next           {j.get('next_run_at')}")
        if j.get("failure_streak"):
            print(f"    FAILURE STREAK {j['failure_streak']}  last_error={str(j.get('last_error'))[:130]}")
        if j.get("last_delivery_error"):
            print(f"    DELIVERY ERROR {str(j['last_delivery_error'])[:150]}")
        if j.get("last_delivery_unverified"):
            print(f"    DELIVERY UNVERIFIED {str(j['last_delivery_unverified'])[:150]}")
        disp = j.get("last_dispatch") or {}
        if disp:
            print(f"    dispatch       late={disp.get('lateness_seconds')}s kind={disp.get('kind')}")
        mode = "script (no_agent)" if j.get("no_agent") else "agent"
        print(f"    mode           {mode}  script={j.get('script')}")
        out = newest_output(str(j.get("id")))
        if out is not None:
            print(f"    newest output  {out.name} ({out.stat().st_size} bytes)")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
