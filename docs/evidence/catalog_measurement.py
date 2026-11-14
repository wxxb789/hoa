#!/usr/bin/env python3
"""Read a pinned catalog snapshot without checkout, network or skill execution.

Usage: python docs/evidence/catalog_measurement.py --ref cabf8c6 [--repo PATH]
Requires the existing scripts/requirements.txt dependency (PyYAML). JSON goes to stdout.
Body strips YAML/frontmatter and exterior blanks; lines/words use splitlines/split.
ATX H2 excludes backtick/tilde fences; p90 uses nearest rank.
"""
import argparse
import json
import math
from pathlib import Path
import re
import statistics
import subprocess

import yaml


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args]).decode("utf-8")


def body_metrics(text):
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise ValueError("missing frontmatter")
    end = lines.index("---", 1)
    metadata = yaml.safe_load("\n".join(lines[1:end]))["metadata"]
    body = lines[end + 1:]
    while body and not body[0].strip():
        body.pop(0)
    while body and not body[-1].strip():
        body.pop()
    headings, fence = 0, None
    for line in body:
        match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if match:
            token, rest = match.groups()
            if fence is None:
                fence = (token[0], len(token))
            elif token[0] == fence[0] and len(token) >= fence[1] and not rest.strip():
                fence = None
            continue
        if fence is None and re.match(r"^ {0,3}##(?:\s|$)", line):
            headings += 1
    return {"kind": metadata["kind"], "body_lines": len(body),
            "body_words": len("\n".join(body).split()), "h2": headings,
            "full_lines": len(lines)}


def distribution(values):
    ordered = sorted(values)
    return {"total": sum(values), "median": statistics.median(values),
            "p90": ordered[math.ceil(0.9 * len(values)) - 1], "max": max(values),
            "over_120": sum(v > 120 for v in values),
            "between_121_and_200": sum(120 < v <= 200 for v in values)}


def measure(repo, ref):
    commit = git(repo, "rev-parse", f"{ref}^{{commit}}").strip()
    paths = git(repo, "ls-tree", "-r", "--name-only", commit).splitlines()
    rows = []
    for path in paths:
        if re.fullmatch(r"skills/[^/]+/SKILL\.md", path):
            rows.append({"skill": path.split("/")[1],
                         **body_metrics(git(repo, "show", f"{commit}:{path}"))})
    queue = [r for r in rows if r["body_lines"] > 200 and (r["h2"] >= 8 or r["body_words"] > 2500)]
    code = []
    for path in paths:
        if path.startswith("ref/") or Path(path).suffix not in {".py", ".sh", ".ts", ".tsx"}:
            continue
        count = len(git(repo, "show", f"{commit}:{path}").splitlines())
        if count > 600:
            code.append({"path": path, "lines": count})
    return {"commit": commit, "tree": git(repo, "rev-parse", f"{commit}^{{tree}}").strip(),
            "skills": len(rows), "body": distribution([r["body_lines"] for r in rows]),
            "full_file": distribution([r["full_lines"] for r in rows]),
            "queue_count": len(queue), "queue": queue,
            "stubs": [r for r in rows if r["body_words"] < 50], "rows": rows,
            "code_over_600": sorted(code, key=lambda r: (-r["lines"], r["path"]))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="repo root (default cwd)")
    parser.add_argument("--ref", required=True, help="local Git commit/ref; no network or checkout")
    args = parser.parse_args()
    print(json.dumps(measure(args.repo, args.ref), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
