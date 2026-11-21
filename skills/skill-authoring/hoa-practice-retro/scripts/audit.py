#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
# ─── How to run ───
# uv run scripts/audit.py --bundle bundle.json --run RUN
"""Mechanical evidence floor: refute findings without two independent, resolvable origins.

Reads every RUN/find-*.json. A history citation is `bundle:<origin_fingerprint>#<file>?line=N`
(or `offset=`, `index=`, `table=T&rowid=N`). Any unresolvable bundle citation refutes its finding;
so does a finding with fewer than two distinct origins (resolved bundle origins plus distinct
non-bundle evidence entries). Output is a verify file in the panel's Verdict format holding only
refutations; the adversarial verifier still rules on every finding.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from urllib.parse import parse_qsl, quote

from safety import output_is_safe


MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_LINE_BYTES = 1024 * 1024
MAX_RUN_FILE_BYTES = 16 * 1024 * 1024


def arguments() -> argparse.Namespace:
    """Parse audit paths."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--output", type=Path, help="default: RUN/verify-citations.json")
    return parser.parse_args()


def load_findings(run: Path) -> list[dict[str, object]]:
    """Every finding object from the run's find files."""
    found: list[dict[str, object]] = []
    for path in sorted(run.glob("find-*.json")):
        if path.stat().st_size > MAX_RUN_FILE_BYTES:
            raise ValueError(f"{path.name} exceeds maximum file size")
        rows = json.loads(path.read_text(encoding="utf-8")).get("findings", [])
        if not isinstance(rows, list):
            raise ValueError(f"{path.name}: findings must be a list")
        found += [row for row in rows if isinstance(row, dict)]
    return found


def parse_citation(evidence: str) -> tuple[str, dict[str, object]] | None:
    """Split `bundle:<origin>#<file>?key=value` into (origin, locator); None when malformed."""
    origin, sep, rest = evidence.removeprefix("bundle:").partition("#")
    name, _, query = rest.partition("?")
    if not (origin and sep and name and query):
        return None
    locator: dict[str, object] = {"file": name}
    for key, value in parse_qsl(query):
        locator[key] = int(value) if key != "table" and value.isdigit() else value
    return origin, locator


def read_bundle(path: Path) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Load an object bundle or a manifest-first JSONL bundle."""
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


def refutation(index: set[tuple[str, str]], finding: dict[str, object], root: Path) -> str | None:
    """Why the finding fails the evidence floor, or None when it passes."""
    evidence = finding.get("evidence", [])
    if not isinstance(evidence, list):
        return "evidence is not a list"
    origins: set[str] = set()
    for item in evidence:
        if not isinstance(item, str):
            continue
        if not item.startswith("bundle:"):
            origins.add(item)
            continue
        citation = parse_citation(item)
        if citation is None or not locator_resolves(citation[1], root) \
                or (citation[0], locator_key(citation[1])) not in index:
            return f"unresolvable bundle citation {item!r}"
        origins.add(citation[0])
    if len(origins) < 2:
        return "fewer than two independent origins"
    return None


def verify(index: set[tuple[str, str]], findings: list[dict[str, object]], root: Path) -> dict[str, object]:
    """Refute every finding below the floor; findings that pass get no verdict here."""
    verdicts = []
    for finding in findings:
        reason = refutation(index, finding, root)
        if reason is not None:
            verdicts.append({"id": str(finding.get("id", "unnamed")), "verdict": "refuted",
                             "rationale": f"evidence floor: {reason}",
                             "checked": ["scripts/audit.py resolved every bundle citation"]})
    return {"dim": "citations", "verdicts": verdicts}


def main() -> int:
    """Apply the evidence floor and write a safe verify file."""
    args = arguments()
    output = args.output or args.run / "verify-citations.json"
    safe, reason = output_is_safe(output)
    if not safe:
        print(json.dumps({"decision": "refuse", "reason": reason}))
        return 1
    try:
        manifest, records = read_bundle(args.bundle)
        result = verify(record_index(manifest, records), load_findings(args.run), args.bundle.parent)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        print(json.dumps({"decision": "error", "reason": "invalid-input"}))
        return 2
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
