#!/usr/bin/env python3
"""Extract the first and last real paragraph of each post (style study).

Usage:
    python3 first_last.py <dir> [prefix]

Why a separate script: raw scraped pages bury the opening under a date+tag line and the ending
under site boilerplate (licence footer, book ad, series TOC). Splitting on blank lines and taking
[0] / [-1] gives you the tag line and the ad, not the prose — which is exactly the two positions
you are trying to study. This filter drops the boilerplate so the sample is usable.

Extend BOILER when a new site adds its own furniture; keep each entry as a substring or regex
fragment, they are OR-ed together.
"""
import re
import sys
from pathlib import Path

BOILER = [
    r"本作品采用", r"知识共享", r"union-click", r"正在加载", r"giscus",
    r"配图指南", r"^\d{2}\.\s*\S",          # series TOC lines (01. 02. ...)
    r"Page: \d+ of", r"^Source:", r"^# ",
    r"各位读者朋友，很高兴",                  # site-wide book ad
    r"^订阅", r"^打赏", r"^关注仓库",
]
DATE_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2}|[A-Z][a-z]{2} \d{1,2}, \d{4})\s*")


def paragraphs(path: Path):
    t = path.read_text()
    t = re.sub(r"─+ \[TRUNCATED\].*", "", t, flags=re.S)
    t = re.sub(r"```.*?```", "", t, flags=re.S)      # code blocks out
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", t)       # images out
    t = re.sub(r"\[\]\([^)]*\)", "", t)              # bare links out
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)  # keep anchor text
    out = []
    # NOTE: split on blank lines BEFORE filtering, and never collapse blank lines first —
    # collapse them and the whole post becomes one paragraph.
    for block in re.split(r"\n\s*\n", t):
        s = re.sub(r"\s+", " ", block.strip())
        if len(s) < 40 or any(re.search(p, s) for p in BOILER):
            continue
        if DATE_LINE.match(s):                        # strip leading date + tag run
            s = DATE_LINE.sub("", s).strip()
            words = s.split(" ")
            while words and re.fullmatch(r"[\w\u4e00-\u9fa5\.\-]{1,24}", words[0]) and len(s) > 40:
                s = s[len(words[0]):].strip()
                words = s.split(" ")
            if len(s) < 40:
                continue
        if re.fullmatch(r"[\w\- ·、]{0,40}", s):      # pure tag blob
            continue
        out.append(s)
    return out


def main():
    d = Path(sys.argv[1])
    prefix = sys.argv[2] if len(sys.argv) > 2 else ""
    files = [f for f in sorted(d.glob(f"{prefix}*.md")) if f.stat().st_size > 800]
    if not files:
        print(f"no files under {d} matching {prefix}*.md")
        return
    for f in files:
        ps = paragraphs(f)
        if not ps:
            print(f"[{f.stem}] (no paragraph survived filtering)")
            continue
        print(f"[{f.stem}]")
        print(f"  开: {ps[0][:110]}")
        print(f"  收: {ps[-1][:110]}")


if __name__ == "__main__":
    main()
