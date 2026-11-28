#!/usr/bin/env python3
"""Evidence-gated, idempotent, backup-first $HOME cleanup.

Design rules:
  * a target is deleted only if it matches the expected shape (evidence gate)
  * a backup tarball is written before the first deletion
  * re-runnable: already-deleted targets are reported as skipped, not fatal
  * files and dirs handled separately (rmtree fails on a regular file)

Edit FARM_WHOLE / FARM_SUBDIR / T4_JUNK for the machine you are cleaning. --dry-run first.
"""
import os, shutil, subprocess, sys, tarfile, time

HOME = os.path.expanduser("~")
SKILLS_STORE = os.path.realpath(os.path.join(HOME, ".agents/skills"))
BACKUP = os.path.join(HOME, ".hermes/cache/scratch",
                      f"home-cleanup-{time.strftime('%Y%m%d')}.tar.gz")

FARM_WHOLE = []            # dirs whose ONLY content is a symlink farm into SKILLS_STORE
FARM_SUBDIR = [".claude/skills", ".pi/skills"]   # keep parent, drop only the farm subdir
T4_JUNK = []               # verified junk: empty dirs, stale one-shot files, old backups


def find_skills_dir(target):
    direct = os.path.join(target, "skills")
    if os.path.isdir(direct):
        return direct
    for root, dirs, _ in os.walk(target):
        if os.path.basename(root) == "skills" and root[len(target):].count(os.sep) <= 3:
            return root
        if root[len(target):].count(os.sep) >= 3:
            dirs[:] = []
    return None


def is_pure_farm(target):
    """True only if every child of the skills dir is a symlink into SKILLS_STORE and no
    real file lives outside that subtree."""
    sd = find_skills_dir(target)
    if sd is None:
        return False, "no skills dir"
    entries = os.listdir(sd)
    if not entries:
        return False, "empty skills dir"
    for name in entries:
        p = os.path.join(sd, name)
        if not os.path.islink(p):
            return False, f"non-symlink: {p}"
        if not os.path.realpath(p).startswith(SKILLS_STORE):
            return False, f"symlink escapes store: {p}"
    real_sd = os.path.realpath(sd)
    for root, _, files in os.walk(target):
        for f in files:
            fp = os.path.join(root, f)
            if not os.path.islink(fp) and not os.path.realpath(fp).startswith(real_sd):
                return False, f"extra file outside skills: {fp}"
    return True, f"{len(entries)} symlinks"


def size_of(path):
    return int(subprocess.run(["du", "-sb", path], capture_output=True, text=True)
               .stdout.split()[0] or 0)


def free_kb():
    s = os.statvfs(HOME)
    return (s.f_bavail * s.f_frsize) // 1024


def main():
    plan, skipped = [], []
    for name in FARM_WHOLE:
        p = os.path.join(HOME, name)
        if not os.path.isdir(p):
            skipped.append((name, "missing")); continue
        ok, why = is_pure_farm(p)
        plan.append((p, "farm")) if ok else skipped.append((name, f"KEPT: {why}"))
    for rel in FARM_SUBDIR:
        p = os.path.join(HOME, rel)
        if not os.path.isdir(p):
            skipped.append((rel, "missing")); continue
        entries = os.listdir(p)
        if entries and all(os.path.islink(os.path.join(p, e)) and
                           os.path.realpath(os.path.join(p, e)).startswith(SKILLS_STORE)
                           for e in entries):
            plan.append((p, "farm-subdir"))
        else:
            skipped.append((rel, "KEPT: not a pure symlink farm"))
    for name in T4_JUNK:
        p = os.path.join(HOME, name)
        (plan.append((p, "junk")) if os.path.exists(p) else skipped.append((name, "missing")))

    print(f"plan: {len(plan)} targets, {sum(size_of(p) for p, _ in plan)/1e6:.1f} MB")
    if "--dry-run" in sys.argv:
        for p, k in plan:
            print(f"  [{k:11s}] {p}")
        for n, w in skipped:
            print(f"  [skip     ] {n}: {w}")
        return

    os.makedirs(os.path.dirname(BACKUP), exist_ok=True)
    before = free_kb()
    with tarfile.open(BACKUP, "w:gz") as tf:
        for p, _ in plan:
            tf.add(p, arcname=os.path.relpath(p, HOME))
    print(f"backup: {BACKUP} ({os.path.getsize(BACKUP)/1e6:.1f} MB)")

    for p, _ in plan:
        if os.path.islink(p) or os.path.isfile(p):
            os.remove(p)
        else:
            shutil.rmtree(p)
    print(f"deleted {len(plan)} targets, freed {(free_kb()-before)/1024:.1f} MB")
    for n, w in skipped:
        print(f"  skip {n}: {w}")


if __name__ == "__main__":
    main()
