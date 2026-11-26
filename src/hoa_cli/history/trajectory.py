"""Build redacted session trajectories and retrieve the original evidence behind them."""

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterable, Iterator, Sequence
from datetime import datetime
from itertools import groupby, islice
from pathlib import Path

from ..io import iter_jsonl, write_json, write_jsonl
from .claude import extract_claude_memories, extract_claude_root
from .codex import extract_codex_memories, extract_codex_root, read_codex_evidence
from .omp import extract_omp_root
from .redact import OMP_REMINDER_RE, _text_blocks
from .sources import Scope


def _compress_clean_streaks(steps: list[dict]) -> list[dict]:
    compressed = []
    for clean, group in groupby(steps, key=lambda step: bool(step.get("compact_ok"))):
        if not clean:
            compressed.extend(group)
            continue
        streak = list(group)
        if len(streak) <= 2:
            compressed.extend(streak)
        else:
            start, end = streak[0]["line"], streak[-1]["line"]
            compressed.append({
                "line": start, "line_end": end, "pivot": False, "kind": "clean_fold",
                "text": f"[L{start}-L{end}: {len(streak)} clean tool calls]",
            })
    return compressed


def build_skeleton_and_spans(
    session_id: str,
    runtime: str,
    project: str,
    locator_path: str,
    meta: dict,
    steps: list[dict],
    *,
    max_span_chars: int = 4600,
) -> tuple[dict, list[dict]]:
    compressed = _compress_clean_streaks(steps)
    skeleton_steps = compressed
    if len(compressed) > 50:
        keep = {0, len(compressed) - 1}
        for i, step in enumerate(compressed):
            if step.get("pivot"):
                keep.update(range(max(0, i - 1), min(len(compressed), i + 2)))
        skeleton_steps = [compressed[i] for i in sorted(keep)]
        if len(skeleton_steps) > 85:
            omitted = len(skeleton_steps) - 75
            skeleton_steps = (
                skeleton_steps[:42]
                + [{"text": f"... [{omitted} middle steps omitted in L0 skeleton] ..."}]
                + skeleton_steps[-33:]
            )

    header = (
        f"SESSION {session_id} | runtime={runtime} | project={project} | "
        f"raw_lines={meta['raw_lines']} | user_turns={meta['user_turns']} | "
        f"tool_errors={meta['tool_errors']} | hook_errors={meta['hook_errors']}"
    )
    location = {"runtime": runtime, "project": project, "path": locator_path}
    skeleton = {
        "id": session_id,
        **location,
        "raw_lines": meta["raw_lines"],
        "user_turns": meta["user_turns"],
        "tool_errors": meta["tool_errors"],
        "hook_errors": meta["hook_errors"],
        "parent_session": meta.get("parent_session"),
        "text": header + "\n" + "\n".join(step["text"] for step in skeleton_steps),
    }

    def make_span(chunk: list[dict]) -> dict:
        start, last = chunk[0]["line"], chunk[-1]
        end = last.get("line_end", last["line"])
        span_id = f"{session_id}@L{start}-{end}"
        return {
            "id": span_id,
            "session_id": session_id,
            **location,
            "l_start": start,
            "l_end": end,
            "has_pivot": any(bool(step.get("pivot")) for step in chunk),
            "text": f"SPAN {span_id}\n" + "\n".join(step["text"] for step in chunk),
        }

    spans = []
    chunk = []
    chunk_len = 0
    for step in compressed:
        step_len = len(step["text"]) + 1
        if len(chunk) >= 5 and chunk_len + step_len > max_span_chars:
            spans.append(make_span(chunk))
            chunk = chunk[-2:]
            chunk_len = sum(len(item["text"]) + 1 for item in chunk)
        chunk.append(step)
        chunk_len += step_len
    if chunk:
        span = make_span(chunk)
        if not spans or spans[-1]["id"] != span["id"]:
            spans.append(span)
    return skeleton, spans


def extract_all(
    out_dir: Path,
    *,
    claude_roots: Iterable[Path] = (),
    omp_roots: Iterable[Path] = (),
    codex_roots: Iterable[Path] = (),
    include_codex_subagents: bool = False,
    include_memories: bool = False,
    dedup_spans: bool = True,
    min_lines: int = 2,
    cursor_file: Path | None = None,
    allow_regex: str | None = None,
    deny_regex: str | None = None,
    redact_regexes: Iterable[str] = (),
    extra_high_signal: Iterable[str] = (),
    since: datetime | None = None,
    max_span_chars: int = 4600,
) -> dict:
    run_started = datetime.now().astimezone().replace(microsecond=0)
    effective_since = since
    if effective_since is None and cursor_file is not None and cursor_file.is_file():
        raw_cursor = cursor_file.read_text(encoding="utf-8").strip()
        if raw_cursor:
            try:
                effective_since = datetime.fromisoformat(raw_cursor)
            except ValueError as exc:
                raise ValueError(f"invalid cursor timestamp in {cursor_file}: {raw_cursor!r}") from exc
    try:
        scope = Scope(
            allow=re.compile(allow_regex) if allow_regex else None,
            deny=re.compile(deny_regex) if deny_regex else None,
            since=effective_since,
            redact=tuple(re.compile(pattern) for pattern in redact_regexes),
            extra_high_signal=tuple(re.compile(pattern) for pattern in extra_high_signal),
            min_lines=min_lines,
        )
    except re.PatternError as exc:
        raise ValueError(f"invalid history regex: {exc}") from exc
    out_dir.mkdir(parents=True, exist_ok=True)
    seen_skeletons: set[str] = set()
    seen_span_ids: set[str] = set()
    seen_span_hashes: dict[str, str] = {}
    skeleton_count = span_count = pivot_span_count = deduped_span_count = 0

    with (
        (out_dir / "skeletons.jsonl").open("w", encoding="utf-8", newline="\n") as skel_out,
        (out_dir / "spans.jsonl").open("w", encoding="utf-8", newline="\n") as span_out,
    ):
        def emit(session_id: str, runtime: str, project: str, path: str, meta: dict, steps: list[dict]) -> None:
            nonlocal skeleton_count, span_count, pivot_span_count, deduped_span_count
            skeleton, chunks = build_skeleton_and_spans(
                session_id, runtime, project, path, meta, steps, max_span_chars=max_span_chars,
            )
            if session_id not in seen_skeletons:
                seen_skeletons.add(session_id)
                skel_out.write(json.dumps(skeleton, ensure_ascii=False) + "\n")
                skeleton_count += 1
            is_branched = bool(meta.get("parent_session"))
            for chunk in chunks:
                if chunk["id"] in seen_span_ids:
                    continue
                if dedup_spans and (is_branched or runtime == "omp"):
                    body = chunk["text"].split("\n", 1)[1] if "\n" in chunk["text"] else chunk["text"]
                    key = hashlib.sha256(f"{runtime}|{project}|{body}".encode("utf-8")).hexdigest()
                    if key in seen_span_hashes:
                        deduped_span_count += 1
                        continue
                    seen_span_hashes[key] = chunk["id"]
                seen_span_ids.add(chunk["id"])
                span_out.write(json.dumps(chunk, ensure_ascii=False) + "\n")
                span_count += 1
                if chunk["has_pivot"]:
                    pivot_span_count += 1
            skel_out.flush()
            span_out.flush()

        coverage: dict[str, list[dict]] = {
            "claude": [extract_claude_root(root.expanduser(), scope, emit) for root in claude_roots],
            "omp": [extract_omp_root(root.expanduser(), scope, emit) for root in omp_roots],
            "codex": [],
        }
        memories: list[dict] = []
        if include_memories:
            mem_cov = []
            for root in claude_roots:
                cov, found = extract_claude_memories(root.expanduser(), scope)
                mem_cov.append(cov)
                memories.extend(found)
            coverage["claude_memories"] = mem_cov
            codex_mem_cov = []
            for root in codex_roots:
                try:
                    cov, found = extract_codex_memories(root.expanduser(), scope)
                except sqlite3.Error as exc:
                    raise ValueError(f"codex memories: {root}: {exc}") from exc
                codex_mem_cov.append(cov)
                memories.extend(found)
            if codex_mem_cov:
                coverage["codex_memories"] = codex_mem_cov
        for root in codex_roots:
            root = root.expanduser()
            try:
                report = extract_codex_root(root, scope, emit, include_subagents=include_codex_subagents)
            except sqlite3.Error as exc:
                raise ValueError(f"codex: {root}: {exc}") from exc
            coverage["codex"].append(report)

    if include_memories:
        write_jsonl(out_dir / "memories.jsonl", memories)
    if cursor_file is not None:
        cursor_file.parent.mkdir(parents=True, exist_ok=True)
        cursor_file.write_text(run_started.isoformat() + "\n", encoding="utf-8")
    summary = {
        "since": effective_since.isoformat() if effective_since else None,
        "cursor_written": run_started.isoformat() if cursor_file is not None else None,
        "skeleton_count": skeleton_count,
        "span_count": span_count,
        "pivot_span_count": pivot_span_count,
        "deduped_span_count": deduped_span_count,
        "memory_count": len(memories),
        "coverage": coverage,
    }
    write_json(out_dir / "extract-manifest.json", summary)
    return summary


class SpanNotFound(Exception):
    """The requested ID is not in the supplied spans file."""


def _format_readable_record(line: int, raw: str) -> list[str]:
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        text = raw.strip()
        return [f"L{line}\t{text}"] if text else []
    if not isinstance(obj, dict):
        return []
    rtype = obj.get("type")
    lines: list[str] = []
    if rtype == "message" and isinstance(msg := obj.get("message"), dict):
        role = msg.get("role")
        content = msg.get("content")
        if role in ("user", "assistant"):
            text = _text_blocks(content)
            if role == "user":
                text = OMP_REMINDER_RE.sub("", text).strip()
            if text and not text.startswith(("<paseo-system", "<system-")):
                lines.append(f"L{line}\t[{role.upper()}] {text}")
        elif role == "toolResult" and msg.get("isError"):
            text = _text_blocks(content).strip()
            if text:
                lines.append(f"L{line}\t[TOOL_ERR {msg.get('toolName', 'tool')}] {text}")
    elif rtype in ("user", "assistant"):
        msg = obj.get("message") or {}
        content = msg.get("content") if isinstance(msg, dict) else obj.get("content")
        if isinstance(content, str) and content.strip():
            lines.append(f"L{line}\t[{rtype.upper()}] {content.strip()}")
        elif isinstance(content, list):
            for block in (b for b in content if isinstance(b, dict)):
                btype = block.get("type")
                if btype == "text" and (text := str(block.get("text", "")).strip()):
                    lines.append(f"L{line}\t[{rtype.upper()}] {text}")
                elif btype == "tool_result" and block.get("is_error"):
                    text = _text_blocks(block.get("content")).strip()
                    if text:
                        lines.append(f"L{line}\t[TOOL_ERR] {text}")
    elif rtype == "system":
        errors = obj.get("hookErrors") or []
        if errors:
            lines.append(f"L{line}\t[HOOK_ERROR] {'; '.join(str(e) for e in errors)}")
        elif obj.get("level") in ("error", "warning") or obj.get("subtype") in ("api_error", "turn_aborted"):
            text = str(obj.get("content") or obj.get("error") or "").strip()
            if text:
                lines.append(f"L{line}\t[SYS:{obj.get('subtype')}] {text}")
    return lines


def show_evidence(
    spans_path: Path, span_ids: Sequence[str], *, context: int = 0, max_line_chars: int = 2000,
    output_format: str = "raw",
) -> Iterator[str]:
    if output_format not in ("raw", "readable"):
        raise ValueError(f"unsupported show format {output_format!r}; expected 'raw' or 'readable'")
    wanted = set(span_ids)
    spans = {span["id"]: span for span in iter_jsonl(spans_path) if span["id"] in wanted}

    def clip(text: str) -> str:
        extra = len(text) - max_line_chars
        return text if extra <= 0 else f"{text[:max_line_chars]} ... [+{extra} chars]"

    for span_id in span_ids:
        span = spans.get(span_id)
        if span is None:
            raise SpanNotFound(f"span id not found in {spans_path}: {span_id}")
        locator = span["path"]
        db_path, sep, thread_id = locator.partition("#thread=")
        start = max(0 if sep else 1, span["l_start"] - context)
        end = span["l_end"] + context
        yield f"== {span_id} | {locator} | {'ordinal' if sep else 'L'}{start}-{end}"
        if sep:
            try:
                for ordinal, kind, item in read_codex_evidence(Path(db_path), thread_id, start, end):
                    yield clip(f"{ordinal}\t{kind}\t{item}")
            except sqlite3.Error as exc:
                raise ValueError(f"codex: {db_path}: {exc}") from exc
        else:
            with Path(locator).open(encoding="utf-8", errors="replace") as stream:
                for line, raw in enumerate(islice(stream, start - 1, end), start=start):
                    if output_format == "readable":
                        for formatted in _format_readable_record(line, raw):
                            yield clip(formatted)
                    else:
                        yield clip(f"L{line}\t{raw.rstrip()}")
