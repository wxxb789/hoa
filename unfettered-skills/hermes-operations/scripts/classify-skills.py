#!/usr/bin/env python3
"""Partition Hermes runtime skills into builtin / hub / local.

Prints '<class>\t<relpath>' per leaf skill (dir containing SKILL.md).
Back up ONLY the 'local' set (plus ~/.agents/.skill-lock.json):
  * builtin -> ships with Hermes (source ~/.hermes/hermes-agent/skills)
  * hub     -> reinstallable from ~/.agents/.skill-lock.json
  * local   -> host-authored / imported, the only skills to sync.

Env overrides: HERMES_HOME (default ~/.hermes).
"""
import json
import os

HOME = os.path.expanduser("~")
HERMES = os.environ.get("HERMES_HOME", os.path.join(HOME, ".hermes"))
AGENTS = os.path.join(HOME, ".agents")
BUILTIN = os.path.join(HERMES, "hermes-agent", "skills")
SKIP = {".git", "node_modules", "__pycache__", ".archive",
        ".curator_backups", ".hub", ".locks"}


def leaves(root):
    out = set()
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in SKIP]
        if "SKILL.md" in fn and dp != root:
            out.add(os.path.relpath(dp, root))
    return out


def main():
    builtin = leaves(BUILTIN) if os.path.isdir(BUILTIN) else set()
    bnames = {os.path.basename(p) for p in builtin}
    lockf = os.path.join(AGENTS, ".skill-lock.json")
    locks = set(json.load(open(lockf))["skills"]) if os.path.exists(lockf) else set()
    for r in sorted(leaves(os.path.join(HERMES, "skills"))):
        b = os.path.basename(r)
        if r in builtin or b in bnames:
            cls = "builtin"
        elif b in locks:
            cls = "hub"
        else:
            cls = "local"
        print(f"{cls}\t{r}")


if __name__ == "__main__":
    main()
