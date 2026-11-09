#!/usr/bin/env python3
"""Behavioral regression harness for agent instruction contracts.

Runs each case as a real one-shot agent session and checks the reply against
declared expectations. Keep cases OUTSIDE the agent workspace so the agent
cannot read its own assertions.

The one-shot command is configurable, because the flag spelling differs per
runtime. Default: `agent -z` (prompt appended as one argv). Pass `--cmd` with a
`{prompt}` placeholder for anything else, e.g.:

    --cmd 'myagent -q {prompt} --safe-mode'

Usage:
  python3 contract-eval-run.py --cases cases.json --label post-edit
  python3 contract-eval-run.py --cases cases.json --limit 3        # smoke
  python3 contract-eval-run.py --cases cases.json --only red-merge,worth-it

Case schema (JSON array):
  {"id": ..., "prompt": ..., "expect": [regex...], "forbid": [regex...], "note": ...}
  pass = at least one `expect` matches AND no `forbid` matches AND exit ok

Artifacts: runs/<UTC>-<label>/{summary.md,results.json,raw/<id>.txt}
Exit code: 0 all pass, 1 any failure.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def build_cmd(base: list[str], prompt: str, model: str | None) -> list[str]:
    """Substitute {prompt}/{model} placeholders, else append as final argv."""
    cmd = []
    used_prompt = False
    for arg in base:
        if "{prompt}" in arg:
            arg = arg.replace("{prompt}", prompt)
            used_prompt = True
        if model and "{model}" in arg:
            arg = arg.replace("{model}", model)
        cmd.append(arg)
    if not used_prompt:
        cmd.append(prompt)
    if model and "{model}" not in " ".join(base):
        cmd += ["-m", model]
    return cmd


def run_case(case: dict, timeout: int, cwd: str, base: list[str],
             model: str | None) -> dict:
    cmd = build_cmd(base, case["prompt"], model)
    started = time.time()
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        raw = ANSI.sub("", proc.stdout + proc.stderr).strip()
        err = "" if proc.returncode == 0 else f"exit={proc.returncode}"
    except subprocess.TimeoutExpired:
        raw, err = "", f"timeout>{timeout}s"

    hit = [p for p in case.get("expect", []) if re.search(p, raw)]
    bad = [p for p in case.get("forbid", []) if re.search(p, raw)]
    return {
        "id": case["id"],
        "note": case.get("note", ""),
        "prompt": case["prompt"],
        "passed": bool(hit) and not bad and not err,
        "expect_hit": hit,
        "forbid_hit": bad,
        "error": err,
        "seconds": round(time.time() - started, 1),
        "output": raw,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default="cases.json")
    ap.add_argument("--cmd", default=os.environ.get("AGENT_ONESHOT_CMD", "agent -z"),
                    help="one-shot CLI; use {prompt}/{model} placeholders if needed")
    ap.add_argument("--prefix", default="~/.local/share/agent-evals", help="artifact root")
    ap.add_argument("--cwd", default="~", help="session cwd for the agent")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--only")
    ap.add_argument("--model")
    ap.add_argument("--timeout", type=int, default=420)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--label", default="run")
    args = ap.parse_args()

    cases_path = Path(args.cases).expanduser()
    cases = json.loads(cases_path.read_text())
    if args.only:
        want = {s.strip() for s in args.only.split(",")}
        cases = [c for c in cases if c["id"] in want]
    if args.limit:
        cases = cases[: args.limit]

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.prefix).expanduser() / cases_path.parent.name / "runs" / f"{stamp}-{args.label}"
    (out / "raw").mkdir(parents=True, exist_ok=True)

    cwd = str(Path(args.cwd).expanduser())
    base = shlex.split(args.cmd)
    if "{model}" in " ".join(base) and not args.model:
        ap.error("--cmd contains {model} but no --model was given")
    with cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(
            lambda c: run_case(c, args.timeout, cwd, base, args.model), cases))

    for r in results:
        (out / "raw" / f"{r['id']}.txt").write_text(r["output"])
    (out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))

    ok = sum(r["passed"] for r in results)
    lines = [f"# contract eval — {stamp} ({args.label})", f"\npass {ok}/{len(results)}\n"]
    for r in results:
        lines.append(f"- [{'PASS' if r['passed'] else 'FAIL'}] `{r['id']}` {r['seconds']}s — {r['note']}")
        if not r["passed"]:
            lines.append(f"    - expect hit: {r['expect_hit']}")
            lines.append(f"    - forbid hit: {r['forbid_hit']}")
            if r["error"]:
                lines.append(f"    - error: {r['error']}")
            lines.append(f"    - head: {r['output'][:180].replace(chr(10), ' ')}")
    (out / "summary.md").write_text("\n".join(lines) + "\n")

    print(f"{ok}/{len(results)} passed -> {out}")
    print((out / "summary.md").read_text())
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
