#!/usr/bin/env python3
"""Masked secret scan for directory trees (standalone-token patterns).

Usage:
    python3 scan_secrets.py <root> [<root> ...]

Prints one line per hit: path | pattern-label | pre-context | masked token (prefix + length).
Never prints a full value. Skips binaries and files over 6 MB. Word-internal matches are already
excluded by the lookbehind in each pattern (task-orders / risk-managed / Novorossiysk- stay clean);
the pre-context print exists so edge cases can still be eyeballed.
"""
import os
import re
import sys

PATTERNS = [
    ('sk_key', re.compile(r'(?<![A-Za-z0-9_])sk-[A-Za-z0-9_\-]{30,}')),
    ('github', re.compile(r'gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,}')),
    ('aws', re.compile(r'AKIA[0-9A-Z]{12,}')),
    ('gcp', re.compile(r'AIza[0-9A-Za-z_\-]{30,}')),
    ('slack', re.compile(r'xox[baprs]-[A-Za-z0-9\-]{10,}')),
    ('pem', re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY')),
    ('huggingface', re.compile(r'hf_[A-Za-z0-9]{30,}')),
    ('replicate', re.compile(r'r8_[A-Za-z0-9]{30,}')),
    ('xai', re.compile(r'xai-[A-Za-z0-9]{20,}')),
    ('jwt', re.compile(r'eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.')),
]
SKIP_DIRS = {'.git'}
MAX_BYTES = 6_000_000


def scan(root):
    hits = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            try:
                if os.path.getsize(p) > MAX_BYTES:
                    continue
                raw = open(p, 'rb').read()
                if b'\x00' in raw[:2048]:  # binary
                    continue
                text = raw.decode('utf-8', errors='replace')
            except OSError:
                continue
            for label, pat in PATTERNS:
                m = pat.search(text)
                if m:
                    pre = text[max(0, m.start() - 12):m.start()].replace('\n', ' ')
                    hits.append((p, label, pre, m.group(0)[:5], len(m.group(0))))
    return hits


if __name__ == '__main__':
    roots = sys.argv[1:] or ['.']
    for root in roots:
        hits = scan(root)
        print(f'# {root}: {len(hits)} masked hits')
        for p, label, pre, prefix, ln in hits:
            print(f'  {p} | {label} | …{pre}| »{prefix}…(len{ln})')
