#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
# ─── How to run ───
# python evals/run.py
"""Run self-contained behavior checks for hoa-introspect safety contracts."""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
FIXTURES = ROOT / "evals" / "fixtures"
CONTENT = FIXTURES / "pii-gate" / "content.txt"


def run_script(script: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Run a local standard-library script with stable text capture."""
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *arguments],
        text=True,
        capture_output=True,
        check=False,
    )


def fixture_path(name: str, file_name: str) -> Path:
    """Return a fixture file path."""
    return FIXTURES / name / file_name


def assert_zero_candidates() -> None:
    """Given no claims, then the audit emits zero candidates without padding."""
    fixture = "zero-blind-spots"
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "actual.json"
        result = run_script(
            "audit.py",
            "--bundle", str(fixture_path(fixture, "bundle.json")),
            "--claims", str(fixture_path(fixture, "claims.json")),
            "--output", str(output),
        )
        assert result.returncode == 0, result.stderr
        actual = json.loads(output.read_text(encoding="utf-8"))
        assert actual["claims"] == []
        assert actual["dropped_claims"] == []


def assert_bad_citation_dropped() -> None:
    """Given an invalid locator, then its claim is excluded entirely."""
    fixture = "bad-citation"
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "actual.json"
        result = run_script(
            "audit.py",
            "--bundle", str(fixture_path(fixture, "bundle.json")),
            "--claims", str(fixture_path(fixture, "claims.json")),
            "--output", str(output),
        )
        assert result.returncode == 0, result.stderr
        actual = json.loads(output.read_text(encoding="utf-8"))
        assert actual["claims"] == []
        assert actual["dropped_claims"] == [{"id": "must-drop", "reason": "fewer than two resolvable independent origins"}]


def assert_pii_gate() -> None:
    """Given tracked, ignored, and outside targets, then enforce safe writes."""
    refused = ROOT / "evals" / "fixtures" / "pii-gate" / "blocked.md"
    rejected = run_script("pii_gate.py", "--target", str(refused), "--content-file", str(CONTENT))
    assert rejected.returncode == 1
    assert not refused.exists()
    assert json.loads(rejected.stdout)["decision"] == "refuse"
    ignored = ROOT / "evals" / "ignored-output" / "written.md"
    accepted = run_script("pii_gate.py", "--target", str(ignored), "--content-file", str(CONTENT))
    assert accepted.returncode == 0, accepted.stderr
    assert ignored.read_text(encoding="utf-8") == "Synthetic shareable report.\n"
    shutil.rmtree(ignored.parent)
    with tempfile.TemporaryDirectory() as directory:
        outside = Path(directory) / "written.md"
        external = run_script("pii_gate.py", "--target", str(outside), "--content-file", str(CONTENT))
        assert external.returncode == 0, external.stderr
        assert outside.exists()


def assert_jsonl_bundle_accepted() -> None:
    """Given a manifest-first JSONL bundle (hoa-agent-retrieve's real output), then parse it."""
    manifest = {"kind": "coverage_manifest", "sources": [{"agent": "demo", "status": "available"}]}
    record = {"kind": "record", "agent": "demo", "origin_fingerprint": "o1", "locator": {"file": "x", "line": 1}, "skills": ["demo"]}
    with tempfile.TemporaryDirectory() as directory:
        bundle = Path(directory) / "bundle.jsonl"
        bundle.write_text(json.dumps(manifest) + "\n" + json.dumps(record) + "\n", encoding="utf-8")
        facets = Path(directory) / "facets.json"
        aggregated = run_script("aggregate.py", "--bundle", str(bundle), "--output", str(facets))
        assert aggregated.returncode == 0, aggregated.stderr
        assert json.loads(facets.read_text(encoding="utf-8"))["aggregated_data"]["record_count"] == 1
        claims = Path(directory) / "claims.json"
        claims.write_text('{"claims": []}', encoding="utf-8")
        verified = Path(directory) / "verified.json"
        audited = run_script("audit.py", "--bundle", str(bundle), "--claims", str(claims), "--output", str(verified))
        assert audited.returncode == 0, audited.stderr


def assert_manifest_only_jsonl() -> None:
    """Given one manifest JSONL row, then aggregation preserves empty coverage."""
    manifest = {
        "kind": "coverage_manifest",
        "sources": [{"agent": "demo", "status": "available", "path_probed": "/private/path", "record_count": 0}],
    }
    with tempfile.TemporaryDirectory() as directory:
        bundle = Path(directory) / "bundle.jsonl"
        bundle.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
        output = Path(directory) / "facets.json"
        result = run_script("aggregate.py", "--bundle", str(bundle), "--output", str(output))
        assert result.returncode == 0, result.stderr
        actual = json.loads(output.read_text(encoding="utf-8"))["aggregated_data"]
        assert actual["record_count"] == 0
        assert actual["coverage"]["sources"] == [{"agent": "demo", "status": "available", "record_count": 0}]


def assert_coverage_isolation() -> None:
    """Given unavailable-agent records, then neither layer uses them as evidence."""
    manifest = {
        "coverage_manifest": {
            "sources": [
                {"agent": "available", "status": "available"},
                {"agent": "blocked", "status": "inaccessible"},
            ]
        },
        "records": [
            {"agent": "available", "origin_fingerprint": "a", "locator": {"file": "a.txt", "line": 1}, "skills": ["kept"]},
            {"agent": "blocked", "origin_fingerprint": "b", "locator": {"file": "b.txt", "line": 1}, "skills": ["excluded"]},
        ],
    }
    claims = {"claims": [{"id": "blocked-claim", "citations": [
        {"origin_fingerprint": "a", "locator": {"file": "a.txt", "line": 1}},
        {"origin_fingerprint": "b", "locator": {"file": "b.txt", "line": 1}},
    ]}]}
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "a.txt").write_text("available\n", encoding="utf-8")
        (root / "b.txt").write_text("blocked\n", encoding="utf-8")
        bundle = root / "bundle.json"
        claims_path = root / "claims.json"
        bundle.write_text(json.dumps(manifest), encoding="utf-8")
        claims_path.write_text(json.dumps(claims), encoding="utf-8")
        facets = root / "facets.json"
        aggregate = run_script("aggregate.py", "--bundle", str(bundle), "--output", str(facets))
        assert aggregate.returncode == 0, aggregate.stderr
        actual = json.loads(facets.read_text(encoding="utf-8"))
        assert actual["aggregated_data"]["record_count"] == 1
        assert actual["facets_summary"]["skill_call_frequency"] == {"kept": 1}
        verified = root / "verified.json"
        audit = run_script("audit.py", "--bundle", str(bundle), "--claims", str(claims_path), "--output", str(verified))
        assert audit.returncode == 0, audit.stderr
        assert json.loads(verified.read_text(encoding="utf-8"))["claims"] == []


def assert_output_gates() -> None:
    """Given tracked targets, then aggregate and audit refuse without writing."""
    fixture = "zero-blind-spots"
    bundle = fixture_path(fixture, "bundle.json")
    claims = fixture_path(fixture, "claims.json")
    for script, arguments in (
        ("aggregate.py", ("--bundle", str(bundle))),
        ("audit.py", ("--bundle", str(bundle), "--claims", str(claims))),
    ):
        blocked = ROOT / "blocked-output.json"
        result = run_script(script, *arguments, "--output", str(blocked))
        assert result.returncode == 1
        assert json.loads(result.stdout)["decision"] == "refuse"
        assert not blocked.exists()
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "facets.json"
        result = run_script("aggregate.py", "--bundle", str(bundle), "--output", str(output))
        assert result.returncode == 0, result.stderr
        assert output.exists()


def assert_bad_source_dropped() -> None:
    """Given missing and non-UTF8 sources, then the audit drops their claim."""
    manifest = {"coverage_manifest": {"sources": [{"agent": "demo", "status": "available"}]}, "records": [
        {"agent": "demo", "origin_fingerprint": "missing", "locator": {"file": "missing.txt", "line": 1}},
        {"agent": "demo", "origin_fingerprint": "binary", "locator": {"file": "binary.txt", "line": 1}},
    ]}
    claims = {"claims": [{"id": "bad-source", "citations": [
        {"origin_fingerprint": "missing", "locator": {"file": "missing.txt", "line": 1}},
        {"origin_fingerprint": "binary", "locator": {"file": "binary.txt", "line": 1}},
    ]}]}
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        bundle = root / "bundle.json"
        claims_path = root / "claims.json"
        output = root / "verified.json"
        (root / "binary.txt").write_bytes(b"\xff\xfe")
        bundle.write_text(json.dumps(manifest), encoding="utf-8")
        claims_path.write_text(json.dumps(claims), encoding="utf-8")
        result = run_script("audit.py", "--bundle", str(bundle), "--claims", str(claims_path), "--output", str(output))
        assert result.returncode == 0, result.stderr
        assert json.loads(output.read_text(encoding="utf-8"))["claims"] == []


def assert_corrupt_git_refused() -> None:
    """Given an unresolved Git marker, then aggregate and audit refuse writes."""
    fixture = "zero-blind-spots"
    bundle = fixture_path(fixture, "bundle.json")
    claims = fixture_path(fixture, "claims.json")
    with tempfile.TemporaryDirectory() as directory:
        target_directory = Path(directory) / "corrupt"
        target_directory.mkdir()
        (target_directory / ".git").write_text("", encoding="utf-8")
        for script, arguments in (
            ("aggregate.py", ("--bundle", str(bundle))),
            ("audit.py", ("--bundle", str(bundle), "--claims", str(claims))),
        ):
            output = target_directory / f"{script}.json"
            result = run_script(script, *arguments, "--output", str(output))
            assert result.returncode == 1
            assert json.loads(result.stdout)["decision"] == "refuse"
            assert not output.exists()


def assert_json_index_citations() -> None:
    """Given JSON index locators, then valid indices qualify and invalid ones drop."""
    manifest = {"coverage_manifest": {"sources": [{"agent": "demo", "status": "available"}]}}
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "items.json").write_text('["first", "second"]', encoding="utf-8")
        (root / "other.txt").write_text("evidence\n", encoding="utf-8")
        valid_index = {"file": "items.json", "index": 2}
        invalid_index = {"file": "items.json", "index": 3}
        text = {"file": "other.txt", "line": 1}
        manifest["records"] = [
            {"agent": "demo", "origin_fingerprint": "json", "locator": valid_index},
            {"agent": "demo", "origin_fingerprint": "json-out", "locator": invalid_index},
            {"agent": "demo", "origin_fingerprint": "text", "locator": text},
        ]
        claims = {"claims": [
            {"id": "index-kept", "citations": [
                {"origin_fingerprint": "json", "locator": valid_index},
                {"origin_fingerprint": "text", "locator": text},
            ]},
            {"id": "index-dropped", "citations": [
                {"origin_fingerprint": "json-out", "locator": invalid_index},
                {"origin_fingerprint": "text", "locator": text},
            ]},
        ]}
        bundle = root / "bundle.json"
        claims_path = root / "claims.json"
        output = root / "verified.json"
        bundle.write_text(json.dumps(manifest), encoding="utf-8")
        claims_path.write_text(json.dumps(claims), encoding="utf-8")
        result = run_script("audit.py", "--bundle", str(bundle), "--claims", str(claims_path), "--output", str(output))
        assert result.returncode == 0, result.stderr
        actual = json.loads(output.read_text(encoding="utf-8"))
        assert [claim["id"] for claim in actual["claims"]] == ["index-kept"]
        assert actual["dropped_claims"] == [{"id": "index-dropped", "reason": "fewer than two resolvable independent origins"}]


def assert_sqlite_citations() -> None:
    """Given read-only SQLite locators, then existing rowids qualify and missing ones drop."""
    manifest = {"coverage_manifest": {"sources": [{"agent": "demo", "status": "available"}]}}
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        database_path = root / "evidence.sqlite"
        database = sqlite3.connect(database_path)
        try:
            database.execute("CREATE TABLE evidence (value TEXT)")
            database.execute("INSERT INTO evidence VALUES ('synthetic')")
            database.commit()
        finally:
            database.close()
        (root / "other.txt").write_text("evidence\n", encoding="utf-8")
        present = {"file": "evidence.sqlite", "table": "evidence", "rowid": 1}
        absent = {"file": "evidence.sqlite", "table": "evidence", "rowid": 2}
        text = {"file": "other.txt", "line": 1}
        manifest["records"] = [
            {"agent": "demo", "origin_fingerprint": "sqlite", "locator": present},
            {"agent": "demo", "origin_fingerprint": "sqlite-missing", "locator": absent},
            {"agent": "demo", "origin_fingerprint": "text", "locator": text},
        ]
        claims = {"claims": [
            {"id": "sqlite-kept", "citations": [
                {"origin_fingerprint": "sqlite", "locator": present},
                {"origin_fingerprint": "text", "locator": text},
            ]},
            {"id": "sqlite-dropped", "citations": [
                {"origin_fingerprint": "sqlite-missing", "locator": absent},
                {"origin_fingerprint": "text", "locator": text},
            ]},
        ]}
        bundle = root / "bundle.json"
        claims_path = root / "claims.json"
        output = root / "verified.json"
        bundle.write_text(json.dumps(manifest), encoding="utf-8")
        claims_path.write_text(json.dumps(claims), encoding="utf-8")
        result = run_script("audit.py", "--bundle", str(bundle), "--claims", str(claims_path), "--output", str(output))
        assert result.returncode == 0, result.stderr
        actual = json.loads(output.read_text(encoding="utf-8"))
        assert [claim["id"] for claim in actual["claims"]] == ["sqlite-kept"]
        assert actual["dropped_claims"] == [{"id": "sqlite-dropped", "reason": "fewer than two resolvable independent origins"}]


def assert_oversized_claims_rejected() -> None:
    """Given a claims document over its cap, then audit exits 2 without writing."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        claims = root / "claims.json"
        claims.write_bytes(b" " * (16 * 1024 * 1024 + 1))
        output = root / "verified.json"
        result = run_script(
            "audit.py",
            "--bundle", str(fixture_path("zero-blind-spots", "bundle.json")),
            "--claims", str(claims),
            "--output", str(output),
        )
        assert result.returncode == 2
        assert json.loads(result.stdout) == {"decision": "error", "reason": "invalid-input"}
        assert not output.exists()


def assert_manifest_first_required() -> None:
    """Given a JSONL bundle whose first row is a record, then both tools reject it."""
    record = {"kind": "record", "agent": "demo", "origin_fingerprint": "o1", "locator": {"file": "x", "line": 1}}
    manifest = {"kind": "coverage_manifest", "sources": [{"agent": "demo", "status": "available"}]}
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        bundle = root / "bundle.jsonl"
        bundle.write_text(json.dumps(record) + "\n" + json.dumps(manifest) + "\n", encoding="utf-8")
        facets = root / "facets.json"
        aggregated = run_script("aggregate.py", "--bundle", str(bundle), "--output", str(facets))
        assert aggregated.returncode == 2
        assert json.loads(aggregated.stdout) == {"decision": "error", "reason": "invalid-input"}
        assert not facets.exists()
        claims = root / "claims.json"
        claims.write_text('{"claims": []}', encoding="utf-8")
        verified = root / "verified.json"
        audited = run_script("audit.py", "--bundle", str(bundle), "--claims", str(claims), "--output", str(verified))
        assert audited.returncode == 2
        assert json.loads(audited.stdout) == {"decision": "error", "reason": "invalid-input"}
        assert not verified.exists()


def main() -> int:
    """Execute all required synthetic fixtures."""
    assert_zero_candidates()
    assert_bad_citation_dropped()
    assert_pii_gate()
    assert_jsonl_bundle_accepted()
    assert_manifest_only_jsonl()
    assert_coverage_isolation()
    assert_output_gates()
    assert_bad_source_dropped()
    assert_corrupt_git_refused()
    assert_json_index_citations()
    assert_sqlite_citations()
    assert_oversized_claims_rejected()
    assert_manifest_first_required()
    print("PASS: zero blind spots; bad citation/source dropped; PII and output gates; JSONL and coverage isolation; corrupt Git; JSON index; SQLite; oversized claims; manifest-first required")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
