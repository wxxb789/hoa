#!/usr/bin/env python3
"""Verify that every `> ` quote in a read-later note is verbatim in its extracted text.

Why: a source note's Evidence section is only evidence if the words are the source's. Hand-copying
loses markdown markers (`**bold**` inside a list item), swaps quote characters (“ ” for 「 」), and
reflows wrapped lines — all three yield a quote that reads right and is not verbatim.

Usage: python3 verify-quotes.py <note.md> [...]. Exit 0 when every quote matches, 1 otherwise.
Matching is whitespace-normalised, so a source file's hard line wrapping does not count as a mismatch;
everything else (markers, quote characters, word order) must match exactly.
"""
import pathlib
import re
import sys

MARKER = "<!-- machine-extracted by read-later.py; do not hand-edit this section -->"


def norm(text):
    return re.sub(r"\s+", " ", text).strip()


def check(path):
    text = pathlib.Path(path).read_text(encoding="utf-8")
    if MARKER not in text:
        print(f"{path}: no extracted-text marker — refusing to guess")
        return 1
    extracted = norm(text.split(MARKER, 1)[1])
    quotes = [line[2:].strip() for line in text.splitlines()
              if line.startswith("> ") and line.strip() != ">"]
    misses = [q for q in quotes if norm(q) not in extracted]
    for miss in misses:
        print(f"{path}: NOT VERBATIM: {norm(miss)[:120]}")
    print(f"{path}: {len(quotes) - len(misses)}/{len(quotes)} quotes verbatim")
    return 1 if misses else 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    sys.exit(max(check(p) for p in sys.argv[1:]))
