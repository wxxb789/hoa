"""Extract Codex sessions from rollouts or the local SQLite history stores."""

import sqlite3
import sys
from collections.abc import Iterator
from contextlib import ExitStack, closing
from itertools import batched, groupby
from operator import itemgetter
from pathlib import Path

from .codex_rollout import _codex_clean_thread, _codex_project, _codex_steps, _read_codex_rollout
from .sources import EmitSession, Scope


def _open_codex_db(stack: ExitStack, path: Path) -> sqlite3.Connection:
    resolved = path.resolve()
    uri = resolved.as_uri() + "?mode=ro"
    with resolved.open("rb") as stream:
        wal_mode = stream.read(20)[18:20] == b"\x02\x02"
    # mode=ro alone can create WAL sidecars in a writable directory.
    use_immutable = wal_mode and not all(
        resolved.with_name(f"{resolved.name}-{suffix}").exists() for suffix in ("wal", "shm")
    )
    if not use_immutable:
        try:
            with ExitStack() as opened:
                db = opened.enter_context(closing(sqlite3.connect(uri, uri=True, timeout=0.1)))
                db.execute("BEGIN")
                db.execute("SELECT 1 FROM sqlite_schema LIMIT 1").fetchone()
                stack.enter_context(opened.pop_all())
                return db
        except sqlite3.OperationalError as exc:
            if (getattr(exc, "sqlite_errorcode", 0) & 0xFF) not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                raise
    print(f"codex: {path}: using immutable read-only view; recent WAL changes may be unavailable", file=sys.stderr)
    return stack.enter_context(closing(sqlite3.connect(uri + "&immutable=1", uri=True)))


def extract_codex_root(root: Path, scope: Scope, emit: EmitSession, *, include_subagents: bool = False) -> dict:
    coverage = dict(root=str(root), status="available", included_threads=0, skipped_threads=0,
                    jsonl_backed=0, sqlite_backed=0)
    if not root.is_dir():
        coverage["status"] = "not-found"
        return coverage

    def emit_thread(
        tid: str, project: str | None, path: str, backing: str, include_clean: bool, meta: dict, steps: list[dict],
    ) -> None:
        if project is None or not steps or not (include_clean or include_subagents or meta["tool_errors"]):
            coverage["skipped_threads"] += 1
            return
        emit(f"codex:{project}:{tid}", "codex", project, path, meta, steps)
        coverage["included_threads"] += 1
        coverage[backing] += 1

    state_path = root / "state_5.sqlite"
    history_path = root / "thread_history_1.sqlite"
    if state_path.is_file() and history_path.is_file():
        with ExitStack() as stack:
            state = _open_codex_db(stack, state_path)
            history = _open_codex_db(stack, history_path)
            pending: dict[str, tuple[str, bool]] = {}
            since_clause, params = ("WHERE updated_at >= ? ", (scope.since.timestamp(),)) if scope.since else ("", ())
            for tid, cwd, rollout_path, source, role in state.execute(
                "SELECT id, cwd, rollout_path, thread_source, agent_role FROM threads "
                f"{since_clause}ORDER BY id", params,
            ):
                project = _codex_project(cwd, scope)
                if project is None:
                    coverage["skipped_threads"] += 1
                    continue
                include_clean = _codex_clean_thread(source, role)
                rollout = root / rollout_path if rollout_path else None
                if rollout is not None and rollout.suffix.lower() == ".jsonl" and rollout.is_file():
                    meta, steps = _read_codex_rollout(rollout, scope.redact, scope.extra_high_signal)
                    emit_thread(tid, project, str(rollout), "jsonl_backed", include_clean, meta, steps)
                else:
                    pending[tid] = (project, include_clean)

            # Batch across threads, including when an exported store has no index.
            for batch in batched(tuple(pending), 500):
                placeholders = ",".join("?" for _ in batch)
                rows = history.execute(
                    "SELECT thread_id, rollout_ordinal, item_type, item_json FROM thread_items "
                    f"WHERE thread_id IN ({placeholders}) ORDER BY thread_id, rollout_ordinal ASC", batch,
                )
                for tid, items in groupby(rows, key=itemgetter(0)):
                    project, include_clean = pending.pop(tid)
                    meta, steps = _codex_steps((row[1:] for row in items), scope.redact, scope.extra_high_signal)
                    emit_thread(tid, project, f"{history_path}#thread={tid}", "sqlite_backed", include_clean, meta, steps)
            coverage["skipped_threads"] += len(pending)
    else:
        for rollout in sorted(root.rglob("rollout-*.jsonl")):
            if rollout.is_file() and scope.modified_since(rollout):
                meta, steps = _read_codex_rollout(rollout, scope.redact, scope.extra_high_signal, scope=scope)
                emit_thread(meta["tid"], meta["project"], str(rollout), "jsonl_backed", meta["include_clean"], meta, steps)
    return coverage


def read_codex_evidence(path: Path, thread_id: str, start: int, end: int) -> Iterator[tuple[int, str, str]]:
    with ExitStack() as stack:
        yield from _open_codex_db(stack, path).execute(
            "SELECT rollout_ordinal, item_type, item_json FROM thread_items "
            "WHERE thread_id = ? AND rollout_ordinal BETWEEN ? AND ? ORDER BY rollout_ordinal",
            (thread_id, start, end),
        )
