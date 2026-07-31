"""Bounded, read-only parsers for Retrieval Bundle source stores."""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

MAX_FILE_BYTES: Final = 64 * 1024 * 1024
MAX_LINE_BYTES: Final = 1024 * 1024
MAX_FILES_PER_SOURCE: Final = 20_000
MAX_RECORDS_PER_SOURCE: Final = 200_000
MAX_SOURCE_BYTES: Final = 512 * 1024 * 1024
TEXT_KEYS: Final = ("text", "content", "message", "summary", "prompt", "value")
ROLE_KEYS: Final = ("role", "type", "kind")
SESSION_KEYS: Final = ("session_id", "sessionId", "id", "thread_id", "conversation_id")
PARENT_KEYS: Final = ("parent_id", "parentId", "parentSessionId")
USAGE_KEYS: Final = {"skills": "skills", "skill_calls": "skills", "mcp": "mcp", "mcp_tools": "mcp", "agent_types": "agent_types", "uses_agent": "agent_types", "friction_events": "friction_events", "tools": "tools"}
JSON_AGENTS: Final = frozenset({"kimi-code", "opencode", "gemini-cli", "cline", "continue"})
MD_AGENTS: Final = frozenset({"aider"})
SQLITE_SUFFIXES: Final = frozenset({".db", ".sqlite", ".sqlite3", ".vscdb"})


@dataclass(frozen=True, slots=True)
class ParsedRecord:
    agent: str
    source: str
    project: str | None
    project_full: str | None
    session_id: str | None
    parent_id: str | None
    timestamp: str | None
    role_or_type: str
    text: str
    file: Path
    locator: dict[str, object]
    confidence: str
    skills: tuple[str, ...]
    mcp: tuple[str, ...]
    agent_types: tuple[str, ...]
    friction_events: tuple[str, ...]
    tools: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SourceResult:
    agent: str
    status: str
    paths: tuple[Path, ...]
    note: str
    records: tuple[ParsedRecord, ...]


@dataclass(frozen=True, slots=True)
class ParseResult:
    records: tuple[ParsedRecord, ...]
    limit_exceeded: bool
    schema_recognized: bool = True
    skipped_lines: int = 0


def default_paths(agent: str) -> tuple[Path, ...]:
    """Return only documented store patterns for an adapter."""
    home = Path.home()
    match agent:
        case "claude-code":
            return (home / ".claude" / "projects", home / ".claude" / "history.jsonl")
        case "codex":
            return (Path(os.environ.get("CODEX_HOME", home / ".codex")) / "sessions",)
        case "pi":
            return (Path(os.environ.get("PI_CODING_AGENT_DIR", home / ".pi")) / "agent" / "sessions",)
        case "kimi-code":
            return (Path(os.environ.get("KIMI_CODE_HOME", home / ".kimi-code")), home / ".kimi" / "sessions")
        case "opencode":
            return (home / ".local" / "share" / "opencode",)
        case _:
            return ()


def configured_paths(value: str | list[str]) -> tuple[Path, ...]:
    """Expand explicit, user-authorized source roots."""
    locations = (value,) if isinstance(value, str) else tuple(item for item in value if isinstance(item, str))
    return tuple(Path(os.path.expandvars(item)).expanduser() for item in locations)


def candidate_files(paths: tuple[Path, ...], denied: list[Path] | None = None) -> Iterator[Path]:
    """Lazily yield regular, non-symlink files; record dirs we cannot enumerate.

    Uses os.scandir (not Path.rglob, which silently swallows PermissionError)
    so a denied subtree is reported through `denied` instead of shrinking
    coverage invisibly and letting the source be mislabelled "available".
    """
    gaps = denied if denied is not None else []
    stack = list(paths)
    while stack:
        current = stack.pop()
        try:
            if current.is_symlink():
                continue
            if current.is_file():
                yield current.resolve()
                continue
            if not current.is_dir():
                continue
        except OSError:
            gaps.append(current)
            continue
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            yield Path(entry.path).resolve()
                    except OSError:
                        gaps.append(Path(entry.path))
        except OSError:
            gaps.append(current)


def format_for(agent: str, path: Path) -> str | None:
    """Return the bounded reader that applies to a candidate."""
    suffix = path.suffix.lower()
    if suffix in SQLITE_SUFFIXES:
        return "sqlite"
    if suffix == ".jsonl":
        return "jsonl"
    if suffix == ".json":
        return "json"
    if suffix in {".md", ".markdown"} or agent in MD_AGENTS:
        return "markdown"
    if agent in JSON_AGENTS and suffix in {".txt", ""}:
        return "json"
    return None


def first_string(value: Mapping[str, object], keys: Sequence[str]) -> str | None:
    """Pick the first non-empty textual field from a known record shape."""
    for key in keys:
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            return item.strip()
    return None


def _strings(value: object) -> tuple[str, ...]:
    """Accept only explicit list-valued usage fields."""
    if not isinstance(value, list):
        return ()
    return tuple(item.strip() for item in value if isinstance(item, str) and item.strip())


def _tool_names(value: object) -> Iterator[str]:
    """Yield declared tool names from structured content blocks only."""
    if isinstance(value, Mapping):
        block_type = value.get("type")
        name = value.get("name")
        if block_type in {"tool_use", "tool_call"} and isinstance(name, str) and name.strip():
            yield name.strip()
        for nested in value.values():
            yield from _tool_names(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _tool_names(nested)


def _usage(value: Mapping[str, object]) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Extract opt-in structured usage fields without interpreting prose."""
    fields: dict[str, list[str]] = {name: [] for name in ("skills", "mcp", "agent_types", "friction_events", "tools")}
    for key, destination in USAGE_KEYS.items():
        fields[destination].extend(_strings(value.get(key)))
    fields["tools"].extend(_tool_names(value))
    return (
        tuple(dict.fromkeys(fields["skills"])),
        tuple(dict.fromkeys(fields["mcp"])),
        tuple(dict.fromkeys(fields["agent_types"])),
        tuple(dict.fromkeys(fields["friction_events"])),
        tuple(dict.fromkeys(fields["tools"])),
    )


def _file_locator(path: Path, **location: int | str) -> dict[str, object]:
    """Build one exact, absolute, locally resolvable record locator."""
    return {"file": str(path.resolve()), **location}


def mapping_record(agent: str, path: Path, locator: dict[str, object], value: Mapping[str, object]) -> ParsedRecord | None:
    """Normalize a documented text-like mapping without schema guessing."""
    text = first_string(value, TEXT_KEYS)
    nested = value.get("message")
    if text is None and isinstance(nested, Mapping):
        text = first_string(nested, TEXT_KEYS)
    if text is None:
        return None
    project = first_string(value, ("project", "cwd", "workspace"))
    skills, mcp, agent_types, friction_events, tools = _usage(value)
    return ParsedRecord(agent, path.stem, project, project, first_string(value, SESSION_KEYS), first_string(value, PARENT_KEYS), first_string(value, ("timestamp", "created_at", "createdAt", "time")), first_string(value, ROLE_KEYS) or "unknown", text, path, locator, "parsed", skills, mcp, agent_types, friction_events, tools)


def _file_is_limited(path: Path) -> bool:
    return path.stat().st_size > MAX_FILE_BYTES


def parse_jsonl(agent: str, path: Path, max_records: int = MAX_RECORDS_PER_SOURCE) -> ParseResult:
    """Stream JSONL, retaining good records and counting malformed lines."""
    if _file_is_limited(path):
        return ParseResult((), True)
    records: list[ParsedRecord] = []
    skipped_lines = 0
    with path.open("rb") as handle:
        for number, raw in enumerate(handle, start=1):
            if len(raw) > MAX_LINE_BYTES:
                return ParseResult(tuple(records), True, skipped_lines=skipped_lines)
            if not raw.strip():
                continue
            try:
                value = json.loads(raw.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                skipped_lines += 1
                continue
            if isinstance(value, dict):
                record = mapping_record(agent, path, _file_locator(path, line=number), value)
                if record is not None:
                    records.append(record)
                    if len(records) >= max_records:
                        return ParseResult(tuple(records), True, skipped_lines=skipped_lines)
    return ParseResult(tuple(records), False, skipped_lines=skipped_lines)


def parse_json(agent: str, path: Path, max_records: int = MAX_RECORDS_PER_SOURCE) -> ParseResult:
    """Read a size-capped JSON document with object or array locators."""
    if _file_is_limited(path):
        return ParseResult((), True)
    value = json.loads(path.read_bytes().decode("utf-8"))
    values = value if isinstance(value, list) else [value]
    records: list[ParsedRecord] = []
    for index, item in enumerate(values, start=1):
        if isinstance(item, dict):
            locator = _file_locator(path, index=index) if isinstance(value, list) else _file_locator(path, offset=0)
            record = mapping_record(agent, path, locator, item)
            if record is not None:
                records.append(record)
                if len(records) >= max_records:
                    return ParseResult(tuple(records), True)
    return ParseResult(tuple(records), False)


def parse_markdown(agent: str, path: Path, max_records: int = MAX_RECORDS_PER_SOURCE) -> ParseResult:
    """Stream Markdown lines, retaining decodable notes and counting bad lines."""
    if _file_is_limited(path):
        return ParseResult((), True)
    records: list[ParsedRecord] = []
    skipped_lines = 0
    with path.open("rb") as handle:
        for number, raw in enumerate(handle, start=1):
            if len(raw) > MAX_LINE_BYTES:
                return ParseResult(tuple(records), True, skipped_lines=skipped_lines)
            try:
                line = raw.decode("utf-8").strip()
            except UnicodeDecodeError:
                skipped_lines += 1
                continue
            if line:
                records.append(ParsedRecord(agent, path.stem, path.parent.name, str(path.parent), None, None, None, "note", line, path, _file_locator(path, line=number), "parsed", (), (), (), (), ()))
                if len(records) >= max_records:
                    return ParseResult(tuple(records), True, skipped_lines=skipped_lines)
    return ParseResult(tuple(records), False, skipped_lines=skipped_lines)


def _quoted(identifier: str) -> str:
    return f'"{identifier.replace(chr(34), chr(34) * 2)}"'


def parse_sqlite(agent: str, path: Path, max_records: int = MAX_RECORDS_PER_SOURCE) -> ParseResult:
    """Read recognized SQLite tables through a percent-encoded read-only URI."""
    if _file_is_limited(path):
        return ParseResult((), True)
    records: list[ParsedRecord] = []
    recognized = False
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        for table_row in tables:
            table = table_row[0]
            if not isinstance(table, str):
                continue
            try:
                columns = [row[1] for row in connection.execute(f"PRAGMA table_info({_quoted(table)})") if isinstance(row[1], str)]
                if not ({column.lower() for column in columns} & set(TEXT_KEYS)):
                    continue
                recognized = True
                cursor = connection.execute(f"SELECT rowid, * FROM {_quoted(table)} LIMIT ?", (max_records - len(records) + 1,))
                names = [description[0] for description in cursor.description[1:]]
                for row in cursor:
                    if len(records) >= max_records:
                        return ParseResult(tuple(records), True, recognized)
                    rowid = row[0]
                    if not isinstance(rowid, int):
                        continue
                    value = dict(zip(names, row[1:], strict=True))
                    record = mapping_record(agent, path, _file_locator(path, table=table, rowid=rowid), value)
                    if record is not None:
                        records.append(record)
            except sqlite3.Error:
                continue
    finally:
        connection.close()
    return ParseResult(tuple(records), False, recognized)


def inspect_agent(agent: str, roots: tuple[Path, ...]) -> SourceResult:
    """Probe one adapter under source-global file, record, and byte budgets."""
    records: list[ParsedRecord] = []
    notes: list[str] = []
    files_seen = 0
    permission_failures = 0
    unsupported_files = 0
    skipped_lines = 0
    remaining_bytes = MAX_SOURCE_BYTES
    denied: list[Path] = []
    try:
        files = candidate_files(roots, denied)
        for path in files:
            if files_seen >= MAX_FILES_PER_SOURCE:
                notes.append("limit-exceeded: files")
                break
            files_seen += 1
            try:
                size = path.stat().st_size
            except PermissionError as error:
                permission_failures += 1
                notes.append(f"skipped {path.name}: {type(error).__name__}")
                continue
            if size > remaining_bytes:
                notes.append("limit-exceeded: source-bytes")
                break
            remaining_bytes -= size
            parser = format_for(agent, path)
            if parser is None:
                unsupported_files += 1
                notes.append(f"skipped {path.name}: unsupported-format")
                continue
            try:
                remaining_records = MAX_RECORDS_PER_SOURCE - len(records)
                if remaining_records <= 0:
                    notes.append("limit-exceeded: records")
                    break
                match parser:
                    case "jsonl":
                        result = parse_jsonl(agent, path, remaining_records)
                    case "json":
                        result = parse_json(agent, path, remaining_records)
                    case "markdown":
                        result = parse_markdown(agent, path, remaining_records)
                    case "sqlite":
                        result = parse_sqlite(agent, path, remaining_records)
                    case _:
                        raise AssertionError("format_for returned an unknown parser")
            except PermissionError as error:
                permission_failures += 1
                notes.append(f"skipped {path.name}: {type(error).__name__}")
                continue
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, sqlite3.DatabaseError, sqlite3.Error) as error:
                unsupported_files += 1
                notes.append(f"skipped {path.name}: {type(error).__name__}")
                continue
            records.extend(result.records)
            skipped_lines += result.skipped_lines
            if result.limit_exceeded:
                notes.append(f"{path.name}: limit-exceeded")
            if not result.schema_recognized:
                notes.append("sqlite schema not recognized")
                unsupported_files += 1
    except PermissionError as error:
        permission_failures += 1
        notes.append(f"store enumeration failed: {type(error).__name__}")
    except OSError as error:
        notes.append(f"store enumeration failed: {type(error).__name__}")
        unsupported_files += 1
    if denied:
        permission_failures += len(denied)
        notes.append(f"inaccessible-paths: {len(denied)}")
    if skipped_lines:
        notes.append(f"skipped-lines: {skipped_lines}")
    note = "; ".join(notes) if notes else "parsed read-only"
    if records:
        return SourceResult(agent, "available", roots, note, tuple(records))
    if permission_failures:
        return SourceResult(agent, "inaccessible", roots, note, ())
    if unsupported_files:
        return SourceResult(agent, "unsupported", roots, note if notes else "no v1 parser for found format", ())
    if files_seen:
        return SourceResult(agent, "available", roots, note if notes else "parsed read-only: 0 records", ())
    return SourceResult(agent, "not-found", roots, "no configured or documented store found", ())
