"""Shared source selection and numbered, tolerant transcript decoding."""

import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .redact import RegexPatterns, _dir_allowed, _modified_since


@dataclass(frozen=True, slots=True)
class Scope:
    allow: re.Pattern[str] | None = None
    deny: re.Pattern[str] | None = None
    since: datetime | None = None
    redact: RegexPatterns = ()
    extra_high_signal: RegexPatterns = ()
    min_lines: int = 2

    def allows(self, *names: str) -> bool:
        return _dir_allowed(names, self.allow, self.deny)

    def modified_since(self, path: Path) -> bool:
        return _modified_since(path, self.since)


type EmitSession = Callable[[str, str, str, str, dict, list[dict]], None]
type ParseSteps = Callable[[Path, RegexPatterns | None, RegexPatterns], tuple[dict, list[dict]]]


def json_object(raw: object) -> dict:
    if isinstance(raw, (str, bytes)):
        try:
            raw = json.loads(raw)
        except ValueError:
            return {}
    return raw if isinstance(raw, dict) else {}


def numbered_records(path: Path) -> Iterator[tuple[int, dict]]:
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line, raw in enumerate(stream, start=1):
            yield line, json_object(raw)


def project_dirs(root: Path, scope: Scope) -> tuple[dict, list[Path]]:
    if not root.exists():
        return {"root": str(root), "status": "not-found"}, []
    included = []
    skipped = 0
    for path in sorted(p for p in root.iterdir() if p.is_dir()):
        if scope.allows(path.name):
            included.append(path)
        else:
            skipped += 1
    return {
        "root": str(root), "status": "available", "included_dirs": len(included), "skipped_dirs": skipped,
    }, included


def project_logs(project: Path, scope: Scope, parse: ParseSteps) -> Iterator[tuple[Path, dict, list[dict]]]:
    for path in sorted(project.glob("*.jsonl")):
        if path.is_file() and scope.modified_since(path):
            meta, steps = parse(path, scope.redact, scope.extra_high_signal)
            if meta["raw_lines"] > scope.min_lines and steps:
                yield path, meta, steps
