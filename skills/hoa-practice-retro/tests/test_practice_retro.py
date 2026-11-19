"""CLI contracts of hoa-practice-retro's deterministic scripts over the bundled fixtures."""
from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

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
