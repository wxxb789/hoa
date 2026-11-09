#!/usr/bin/env python3
"""Verify an instruction-file rewrite (SOUL.md / AGENTS.md / spec) lost no rule.

A compression pass must be behavior-preserving. This checks that every rule you
declared as a distinctive marker still appears in the rewritten file, and reports
measured size deltas so savings claims rest on numbers, not impressions.

Usage:
    python3 contract-coverage-check.py OLD.md NEW.md markers.txt
        [--allow-missing "marker1,marker2"]

markers.txt: one distinctive substring per rule; '#' starts a comment line.
Exit: 0 = every marker present, 1 = something was lost.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys


def read(p: str) -> str:
    return pathlib.Path(p).read_text(encoding="utf-8")


def rule_lines(text: str) -> list[str]:
    """Non-empty lines that are not headings (the rule payload)."""
    return [
        ln for ln in text.splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]


def pct(old: int, new: int) -> str:
    return f"{(new / old - 1) * 100:+.1f}%" if old else "n/a"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("old", help="pre-edit copy (a backup file is fine)")
    ap.add_argument("new", help="rewritten file")
    ap.add_argument("markers", help="file with one marker substring per line")
    ap.add_argument("--allow-missing", default="",
                    help="comma-separated markers allowed to disappear")
    args = ap.parse_args()

    old, new = read(args.old), read(args.new)
    allowed = {x.strip() for x in args.allow_missing.split(",") if x.strip()}
    markers = [
        m.strip() for m in read(args.markers).splitlines()
        if m.strip() and not m.lstrip().startswith("#")
    ]
    if not markers:
        print("no markers declared — nothing to verify", file=sys.stderr)
        return 2

    missing = [m for m in markers if m not in new and m not in allowed]
    dup = [m for m in markers if new.count(m) > 1]

    old_b, new_b = len(old.encode()), len(new.encode())
    old_l, new_l = len(rule_lines(old)), len(rule_lines(new))

    print(f"markers:    {len(markers)}  present: {len(markers) - len(missing)}  missing: {len(missing)}")
    print(f"bytes:      {old_b:,} -> {new_b:,}  ({pct(old_b, new_b)})")
    print(f"rule lines: {old_l:,} -> {new_l:,}  ({pct(old_l, new_l)})")
    print(f"sections:   {len(re.findall(r'^## ', old, re.M))} -> {len(re.findall(r'^## ', new, re.M))}")

    if dup:
        print("warning: marker appears more than once in NEW (duplicate rule?):")
        for m in dup:
            print(f"  {m}  x{new.count(m)}")

    if missing:
        print("LOST — not found in NEW:")
        for m in missing:
            print(f"  {m}")
        return 1

    print("OK: every declared rule marker survived")
    return 0


if __name__ == "__main__":
    sys.exit(main())
