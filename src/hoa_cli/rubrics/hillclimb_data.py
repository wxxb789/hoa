"""Dataset validation and scratch writes for rubric hillclimbing."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from hoa_cli.io import read_json, read_jsonl


def _records(rows: object, source: Path, *, labeled: bool) -> list[dict]:
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{source}: expected at least one record")
    ids = set()
    expected_type = None
    for number, row in enumerate(rows, 1):
        if (not isinstance(row, dict) or not isinstance(row.get("id"), str)
                or not row["id"] or not isinstance(row.get("text"), str)):
            raise ValueError(f"{source}: record {number} needs a non-empty string id and string text")
        if row["id"] in ids:
            raise ValueError(f"{source}: record {number} has a duplicate id")
        ids.add(row["id"])
        if labeled:
            expected = row.get("expected")
            if type(expected) is not bool and (not isinstance(expected, str) or not expected):
                raise ValueError(f"{source}: record {number} needs a boolean or non-empty string expected label")
            if expected_type is not None and type(expected) is not expected_type:
                raise ValueError(f"{source}: boolean and string expected labels cannot be mixed")
            expected_type = type(expected)
        elif "expected" in row:
            raise ValueError(f"{source}: record {number} is labeled; sample requires an unlabeled pool")
    return rows


def read_records(path: Path, *, labeled: bool) -> list[dict]:
    return _records(read_jsonl(path), path, labeled=labeled)


def read_anchors(rubric: Path, embedded: object, anchors: Path | None, check_anchors: bool) -> list[dict] | None:
    if anchors is not None:
        source = anchors
        rows = read_jsonl(source) if source.suffix.lower() == ".jsonl" else read_json(source)
        if isinstance(rows, dict):
            rows = rows.get("anchors")
    elif check_anchors:
        source, rows = rubric, embedded
    else:
        return None
    rows = _records(rows, source, labeled=True)
    if isinstance(rows[0]["expected"], bool) and {row["expected"] for row in rows} != {False, True}:
        raise ValueError(f"{source}: binary anchors must include both positive and negative examples")
    return rows


def output_paths(out_dir: Path | None, inputs: tuple[Path, ...], *outputs: Path) -> list[Path]:
    protected = [path.resolve() for path in inputs]
    root = out_dir.resolve() if out_dir is not None else None
    paths = []
    for value in outputs:
        path = value.resolve() if root is None else (root / value).resolve()
        if root is not None and (path == root or not path.is_relative_to(root)):
            raise ValueError(f"{value}: output must be inside --out-dir")
        if any(path == other or (path.exists() and other.exists() and path.samefile(other)) for other in protected):
            raise ValueError(f"{value}: output aliases an input or another output")
        paths.append(path)
        protected.append(path)
    return paths


def record_step(
    ledger: Path, best_out: Path, candidate_bytes: bytes, baseline: dict, candidate: dict, *, accepted: bool, note: str,
) -> dict:
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a+", encoding="utf-8", newline="\n") as dest:
        dest.seek(0)
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "iter": sum(bool(line.strip()) for line in dest) + 1,
            "sha256": hashlib.sha256(candidate_bytes).hexdigest(),
            "baseline": baseline,
            "candidate": candidate,
            "accepted": accepted,
            "status": "accepted" if accepted else "reverted",
            "note": note,
        }
        line = json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n"
        if accepted:
            best_out.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(dir=best_out.parent, delete_on_close=False) as staged:
                staged.write(candidate_bytes)
                staged.close()
                Path(staged.name).replace(best_out)
        dest.write(line)
    return record
