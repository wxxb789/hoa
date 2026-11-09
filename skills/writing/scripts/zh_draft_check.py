#!/usr/bin/env python3
"""Chinese draft self-check: sentence length, structure-level AI counters, rewrite similarity.

Usage:
    python3 zh_draft_check.py draft.md [--old previous.md] [--limit 55]

Why script it: sentence length, banned-pattern counts and "is this a real rewrite or the old
article in new clothes" are all measurable. Eyeballing them is how uniform, machine-smooth prose
gets shipped.

Reads the draft as prose (frontmatter and fenced code blocks removed for stats; code blocks are
never judged). Enumeration lines (label lists, field lists, ledgers) are marked [ENUM] because the
contract exempts them from the 55-char limit -- do not split sentences to please the counter.
"""
import argparse
import difflib
import re
from pathlib import Path

CJK_END = "\u3002\uff01\uff1f"  # 。！？
BANNED = r"(赋能|抓手|闭环|范式|一文读懂|深度解析|浅谈|你必须知道|降维打击)"


def strip_frontmatter(text):
    m = re.match(r"^---\n.*?\n---\n", text, flags=re.S)
    return text[m.end():] if m else text


def split_code(text):
    blocks = re.findall(r"```.*?```", text, flags=re.S)
    prose = re.sub(r"```.*?```", "[[CODE]]", text, flags=re.S)
    return prose, blocks


def is_enum(s):
    """Label lists / field lists / ledger lines: exempt from the single-sentence limit."""
    if s.count("\u3001") >= 2:
        return True
    if len(re.findall(r"\d+\s*(份|条|项|个|行|篇|次|倍|字段)", s)) >= 3:
        return True
    return bool(re.match(r"^[\w\- ]{2,20}\s*\d+\s*(份|条|项|个|行)$", s.strip()))


def sentences(prose):
    """[(sentence, counted_length)] -- inline code and quoted spans do not count."""
    out = []
    for line in prose.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("[[CODE]]"):
            continue
        if line.startswith("|") or line.startswith("---"):
            continue
        line = re.sub(r"^\s*[-*]\s+", "", line)
        line = re.sub(r"^\d+\.\s+", "", line)
        for part in re.split(f"[{CJK_END}]", line):
            part = part.strip()
            if not part:
                continue
            counted = re.sub(r"`[^`]*`", "", part)
            counted = re.sub(r"\u300c[^\u300d]*\u300d|\u201c[^\u201d]*\u201d|\"[^\"]*\"", "", counted)
            out.append((part, len(re.sub(r"\s", "", counted))))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("draft")
    ap.add_argument("--old", help="previous version, to measure how much was actually rewritten")
    ap.add_argument("--limit", type=int, default=55)
    a = ap.parse_args()

    text = strip_frontmatter(Path(a.draft).read_text())
    prose, blocks = split_code(text)
    sents = sentences(prose)
    lens = [n for _, n in sents]
    chars = len(re.sub(r"\s", "", prose))
    print(f"chars(prose)={chars} sentences={len(sents)}")
    if lens:
        print(f"avg={sum(lens)/len(lens):.1f} max={max(lens)} limit={a.limit}")

    over = [(s, n) for s, n in sents if n > a.limit]
    real = [(s, n) for s, n in over if not is_enum(s)]
    print(f"over={len(over)} (exempt-enum={len(over)-len(real)}, real={len(real)}) limit={a.limit}")
    for s, n in over:
        tag = "ENUM" if is_enum(s) else "FIX "
        print(f"  [{tag}] {n}\u5b57 {s[:70]}")

    short = [s for s, n in sents if n <= 10]
    print(f"short<=10={len(short)} (contract wants >=3)")
    for s in short[:6]:
        print(f"  - {s}")

    checks = {
        "不是…而是": len(re.findall(r"不是[^。！？]{0,25}而是", prose)),
        "段首连接词": len(re.findall(r"(值得注意的是|事实上|此外|然而|与此同时|换言之)", prose)),
        "升维词": len(re.findall(r"(本质上|归根结底|说到底)", prose)),
        "自编靶子": len(re.findall(r"(有人可能会问|你可能会觉得|你或许会)", prose)),
        "命名仪式": len(re.findall(r"(我把它称为|我称之为|即所谓)", prose)),
        "推断标记": len(re.findall(r"推断：", prose)),
        "禁词": len(re.findall(BANNED, prose)),
        "破折号": prose.count("——"),
    }
    for k, v in checks.items():
        print(f"{k}={v}")
    print(f"code_blocks={len(blocks)}")

    if a.old:
        old_text = strip_frontmatter(Path(a.old).read_text())
        old_prose, _ = split_code(old_text)
        ratio = difflib.SequenceMatcher(None, re.sub(r"\s", "", old_prose), re.sub(r"\s", "", prose)).ratio()
        print(f"\nsimilarity_char={ratio*100:.1f}%")
        old_s = {re.sub(r"\s", "", s) for s, _ in sentences(old_prose)}
        new_s = [re.sub(r"\s", "", s) for s, _ in sentences(prose)]
        reused = [s for s in new_s if s and s in old_s]
        print(f"sentences_new={len(new_s)} verbatim_reused={len(reused)} ({len(reused)/max(1,len(new_s))*100:.0f}%)")
        for s in reused:
            kind = "材料/固定句" if re.match(r"(推断：|依据是|\*\*上文\*\*|\*\*下文\*\*|\*\*旁支\*\*)", s) else "旧稿叙述句!"
            print(f"  [{kind}] {s[:80]}")

    nums = sorted(set(re.findall(r"\d[\d,\.]*", prose)))
    print(f"\nnumbers({len(nums)}): {' '.join(nums)}")
    print("next: trace every number with fact_check.py against run-logs/ledger/report")


if __name__ == "__main__":
    main()
