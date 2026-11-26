"""Build redacted session trajectories and retrieve the original evidence behind them."""

import re
import sqlite3
from collections.abc import Iterable, Iterator, Sequence
from datetime import datetime
from itertools import groupby, islice
from pathlib import Path

from ..io import iter_jsonl, write_json, write_jsonl
from .claude import extract_claude_root
from .codex import extract_codex_root, read_codex_evidence
from .omp import extract_omp_root
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
    allow_regex: str | None = None,
    deny_regex: str | None = None,
    redact_regexes: Iterable[str] = (),
    extra_high_signal: Iterable[str] = (),
    since: datetime | None = None,
    max_span_chars: int = 4600,
) -> dict:
    try:
        scope = Scope(
            allow=re.compile(allow_regex) if allow_regex else None,
            deny=re.compile(deny_regex) if deny_regex else None,
            since=since,
            redact=tuple(re.compile(pattern) for pattern in redact_regexes),
            extra_high_signal=tuple(re.compile(pattern) for pattern in extra_high_signal),
        )
    except re.PatternError as exc:
        raise ValueError(f"invalid history regex: {exc}") from exc
    out_dir.mkdir(parents=True, exist_ok=True)
    skeletons: dict[str, dict] = {}
    spans: dict[str, dict] = {}

    def emit(session_id: str, runtime: str, project: str, path: str, meta: dict, steps: list[dict]) -> None:
        skeleton, chunks = build_skeleton_and_spans(
            session_id, runtime, project, path, meta, steps, max_span_chars=max_span_chars,
        )
        skeletons[session_id] = skeleton
        spans.update((chunk["id"], chunk) for chunk in chunks)

    coverage = {
        "claude": [extract_claude_root(root.expanduser(), scope, emit) for root in claude_roots],
        "omp": [extract_omp_root(root.expanduser(), scope, emit) for root in omp_roots],
        "codex": [],
    }
    for root in codex_roots:
        root = root.expanduser()
        try:
            report = extract_codex_root(root, scope, emit, include_subagents=include_codex_subagents)
        except sqlite3.Error as exc:
            raise ValueError(f"codex: {root}: {exc}") from exc
        coverage["codex"].append(report)

    write_jsonl(out_dir / "skeletons.jsonl", skeletons.values())
    write_jsonl(out_dir / "spans.jsonl", spans.values())
    summary = {
        "since": since.isoformat() if since else None,
        "skeleton_count": len(skeletons),
        "span_count": len(spans),
        "pivot_span_count": sum(1 for span in spans.values() if span["has_pivot"]),
        "coverage": coverage,
    }
    write_json(out_dir / "extract-manifest.json", summary)
    return summary


class SpanNotFound(Exception):
    """The requested ID is not in the supplied spans file."""


def show_evidence(
    spans_path: Path, span_ids: Sequence[str], *, context: int = 0, max_line_chars: int = 2000,
) -> Iterator[str]:
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
                    yield clip(f"L{line}\t{raw.rstrip()}")
