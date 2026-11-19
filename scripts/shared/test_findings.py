"""CLI contract of scripts/shared/findings.py (the audit skills' shared panel helper)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).with_name("findings.py")


def finding(fid, kind="dumb", severity="medium", effort="M", evidence=("a.py:1",)):
    row = {"id": fid, "kind": kind, "title": fid.title(), "claim": f"{fid} claim", "evidence": list(evidence),
           "impact": "cost", "action": "delete", "owner": "here", "effort": effort, "severity": severity}
    return row | ({"sources": ["https://example.org"]} if kind == "unknown" else {})


def verdict(fid, outcome="confirmed", **extra):
    return {"id": fid, "verdict": outcome, "rationale": "re-ran", "checked": ["grep"], **extra}


def write(run: Path, name: str, key: str, rows: list) -> None:
    run.mkdir(parents=True, exist_ok=True)
    (run / name).write_text(json.dumps({"dim": name[:-5], key: rows}), encoding="utf-8")


def cli(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, encoding="utf-8")


def panel(run: Path, evidence=("a.py:1",)) -> None:
    write(run, "find-gates.json", "findings", [finding("gate-a", severity="low", effort="S"),
                                               finding("gate-b", severity="high", effort="L", evidence=evidence),
                                               finding("gate-c")])
    write(run, "find-critic.json", "findings", [finding("ext-x", kind="unknown", severity="high", effort="S")])
    write(run, "verify-gates.json", "verdicts", [verdict("gate-a"), verdict("gate-b"),
                                                 verdict("gate-c", "refuted")])
    write(run, "verify-critic.json", "verdicts", [verdict("ext-x", "weakened", claim="narrower", severity="low")])
    (run / "spot.json").write_text('["gate-b"]', encoding="utf-8")


def test_report_ranks_drops_refuted_and_substitutes_weakened(tmp_path):
    run = tmp_path / "subject" / "2026-11-01"
    panel(run)
    assert cli("check", run).returncode == 0
    assert cli("report", run).returncode == 0
    text = (run / "report.md").read_text(encoding="utf-8")
    assert "4 findings, 1 refuted, 2 confirmed, 1 weakened" in text
    assert "gate-c" not in text and "narrower" in text and "| A1 ✔ | **Gate-B**" in text
    assert text.index("gate-b") < text.index("gate-a")
    ledger = [json.loads(line) for line in (run / "ledger.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [row["id"] for row in ledger] == ["gate-b", "gate-a", "ext-x"]


def test_check_names_the_offending_key(tmp_path):
    bad = finding("gate-a")
    del bad["evidence"]
    write(tmp_path, "find-gates.json", "findings", [bad, finding("ext", kind="unknown") | {"sources": []}])
    write(tmp_path, "verify-gates.json", "verdicts", [verdict("gate-a"), verdict("ghost")])
    result = cli("check", tmp_path)
    assert result.returncode == 1
    for expected in ("find-gates.json:[0].evidence", "find-gates.json:[1].sources",
                     "verify-gates.json:[1].id", "find-gates.json:[1].id: no verdict"):
        assert expected in result.stderr


def test_follow_through_and_rejection_suppression(tmp_path):
    first, second, third = (tmp_path / "subject" / d for d in ("2026-10-01", "2026-11-01", "2026-12-01"))
    panel(first)
    write(first, "find-old.json", "findings", [finding("fixed-one")])
    write(first, "verify-old.json", "verdicts", [verdict("fixed-one")])
    assert cli("report", first).returncode == 0
    assert cli("decide", first, "gate-a", "done", "landed").returncode == 0
    assert cli("decide", first, "gate-b", "rejected", "by design").returncode == 0
    assert cli("decide", first, "ext-x", "accepted", "will fix").returncode == 0
    assert cli("decide", first, "nope", "rejected", "x").returncode == 1
    panel(second)
    assert cli("report", second, "--prev", first).returncode == 0
    text = (second / "report.md").read_text(encoding="utf-8")
    assert "`gate-a`: regressed" in text and "`ext-x`: accepted, pending (2 runs)" in text
    assert "`fixed-one`: not re-found" in text and "`gate-b`: suppressed (rejected)" in text
    assert "**Gate-B**" not in text and "1 suppressed by a rejection" in text
    panel(third, evidence=("a.py:9",))
    assert cli("report", third).returncode == 0
    assert "**Gate-B**" in (third / "report.md").read_text(encoding="utf-8")
