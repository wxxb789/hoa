#!/usr/bin/env python3
"""Check that every number in a draft traces back to the source corpus.

Usage:
    python3 fact_check.py draft.md --corpus path/to/run-logs \
                                   --corpus path/to/ledger.jsonl

Why: rewriting an old draft is the highest-risk path for inheriting a wrong
statistic. Eyeballing numbers does not work; token-by-token lookup does.
Exit code 1 when any number is missing from the corpus, so it can gate a commit.

Numbers are compared as text, so keep the corpus raw (run-logs, ledger, reports);
do not pre-format it.
"""
import argparse
import re
import sys
from pathlib import Path

TEXT_SUFFIXES = {".md", ".txt", ".log", ".json", ".jsonl", ".yaml", ".yml", ".csv", ".tsv"}


def corpus_text(paths):
    chunks = []
    for raw in paths:
        p = Path(raw).expanduser()
        if p.is_dir():
            for f in p.rglob("*"):
                if f.is_file() and f.suffix in TEXT_SUFFIXES:
                    try:
                        chunks.append(f.read_text(errors="ignore"))
                    except OSError:
                        pass
        elif p.is_file():
            chunks.append(p.read_text(errors="ignore"))
        else:
            print(f"warn: corpus path not found: {p}", file=sys.stderr)
    return "\n".join(chunks)


def numbers(text):
    # strip fenced code: code samples carry their own numbers (line numbers, ports)
    body = re.sub(r"```.*?```", " ", text, flags=re.S)
    seen = []
    for n in re.findall(r"\d[\d,.]*", body):
        n = n.strip(".,")
        if n and n not in seen:
            seen.append(n)
    return seen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("draft")
    ap.add_argument("--corpus", action="append", required=True,
                    help="file or directory of source material; repeatable")
    args = ap.parse_args()

    corpus = corpus_text(args.corpus)
    missing = []
    for n in numbers(Path(args.draft).expanduser().read_text()):
        hit = n in corpus or n.replace(",", "") in corpus
        print(f"{'OK  ' if hit else 'MISS'} {n}")
        if not hit:
            missing.append(n)

    print(f"\nchecked={len(numbers(Path(args.draft).expanduser().read_text()))} "
          f"missing={len(missing)}")
    if missing:
        print("unverified: " + ", ".join(missing))
        print("each one must be traced to a source line or deleted before publishing")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
