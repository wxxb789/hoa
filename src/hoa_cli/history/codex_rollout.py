"""Normalize Codex thread items and both generations of rollout events."""

import re
from collections.abc import Iterable
from pathlib import Path

from .redact import CODEX_FRAME_RE, EXIT_ERR_RE, RegexPatterns, matches_high_signal, redact_text
from .sources import Scope, json_object, numbered_records


def _codex_project(cwd: str | None, scope: Scope) -> str | None:
    cwd = (cwd or "").removeprefix("\\\\?\\")
    project = re.sub(r"[\\/:]+", "-", cwd).strip("-") or "unknown"
    return project if scope.allows(cwd, project) else None


def _codex_clean_thread(source: object, role: object) -> bool:
    return source in ("user", None, "") or role in ("worker", "default")


def _codex_message(content: object, *, user: bool) -> str:
    if isinstance(content, str):
        parts = [content]
    elif isinstance(content, list):
        parts = [
            block if isinstance(block, str) else str(block.get("text") or "")
            for block in content
            if isinstance(block, str) or (
                isinstance(block, dict)
                and str(block.get("type", "text")).lower() in ("text", "input_text", "output_text")
            )
        ]
    else:
        return ""
    if user:
        parts = [CODEX_FRAME_RE.sub("", part).strip() for part in parts]
    return "\n".join(part for part in parts if part).strip()


def _codex_steps(
    rows: Iterable[tuple[int, str, object]], extra_redact: RegexPatterns | None,
    extra_high_signal: RegexPatterns = (),
) -> tuple[dict, list[dict]]:
    meta = {"raw_lines": 0, "user_turns": 0, "tool_errors": 0, "hook_errors": 0}
    steps = []
    for line, kind, raw in rows:
        meta["raw_lines"] += 1
        item = json_object(raw)
        if not item or not isinstance(kind, str):
            continue
        kind = kind.casefold()
        if kind in ("usermessage", "agentmessage"):
            user = kind == "usermessage"
            text = _codex_message(item.get("text") or item.get("content"), user=user)
            if text:
                meta["user_turns"] += int(user)
                label = "USER" if user else "ASST"
                steps.append({
                    "line": line, "pivot": user, "kind": "user" if user else "assistant",
                    "text": f"[L{line} {label}] " + redact_text(text, extra_redact)[:660],
                })
            continue

        if kind == "commandexecution":
            command = item.get("command") or ""
            command = " ".join(map(str, command)) if isinstance(command, list) else str(command)
            summary = "exec(" + redact_text(command, extra_redact).replace("\n", " ; ")[:130] + ")"
            output = str(item.get("aggregatedOutput", item.get("aggregated_output")) or "")
            exit_code = item.get("exitCode", item.get("exit_code"))
            is_error = exit_code not in (0, None) or bool(EXIT_ERR_RE.search(output))
            if exit_code not in (0, None):
                output = f"exit={exit_code} {output}"
            special = matches_high_signal(command, extra_high_signal)
        elif kind == "mcptoolcall":
            summary = redact_text(f"{item.get('server') or 'mcp'}.{item.get('tool') or 'tool'}", extra_redact)[:130]
            result = item.get("result")
            status = item.get("status")
            fields = json_object(result)
            payload = json_object(fields.get("Ok", fields))
            structured = json_object(payload.get("structuredContent", payload.get("structured_content")))
            is_error = status != "completed" or bool(item.get("error")) or "Err" in fields or any(
                obj.get("ok") is False or obj.get("isError") is True or obj.get("is_error") is True or obj.get("error")
                for obj in (fields, payload, structured)
            )
            output = str(item.get("error") or result or status or "")
            if result and status and status != "completed":
                output = f"status={status} {output}"
            special = False
        elif kind == "error":
            summary, output, is_error, special = "codex", str(item.get("message") or ""), True, False
        else:
            continue

        meta["tool_errors"] += int(is_error)
        label = "TOOL_ERR" if is_error else "TOOL_OK"
        step = {"line": line, "pivot": is_error, "text": f"[L{line} {label} {summary}]"}
        if is_error or special:
            step["kind"] = "tool_error" if is_error else "tool_special"
            if output:
                step["text"] += " " + redact_text(output, extra_redact)[:500 if is_error else 200]
        else:
            step.update(kind="tool_ok", compact_ok=True)
        steps.append(step)
    return meta, steps


def _codex_response_item(payload: dict, calls: dict[str, tuple[str, dict]]) -> tuple[str, dict]:
    kind, call_id = payload.get("type"), payload.get("call_id")
    if kind == "message" and payload.get("role") in ("user", "assistant"):
        return ("UserMessage" if payload["role"] == "user" else "AgentMessage"), payload
    if kind == "function_call" and isinstance(call_id, str):
        name = str(payload.get("name") or "")
        if name in ("exec_command", "shell_command", "shell", "write_stdin"):
            args = json_object(payload.get("arguments"))
            calls[call_id] = ("CommandExecution", {"command": args.get("cmd") or args.get("command") or name})
        elif name.startswith("mcp__"):
            server, _, tool = name[5:].partition("__")
            calls[call_id] = ("McpToolCall", {"server": server, "tool": tool})
    elif kind == "function_call_output" and isinstance(call_id, str) and call_id in calls:
        item_kind, item = calls.pop(call_id)
        output = payload.get("output")
        if item_kind == "CommandExecution":
            item["aggregated_output"] = output
        else:
            item.update(status="completed", result=output)
        return item_kind, item
    return "", {}


def _read_codex_rollout(
    path: Path, extra_redact: RegexPatterns | None, extra_high_signal: RegexPatterns = (), *, scope: Scope | None = None,
) -> tuple[dict, list[dict]]:
    session = {}
    project = None
    rows, failures = [], []
    calls: dict[str, tuple[str, dict]] = {}
    has_completed = False
    raw_lines = 0
    for raw_lines, row in numbered_records(path):
        record_type = row.get("type")
        payload = json_object(row.get("payload"))
        if record_type == "session_meta" and payload and not session:
            session = payload
            if scope is not None:
                project = _codex_project(session.get("cwd"), scope)
                if project is None:
                    break  # Do not parse transcript contents for excluded projects.
            continue
        if scope is not None and not session:
            continue
        if record_type == "event_msg" and payload.get("type") == "item_completed":
            if not has_completed:
                has_completed = True
                rows.clear()
                calls.clear()
            item = json_object(payload.get("item"))
            if isinstance(item.get("type"), str):
                rows.append((raw_lines, item["type"], item))
        elif record_type == "event_msg" and payload.get("type") == "error":
            failures.append((raw_lines, "error", payload))
        elif record_type == "response_item" and not has_completed:
            kind, item = _codex_response_item(payload, calls)
            if kind:
                rows.append((raw_lines, kind, item))

    if failures:
        rows.extend(failures)
        rows.sort(key=lambda row: row[0])
    meta, steps = _codex_steps(rows, extra_redact, extra_high_signal)
    source = session.get("thread_source")
    if not source and (session.get("source") == "subagent" or "subagent" in json_object(session.get("source"))):
        source = "subagent"
    meta.update(
        raw_lines=raw_lines, tid=session.get("id") or path.stem, project=project,
        include_clean=_codex_clean_thread(source, session.get("agent_role")),
    )
    return meta, steps
