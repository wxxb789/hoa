#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
# ─── How to run ───
# python scripts/aggregate.py --bundle path/to/bundle.json --output path/to/facets.json
"""Deterministically aggregate explicit usage fields from a Retrieval Bundle."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Final, TypedDict

from safety import output_is_safe


class Bundle(TypedDict, total=False):
    coverage_manifest: dict[str, object]
    records: list[dict[str, object]]


class Facets(TypedDict):
    aggregated_data: dict[str, object]
    facets_summary: dict[str, object]


ALIASES: Final[dict[str, tuple[str, ...]]] = {
    "skills": ("skills", "skill_calls"),
    "mcp": ("mcp", "mcp_tools"),
    "agents": ("agent_types", "uses_agent"),
    "friction": ("friction_events",),
}
MAX_FILE_BYTES: Final = 64 * 1024 * 1024
MAX_LINE_BYTES: Final = 1024 * 1024


def parse_args() -> argparse.Namespace:
    """Parse command-line input."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def read_bundle(path: Path) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Read an object bundle or manifest-first JSONL bundle.

    A single JSON object (compact or pretty-printed) is used as-is. Otherwise the
    file is parsed as manifest-first JSONL: the first row is the coverage manifest
    (either ``{"kind": "coverage_manifest", ...}`` or ``{"coverage_manifest": ...}``)
    and each remaining row is one record. The object form is tried first because a
    manifest-first JSONL bundle also begins with ``{``.
    """
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("bundle exceeds maximum file size")
    try:
        with path.open(encoding="utf-8") as source:
            loaded = json.load(source)
    except json.JSONDecodeError:
        loaded = None
    if isinstance(loaded, dict) and ("records" in loaded or "coverage_manifest" in loaded):
        manifest = loaded.get("coverage_manifest", {})
        records = loaded.get("records", [])
        if not isinstance(manifest, dict) or not isinstance(records, list):
            raise ValueError("object bundle needs an object manifest and records list")
        return manifest, [record for record in records if isinstance(record, dict)]

    rows: list[dict[str, object]] = []
    with path.open(encoding="utf-8") as source:
        for line in source:
            if len(line.encode("utf-8")) > MAX_LINE_BYTES:
                raise ValueError("bundle line exceeds maximum size")
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("JSONL bundle rows must be objects")
            rows.append(row)
    if not rows or not isinstance(rows[0], dict):
        raise ValueError("JSONL bundle needs a manifest row")
    first = rows[0]
    if isinstance(first.get("coverage_manifest"), dict):
        manifest = first["coverage_manifest"]
    elif first.get("kind") == "coverage_manifest":
        manifest = first
    else:
        raise ValueError("JSONL bundle must begin with a coverage-manifest row")
    return manifest, rows[1:]


def values(record: dict[str, object], facet: str) -> list[str] | None:
    """Return the first explicit list-like value for a facet, if measured."""
    for field in ALIASES[facet]:
        raw = record.get(field)
        if isinstance(raw, list):
            return [item for item in raw if isinstance(item, str)]
        if isinstance(raw, bool) and facet == "agents":
            return ["unspecified"] if raw else []
    return None


def count_facet(records: list[dict[str, object]], facet: str) -> tuple[Counter[str], int]:
    """Count explicit values and measured-record denominator for one facet."""
    counts: Counter[str] = Counter()
    measured = 0
    for record in records:
        found = values(record, facet)
        if found is not None:
            measured += 1
            counts.update(found)
    return counts, measured


def sorted_counts(counts: Counter[str]) -> dict[str, int]:
    """Return stable, descending-frequency count mappings."""
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def available_agents(manifest: dict[str, object]) -> set[str]:
    """Return the only manifest agents permitted to contribute to L1."""
    sources = manifest.get("sources", [])
    if not isinstance(sources, list):
        return set()
    return {
        source["agent"]
        for source in sources
        if isinstance(source, dict)
        and source.get("status") == "available"
        and isinstance(source.get("agent"), str)
    }


def safe_coverage(manifest: dict[str, object]) -> dict[str, object]:
    """Preserve coverage bounds without copying private probe paths."""
    coverage = {key: manifest[key] for key in ("generated_at", "time_window") if key in manifest}
    sources = manifest.get("sources", [])
    coverage["sources"] = [
        {key: source[key] for key in ("agent", "status", "record_count", "note") if key in source}
        for source in sources
        if isinstance(source, dict)
    ] if isinstance(sources, list) else []
    return coverage


def build_facets(manifest: dict[str, object], records: list[dict[str, object]]) -> Facets:
    """Create stable L1 facets without inferring any event from prose."""
    permitted_agents = available_agents(manifest)
    typed_records = [record for record in records if record.get("agent") in permitted_agents]
    skills, skill_measured = count_facet(typed_records, "skills")
    mcp, mcp_measured = count_facet(typed_records, "mcp")
    agents, agent_measured = count_facet(typed_records, "agents")
    friction, friction_measured = count_facet(typed_records, "friction")
    agent_records = sum(bool(values(record, "agents")) for record in typed_records)
    namespaces = Counter(
        skill.split(":", maxsplit=1)[0] for skill, count in skills.items() for _ in range(count) if ":" in skill
    )
    percent = round(100 * agent_records / agent_measured, 2) if agent_measured else None
    return {
        "aggregated_data": {
            "record_count": len(typed_records),
            "available_agents": sorted(permitted_agents),
            "coverage": safe_coverage(manifest),
            "measured_records": {
                "skills": skill_measured,
                "mcp": mcp_measured,
                "agent_orchestration": agent_measured,
                "friction": friction_measured,
            },
        },
        "facets_summary": {
            "skill_call_frequency": sorted_counts(skills),
            "plugin_namespace_distribution": sorted_counts(namespaces),
            "mcp_usage": {"counts": sorted_counts(mcp), "measured_records": mcp_measured},
            "agent_orchestration": {
                "records_with_orchestration": agent_records,
                "measured_records": agent_measured,
                "percent": percent,
            },
            "friction": {"counts": sorted_counts(friction), "measured_records": friction_measured},
        },
    }


def main() -> int:
    """Write facets JSON."""
    args = parse_args()
    safe, reason = output_is_safe(args.output)
    if not safe:
        print(json.dumps({"decision": "refuse", "reason": reason}))
        return 1
    try:
        manifest, records = read_bundle(args.bundle)
        facets = build_facets(manifest, records)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        print(json.dumps({"decision": "error", "reason": "invalid-input"}))
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(facets, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
