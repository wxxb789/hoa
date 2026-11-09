#!/usr/bin/env python3
"""Check whether installed, GitHub-backed skills match upstream HEAD.

Answers "are my skills up to date?" by byte-for-byte diffing each skill's local
SKILL.md against its upstream HEAD -- NOT by trusting lock timestamps. The installer
only rewrites changed files, so an unchanged skill keeps an old `updatedAt`; that
old timestamp is not evidence of staleness.

Reads:
  --config (default $SKILL_RUNTIME_CONFIG, else $XDG_CONFIG_HOME/agent/config.yaml,
            i.e. ~/.config/agent/config.yaml)
            optional: `skills.disabled` list -> enabled/disabled label
  --lock   (default $SKILLS_LOCK, else ~/.agents/.skill-lock.json)
            shared-store installs: sourceUrl, skillPath
  --skills-root (default $SKILLS_ROOT, else <lock dir>/skills)
            scanned recursively for SKILL.md; repeats allowed

Every path can be overridden, so the check is not tied to one runtime's home
layout: point --skills-root at whichever directory the runtime actually loads
skills from.

node_modules phantom skills (vendored npm packages that ship a SKILL.md) are
excluded -- loaders skip node_modules, so they are never injected.

Prints only DIFF/ERR rows + a SAME/DIFF/ERR tally. Exit 1 if any DIFF or ERR
(so it can gate). Nothing to do on a clean library.

Usage:
  python3 upstream-freshness-check.py            # all github-backed skills
  python3 upstream-freshness-check.py --enabled  # only skills not disabled
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import glob
import json
import os
import sys
import urllib.request

DEFAULT_LOCK = os.path.expanduser("~/.agents/.skill-lock.json")


def config_path(explicit: str | None) -> str:
    if explicit:
        return os.path.expanduser(explicit)
    env = os.environ.get("SKILL_RUNTIME_CONFIG")
    if env:
        return os.path.expanduser(env)
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "agent", "config.yaml")


def load_disabled(path: str) -> set[str]:
    try:
        import yaml
        cfg = yaml.safe_load(open(path)) or {}
        return set((cfg.get("skills") or {}).get("disabled") or [])
    except Exception:
        return set()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--enabled", action="store_true",
                    help="only skills not present in the disabled list")
    ap.add_argument("--lock", help="installer lock file (JSON)")
    ap.add_argument("--skills-root", action="append",
                    help="directory scanned for SKILL.md (repeatable)")
    ap.add_argument("--config", help="runtime config file with skills.disabled")
    args = ap.parse_args(argv)

    lock_path = os.path.expanduser(args.lock or os.environ.get("SKILLS_LOCK") or DEFAULT_LOCK)
    if not os.path.exists(lock_path):
        print(f"no installer lock at {lock_path}", file=sys.stderr)
        return 2
    disabled = load_disabled(config_path(args.config))

    roots = args.skills_root or ([os.environ["SKILLS_ROOT"]]
                                 if os.environ.get("SKILLS_ROOT")
                                 else [os.path.join(os.path.dirname(lock_path), "skills")])

    skills: dict[str, str] = {}
    for root in roots:
        for p in glob.glob(os.path.join(os.path.expanduser(root), "**", "SKILL.md"),
                           recursive=True):
            if "/node_modules/" in p:  # phantom vendored skill -- not injected
                continue
            skills.setdefault(os.path.basename(os.path.dirname(p)), p)
    if not skills:
        print(f"no SKILL.md under {roots}", file=sys.stderr)
        return 2

    agents_lock = json.load(open(lock_path)).get("skills", {})
    targets = [n for n in skills
               if n in agents_lock and "github.com" in (agents_lock[n].get("sourceUrl") or "")]
    if args.enabled:
        targets = [n for n in targets if n not in disabled]

    def check(n: str) -> tuple[str, str, str, str]:
        v = agents_lock[n]
        slug = v["sourceUrl"].replace("https://github.com/", "").replace(".git", "")
        raw = f"https://raw.githubusercontent.com/{slug}/HEAD/{v['skillPath']}"
        status = "enabled" if n not in disabled else "disabled"
        try:
            up = urllib.request.urlopen(raw, timeout=20).read().decode("utf-8", "ignore")
        except Exception as e:
            return (n, "ERR", str(e)[:60], status)
        local = open(skills[n], encoding="utf-8", errors="ignore").read()
        same = (up.replace("\r\n", "\n").strip()
                == local.replace("\r\n", "\n").strip())
        return (n, "SAME" if same else "DIFF", f"local={len(local)}c up={len(up)}c", status)

    print(f"checking {len(targets)} github-backed skills (node_modules excluded)...\n")
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        rows = list(ex.map(check, sorted(targets)))

    for n, tag, info, st in rows:
        if tag != "SAME":
            print(f"{tag:5} {st:9} {n:30} {info}")
    s = sum(1 for r in rows if r[1] == "SAME")
    d = sum(1 for r in rows if r[1] == "DIFF")
    e = sum(1 for r in rows if r[1] == "ERR")
    print(f"\nSUMMARY: {len(rows)} checked | SAME={s} DIFF={d} ERR={e}")
    return 1 if (d or e) else 0


if __name__ == "__main__":
    sys.exit(main())
