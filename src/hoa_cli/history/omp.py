"""Extract OMP sessions, retaining parent links and tool failure evidence."""

import json
from pathlib import Path

from .redact import OMP_REMINDER_RE, RegexPatterns, _summarize_tool, _text_blocks
from .sources import EmitSession, Scope, numbered_records, project_dirs, project_logs
from .steps import assistant_step, tool_result_step, user_step


def parse_omp_steps(
    path: Path, extra_redact: RegexPatterns | None = None, extra_high_signal: RegexPatterns = (),
) -> tuple[dict, list[dict]]:
    tool_calls: dict[str, tuple[int, str]] = {}
    steps: list[dict] = []
    raw_lines = user_turns = tool_errors = 0
    parent_session = None

    for raw_lines, record in numbered_records(path):
        line = raw_lines
        record_type = record.get("type")
        if record_type == "session":
            if parent := record.get("parentSession"):
                parent_session = str(parent)
            continue
        if record_type != "message" or not isinstance(message := record.get("message"), dict):
            continue
        role = message.get("role")
        content = message.get("content")
        if role == "user":
            text = OMP_REMINDER_RE.sub("", _text_blocks(content)).strip()
            if text.startswith("<chat-history-summary>") and "</chat-history-summary>" in text:
                text = text.split("</chat-history-summary>", 1)[1].strip()
            if text:
                steps.append(user_step(line, text, extra_redact))
                user_turns += 1
        elif role == "assistant" and isinstance(content, list):
            for block in (block for block in content if isinstance(block, dict)):
                kind = block.get("type")
                if kind == "toolCall" and (call_id := str(block.get("id") or "")):
                    name = str(block.get("name") or "tool")
                    args = block.get("arguments")
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    tool_calls[call_id] = (line, _summarize_tool(name, args or {}))
                elif kind == "text" and (text := str(block.get("text", "")).strip()):
                    steps.append(assistant_step(line, text, extra_redact))
        elif role == "toolResult":
            call_id = str(message.get("toolCallId") or "")
            name = str(message.get("toolName") or "tool")
            call_line, summary = tool_calls.get(call_id, (line, name))
            step = tool_result_step(line, call_line, summary, content, bool(message.get("isError")),
                                    extra_redact, extra_high_signal)
            tool_errors += int(step["pivot"])
            steps.append(step)

    return {
        "raw_lines": raw_lines, "user_turns": user_turns, "tool_errors": tool_errors,
        "hook_errors": 0, "parent_session": parent_session,
    }, steps


def extract_omp_root(root: Path, scope: Scope, emit: EmitSession) -> dict:
    coverage, projects = project_dirs(root, scope)
    for project in projects:
        for path, meta, steps in project_logs(project, scope, parse_omp_steps):
            emit(f"omp:{project.name}:{path.stem}", "omp", project.name, str(path), meta, steps)
    return coverage
