#!/usr/bin/env python3
"""Run synthetic, read-only Retrieval Bundle regression evaluations."""

# /// script
# requires-python = ">=3.11"
# ///
# ─── How to run ───
# python run_evals.py

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import retrieve_sources  # noqa: E402
import retrieve  # noqa: E402
import safety  # noqa: E402


def run_retriever(config: Path, output: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    """Run the CLI only against a synthetic config and supplied output."""
    return subprocess.run([sys.executable, str(SCRIPTS / "retrieve.py"), "--config", str(config), "--output", str(output), *extra], capture_output=True, text=True, check=False)


def read_bundle(path: Path) -> list[dict[str, object]]:
    """Load the small synthetic output fixture for JSON-field assertions."""
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class DeniedPath:
    """Synthetic regular file that fails only at the real parser open boundary."""

    name = "denied.jsonl"
    suffix = ".jsonl"

    def is_symlink(self) -> bool:
        return False

    def is_file(self) -> bool:
        return True

    def is_dir(self) -> bool:
        return False

    def resolve(self) -> DeniedPath:
        return self

    def stat(self) -> os.stat_result:
        return os.stat_result((0,) * 10)

    def open(self, *args: object, **kwargs: object) -> object:
        raise PermissionError("synthetic denial")


def test_manifest_statuses(fixture_dir: Path, temp: Path) -> None:
    """Given present/absent/bad stores, the manifest reports each exact state."""
    config = temp / "sources.json"
    output = temp / "bundle.jsonl"
    config.write_text(json.dumps({"sources": {"claude-code": str(fixture_dir / "claude.jsonl"), "codex": str(temp / "deliberately-absent"), "kimi-code": str(fixture_dir / "kimi-unparseable.json")}}), encoding="utf-8")
    result = run_retriever(config, output)
    assert result.returncode == 0, result.stderr
    manifest = read_bundle(output)[0]
    statuses = {item["agent"]: item["status"] for item in manifest["sources"]}
    expected = {"claude-code": "available", "codex": "not-found", "kimi-code": "unsupported"}
    assert statuses == expected, (statuses, expected)
    assert manifest["sources"][0]["record_count"] == 2, manifest
    assert manifest["deduplication"]["sessions_with_branches"] == 1, manifest
    assert manifest["deduplication"]["branch_records_canonicalized"] == 1, manifest


def test_usage_fields_and_cross_agent_dedup(temp: Path) -> None:
    """Given synced structured records, one row retains explicitly declared facets."""
    first = temp / "first.jsonl"
    second = temp / "second.jsonl"
    record = {"session_id": "fake-root", "timestamp": "2026-07-01T10:00:00Z", "role": "user", "project": "fake-project", "text": "Synthetic shared content.", "skills": ["fake-skill"], "mcp_tools": ["fake-mcp"], "uses_agent": ["fake-agent"], "content": [{"type": "tool_use", "name": "fake-tool"}]}
    first.write_text(json.dumps(record) + "\n", encoding="utf-8")
    second.write_text(json.dumps(record) + "\n", encoding="utf-8")
    config = temp / "sources.json"
    output = temp / "bundle.jsonl"
    config.write_text(json.dumps({"sources": {"claude-code": str(first), "codex": str(second)}}), encoding="utf-8")
    result = run_retriever(config, output)
    assert result.returncode == 0, result.stderr
    rows = read_bundle(output)
    assert len(rows) == 2, rows
    row = rows[1]
    assert row["skills"] == ["fake-skill"], row
    assert row["mcp"] == ["fake-mcp"], row
    assert row["agent_types"] == ["fake-agent"], row
    assert row["tools"] == ["fake-tool"], row
    assert rows[0]["deduplication"]["origin_records_removed"] == 1, rows[0]


def test_inaccessible_enumeration_does_not_abort(temp: Path) -> None:
    """Given enumeration and file-open denials, statuses remain honest."""
    accessible = temp / "available.jsonl"
    accessible.write_text('{"text":"Synthetic accessible content."}\n', encoding="utf-8")
    inaccessible = retrieve_sources.inspect_agent("claude-code", (DeniedPath(),))
    available = retrieve_sources.inspect_agent("codex", (accessible,))
    assert inaccessible.status == "inaccessible", inaccessible
    assert available.status == "available", available
    assert len(available.records) == 1, available
    manifest = retrieve.manifest([inaccessible, available], list(available.records), 1, 1, {}, {}, argparse.Namespace(start=None, end=None))
    assert {item["agent"]: item["status"] for item in manifest["sources"]} == {"claude-code": "inaccessible", "codex": "available"}, manifest


def test_cross_worktree_refusal(temp: Path) -> None:
    """Given an output inside another Git worktree, the CLI refuses before writing."""
    source = temp / "source.jsonl"
    source.write_text('{"text":"Synthetic content."}\n', encoding="utf-8")
    config = temp / "sources.json"
    config.write_text(json.dumps({"sources": {"claude-code": str(source)}}), encoding="utf-8")
    worktree = temp / "other-worktree"
    subprocess.run(["git", "init", str(worktree)], capture_output=True, text=True, check=True)
    output = worktree / "bundle.jsonl"
    result = run_retriever(config, output)
    assert result.returncode == 1, result.stderr
    assert json.loads(result.stdout)["decision"] == "refuse", result.stdout
    assert not output.exists(), output


def test_sqlite_and_limit(temp: Path) -> None:
    """Given recognized SQLite and a capped JSONL, both yield bounded observable results."""
    database = temp / "fake-opencode.sqlite"
    connection = sqlite3.connect(database)
    try:
        connection.execute("CREATE TABLE messages (content TEXT, role TEXT, timestamp TEXT, project TEXT)")
        connection.execute("INSERT INTO messages VALUES (?, ?, ?, ?)", ("Synthetic SQLite content.", "assistant", "2026-07-01T10:00:00Z", "fake-project"))
        connection.commit()
    finally:
        connection.close()
    parsed = retrieve_sources.inspect_agent("opencode", (database,))
    assert parsed.status == "available", parsed
    assert len(parsed.records) >= 1, parsed
    capped = temp / "capped.jsonl"
    capped.write_text("".join('{"text":"Synthetic line."}\n' for _ in range(3)), encoding="utf-8")
    with patch.object(retrieve_sources, "MAX_RECORDS_PER_SOURCE", 2):
        limited = retrieve_sources.inspect_agent("claude-code", (capped,))
    assert len(limited.records) == 2, limited
    assert "limit-exceeded" in limited.note, limited


def test_locator_shapes(temp: Path) -> None:
    """Given each structured format, emitted records have one exact locator form."""
    array = temp / "array.json"
    array.write_text(json.dumps([{"text": "Synthetic array content."}]), encoding="utf-8")
    single = temp / "single.json"
    single.write_text(json.dumps({"text": "Synthetic object content."}), encoding="utf-8")
    database = temp / "locator.sqlite"
    connection = sqlite3.connect(database)
    try:
        connection.execute("CREATE TABLE messages (content TEXT)")
        connection.execute("INSERT INTO messages VALUES (?)", ("Synthetic SQLite locator content.",))
        connection.commit()
    finally:
        connection.close()
    array_record = retrieve_sources.parse_json("opencode", array).records[0]
    single_record = retrieve_sources.parse_json("opencode", single).records[0]
    sqlite_record = retrieve_sources.parse_sqlite("opencode", database).records[0]
    assert array_record.locator == {"file": str(array.resolve()), "index": 1}, array_record
    assert single_record.locator == {"file": str(single.resolve()), "offset": 0}, single_record
    assert sqlite_record.locator == {"file": str(database.resolve()), "table": "messages", "rowid": 1}, sqlite_record


def test_partial_jsonl_and_source_budgets(temp: Path) -> None:
    """Given corrupt lines and a source cap, good records and coverage gaps survive."""
    partial = temp / "partial.jsonl"
    partial.write_bytes(b'{"text":"Synthetic first."}\nnot-json\n{"text":"Synthetic second."}\n')
    parsed = retrieve_sources.inspect_agent("claude-code", (partial,))
    assert parsed.status == "available", parsed
    assert len(parsed.records) == 2, parsed
    assert "skipped-lines: 1" in parsed.note, parsed
    budget = temp / "budget"
    budget.mkdir()
    first = budget / "first.jsonl"
    second = budget / "second.jsonl"
    first.write_text('{"text":"Synthetic budget content."}\n', encoding="utf-8")
    second.write_text('{"text":"Synthetic budget content."}\n', encoding="utf-8")
    with patch.object(retrieve_sources, "MAX_SOURCE_BYTES", first.stat().st_size):
        limited = retrieve_sources.inspect_agent("claude-code", (budget,))
    assert len(limited.records) == 1, limited
    assert "limit-exceeded: source-bytes" in limited.note, limited


def test_symlinks_and_safety_fail_closed(temp: Path) -> None:
    """Given symlinks or masked Git discovery, retrieval never assumes safety."""
    source = temp / "source.jsonl"
    source.write_text('{"text":"Synthetic linked content."}\n', encoding="utf-8")
    linked = temp / "linked.jsonl"
    linked.symlink_to(source)
    parsed = retrieve_sources.inspect_agent("claude-code", (linked,))
    assert parsed.status == "not-found", parsed
    corrupt = temp / "corrupt-git"
    corrupt.mkdir()
    (corrupt / ".git").write_text("", encoding="utf-8")
    safe, reason = safety.output_is_safe(corrupt / "bundle.jsonl")
    assert not safe and reason != "outside-worktree", (safe, reason)
    repository = temp / "tracked-repo"
    subprocess.run(["git", "init", str(repository)], capture_output=True, text=True, check=True)
    target = repository / "bundle.jsonl"
    with patch.dict(os.environ, {"GIT_CEILING_DIRECTORIES": str(temp)}, clear=False):
        safe, reason = safety.output_is_safe(target)
    assert not safe and reason != "outside-worktree", (safe, reason)


def test_project_and_time_filters(temp: Path) -> None:
    """Given source-only project text and bad timestamps, scope filters exclude them."""
    source = temp / "fake-project-source.jsonl"
    source.write_text("\n".join((json.dumps({"text": "Synthetic source-only project token.", "timestamp": "2026-07-01T00:00:00Z"}), json.dumps({"project": "fake-project", "text": "Synthetic bad-time record.", "timestamp": "not-a-time"}))) + "\n", encoding="utf-8")
    config = temp / "sources.json"
    output = temp / "bundle.jsonl"
    config.write_text(json.dumps({"sources": {"claude-code": str(source)}}), encoding="utf-8")
    source_only = run_retriever(config, output, "--project", "project-source")
    assert source_only.returncode == 0, source_only.stderr
    assert len(read_bundle(output)) == 1, read_bundle(output)
    timed_output = temp / "timed-bundle.jsonl"
    malformed_time = run_retriever(config, timed_output, "--from", "2026-07-01T00:00:00Z")
    assert malformed_time.returncode == 0, malformed_time.stderr
    assert len(read_bundle(timed_output)) == 2, read_bundle(timed_output)
    inverted = run_retriever(config, temp / "inverted-bundle.jsonl", "--from", "2026-07-02T00:00:00Z", "--to", "2026-07-01T00:00:00Z")
    assert inverted.returncode == 2, inverted.stderr


def main() -> int:
    """Execute isolated fake-store scenarios and print their expected-vs-actual results."""
    fixture_dir = Path(__file__).resolve().parent / "fixtures"
    cases = (("manifest-statuses", lambda temp: test_manifest_statuses(fixture_dir, temp)), ("usage-fields-and-cross-agent-dedup", test_usage_fields_and_cross_agent_dedup), ("inaccessible-enumeration", test_inaccessible_enumeration_does_not_abort), ("cross-worktree-refusal", test_cross_worktree_refusal), ("sqlite-and-limit", test_sqlite_and_limit), ("locator-shapes", test_locator_shapes), ("partial-jsonl-and-source-budgets", test_partial_jsonl_and_source_budgets), ("symlinks-and-safety-fail-closed", test_symlinks_and_safety_fail_closed), ("project-and-time-filters", test_project_and_time_filters))
    outcomes: list[dict[str, str]] = []
    for name, case in cases:
        with tempfile.TemporaryDirectory(prefix="hoa-agent-retrieve-eval-") as directory:
            case(Path(directory))
        outcomes.append({"fixture": name, "expected": "pass", "actual": "pass"})
    for outcome in outcomes:
        print(json.dumps(outcome, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
