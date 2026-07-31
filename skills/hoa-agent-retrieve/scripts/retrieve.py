#!/usr/bin/env python3
"""Create a read-only, manifest-first Retrieval Bundle from configured stores."""

# /// script
# requires-python = ">=3.11"
# ///
# ─── How to run ───
# python retrieve.py --config /path/to/config.json --query "auth"

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tomllib
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Iterable

from retrieve_sources import ParsedRecord, SourceResult, configured_paths, default_paths, inspect_agent
from safety import output_is_safe

CORE_AGENTS: Final = ("claude-code", "codex", "pi", "kimi-code", "hermes", "opencode")


def parse_args() -> argparse.Namespace:
    """Parse only retrieval scope and output options supplied by the agent."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--source", action="append", default=[], metavar="AGENT=PATH")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--query")
    parser.add_argument("--project")
    parser.add_argument("--from", dest="start")
    parser.add_argument("--to", dest="end")
    return parser.parse_args()


def load_config(path: Path | None) -> dict[str, str | list[str]]:
    """Load a supplied JSON or TOML source map."""
    if path is None:
        return {}
    raw = path.read_bytes()
    value = tomllib.loads(raw.decode("utf-8")) if path.suffix.lower() == ".toml" else json.loads(raw)
    sources = value.get("sources", {})
    if not isinstance(sources, dict):
        raise ValueError("config sources must be an object/table")
    return {agent: location for agent, location in sources.items() if isinstance(agent, str) and isinstance(location, (str, list))}


def fingerprint(record: ParsedRecord) -> str:
    """Create an agent-agnostic content-origin identity for synced-copy deduplication."""
    # Identical content in one context collapses to one origin: this prevents
    # synced copies masquerading as independent L2 evidence, while the rare
    # identical no-timestamp texts conservatively under-count L1 independence.
    text = "\x1f".join((record.text, record.role_or_type, record.timestamp or "", record.project or ""))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_sessions(records: Iterable[ParsedRecord]) -> tuple[dict[str, str], dict[str, int]]:
    """Resolve session roots deterministically, including conflicting/cyclic parent links."""
    session_ids = {record.session_id for record in records if record.session_id}
    choices: dict[str, set[str]] = defaultdict(set)
    for record in records:
        if record.session_id and record.parent_id:
            choices[record.session_id].add(record.parent_id)
    roots: dict[str, str] = {}
    for session in session_ids:
        seen: list[str] = []
        current = session
        while current in choices:
            if current in seen:
                roots[session] = min(seen[seen.index(current):])
                break
            seen.append(current)
            current = min(choices[current])
        else:
            roots[session] = current
    counts: dict[str, int] = defaultdict(int)
    for root in roots.values():
        counts[root] += 1
    return roots, counts


def parse_timestamp(value: str | None) -> datetime | None:
    """Parse a source or CLI time as an aware UTC instant."""
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def selected(record: ParsedRecord, args: argparse.Namespace, start: datetime | None, end: datetime | None) -> bool:
    """Apply scope filters after parsing and origin deduplication."""
    query_haystack = "\n".join((record.text, record.project or "", record.project_full or "", record.source)).lower()
    if args.query and args.query.lower() not in query_haystack:
        return False
    project_haystack = "\n".join((record.project or "", record.project_full or "")).lower()
    if args.project and args.project.lower() not in project_haystack:
        return False
    if start or end:
        timestamp = parse_timestamp(record.timestamp)
        if timestamp is None:
            return False
        if start and timestamp < start:
            return False
        if end and timestamp > end:
            return False
    return True


def output_path(explicit: Path | None) -> Path:
    """Choose a state-directory default; all targets are safety-validated by main."""
    if explicit is not None:
        return explicit.expanduser().resolve()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    state = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "state")) / "hoa" / "retrieval"
    return (state / stamp / "retrieval-bundle.jsonl").resolve()


def manifest(results: list[SourceResult], records: list[ParsedRecord], input_count: int, unique_count: int, roots: dict[str, str], branches: dict[str, int], args: argparse.Namespace) -> dict[str, object]:
    """Build the canonical manifest before the bundle is written."""
    counts = {agent: sum(record.agent == agent for record in records) for agent in (result.agent for result in results)}
    values = tuple(branches.values())
    remapped = sum(
        record.session_id is not None and roots.get(record.session_id, record.session_id) != record.session_id
        for record in records
    )
    return {"kind": "coverage_manifest", "generated_at": datetime.now(UTC).isoformat(), "time_window": {"from": args.start, "to": args.end}, "sources": [{"agent": item.agent, "status": item.status, "path_probed": [str(path) for path in item.paths], "record_count": counts[item.agent], "note": item.note} for item in results], "deduplication": {"input_records": input_count, "origin_records_removed": input_count - unique_count, "branch_records_canonicalized": remapped, "sessions_with_branches": sum(value > 1 for value in values), "max_branches_per_session": max(values, default=0), "avg_branches_per_session": round(sum(values) / len(values), 2) if values else 0.0}}


def bundle_row(record: ParsedRecord, roots: dict[str, str]) -> dict[str, object]:
    """Serialize a normalized record and its explicit structured usage evidence."""
    row: dict[str, object] = {"kind": "record", "source": record.source, "agent": record.agent, "project": record.project, "project_full": record.project_full, "session_id": roots.get(record.session_id or "", record.session_id), "timestamp": record.timestamp, "dur_min": None, "role_or_type": record.role_or_type, "text_or_summary": record.text, "locator": record.locator, "origin_fingerprint": fingerprint(record), "status_or_confidence": record.confidence}
    for name, values in (("skills", record.skills), ("mcp", record.mcp), ("agent_types", record.agent_types), ("friction_events", record.friction_events), ("tools", record.tools)):
        if values:
            row[name] = list(values)
    return row


def main() -> int:
    """Discover, normalize, deduplicate, filter, and safely write one bundle."""
    args = parse_args()
    start = parse_timestamp(args.start)
    end = parse_timestamp(args.end)
    if (args.start and start is None) or (args.end and end is None) or (start and end and start > end):
        print("retrieve: invalid or inverted time window", file=sys.stderr)
        return 2
    try:
        configured = load_config(args.config)
        for entry in args.source:
            agent, separator, location = entry.partition("=")
            if not separator or not agent or not location:
                raise ValueError("--source requires AGENT=PATH")
            configured[agent] = location
        agents = tuple(configured) if configured else CORE_AGENTS
        results = [inspect_agent(agent, configured_paths(configured[agent]) if agent in configured else default_paths(agent)) for agent in agents]
        parsed = [record for result in results for record in result.records]
        roots, branches = canonical_sessions(parsed)
        unique = {fingerprint(record): record for record in reversed(parsed)}
        unique_records = list(reversed(tuple(unique.values())))
        records = [record for record in unique_records if selected(record, args, start, end)]
        target = output_path(args.output)
    except (OSError, ValueError, tomllib.TOMLDecodeError, json.JSONDecodeError) as error:
        print(f"retrieve: {error}", file=sys.stderr)
        return 2
    safe, reason = output_is_safe(target)
    if not safe:
        print(json.dumps({"decision": "refuse", "reason": reason, "target_kind": "bundle"}))
        return 1
    bundle_manifest = manifest(results, records, len(parsed), len(unique_records), roots, branches, args)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(bundle_manifest, ensure_ascii=False) + "\n")
        for record in records:
            handle.write(json.dumps(bundle_row(record, roots), ensure_ascii=False) + "\n")
    print(json.dumps({"bundle": str(target), "available_sources": sum(item.status == "available" for item in results), "records": len(records)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
