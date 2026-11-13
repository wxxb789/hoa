#!/usr/bin/env python3
"""Audit config drift between the root Hermes config and every served profile.

Usage:
    python3 audit-config-drift.py [--hermes-home ~/.hermes] [--agent-dir ~/.hermes/hermes-agent]
                                  [--show-defaults]

Per profile it prints:
  MISS  root deviates from the built-in default but the profile lacks the key  -> real miss, mirror it
  DIFF  present in both with different values                                  -> per-profile tuning, ask first
  ONLY  profile-only key                                                       -> report, usually intentional

Exit code 1 when any MISS is found (usable as a check).
Requires PyYAML; run it with an interpreter that can import it (a Hermes venv, or the toolchain python once
its shim is installed).
"""
from __future__ import annotations

import argparse
import pathlib
import sys

SECRET_HINTS = ("api_key", "token", "secret", "password", "webhook")
# Provider/model catalogs are mirrored separately and must be probed live; skip them here.
IGNORE_PREFIXES = ("providers.",)


def load_yaml(path: pathlib.Path) -> dict:
    import yaml

    return yaml.safe_load(path.read_text()) or {}


def leaves(d, prefix: str = ""):
    if isinstance(d, dict):
        for k, v in d.items():
            yield from leaves(v, f"{prefix}.{k}" if prefix else str(k))
    else:
        yield prefix, d


def shown(path: str, value) -> str:
    if any(h in path.lower() for h in SECRET_HINTS):
        return "***"
    text = repr(value)
    return text if len(text) <= 70 else text[:67] + "..."


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hermes-home", default=str(pathlib.Path.home() / ".hermes"))
    ap.add_argument("--agent-dir", default=str(pathlib.Path.home() / ".hermes/hermes-agent"))
    ap.add_argument("--show-defaults", action="store_true", help="print the built-in default next to each MISS")
    args = ap.parse_args()

    defaults: dict = {}
    sys.path.insert(0, args.agent_dir)
    try:
        from hermes_cli.config_defaults import DEFAULT_CONFIG  # type: ignore

        defaults = dict(leaves(DEFAULT_CONFIG))
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: cannot import DEFAULT_CONFIG from {args.agent_dir}: {exc}")
        print("      Deviation-vs-default classification disabled; drift/diff passes still run.\n")

    home = pathlib.Path(args.hermes_home)
    root_file = home / "config.yaml"
    if not root_file.exists():
        print(f"no root config at {root_file}")
        return 2
    root = dict(leaves(load_yaml(root_file)))

    profiles = sorted((home / "profiles").glob("*/config.yaml"))
    if not profiles:
        print(f"no profiles under {home / 'profiles'}")
        return 0

    found_miss = False
    for f in profiles:
        prof = dict(leaves(load_yaml(f)))
        misses = {
            k: v
            for k, v in root.items()
            if k not in prof
            and not k.startswith(IGNORE_PREFIXES)
            and k in defaults
            and defaults[k] != v
        }
        diffs = {
            k: (root[k], prof[k])
            for k in root
            if k in prof and root[k] != prof[k] and not k.startswith(IGNORE_PREFIXES)
        }
        only = {k: v for k, v in prof.items() if k not in root and not k.startswith(IGNORE_PREFIXES)}

        print(f"### {f.parent.name}: {len(misses)} MISS, {len(diffs)} DIFF, {len(only)} ONLY")
        for k, v in sorted(misses.items()):
            extra = f"   [default={shown(k, defaults[k])}]" if args.show_defaults else ""
            print(f"  MISS  {k} = {shown(k, v)}{extra}")
        for k, (a, b) in sorted(diffs.items()):
            print(f"  DIFF  {k}: root={shown(k, a)} profile={shown(k, b)}")
        for k, v in sorted(only.items()):
            print(f"  ONLY  {k} = {shown(k, v)}")
        print()
        found_miss = found_miss or bool(misses)

    print("RESULT:", "drift found - review MISS lines" if found_miss else "no root-only deviations to mirror")
    return 1 if found_miss else 0


if __name__ == "__main__":
    raise SystemExit(main())
