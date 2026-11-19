"""CLI contracts of hoa-practice-retro's deterministic scripts over the bundled fixtures."""
from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1]
FIXTURES = SKILL / "tests" / "fixtures"


def run(script: str, *args) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SKILL / "scripts" / script), *map(str, args)],
                          capture_output=True, encoding="utf-8")


def audit(fixture: str, run_dir: Path) -> dict:
    shutil.copy(FIXTURES / fixture / "find-habits.json", run_dir / "find-habits.json")
    result = run("audit.py", "--bundle", FIXTURES / fixture / "bundle.json", "--run", run_dir)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads((run_dir / "verify-citations.json").read_text(encoding="utf-8"))


def test_zero_findings_is_a_complete_retro(tmp_path):
    assert audit("zero-blind-spots", tmp_path)["verdicts"] == []
    assert run("findings.py", "report", tmp_path).returncode == 0
    assert "0 findings" in (tmp_path / "report.md").read_text(encoding="utf-8")


def test_evidence_floor_refutes_broken_and_single_origin_findings(tmp_path):
    verdicts = {v["id"]: v for v in audit("bad-citation", tmp_path)["verdicts"]}
    assert set(verdicts) == {"must-drop", "single-origin"}
    assert all(v["verdict"] == "refuted" and v["checked"] for v in verdicts.values())
    assert "unresolvable" in verdicts["must-drop"]["rationale"]


def test_jsonl_bundle_resolves_every_locator_kind_and_isolates_unavailable_sources(tmp_path):
    (tmp_path / "obj.json").write_text('{"a": 1}', encoding="utf-8")
    (tmp_path / "arr.json").write_text("[1, 2]", encoding="utf-8")
    (tmp_path / "log.txt").write_text("seen\n", encoding="utf-8")
    with sqlite3.connect(tmp_path / "db.sqlite") as db:
        db.execute("CREATE TABLE messages (text)")
        db.execute("INSERT INTO messages VALUES ('hi')")
    db.close()
    sources = [{"agent": "up", "status": "available"}, {"agent": "down", "status": "inaccessible"}]
    records = [("up", "o-off", {"file": "obj.json", "offset": 2}), ("up", "o-idx", {"file": "arr.json", "index": 2}),
               ("up", "o-sql", {"file": "db.sqlite", "table": "messages", "rowid": 1}),
               ("down", "o-gap", {"file": "log.txt", "line": 1})]
    bundle = tmp_path / "bundle.jsonl"
    bundle.write_text("\n".join(json.dumps(row) for row in [{"kind": "coverage_manifest", "sources": sources}] + [
        {"agent": agent, "origin_fingerprint": origin, "locator": locator} for agent, origin, locator in records]),
        encoding="utf-8")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    findings = [{"id": "all-kinds", "evidence": ["bundle:o-off#obj.json?offset=2", "bundle:o-idx#arr.json?index=2",
                                                 "bundle:o-sql#db.sqlite?table=messages&rowid=1"]},
                {"id": "gap-only", "evidence": ["bundle:o-gap#log.txt?line=1", "git:repo@abc"]}]
    (run_dir / "find-habits.json").write_text(json.dumps({"dim": "habits", "findings": findings}), encoding="utf-8")
    result = run("audit.py", "--bundle", bundle, "--run", run_dir)
    assert result.returncode == 0, result.stdout + result.stderr
    verdicts = json.loads((run_dir / "verify-citations.json").read_text(encoding="utf-8"))["verdicts"]
    assert [(v["id"], "unresolvable" in v["rationale"]) for v in verdicts] == [("gap-only", True)]


def test_pii_gate_refuses_tracked_and_unignored_paths_but_allows_ignored(tmp_path):
    content = FIXTURES / "pii-gate" / "content.txt"
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    tracked = tmp_path / "tracked.md"
    tracked.write_text("unchanged", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", tracked.name], check=True)
    untracked = tmp_path / "untracked.md"
    for blocked in (tracked, untracked):
        refused = run("pii_gate.py", "--target", blocked, "--content-file", content)
        assert refused.returncode == 1
        assert json.loads(refused.stdout)["reason"] == "tracked-or-unignored-worktree-path"
    assert tracked.read_text(encoding="utf-8") == "unchanged"
    assert not untracked.exists()
    (tmp_path / ".gitignore").write_text("report.md\n", encoding="utf-8")
    ignored = tmp_path / "report.md"
    assert run("pii_gate.py", "--target", ignored, "--content-file", content).returncode == 0
    assert ignored.read_text(encoding="utf-8") == content.read_text(encoding="utf-8")


def test_aggregate_emits_facets(tmp_path):
    output = tmp_path / "facets.json"
    result = run("aggregate.py", "--bundle", FIXTURES / "zero-blind-spots" / "bundle.json", "--output", output)
    assert result.returncode == 0, result.stderr
    facets = json.loads(output.read_text(encoding="utf-8"))
    assert facets["aggregated_data"]["record_count"] == 2
    assert facets["facets_summary"]["skill_call_frequency"]


def test_recurrence_candidate_decision_uses_report_ledger(tmp_path):
    candidate_id = "repeat-release-check"
    finding = {
        "id": candidate_id, "kind": "dumb", "title": "Repeated release check",
        "claim": "The same manual release check recurred three times across two projects",
        "evidence": ["git:repo-a@abc", "git:repo-b@def", "git:repo-b@123"],
        "impact": "Repeated manual work", "action": "Propose a skill",
        "owner": "here", "effort": "S", "severity": "low",
    }
    (tmp_path / "find-recurrence.json").write_text(json.dumps({
        "dim": "recurrence", "findings": [finding],
    }), encoding="utf-8")
    (tmp_path / "verify-recurrence.json").write_text(json.dumps({
        "dim": "recurrence", "verdicts": [{
            "id": candidate_id, "verdict": "confirmed",
            "rationale": "Independent evidence confirms recurrence", "checked": ["git log"],
        }],
    }), encoding="utf-8")
    decisions = tmp_path / "decisions.jsonl"
    decision_args = ("decide", tmp_path, candidate_id, "accepted", "Owner approved this ID")
    assert run("findings.py", *decision_args).returncode == 1
    assert not decisions.exists()

    report = run("findings.py", "report", tmp_path)
    assert report.returncode == 0, report.stderr
    ledger_row = json.loads((tmp_path / "ledger.jsonl").read_text(encoding="utf-8"))
    assert (ledger_row["id"], ledger_row["dim"]) == (candidate_id, "recurrence")
    for approval in ("looks good", "all of them", f"{candidate_id},another-id"):
        assert run("findings.py", "decide", tmp_path, approval, "accepted", "Owner reply").returncode == 1
    assert not decisions.exists()

    decision = run("findings.py", *decision_args)
    assert decision.returncode == 0, decision.stderr
    recorded = json.loads(decisions.read_text(encoding="utf-8"))
    assert (recorded["id"], recorded["decision"]) == (candidate_id, "accepted")
    assert recorded["evidence_hash"] == ledger_row["evidence_hash"]


@pytest.mark.parametrize("script", ["aggregate.py", "audit.py"])
@pytest.mark.parametrize("marker", ["", "gitdir: missing-git-dir\n"], ids=["corrupt", "dangling"])
def test_unresolved_git_marker_refuses_output(tmp_path, script, marker):
    (tmp_path / ".git").write_text(marker, encoding="utf-8")
    bundle = FIXTURES / "zero-blind-spots" / "bundle.json"
    output = tmp_path / "output.json"
    args = ("--run", tmp_path) if script == "audit.py" else ()
    result = run(script, "--bundle", bundle, "--output", output, *args)
    assert result.returncode == 1, result.stdout + result.stderr
    assert json.loads(result.stdout)["decision"] == "refuse"
    assert not output.exists()


@pytest.mark.parametrize("script", ["aggregate.py", "audit.py"])
def test_jsonl_requires_manifest_first(tmp_path, script):
    bundle = tmp_path / "bundle.jsonl"
    record = {"kind": "record", "agent": "demo", "origin_fingerprint": "o1",
              "locator": {"file": "x", "line": 1}}
    manifest = {"kind": "coverage_manifest", "sources": [{"agent": "demo", "status": "available"}]}
    bundle.write_text(json.dumps(record) + "\n" + json.dumps(manifest) + "\n", encoding="utf-8")
    output = tmp_path / "output.json"
    args = ("--run", tmp_path) if script == "audit.py" else ()
    result = run(script, "--bundle", bundle, "--output", output, *args)
    assert result.returncode == 2, result.stdout + result.stderr
    assert json.loads(result.stdout)["reason"] == "invalid-input"
    assert not output.exists()


def test_audit_rejects_oversized_findings_file(tmp_path):
    bundle = FIXTURES / "zero-blind-spots" / "bundle.json"
    (tmp_path / "find-habits.json").write_bytes(b'{"findings": []}' + b" " * (16 * 1024 * 1024))
    result = run("audit.py", "--bundle", bundle, "--run", tmp_path)
    assert result.returncode == 2, result.stdout + result.stderr
    assert json.loads(result.stdout)["reason"] == "invalid-input"
    assert not (tmp_path / "verify-citations.json").exists()


def test_audit_refutes_citations_to_missing_and_non_utf8_sources(tmp_path):
    (tmp_path / "binary.txt").write_bytes(b"\xff\xfe")
    bundle = tmp_path / "bundle.json"
    bundle.write_text(json.dumps({
        "coverage_manifest": {"sources": [{"agent": "demo", "status": "available"}]},
        "records": [
            {"agent": "demo", "origin_fingerprint": origin, "locator": {"file": f"{origin}.txt", "line": 1}}
            for origin in ("missing", "binary")
        ],
    }), encoding="utf-8")
    (tmp_path / "find-habits.json").write_text(json.dumps({
        "dim": "habits",
        "findings": [
            {"id": origin, "evidence": [f"bundle:{origin}#{origin}.txt?line=1", "git:repo@abc"]}
            for origin in ("missing", "binary")
        ],
    }), encoding="utf-8")
    result = run("audit.py", "--bundle", bundle, "--run", tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    verdicts = json.loads((tmp_path / "verify-citations.json").read_text(encoding="utf-8"))["verdicts"]
    assert {v["id"]: v["verdict"] for v in verdicts} == {"missing": "refuted", "binary": "refuted"}
