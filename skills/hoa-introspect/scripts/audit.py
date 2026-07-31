#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
# ─── How to run ───
# python scripts/audit.py --bundle bundle.json --claims claims.json --output verified-claims.json
"""Drop L2 claims that lack two independently resolvable origins."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from urllib.parse import quote

from safety import output_is_safe


MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_LINE_BYTES = 1024 * 1024
MAX_CLAIMS_BYTES = 16 * 1024 * 1024


def arguments() -> argparse.Namespace:
    """Parse audit paths."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--claims", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def load_object(path: Path) -> dict[str, object]:
    """Load an object JSON document."""
    if path.stat().st_size > MAX_CLAIMS_BYTES:
        raise ValueError("claims exceeds maximum file size")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return loaded


def read_bundle(path: Path) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Load an object bundle or a manifest-first JSONL bundle from hoa-agent-retrieve."""
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
        raise ValueError(f"{path.name} needs a manifest row")
    first = rows[0]
    if isinstance(first.get("coverage_manifest"), dict):
        manifest = first["coverage_manifest"]
    elif first.get("kind") == "coverage_manifest":
        manifest = first
    else:
        raise ValueError("JSONL bundle must begin with a coverage-manifest row")
    return manifest, rows[1:]


def locator_resolves(locator: dict[str, object], root: Path) -> bool:
    """Confirm a locator's referenced file and one declared position exist."""
    try:
        name = locator.get("file")
        if not isinstance(name, str):
            return False
        source = (root / name).resolve()
        if not source.is_file() or source.stat().st_size > MAX_FILE_BYTES:
            return False
        shapes = (
            isinstance(locator.get("line"), int)
            + isinstance(locator.get("offset"), int)
            + isinstance(locator.get("index"), int)
            + (isinstance(locator.get("table"), str) and isinstance(locator.get("rowid"), int))
        )
        if shapes != 1:
            return False
        line = locator.get("line")
        if isinstance(line, int):
            if line < 1:
                return False
            with source.open(encoding="utf-8") as contents:
                for number, text in enumerate(contents, start=1):
                    if len(text.encode("utf-8")) > MAX_LINE_BYTES:
                        return False
                    if number == line:
                        return True
            return False
        offset = locator.get("offset")
        if isinstance(offset, int) and 0 <= offset < source.stat().st_size:
            with source.open("rb") as contents:
                contents.seek(offset)
                return bool(contents.read(1))
        index = locator.get("index")
        if isinstance(index, int):
            with source.open(encoding="utf-8") as contents:
                values = json.load(contents)
            return isinstance(values, list) and 1 <= index <= len(values)
        table = locator.get("table")
        rowid = locator.get("rowid")
        if isinstance(table, str) and isinstance(rowid, int):
            quoted_table = table.replace('"', '""')
            uri = f"file:{quote(str(source), safe='/')}?mode=ro"
            with sqlite3.connect(uri, uri=True) as database:
                return database.execute(
                    f'SELECT 1 FROM "{quoted_table}" WHERE rowid=? LIMIT 1', (rowid,)
                ).fetchone() is not None
    except (OSError, RuntimeError, UnicodeDecodeError, json.JSONDecodeError, sqlite3.Error):
        return False
    return False


def available_agents(manifest: dict[str, object]) -> set[str]:
    """Return the only manifest agents permitted to contribute to L2."""
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


def locator_key(locator: dict[str, object]) -> str:
    """Make semantically identical JSON locators comparable in the compact index."""
    return json.dumps(locator, sort_keys=True, separators=(",", ":"))


def record_index(manifest: dict[str, object], records: list[dict[str, object]]) -> set[tuple[str, str]]:
    """Index only resolvable citation identities from available sources."""
    permitted_agents = available_agents(manifest)
    return {
        (origin, locator_key(locator))
        for record in records
        if record.get("agent") in permitted_agents
        and isinstance((origin := record.get("origin_fingerprint")), str)
        and isinstance((locator := record.get("locator")), dict)
    }


def cited_origins(index: set[tuple[str, str]], claim: dict[str, object], root: Path) -> set[str]:
    """Return independent origins whose citation matches and resolves."""
    citations = claim.get("citations", [])
    if not isinstance(citations, list):
        return set()
    valid: set[str] = set()
    for citation in citations:
        if not isinstance(citation, dict) or not isinstance(citation.get("locator"), dict):
            continue
        origin = citation.get("origin_fingerprint")
        locator = citation["locator"]
        if not isinstance(origin, str) or not locator_resolves(locator, root):
            continue
        if (origin, locator_key(locator)) in index:
            valid.add(origin)
    return valid


def verify(index: set[tuple[str, str]], claims: dict[str, object], root: Path) -> dict[str, object]:
    """Separate qualifying claims from mechanically invalid claims."""
    candidates = claims.get("claims", [])
    if not isinstance(candidates, list):
        raise ValueError("claims must be a list")
    retained: list[dict[str, object]] = []
    dropped: list[dict[str, str]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        origins = cited_origins(index, candidate, root)
        identifier = candidate.get("id", "unnamed")
        if len(origins) >= 2:
            retained.append(candidate)
        else:
            dropped.append({"id": str(identifier), "reason": "fewer than two resolvable independent origins"})
    return {"claims": retained, "dropped_claims": dropped}


def main() -> int:
    """Validate citations and write a safe claims sidecar."""
    args = arguments()
    safe, reason = output_is_safe(args.output)
    if not safe:
        print(json.dumps({"decision": "refuse", "reason": reason}))
        return 1
    try:
        manifest, records = read_bundle(args.bundle)
        result = verify(record_index(manifest, records), load_object(args.claims), args.bundle.parent)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        print(json.dumps({"decision": "error", "reason": "invalid-input"}))
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
