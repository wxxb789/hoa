#!/usr/bin/env python3
"""Attribute a driver log's wall-clock to busy vs dead windows.

Usage:
    wallclock-attribution.py <log-dir-or-file> [--keys k1,k2,...] [--blocked BLOCKED]
                             [--resume "resume at"] [--top 5]

Reads every file under the given path (a log directory is the normal case), keeps the lines shaped
`[YYYY-MM-DD HH:MM:SS] message` whose message contains one of --keys, prints them in time order with the
delta from the previous event, then classifies every inter-event window as BUSY or WAIT and totals each.

A window is WAIT when the event opening it looks like a stop (--blocked) or the event closing it looks
like a recovery (--resume); everything else is BUSY. Duplicate (timestamp, message) pairs are dropped —
the same event usually appears once per rotated log file.

Why: "this series is slow" has three causes that need three different fixes — machine-busy time, dead wait
on an owner decision, and dead wait nothing notified anyone about. Only the timestamps separate them, and
the largest WAIT windows are the ones that have to be explained (and designed away).
"""
import argparse
import datetime
import glob
import os
import re
import sys

DEFAULT_KEYS = [
    "dispatch", "gate rc=", "pushed", "machine review", "acceptance audit",
    "BLOCKED", "resume at", "conductor start", "merged", "CI repair pushed", "watching PR",
]
LINE = re.compile(r"^\s*(?:.*?\[)?(\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d)\]\s*(.*)$")


def parse_ts(text):
    return datetime.datetime.strptime(text.replace("T", " "), "%Y-%m-%d %H:%M:%S")


def load(path, keys):
    if os.path.isdir(path):
        files = sorted(glob.glob(os.path.join(path, "*.log")))
        if not files:
            files = sorted(p for p in glob.glob(os.path.join(path, "*")) if os.path.isfile(p))
    else:
        files = [path]
    events, seen = [], set()
    for name in files:
        try:
            handle = open(name, "r", errors="replace")
        except OSError as exc:
            print(f"skip {name}: {exc}", file=sys.stderr)
            continue
        with handle:
            for line in handle:
                match = LINE.match(line)
                if not match:
                    continue
                ts, msg = parse_ts(match.group(1)), match.group(2).strip()
                if not any(key in msg for key in keys):
                    continue
                if (ts, msg) in seen:
                    continue
                seen.add((ts, msg))
                events.append((ts, msg, os.path.basename(name)))
    events.sort(key=lambda event: event[0])  # stable: same-second order stays as read
    return events


def main():
    parser = argparse.ArgumentParser(description="attribute a driver log's wall-clock")
    parser.add_argument("path")
    parser.add_argument("--keys", default="", help="comma-separated; replaces the defaults")
    parser.add_argument("--blocked", default="BLOCKED")
    parser.add_argument("--resume", default="resume at")
    parser.add_argument("--top", type=int, default=5)
    args = parser.parse_args()

    keys = [k.strip() for k in args.keys.split(",") if k.strip()] or DEFAULT_KEYS
    events = load(args.path, keys)
    if len(events) < 2:
        print(f"{len(events)} matching event(s) — nothing to attribute; widen --keys")
        return 1

    print(f"{len(events)} events, {events[0][0]:%Y-%m-%d %H:%M} -> {events[-1][0]:%Y-%m-%d %H:%M}")
    print()
    windows = []
    prev = None
    for index, (ts, msg, _src) in enumerate(events):
        delta = "" if prev is None else f"  (+{(ts - prev).total_seconds() / 60:7.1f}m)"
        print(f"{ts:%m-%d %H:%M}{delta}  {msg[:140]}")
        if prev is not None:
            opening = events[index - 1][1]
            kind = "WAIT" if (args.blocked in opening or args.resume in msg) else "BUSY"
            windows.append(((ts - prev).total_seconds(), kind, opening, msg))
        prev = ts

    for kind in ("BUSY", "WAIT"):
        chosen = [w for w in windows if w[1] == kind]
        secs = sum(w[0] for w in chosen)
        print(f"\n{kind}: {secs / 3600:.1f}h ({secs / 60:.0f}m) over {len(chosen)} window(s)")
    span = sum(w[0] for w in windows)
    print(f"span: {span / 3600:.1f}h")
    waits = sorted((w for w in windows if w[1] == "WAIT"), reverse=True)[: args.top]
    if waits:
        print("\nlargest WAIT windows (opening event -> closing event):")
        for secs, _kind, opening, closing in waits:
            print(f"  {secs / 3600:5.1f}h  {opening[:70]!r} -> {closing[:70]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
