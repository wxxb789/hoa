"""Extract Claude Code sessions and failed workflow subagents."""

from collections.abc import Iterator
from pathlib import Path

from .redact import RegexPatterns, _summarize_tool, redact_text
from .sources import EmitSession, Scope, json_object, numbered_records, project_dirs, project_logs
from .steps import assistant_step, tool_result_step, user_step


def parse_claude_steps(
    path: Path, extra_redact: RegexPatterns | None = None, extra_high_signal: RegexPatterns = (),
) -> tuple[dict, list[dict]]:
    tool_uses: dict[str, tuple[int, str]] = {}
    steps: list[dict] = []
    raw_lines = user_turns = tool_errors = hook_errors = 0

    for raw_lines, record in numbered_records(path):
        line = raw_lines
        record_type = record.get("type")
        if record_type == "system":
            errors = record.get("hookErrors") or []
            subtype = record.get("subtype")
            if errors:
                hook_errors += len(errors)
                text = "; ".join(redact_text(str(error), extra_redact)[:360] for error in errors)
                steps.append({"line": line, "pivot": True, "kind": "hook_error", "text": f"[L{line} HOOK_ERROR] {text}"})
            elif record.get("level") in ("error", "warning") or subtype in ("api_error", "turn_aborted"):
                text = redact_text(str(record.get("content") or record.get("error") or ""), extra_redact)[:320]
                steps.append({"line": line, "pivot": True, "kind": "sys_warn", "text": f"[L{line} SYS:{subtype}] {text}"})
            continue
        if record_type not in ("assistant", "user"):
            continue

        message = record.get("message") or {}
        content = message.get("content") if isinstance(message, dict) else record.get("content")
        if record_type == "assistant":
            if not isinstance(content, list):
                continue
            for block in (block for block in content if isinstance(block, dict)):
                kind = block.get("type")
                if kind == "tool_use" and (tool_id := block.get("id")):
                    name = str(block.get("name", "tool"))
                    tool_uses[str(tool_id)] = (line, _summarize_tool(name, block.get("input") or {}))
                elif kind == "text" and (text := str(block.get("text", "")).strip()):
                    steps.append(assistant_step(line, text, extra_redact))
            continue

        is_meta = bool(record.get("isMeta"))
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else content
        if not isinstance(blocks, list):
            continue
        for block in (block for block in blocks if isinstance(block, dict)):
            kind = block.get("type")
            if kind == "tool_result":
                tool_id = str(block.get("tool_use_id") or "")
                call_line, summary = tool_uses.get(tool_id, (line, "tool"))
                step = tool_result_step(line, call_line, summary, block.get("content"), bool(block.get("is_error")),
                                        extra_redact, extra_high_signal)
                tool_errors += int(step["pivot"])
                steps.append(step)
            elif kind == "text" and not is_meta:
                text = str(block.get("text", "")).strip()
                if text and not text.startswith("<local-command"):
                    steps.append(user_step(line, text, extra_redact))
                    user_turns += 1

    return {
        "raw_lines": raw_lines, "user_turns": user_turns, "tool_errors": tool_errors,
        "hook_errors": hook_errors, "parent_session": None,
    }, steps


def _failed_agents(project: Path, scope: Scope) -> Iterator[Path]:
    for journal in sorted(project.rglob("journal.jsonl")):
        if not journal.is_file():
            continue
        with journal.open(encoding="utf-8", errors="replace") as stream:
            for raw in stream:
                if any(token in raw for token in ('"failed"', '"error"', '"aborted"')):
                    if agent_id := json_object(raw).get("agentId"):
                        path = journal.parent / f"agent-{agent_id}.jsonl"
                        if path.is_file() and scope.modified_since(path):
                            yield path


def extract_claude_root(root: Path, scope: Scope, emit: EmitSession) -> dict:
    coverage, projects = project_dirs(root, scope)
    for project in projects:
        for path, meta, steps in project_logs(project, scope, parse_claude_steps):
            emit(f"claude:{project.name}:{path.stem}", "claude-code", project.name, str(path), meta, steps)
        for path in _failed_agents(project, scope):
            meta, steps = parse_claude_steps(path, scope.redact, scope.extra_high_signal)
            if steps:
                emit(f"claude-sub:{project.name}:{path.stem}", "claude-subagent", project.name, str(path), meta, steps)
    return coverage
