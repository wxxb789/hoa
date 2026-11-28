#!/usr/bin/env python3
"""Who is holding <home>/state.db — and the safe way to clear the disposable holders.

Why: `hermes sessions optimize-storage` and `hermes sessions prune` refuse while ANY process holds the
DB. A gateway stop clears exactly one of them. App-spawned `hermes serve --isolated …
--ssh-session-token-file …` backends keep the DB open, and under a client reconnect storm they come back
within seconds, so the maintenance run has to be a retry loop around this probe.

Enumerate by open descriptor. Never kill by pattern: `pkill -f '<pattern>'` also matches the shell whose
own command line contains the pattern, so it terminates the command you are running (SIGTERM, exit 15).

Usage:
    state-db-holders.py                    # list holders: pid, age, rss, kind, short cmdline
    state-db-holders.py --reap-backends    # TERM then KILL only the app-spawned backends
    state-db-holders.py --db <path>        # a different home / profile DB

Exit code: 0 when no holder remains, 1 when holders remain (usable as a retry guard).
"""

import argparse
import os
import signal
import sys
import time

HERMES_ROOT = os.path.expanduser(os.environ.get("HERMES_ROOT", os.environ.get("HERMES_HOME", "~/.hermes")))
DEFAULT_DB = os.path.join(HERMES_ROOT, "state.db")


def ancestors(start: int) -> set:
    """self, parents, … up to pid 1 — never candidates for a kill."""
    seen = set()
    pid = start
    while pid and pid != 1:
        seen.add(pid)
        try:
            with open(f"/proc/{pid}/stat", "rb") as fh:
                pid = int(fh.read().rsplit(b")", 1)[1].split()[1])
        except (OSError, IndexError, ValueError):
            break
    return seen


def cmdline(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            return fh.read().replace(b"\0", b" ").decode("utf-8", "replace").strip()
    except OSError:
        return ""


def rss_mb(pid: int) -> int:
    try:
        with open(f"/proc/{pid}/status") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) // 1024
    except (OSError, IndexError, ValueError):
        pass
    return 0


def age_s(pid: int) -> int:
    try:
        return int(time.time() - os.path.getmtime(f"/proc/{pid}"))
    except OSError:
        return -1


def kind(cmd: str) -> str:
    if "gateway run" in cmd:
        return "gateway"
    if "ssh-session-token-file" in cmd or "--ssh-owner-nonce" in cmd or (
        " serve " in cmd and "--isolated" in cmd
    ):
        return "backend"
    if "hermes" in cmd:
        return "hermes-other"
    return "other"


def holders(db: str) -> list:
    target = os.path.realpath(db)
    exclude = ancestors(os.getpid())
    found = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = int(entry)
        if pid in exclude:
            continue
        fddir = f"/proc/{pid}/fd"
        try:
            fds = os.listdir(fddir)
        except OSError:
            continue
        for fd in fds:
            try:
                link = os.readlink(f"{fddir}/{fd}")
            except OSError:
                continue
            if link == target or link.startswith(target + "-"):
                cmd = cmdline(pid)
                found[pid] = (age_s(pid), rss_mb(pid), kind(cmd), cmd[:110])
                break
    return sorted(found.items(), key=lambda kv: kv[1][2] != "backend")


def show(items) -> None:
    if not items:
        print("no holder")
        return
    for pid, (age, rss, k, cmd) in items:
        print(f"{pid:>8}  {k:<11} {rss:>5} MB  age {age:>6}s  {cmd}")


def reap_backends(items, keep_freshest: int = 1) -> None:
    targets = [pid for pid, (_, _, k, _) in items if k == "backend"]
    if len(targets) <= keep_freshest:
        print(f"backends: {len(targets)} live, keeping the freshest {keep_freshest} — nothing to reap")
        return
    drop = targets[keep_freshest:]
    print(f"reaping backends (keeping freshest {keep_freshest}): {drop}")
    for pid in drop:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    time.sleep(6)
    for pid in drop:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    time.sleep(2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--reap-backends", action="store_true",
                    help="TERM/KILL app-spawned backends, keeping the freshest one")
    args = ap.parse_args()

    items = holders(args.db)
    print(f"db: {args.db}")
    show(items)
    if args.reap_backends:
        reap_backends(items)
        items = holders(args.db)
        print("\nafter reap:")
        show(items)
    return 1 if items else 0


if __name__ == "__main__":
    sys.exit(main())
