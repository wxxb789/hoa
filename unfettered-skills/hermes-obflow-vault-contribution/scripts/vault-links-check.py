#!/usr/bin/env python3
"""Resolve every [[wikilink]] in the given vault notes.

Why: sync does not gate on link health, so a typo'd or renamed target ships silently and only a later
wiki audit sees it. Run this before leaving new or renamed notes in the working tree.

Usage: python3 vault-links-check.py [--vault PATH] <file> [<file> ...]
Files may be absolute or relative to the vault root. Exit 1 with one line per unresolved target.

A target with a slash is resolved as a path (`.md` appended when missing); a bare name is resolved by
file stem anywhere in the vault. Block references (`[[note#Heading]]`) and labels (`[[note|Label]]`) are
stripped before resolving.
"""
import argparse
import pathlib
import re
import sys

LINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", default=str(pathlib.Path.home() / "repos/<notes-repo>/<notes-vault>"))
    ap.add_argument("files", nargs="+")
    args = ap.parse_args()

    vault = pathlib.Path(args.vault).expanduser().resolve()
    if not vault.is_dir():
        print(f"vault not found: {vault}")
        return 1

    stems = {}
    for note in vault.rglob("*.md"):
        stems.setdefault(note.stem, note)

    unresolved = 0
    for raw in args.files:
        note = pathlib.Path(raw)
        if not note.is_absolute():
            note = vault / note
        if not note.exists():
            print(f"MISSING FILE {raw}")
            unresolved += 1
            continue
        label = note.relative_to(vault) if note.is_relative_to(vault) else note
        for target in LINK.findall(note.read_text(encoding="utf-8")):
            target = target.strip()
            if "/" in target:
                candidate = vault / (target if target.endswith(".md") else target + ".md")
                ok = candidate.exists()
            else:
                ok = target in stems
            if not ok:
                print(f"UNRESOLVED {label} -> [[{target}]]")
                unresolved += 1

    print(f"unresolved: {unresolved}")
    return 1 if unresolved else 0


if __name__ == "__main__":
    sys.exit(main())
