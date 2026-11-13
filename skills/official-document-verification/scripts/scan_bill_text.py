#!/usr/bin/env python3
"""Mechanical pass over one print of a bill or statute.

Counts section-number hits, shows the window around each citation of an older law, and counts the
named things an absence claim rests on. It answers "what does this fetched text contain" — never
"what does the bill say", and never a procedural forecast.

Usage:
    python3 scan_bill_text.py <file> [--section 904] [--cite "42 U.S.C. 1396"] [--term "renewal"] ...

Output is JSON on stdout so the caller can quote exact counts in the evidence note.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

WINDOW = 240


def normalize(text: str) -> str:
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;?", " ", text)
    return re.sub(r"[ \t]+", " ", text)


def section_hits(text: str, section: str) -> list[dict]:
    pattern = re.compile(rf"\bSEC(?:TION)?\.?\s*{re.escape(section)}\b", re.I)
    hits = []
    for match in pattern.finditer(text):
        start = max(0, match.start() - 80)
        heading = text[match.start(): match.start() + WINDOW].split("\n", 1)[0]
        hits.append({"offset": match.start(), "heading": heading.strip(), "context": text[start:match.end() + 120].strip()})
    return hits


def citation_windows(text: str, cite: str) -> list[dict]:
    pattern = re.compile(re.escape(cite), re.I)
    return [
        {"offset": m.start(), "window": text[max(0, m.start() - WINDOW): m.end() + WINDOW].strip()}
        for m in pattern.finditer(text)
    ]


def term_counts(text: str, terms: list[str]) -> dict:
    return {term: len(re.findall(re.escape(term), text, re.I)) for term in terms}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", help="downloaded HTML or text file, one print only")
    ap.add_argument("--section", action="append", default=[], help="section number to locate (repeatable)")
    ap.add_argument("--cite", action="append", default=[], help="citation of an older law (repeatable)")
    ap.add_argument("--term", action="append", default=[], help="named thing to count (repeatable)")
    args = ap.parse_args()

    raw = Path(args.path).read_text(encoding="utf-8", errors="replace")
    text = normalize(raw)
    out = {
        "file": str(Path(args.path).resolve()),
        "print": "unnamed — record chamber/print/size/line count with the claim",
        "characters": len(text),
        "sections": {s: section_hits(text, s) for s in args.section},
        "citations": {c: citation_windows(text, c) for c in args.cite},
        "terms": term_counts(text, args.term),
        "note": "counts describe THIS fetched print; a zero count is an absence claim bounded to it",
    }
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
