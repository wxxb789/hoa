#!/usr/bin/env python3
"""Vendor shared scripts into each skill package (single source of truth).

npx skills installs each skill folder as a self-contained package, so shared
helpers must be physically copied into every skill that needs them. This
script keeps that honest: the canonical copy lives in scripts/shared/, and
this vendoring pass copies it (verbatim) to every consumer. Run it after
editing a shared script, then commit all updated copies together.

Usage:
    python scripts/vendor_shared.py           # copy shared/ → each consumer
    python scripts/vendor_shared.py --check   # exit 1 on drift (CI)
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHARED = ROOT / "scripts" / "shared"

# shared script name → destination skill script dirs
CONSUMERS: dict[str, list[str]] = {
    "safety.py": [
        "skills/hoa-introspect/scripts",
        "skills/hoa-introspect-distill/scripts",
        "skills/hoa-agent-retrieve/scripts",
    ],
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="verify vendored copies match shared/; exit 1 on drift")
    args = ap.parse_args(argv)

    status = 0
    for name, consumers in sorted(CONSUMERS.items()):
        source = SHARED / name
        if not source.is_file():
            print(f"vendor_shared: missing shared source {source}", file=sys.stderr)
            return 1
        src_hash = digest(source)
        for consumer in consumers:
            dest = ROOT / consumer / name
            if args.check:
                if not dest.is_file() or digest(dest) != src_hash:
                    print(f"vendor_shared: {dest} is stale; run "
                          f"python scripts/vendor_shared.py", file=sys.stderr)
                    status = 1
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(source.read_bytes())
                print(f"vendored {name} → {consumer}/")
    if not args.check and status == 0:
        print("all consumers up to date")
    return status


if __name__ == "__main__":
    sys.exit(main())
