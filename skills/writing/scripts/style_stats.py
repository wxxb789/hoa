#!/usr/bin/env python3
"""Per-post style metrics for a sample of scraped blog posts.

Usage:
    python3 style_stats.py <dir> [prefix]      # files = one post each

Input: plain text or markdown, one post per file (page-extractor output or cleaned curl HTML).
Output: one markdown table row per post + column means/medians, so two corpora can be compared
side by side against your own current draft (run it on the draft too — same script, same units).

Columns answer the questions that actually differentiate prose styles:
  chars           body size (code blocks and images excluded)
  heads           heading count -> structured explainer vs essay
  quote_blocks    blockquotes (series preambles, epigraphs)
  code / code_pct code block count and share of characters
  imgs / links    evidence style
  paras/para_mean paragraphs and their mean length in chars (>200 = one-argument paragraphs)
  sent_mean/median/p90  sentence rhythm; p90 exposes run-on sentences
  sent_short      %% of sentences <=15 chars (short-sentence density)
  nums/num_per_1k number density: >15 usually means the piece reads as a data dump
  me              first person 我 per 1k chars
  q / paren       questions and Chinese parentheses per post (voice variety)
  ascii_ratio     %% ASCII chars: high for term-heavy bilingual technical prose
"""
import re
import sys
from pathlib import Path
from statistics import mean, median


def clean(text):
    text = re.sub(r"─+ \[TRUNCATED\].*", "", text, flags=re.S)
    text = re.sub(r"Page: \d+ of \d+.*", "", text)
    text = re.sub(r"^Source: .*$", "", text, flags=re.M)
    text = re.sub(r"^\[跳到正文\].*$", "", text, flags=re.M)
    out = []
    for ln in text.splitlines():
        s = ln.strip()
        # drop pure navigation lines: a chain of links only
        if s and s.startswith("[") and "](" in s and len(s) < 250 and s.count("](") > 1:
            continue
        out.append(ln)
    return "\n".join(out)


def stats(path):
    raw = clean(path.read_text())
    code = re.findall(r"```.*?```", raw, flags=re.S)
    prose = re.sub(r"```.*?```", "", raw, flags=re.S)
    prose = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", prose)
    links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", prose)
    ptxt = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", prose)   # keep anchor text only
    heads = re.findall(r"(?m)^#{1,6}\s+\S", raw)
    quotes = re.findall(r"(?m)^>\s?", raw)

    sents = []
    for line in ptxt.splitlines():
        for s in re.split(r"[。！？!?]+", line):
            s = s.strip()
            if len(s) > 1:
                sents.append(s)
    lens = [len(re.sub(r"\s", "", s)) for s in sents]
    paras = [x for x in re.split(r"\n\s*\n", ptxt) if len(x.strip()) > 40]
    chars = len(re.sub(r"\s", "", ptxt))
    code_chars = sum(len(re.sub(r"\s", "", c)) for c in code)
    nums = re.findall(r"\d[\d,\.]*", ptxt)

    return dict(
        file=path.name,
        chars=chars,
        heads=len(heads),
        quote_blocks=len(quotes),
        code=len(code),
        code_pct=round(100 * code_chars / max(1, chars + code_chars)),
        imgs=len(re.findall(r"!\[[^\]]*\]\(", raw)),
        links=len(links),
        paras=len(paras),
        para_mean=round(mean([len(re.sub(r"\s", "", x)) for x in paras])) if paras else 0,
        sents=len(sents),
        sent_mean=round(mean(lens), 1) if lens else 0,
        sent_median=median(lens) if lens else 0,
        sent_p90=sorted(lens)[int(len(lens) * 0.9)] if lens else 0,
        sent_short=round(100 * sum(1 for l in lens if l <= 15) / max(1, len(lens))),
        nums=len(nums),
        num_per_1k=round(1000 * len(nums) / max(1, chars), 1),
        me=round(1000 * ptxt.count("我") / max(1, chars), 1),
        q=ptxt.count("？"),
        paren=ptxt.count("（"),
        ascii_ratio=round(100 * len(re.findall(r"[A-Za-z]", ptxt)) / max(1, chars)),
    )


COLS = ["file", "chars", "heads", "quote_blocks", "code", "code_pct", "imgs", "links",
        "paras", "para_mean", "sents", "sent_mean", "sent_median", "sent_p90",
        "sent_short", "nums", "num_per_1k", "me", "q", "paren", "ascii_ratio"]


def main():
    d = Path(sys.argv[1])
    prefix = sys.argv[2] if len(sys.argv) > 2 else ""
    rows = [stats(f) for f in sorted(d.glob(f"{prefix}*.md")) if f.stat().st_size > 800]
    if not rows:
        print(f"no files under {d} matching {prefix}*.md")
        return
    print("| " + " | ".join(COLS) + " |")
    print("|" + "|".join(["---"] * len(COLS)) + "|")
    for r in rows:
        print("| " + " | ".join(str(r[c]) for c in COLS) + " |")
    print()
    for k in ["chars", "para_mean", "sent_mean", "sent_short", "num_per_1k", "me", "heads"]:
        v = [r[k] for r in rows]
        print(f"{k}: mean={mean(v):.1f} median={median(v):.1f}")


if __name__ == "__main__":
    main()
