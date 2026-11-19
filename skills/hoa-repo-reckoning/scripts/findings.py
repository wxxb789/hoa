#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Validate, rank, render and ledger an audit panel's findings (see references/panel.md).

    uv run scripts/findings.py check RUN
    uv run scripts/findings.py report RUN [--prev PREV_RUN] [--top N]
    uv run scripts/findings.py decide RUN ID accepted|rejected|done "reason"

RUN holds find-*.json ({"dim", "findings"}), verify-*.json ({"dim", "verdicts"}) and an
optional spot.json (ids the parent re-checked). Every error names file:[index].key; exit 1.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import sys
from pathlib import Path

FINDING = ("id", "kind", "title", "claim", "evidence", "impact", "action", "owner", "effort", "severity")
VERDICT = ("id", "verdict", "rationale", "checked")
ENUMS = {"kind": ("dumb", "unknown"), "effort": ("S", "M", "L"),
         "severity": ("high", "medium", "low"), "verdict": ("confirmed", "weakened", "refuted")}


def jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()] if path.is_file() else []


def evidence_hash(finding: dict) -> str:
    return hashlib.sha256(json.dumps(sorted(finding["evidence"])).encode()).hexdigest()[:12]


def entries(path: Path, key: str, required: tuple, errors: list) -> list[dict]:
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))[key]
        assert isinstance(rows, list)
    except (OSError, ValueError, KeyError, TypeError, AssertionError):
        errors.append(f"{path.name}:{key}: missing or not a list")
        return []
    for i, row in enumerate(rows):
        where = f"{path.name}:[{i}]"
        if not isinstance(row, dict):
            errors.append(f"{where}: not an object")
            continue
        for field in required:
            if row.get(field) in (None, "", []):
                errors.append(f"{where}.{field}: missing")
        for field, allowed in ENUMS.items():
            if field in row and row[field] not in allowed:
                errors.append(f"{where}.{field}: {row[field]!r} not in {allowed}")
        if key == "findings" and row.get("kind") == "unknown" and not row.get("sources"):
            errors.append(f"{where}.sources: required when kind is unknown")
        if key == "verdicts" and row.get("verdict") == "weakened" and not row.get("claim"):
            errors.append(f"{where}.claim: required when verdict is weakened")
    return [row for row in rows if isinstance(row, dict)]


def load(run: Path) -> tuple[dict, dict, list]:
    """Return ({id: finding+dim}, {id: [verdicts]}, errors)."""
    errors: list[str] = []
    findings: dict[str, dict] = {}
    verdicts: dict[str, list] = {}
    for path in sorted(run.glob("find-*.json")):
        for i, row in enumerate(entries(path, "findings", FINDING, errors)):
            if row.get("id") in findings:
                errors.append(f"{path.name}:[{i}].id: duplicate {row['id']!r}")
            findings[row.get("id")] = {**row, "dim": path.stem[5:], "where": f"{path.name}:[{i}].id"}
    for path in sorted(run.glob("verify-*.json")):
        for i, row in enumerate(entries(path, "verdicts", VERDICT, errors)):
            if row.get("id") not in findings:
                errors.append(f"{path.name}:[{i}].id: no finding {row.get('id')!r}")
            verdicts.setdefault(row.get("id"), []).append(row)
    errors += [f"{f['where']}: no verdict for {i!r}" for i, f in findings.items() if i not in verdicts]
    return findings, verdicts, errors


def merge(finding: dict, verdicts: list) -> dict | None:
    """Refuted anywhere drops the finding; a weakened verdict substitutes its claim/severity."""
    if any(v["verdict"] == "refuted" for v in verdicts):
        return None
    weak = [v for v in verdicts if v["verdict"] == "weakened"]
    if not weak:
        return {**finding, "status": "confirmed"}
    return {**finding, "claim": weak[-1]["claim"], "severity": weak[-1].get("severity", finding["severity"]),
            "status": "weakened"}


def cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def report(run: Path, prev: Path | None, top: int | None) -> int:
    findings, verdicts, errors = load(run)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    earlier = [d for d in run.parent.iterdir() if d.is_dir() and d.name < run.name]
    decisions = [row for d in [*earlier, run] for row in jsonl(d / "decisions.jsonl")]
    rejected = {(row["id"], row.get("evidence_hash")) for row in decisions if row["decision"] == "rejected"}
    done = {row["id"] for row in decisions if row["decision"] == "done"}
    accepted = {row["id"] for row in decisions if row["decision"] == "accepted"} - done
    spot = set(json.loads((run / "spot.json").read_text(encoding="utf-8"))) if (run / "spot.json").is_file() else set()
    merged = {i: merge(f, verdicts[i]) for i, f in findings.items()}
    suppressed = {f["id"] for f in merged.values() if f and (f["id"], evidence_hash(f)) in rejected}
    live = [f for f in merged.values() if f and f["id"] not in suppressed]
    order = {"high": 0, "medium": 1, "low": 2, "S": 0, "M": 1, "L": 2, "confirmed": 0, "weakened": 1}
    live.sort(key=lambda f: (order[f["severity"]], order[f["effort"]], order[f["status"]], f["id"]))
    counts = {s: sum(1 for f in merged.values() if f and f["status"] == s) for s in ("confirmed", "weakened")}
    scope = (run / "scope.md").read_text(encoding="utf-8") if (run / "scope.md").is_file() else ""
    lines = [f"# Audit report: {run.parent.name} {run.name}", "",
             f"{len(findings)} findings, {list(merged.values()).count(None)} refuted, {counts['confirmed']} confirmed, "
             f"{counts['weakened']} weakened, {len(suppressed)} suppressed by a rejection."]
    lines += [line.strip() for line in scope.splitlines() if line.strip().lower().startswith("verification:")]
    for kind, label, title in (("dumb", "A", "A. Dumb things still being done"), ("unknown", "B", "B. Unknown unknowns")):
        rows = [f for f in live if f["kind"] == kind][:top]
        lines += ["", f"## {title}", ""]
        if not rows:
            lines.append("_external lane not run_" if kind == "unknown" and "external lane: not run" in scope.lower()
                         else "_none_")
            continue
        lines += ["| # | Finding | Severity | Effort | Owner | Action |", "|---|---|---|---|---|---|"]
        lines += [f"| {label}{n}{' ✔' if f['id'] in spot else ''} | **{cell(f['title'])}**: {cell(f['claim'])} "
                  f"(`{f['id']}`) | {f['severity']} | {f['effort']} | {cell(f['owner'])} | {cell(f['action'])} |"
                  for n, f in enumerate(rows, 1)]
    if prev:
        ids = {f["id"] for f in live}
        lines += ["", f"## Follow-through since {prev.name}", ""]
        for row in jsonl(prev / "ledger.jsonl"):
            seen = sum(1 for d in earlier if any(r["id"] == row["id"] for r in jsonl(d / "ledger.jsonl")))
            if row["id"] in ids:
                status = "accepted, pending" if row["id"] in accepted else "recurring"
                state = "regressed" if row["id"] in done else f"{status} ({seen + 1} runs)"
            else:
                state = "suppressed (rejected)" if row["id"] in suppressed else "not re-found: verify addressed"
            lines.append(f"- `{row['id']}`: {state}")
    (run / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (run / "ledger.jsonl").write_text("".join(json.dumps(
        {k: f[k] for k in ("id", "kind", "dim", "title", "severity", "effort", "owner", "status")}
        | {"evidence_hash": evidence_hash(f)}) + "\n" for f in live), encoding="utf-8")
    print(f"report: {run / 'report.md'} ({len(live)} findings)")
    return 0


def decide(run: Path, finding_id: str, decision: str, reason: str) -> int:
    row = next((r for r in jsonl(run / "ledger.jsonl") if r["id"] == finding_id), None)
    if row is None:
        print(f"ledger.jsonl:id {finding_id!r}: not in this run's ledger; run report first", file=sys.stderr)
        return 1
    with (run / "decisions.jsonl").open("a", encoding="utf-8") as out:
        out.write(json.dumps({"id": finding_id, "decision": decision, "reason": reason,
                              "date": datetime.date.today().isoformat(),
                              "evidence_hash": row["evidence_hash"]}) + "\n")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check").add_argument("run", type=Path)
    rep = sub.add_parser("report")
    rep.add_argument("run", type=Path)
    rep.add_argument("--prev", type=Path)
    rep.add_argument("--top", type=int)
    dec = sub.add_parser("decide")
    dec.add_argument("run", type=Path)
    dec.add_argument("id")
    dec.add_argument("decision", choices=("accepted", "rejected", "done"))
    dec.add_argument("reason")
    args = parser.parse_args(argv)
    if args.command == "report":
        return report(args.run.resolve(), args.prev.resolve() if args.prev else None, args.top)
    if args.command == "decide":
        return decide(args.run, args.id, args.decision, args.reason)
    findings, verdicts, errors = load(args.run)
    print("\n".join(errors) or f"check: {len(findings)} findings, {sum(map(len, verdicts.values()))} verdicts OK",
          file=sys.stderr if errors else sys.stdout)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
