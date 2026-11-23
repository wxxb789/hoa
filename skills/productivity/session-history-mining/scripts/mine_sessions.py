#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Two-level session transcript miner for Claude Code, OMP, and Codex stores.

Subcommands:
  extract       Extract redacted L0 session skeletons + L1 overlapping causal spans
  judge         Evaluate skeletons or spans with orthogonal /v1/decisions heads
  filter-spans  Select L1 pivot spans belonging to L0-surviving sessions
  residuals     Extract OOD escape-hatch, gray-zone, and refusal pools for reflection
  anchor-check  Verify rubric monotonicity on the locked gold anchor set
  show          Print the raw session lines or Codex SQLite items behind span ids
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, closing
from itertools import batched, groupby, islice
from operator import itemgetter
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import skill_config as sc  # noqa: E402

SKILL = "session-history-mining"
RUBRICS_PATH = HERE / "mining_rubrics.json"
SUPPORTED_APIS = ("decisions", "chat-completions")

SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"), "<REDACTED_GH_TOKEN>"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), "<REDACTED_GH_PAT>"),
    (re.compile(r"sk-[A-Za-z0-9_-]{20,}"), "<REDACTED_SK>"),
    (re.compile(r"AIza[0-9A-Za-z_-]{30,}"), "<REDACTED_API_KEY>"),
    (re.compile(r"(?i)(authorization:\s*bearer\s+)[A-Za-z0-9._-]+"), r"\1<REDACTED_BEARER>"),
    (
        re.compile(r"(?i)(api[_-]?key|token|secret|password)(\s*[:=]\s*['\"]?)[A-Za-z0-9._/-]{16,}"),
        r"\1\2<REDACTED_SECRET>",
    ),
)

HARNESS_FRAME_RE = re.compile(
    r"\[Workflow harness — computed task\].*?The computed task text follows:\s*",
    re.DOTALL,
)
OMP_REMINDER_RE = re.compile(
    r"<system-(?:reminder|notice)>.*?</system-(?:reminder|notice)>\s*",
    re.DOTALL,
)
CODEX_FRAME_RE = re.compile(
    r"^[ \t]*# AGENTS\.md instructions[^\n]*\n\s*(?=<INSTRUCTIONS>)"
    r"|<(INSTRUCTIONS|environment_context)>.*?(?:</\1>|\Z)"
    r"|^[ \t]*# AGENTS\.md instructions.*\Z",
    re.MULTILINE | re.DOTALL,
)
EXIT_ERR_RE = re.compile(r"(?:Exit code|exit status|exited with code)[:\s]+([1-9]\d*)")
HIGH_SIGNAL_CMD_RE = re.compile(
    r"(?i)(memory|AGENTS\.md|CLAUDE\.md|chezmoi|gh\s+pr|git\s+worktree|git\s+branch|paseo|herdr|tmux|nmem|doctor|install|junction|symlink|wsl|hook)"
)


def redact_text(text: str, extra_patterns: list[re.Pattern[str]] | None = None) -> str:
    if not text:
        return ""
    out = HARNESS_FRAME_RE.sub("[Delegated workflow task] ", text)
    for pat, repl in SECRET_PATTERNS:
        out = pat.sub(repl, out)
    if extra_patterns:
        for pat in extra_patterns:
            out = pat.sub("<REDACTED_SCOPE>", out)
    return out


def _text_blocks(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    return str(content or "")


def _summarize_tool(name: str, inp: object) -> str:
    if not isinstance(inp, dict):
        return name
    low = name.lower()
    if low == "bash":
        cmd = str(inp.get("command", "")).strip().replace("\n", " ; ")
        return f"{name}({cmd[:130]})"
    if low in ("read", "edit", "write", "multiedit"):
        fp = str(inp.get("file_path") or inp.get("path") or "")
        return f"{name}({fp[-85:]})"
    if low in ("agent", "task"):
        desc = str(inp.get("description") or inp.get("subagent_type") or inp.get("context") or "")
        return f"{name}({desc[:85].replace(chr(10), ' ')})"
    keys = ",".join(list(inp.keys())[:3])
    return f"{name}({keys})"


def parse_claude_steps(
    path: Path, extra_redact: list[re.Pattern[str]] | None = None
) -> tuple[dict, list[dict]]:
    raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    tool_uses: dict[str, tuple[int, str, str]] = {}
    steps: list[dict] = []
    user_turns = 0
    tool_errors = 0
    hook_errors = 0

    for idx, ln in enumerate(raw_lines, start=1):
        if not ln.strip():
            continue
        try:
            rec = json.loads(ln)
        except json.JSONDecodeError:
            continue
        rtype = rec.get("type")
        if rtype == "system":
            herrs = rec.get("hookErrors") or []
            subtype = rec.get("subtype")
            if herrs:
                hook_errors += len(herrs)
                steps.append(
                    {
                        "line": idx,
                        "pivot": True,
                        "kind": "hook_error",
                        "text": f"[L{idx} HOOK_ERROR] "
                        + redact_text("; ".join(str(x)[:360] for x in herrs), extra_redact),
                    }
                )
            elif rec.get("level") in ("error", "warning") or subtype in ("api_error", "turn_aborted"):
                steps.append(
                    {
                        "line": idx,
                        "pivot": True,
                        "kind": "sys_warn",
                        "text": f"[L{idx} SYS:{subtype}] "
                        + redact_text(str(rec.get("content") or rec.get("error") or "")[:320], extra_redact),
                    }
                )
        elif rtype == "assistant":
            msg = rec.get("message") or {}
            content = msg.get("content")
            if isinstance(content, list):
                for blk in content:
                    if not isinstance(blk, dict):
                        continue
                    btype = blk.get("type")
                    if btype == "tool_use":
                        tid = blk.get("id")
                        tname = str(blk.get("name", "tool"))
                        tsum = _summarize_tool(tname, blk.get("input") or {})
                        if tid:
                            tool_uses[str(tid)] = (idx, tname, tsum)
                    elif btype == "text":
                        txt = str(blk.get("text", "")).strip()
                        if txt:
                            snip = (txt[:360] + " ... " + txt[-260:]) if len(txt) > 660 else txt
                            steps.append(
                                {
                                    "line": idx,
                                    "pivot": False,
                                    "kind": "assistant",
                                    "text": f"[L{idx} ASST] " + redact_text(snip, extra_redact),
                                }
                            )
        elif rtype == "user":
            is_meta = bool(rec.get("isMeta"))
            msg = rec.get("message") or {}
            content = msg.get("content") if isinstance(msg, dict) else rec.get("content")
            if isinstance(content, list):
                for blk in content:
                    if not isinstance(blk, dict):
                        continue
                    btype = blk.get("type")
                    if btype == "tool_result":
                        tid = str(blk.get("tool_use_id") or "")
                        u_line, _, tsum = tool_uses.get(tid, (idx, "tool", "tool"))
                        res_txt = _text_blocks(blk.get("content")).strip()
                        is_err = bool(blk.get("is_error")) or bool(EXIT_ERR_RE.search(res_txt))
                        if is_err:
                            tool_errors += 1
                            snip = res_txt[:340] + (" ... " + res_txt[-220:] if len(res_txt) > 600 else "")
                            steps.append(
                                {
                                    "line": idx,
                                    "pivot": True,
                                    "kind": "tool_error",
                                    "text": f"[L{u_line}->{idx} TOOL_ERR {redact_text(tsum, extra_redact)}] "
                                    + redact_text(snip, extra_redact),
                                }
                            )
                        elif HIGH_SIGNAL_CMD_RE.search(tsum):
                            steps.append(
                                {
                                    "line": idx,
                                    "pivot": False,
                                    "kind": "tool_special",
                                    "text": f"[L{u_line}->{idx} TOOL_OK {redact_text(tsum, extra_redact)}] "
                                    + redact_text(res_txt[:200].replace("\n", " | "), extra_redact),
                                }
                            )
                        else:
                            steps.append(
                                {
                                    "line": idx,
                                    "pivot": False,
                                    "compact_ok": True,
                                    "kind": "tool_ok",
                                    "text": f"[L{u_line} TOOL_OK {redact_text(tsum[:75], extra_redact)}]",
                                }
                            )
                    elif btype == "text" and not is_meta:
                        utxt = str(blk.get("text", "")).strip()
                        if utxt and not utxt.startswith("<local-command"):
                            user_turns += 1
                            steps.append(
                                {
                                    "line": idx,
                                    "pivot": True,
                                    "kind": "user",
                                    "text": f"[L{idx} USER] " + redact_text(utxt[:560], extra_redact),
                                }
                            )
            elif isinstance(content, str) and not is_meta:
                utxt = content.strip()
                if utxt and not utxt.startswith("<local-command"):
                    user_turns += 1
                    steps.append(
                        {
                            "line": idx,
                            "pivot": True,
                            "kind": "user",
                            "text": f"[L{idx} USER] " + redact_text(utxt[:560], extra_redact),
                        }
                    )

    meta = {
        "raw_lines": len(raw_lines),
        "user_turns": user_turns,
        "tool_errors": tool_errors,
        "hook_errors": hook_errors,
        "parent_session": None,
    }
    return meta, steps


def parse_omp_steps(
    path: Path, extra_redact: list[re.Pattern[str]] | None = None
) -> tuple[dict, list[dict]]:
    raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    tool_calls: dict[str, tuple[int, str, str]] = {}
    steps: list[dict] = []
    user_turns = 0
    tool_errors = 0
    parent_session: str | None = None

    for idx, ln in enumerate(raw_lines, start=1):
        if not ln.strip():
            continue
        try:
            rec = json.loads(ln)
        except json.JSONDecodeError:
            continue
        rtype = rec.get("type")
        if rtype == "session":
            if rec.get("parentSession"):
                parent_session = str(rec["parentSession"])
            continue
        if rtype != "message":
            continue
        msg = rec.get("message") or {}
        role = msg.get("role")
        content = msg.get("content")

        if role == "user":
            utxt = OMP_REMINDER_RE.sub("", _text_blocks(content)).strip()
            # Skip synthetic chat-history-summary preamble dumps when mining original user intent
            if utxt.startswith("<chat-history-summary>") and "</chat-history-summary>" in utxt:
                utxt = utxt.split("</chat-history-summary>", 1)[1].strip()
            if utxt:
                user_turns += 1
                steps.append(
                    {
                        "line": idx,
                        "pivot": True,
                        "kind": "user",
                        "text": f"[L{idx} USER] " + redact_text(utxt[:560], extra_redact),
                    }
                )
        elif role == "assistant" and isinstance(content, list):
            for blk in content:
                if not isinstance(blk, dict):
                    continue
                btype = blk.get("type")
                if btype == "toolCall":
                    cid = str(blk.get("id") or "")
                    tname = str(blk.get("name") or "tool")
                    args = blk.get("arguments")
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    tsum = _summarize_tool(tname, args or {})
                    if cid:
                        tool_calls[cid] = (idx, tname, tsum)
                elif btype == "text":
                    txt = str(blk.get("text", "")).strip()
                    if txt:
                        snip = (txt[:360] + " ... " + txt[-260:]) if len(txt) > 660 else txt
                        steps.append(
                            {
                                "line": idx,
                                "pivot": False,
                                "kind": "assistant",
                                "text": f"[L{idx} ASST] " + redact_text(snip, extra_redact),
                            }
                        )
        elif role == "toolResult":
            cid = str(msg.get("toolCallId") or "")
            tname = str(msg.get("toolName") or "tool")
            u_line, _, tsum = tool_calls.get(cid, (idx, tname, tname))
            res_txt = _text_blocks(content).strip()
            is_err = bool(msg.get("isError")) or bool(EXIT_ERR_RE.search(res_txt))
            if is_err:
                tool_errors += 1
                snip = res_txt[:340] + (" ... " + res_txt[-220:] if len(res_txt) > 600 else "")
                steps.append(
                    {
                        "line": idx,
                        "pivot": True,
                        "kind": "tool_error",
                        "text": f"[L{u_line}->{idx} TOOL_ERR {redact_text(tsum, extra_redact)}] "
                        + redact_text(snip, extra_redact),
                    }
                )
            elif HIGH_SIGNAL_CMD_RE.search(tsum):
                steps.append(
                    {
                        "line": idx,
                        "pivot": False,
                        "kind": "tool_special",
                        "text": f"[L{u_line}->{idx} TOOL_OK {redact_text(tsum, extra_redact)}] "
                        + redact_text(res_txt[:200].replace("\n", " | "), extra_redact),
                    }
                )
            else:
                steps.append(
                    {
                        "line": idx,
                        "pivot": False,
                        "compact_ok": True,
                        "kind": "tool_ok",
                        "text": f"[L{u_line} TOOL_OK {redact_text(tsum[:75], extra_redact)}]",
                    }
                )

    meta = {
        "raw_lines": len(raw_lines),
        "user_turns": user_turns,
        "tool_errors": tool_errors,
        "hook_errors": 0,
        "parent_session": parent_session,
    }
    return meta, steps


def _codex_object(raw: object) -> dict:
    if isinstance(raw, (str, bytes)):
        try:
            raw = json.loads(raw)
        except ValueError:
            return {}
    return raw if isinstance(raw, dict) else {}


def _codex_message(content: object, *, user: bool) -> str:
    if isinstance(content, str):
        parts = [content]
    elif isinstance(content, list):
        parts = [
            block if isinstance(block, str) else str(block.get("text") or "")
            for block in content
            if isinstance(block, str) or (
                isinstance(block, dict) and str(block.get("type", "text")).lower() in ("text", "input_text", "output_text")
            )
        ]
    else:
        return ""
    if user:
        parts = [CODEX_FRAME_RE.sub("", part).strip() for part in parts]
    return "\n".join(part for part in parts if part).strip()


def _codex_project(cwd: str | None, allow_re: re.Pattern | None, deny_re: re.Pattern | None) -> str | None:
    cwd = (cwd or "").removeprefix("\\\\?\\")
    project = re.sub(r"[\\/:]+", "-", cwd).strip("-") or "unknown"
    if any(not _dir_allowed(value, None, deny_re) for value in (cwd, project)):
        return None
    return project if any(_dir_allowed(value, allow_re, None) for value in (cwd, project)) else None


def _codex_clean_thread(source: object, role: object) -> bool:
    return source in ("user", None, "") or role in ("worker", "default")


def _codex_steps(
    rows: Iterable[tuple[int, str, object]], extra_redact: list[re.Pattern[str]],
) -> tuple[dict, list[dict]]:
    meta = {"raw_lines": 0, "user_turns": 0, "tool_errors": 0, "hook_errors": 0}
    steps = []
    for line, kind, raw in rows:
        meta["raw_lines"] += 1
        item = _codex_object(raw)
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
            if isinstance(command, list):
                command = " ".join(map(str, command))
            summary = "exec(" + redact_text(str(command), extra_redact).replace("\n", " ; ")[:130] + ")"
            output = str(item.get("aggregatedOutput", item.get("aggregated_output")) or "")
            exit_code = item.get("exitCode", item.get("exit_code"))
            is_error = exit_code not in (0, None) or bool(EXIT_ERR_RE.search(output))
            if exit_code not in (0, None):
                output = f"exit={exit_code} {output}"
            special = bool(HIGH_SIGNAL_CMD_RE.search(str(command)))
        elif kind == "mcptoolcall":
            summary = redact_text(f"{item.get('server') or 'mcp'}.{item.get('tool') or 'tool'}", extra_redact)[:130]
            result = item.get("result")
            status = item.get("status")
            fields = _codex_object(result)
            payload = _codex_object(fields.get("Ok", fields))
            structured = _codex_object(payload.get("structuredContent", payload.get("structured_content")))
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


def _codex_response_item(payload: dict, calls: dict) -> tuple[str, dict]:
    kind, call_id = payload.get("type"), payload.get("call_id")
    if kind == "message" and payload.get("role") in ("user", "assistant"):
        return ("UserMessage" if payload["role"] == "user" else "AgentMessage"), payload
    if kind == "function_call" and isinstance(call_id, str):
        name = str(payload.get("name") or "")
        if name in ("exec_command", "shell_command", "shell", "write_stdin"):
            args = _codex_object(payload.get("arguments"))
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
    path: Path, extra_redact: list[re.Pattern[str]], *,
    scope: tuple[re.Pattern | None, re.Pattern | None] | None = None,
) -> tuple[dict, list[dict]]:
    session = {}
    project = None
    completed, legacy, failures = [], [], []
    calls: dict = {}
    has_completed = False
    raw_lines = 0
    with path.open(encoding="utf-8", errors="replace") as stream:
        for raw_lines, raw in enumerate(stream, start=1):
            row = _codex_object(raw)
            payload = _codex_object(row.get("payload"))
            record_type = row.get("type")
            if scope is not None and not session:
                if record_type == "session_meta" and payload:
                    session = payload
                    project = _codex_project(session.get("cwd"), *scope)
                    if project is None:
                        break  # Do not parse transcript contents for excluded projects.
                continue
            if record_type == "event_msg" and payload.get("type") == "item_completed":
                if not has_completed:
                    has_completed = True
                    legacy.clear()
                    calls.clear()
                item = _codex_object(payload.get("item"))
                if isinstance(item.get("type"), str):
                    completed.append((raw_lines, item["type"], item))
            elif record_type == "event_msg" and payload.get("type") == "error":
                failures.append((raw_lines, "error", payload))
            elif record_type == "response_item" and not has_completed:
                kind, item = _codex_response_item(payload, calls)
                if kind:
                    legacy.append((raw_lines, kind, item))

    rows = completed if has_completed else legacy
    if failures:
        rows = sorted(rows + failures, key=lambda row: row[0])
    meta, steps = _codex_steps(rows, extra_redact)
    source = session.get("thread_source")
    if not source and (session.get("source") == "subagent" or "subagent" in _codex_object(session.get("source"))):
        source = "subagent"
    meta.update(raw_lines=raw_lines, tid=session.get("id") or path.stem, project=project,
                include_clean=_codex_clean_thread(source, session.get("agent_role")))
    return meta, steps


def _compress_clean_streaks(steps: list[dict]) -> list[dict]:
    compressed: list[dict] = []
    ok_buf: list[dict] = []

    def flush() -> None:
        nonlocal ok_buf
        if not ok_buf:
            return
        if len(ok_buf) <= 2:
            compressed.extend(ok_buf)
        else:
            compressed.append(
                {
                    "line": ok_buf[0]["line"],
                    "line_end": ok_buf[-1]["line"],
                    "pivot": False,
                    "kind": "clean_fold",
                    "text": f"[L{ok_buf[0]['line']}-L{ok_buf[-1]['line']}: {len(ok_buf)} clean tool calls]",
                }
            )
        ok_buf = []

    for st in steps:
        if st.get("compact_ok"):
            ok_buf.append(st)
        else:
            flush()
            compressed.append(st)
    flush()
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
    # Build bounded L0 skeleton: keep all pivots (user, tool_error, hook_error, sys_warn), neighbors, head & tail
    if len(compressed) > 50:
        must = [i for i, s in enumerate(compressed) if s.get("pivot")]
        keep = set(must) | {0, len(compressed) - 1}
        for i in must:
            if i > 0:
                keep.add(i - 1)
            if i + 1 < len(compressed):
                keep.add(i + 1)
        sk_steps = [compressed[i] for i in sorted(keep)]
        if len(sk_steps) > 85:
            omitted = len(sk_steps) - 75
            sk_steps = (
                sk_steps[:42]
                + [{"text": f"... [{omitted} middle steps omitted in L0 skeleton] ..."}]
                + sk_steps[-33:]
            )
    else:
        sk_steps = compressed

    header = (
        f"SESSION {session_id} | runtime={runtime} | project={project} | "
        f"raw_lines={meta['raw_lines']} | user_turns={meta['user_turns']} | "
        f"tool_errors={meta['tool_errors']} | hook_errors={meta['hook_errors']}"
    )
    skeleton = {
        "id": session_id,
        "runtime": runtime,
        "project": project,
        "path": locator_path,
        "raw_lines": meta["raw_lines"],
        "user_turns": meta["user_turns"],
        "tool_errors": meta["tool_errors"],
        "hook_errors": meta["hook_errors"],
        "parent_session": meta.get("parent_session"),
        "text": header + "\n" + "\n".join(s["text"] for s in sk_steps),
    }

    spans: list[dict] = []
    cur: list[dict] = []
    cur_len = 0
    for st in compressed:
        tlen = len(st["text"]) + 1
        if cur and cur_len + tlen > max_span_chars and len(cur) >= 5:
            l0, l1 = cur[0]["line"], cur[-1].get("line_end", cur[-1]["line"])
            sp_id = f"{session_id}@L{l0}-{l1}"
            spans.append(
                {
                    "id": sp_id,
                    "session_id": session_id,
                    "runtime": runtime,
                    "project": project,
                    "path": locator_path,
                    "l_start": l0,
                    "l_end": l1,
                    "has_pivot": any(bool(x.get("pivot")) for x in cur),
                    "text": f"SPAN {sp_id}\n" + "\n".join(x["text"] for x in cur),
                }
            )
            cur = cur[-2:]
            cur_len = sum(len(x["text"]) + 1 for x in cur)
        cur.append(st)
        cur_len += tlen

    if cur:
        l0, l1 = cur[0]["line"], cur[-1].get("line_end", cur[-1]["line"])
        sp_id = f"{session_id}@L{l0}-{l1}"
        if not spans or spans[-1]["id"] != sp_id:
            spans.append(
                {
                    "id": sp_id,
                    "session_id": session_id,
                    "runtime": runtime,
                    "project": project,
                    "path": locator_path,
                    "l_start": l0,
                    "l_end": l1,
                    "has_pivot": any(bool(x.get("pivot")) for x in cur),
                    "text": f"SPAN {sp_id}\n" + "\n".join(x["text"] for x in cur),
                }
            )
    return skeleton, spans


def _modified_since(path: Path, since: datetime.datetime | None) -> bool:
    return since is None or path.stat().st_mtime >= since.timestamp()


def _dir_allowed(name: str, allow_re: re.Pattern[str] | None, deny_re: re.Pattern[str] | None) -> bool:
    if deny_re and deny_re.search(name):
        return False
    if allow_re and not allow_re.search(name):
        return False
    return True


def _open_codex_db(stack: ExitStack, path: Path) -> sqlite3.Connection:
    uri = path.resolve().as_uri() + "?mode=ro"
    with path.open("rb") as stream:
        wal_mode = stream.read(20)[18:20] == b"\x02\x02"
    # A mode=ro connection can still create SQLite sidecars in a writable directory.
    use_immutable = wal_mode and not all(Path(f"{path}-{suffix}").exists() for suffix in ("wal", "shm"))
    if not use_immutable:
        try:
            with ExitStack() as opened:
                conn = opened.enter_context(closing(sqlite3.connect(uri, uri=True, timeout=0.1)))
                conn.execute("BEGIN")
                conn.execute("SELECT 1 FROM sqlite_schema LIMIT 1").fetchone()
                stack.enter_context(opened.pop_all())
                return conn
        except sqlite3.OperationalError as exc:
            if (getattr(exc, "sqlite_errorcode", 0) & 0xFF) not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                raise
    print(f"codex: {path}: using immutable read-only view; recent WAL changes may be unavailable", file=sys.stderr)
    return stack.enter_context(closing(sqlite3.connect(uri + "&immutable=1", uri=True)))


def _extract_codex_root(
    root: Path, args: argparse.Namespace, allow_re: re.Pattern | None, deny_re: re.Pattern | None,
    extra_redact: list[re.Pattern[str]], skeletons: list[dict], spans: list[dict],
) -> dict:
    coverage = dict(root=str(root), status="available", included_threads=0, skipped_threads=0,
                    jsonl_backed=0, sqlite_backed=0)
    if not root.is_dir():
        coverage["status"] = "not-found"
        return coverage

    def emit(tid: str, project: str | None, path: str, backing: str, include_clean: bool, meta: dict, steps: list[dict]) -> None:
        if not project or not steps or not (include_clean or args.include_codex_subagents or meta["tool_errors"]):
            coverage["skipped_threads"] += 1
            return
        sk, sps = build_skeleton_and_spans(
            f"codex:{project}:{tid}", "codex", project, path, meta, steps, max_span_chars=args.max_span_chars,
        )
        skeletons.append(sk)
        spans.extend(sps)
        coverage["included_threads"] += 1
        coverage[backing] += 1

    state_path = root / "state_5.sqlite"
    history_path = root / "thread_history_1.sqlite"
    if state_path.is_file() and history_path.is_file():
        with ExitStack() as stack:
            state = _open_codex_db(stack, state_path)
            history = _open_codex_db(stack, history_path)
            pending: dict[str, tuple[str, bool]] = {}
            since_clause, since_params = ("WHERE updated_at >= ? ", (args.since.timestamp(),)) if args.since else ("", ())
            for tid, cwd, rollout_path, source, role in state.execute(
                "SELECT id, cwd, rollout_path, thread_source, agent_role FROM threads "
                f"{since_clause}ORDER BY id", since_params,
            ):
                project = _codex_project(cwd, allow_re, deny_re)
                if project is None:
                    coverage["skipped_threads"] += 1
                    continue
                include_clean = _codex_clean_thread(source, role)
                rollout = root / rollout_path if rollout_path else None
                if rollout is not None and rollout.suffix.lower() == ".jsonl" and rollout.is_file():
                    meta, steps = _read_codex_rollout(rollout, extra_redact)
                    emit(tid, project, str(rollout), "jsonl_backed", include_clean, meta, steps)
                else:
                    pending[tid] = (project, include_clean)

            # Batch even on exports without an index; never rescan history once per thread.
            for batch in batched(tuple(pending), 500):
                placeholders = ",".join("?" for _ in batch)
                rows = history.execute(
                    "SELECT thread_id, rollout_ordinal, item_type, item_json FROM thread_items "
                    f"WHERE thread_id IN ({placeholders}) ORDER BY thread_id, rollout_ordinal ASC", batch,
                )
                for tid, items in groupby(rows, key=itemgetter(0)):
                    project, include_clean = pending.pop(tid)
                    meta, steps = _codex_steps((row[1:] for row in items), extra_redact)
                    emit(tid, project, f"{history_path}#thread={tid}", "sqlite_backed", include_clean, meta, steps)
            coverage["skipped_threads"] += len(pending)
    else:
        for rollout in sorted(root.rglob("rollout-*.jsonl")):
            if not rollout.is_file() or not _modified_since(rollout, args.since):
                continue
            meta, steps = _read_codex_rollout(rollout, extra_redact, scope=(allow_re, deny_re))
            emit(meta["tid"], meta["project"], str(rollout), "jsonl_backed", meta["include_clean"], meta, steps)
    return coverage


def cmd_extract(args: argparse.Namespace) -> int:
    allow_re = re.compile(args.allow_regex) if args.allow_regex else None
    deny_re = re.compile(args.deny_regex) if args.deny_regex else None
    extra_redact = [re.compile(p) for p in (args.redact_regex or [])]
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    skeletons: list[dict] = []
    spans: list[dict] = []
    manifest: dict[str, list[dict]] = {"claude": [], "omp": [], "codex": []}

    for root_str in args.claude_root or []:
        root = Path(root_str).expanduser()
        if not root.exists():
            manifest["claude"].append({"root": str(root), "status": "not-found"})
            continue
        included_dirs = 0
        skipped_dirs = 0
        for proj_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            if not _dir_allowed(proj_dir.name, allow_re, deny_re):
                skipped_dirs += 1
                continue
            included_dirs += 1
            for jf in sorted(proj_dir.glob("*.jsonl")):
                if not _modified_since(jf, args.since):
                    continue
                meta, steps = parse_claude_steps(jf, extra_redact)
                if meta["raw_lines"] <= 2 or not steps:
                    continue
                sid = f"claude:{proj_dir.name}:{jf.stem}"
                sk, sps = build_skeleton_and_spans(
                    sid, "claude-code", proj_dir.name, str(jf), meta, steps, max_span_chars=args.max_span_chars
                )
                skeletons.append(sk)
                spans.extend(sps)
            # Failed workflow subagents
            for jpath in sorted(proj_dir.rglob("journal.jsonl")):
                for ln in jpath.read_text(encoding="utf-8", errors="replace").splitlines():
                    if any(tok in ln for tok in ('"failed"', '"error"', '"aborted"')):
                        try:
                            aid = json.loads(ln).get("agentId")
                        except json.JSONDecodeError:
                            aid = None
                        if not aid:
                            continue
                        ap = jpath.parent / f"agent-{aid}.jsonl"
                        if ap.exists() and _modified_since(ap, args.since):
                            meta, steps = parse_claude_steps(ap, extra_redact)
                            if steps:
                                sid = f"claude-sub:{proj_dir.name}:{ap.stem}"
                                sk, sps = build_skeleton_and_spans(
                                    sid,
                                    "claude-subagent",
                                    proj_dir.name,
                                    str(ap),
                                    meta,
                                    steps,
                                    max_span_chars=args.max_span_chars,
                                )
                                skeletons.append(sk)
                                spans.extend(sps)
        manifest["claude"].append(
            {"root": str(root), "status": "available", "included_dirs": included_dirs, "skipped_dirs": skipped_dirs}
        )

    for root_str in args.omp_root or []:
        root = Path(root_str).expanduser()
        if not root.exists():
            manifest["omp"].append({"root": str(root), "status": "not-found"})
            continue
        included_dirs = 0
        skipped_dirs = 0
        for proj_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            if not _dir_allowed(proj_dir.name, allow_re, deny_re):
                skipped_dirs += 1
                continue
            included_dirs += 1
            for jf in sorted(proj_dir.glob("*.jsonl")):
                if not _modified_since(jf, args.since):
                    continue
                meta, steps = parse_omp_steps(jf, extra_redact)
                if meta["raw_lines"] <= 2 or not steps:
                    continue
                sid = f"omp:{proj_dir.name}:{jf.stem}"
                sk, sps = build_skeleton_and_spans(
                    sid, "omp", proj_dir.name, str(jf), meta, steps, max_span_chars=args.max_span_chars
                )
                skeletons.append(sk)
                spans.extend(sps)
        manifest["omp"].append(
            {"root": str(root), "status": "available", "included_dirs": included_dirs, "skipped_dirs": skipped_dirs}
        )

    for root_str in args.codex_root:
        root = Path(root_str).expanduser()
        try:
            manifest["codex"].append(_extract_codex_root(root, args, allow_re, deny_re, extra_redact, skeletons, spans))
        except (OSError, sqlite3.Error) as exc:
            print(f"codex: {root}: {exc}", file=sys.stderr)
            return 1

    # Deduplicate skeletons by id (in case subagent journal listed same agent twice)
    dedup_sk = list({s["id"]: s for s in skeletons}.values())
    dedup_sp = list({s["id"]: s for s in spans}.values())

    (out_dir / "skeletons.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in dedup_sk) + ("\n" if dedup_sk else ""),
        encoding="utf-8",
    )
    (out_dir / "spans.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in dedup_sp) + ("\n" if dedup_sp else ""),
        encoding="utf-8",
    )
    summary = {
        "since": args.since.isoformat() if args.since else None,
        "skeleton_count": len(dedup_sk),
        "span_count": len(dedup_sp),
        "pivot_span_count": sum(1 for x in dedup_sp if x["has_pivot"]),
        "coverage": manifest,
    }
    (out_dir / "extract-manifest.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def _resolve_endpoint(args: argparse.Namespace) -> tuple[str, str, str, str, int]:
    def get_key(key: str, flag: str | None = None, default: str | None = None) -> str | None:
        val = sc.resolve(SKILL, key, flag=flag)
        if val is not None:
            return str(val)
        for prefix in ("GHC_DECISIONS", "EVALS"):
            env_v = os.environ.get(f"{prefix}_{key.upper()}")
            if env_v:
                return env_v
        return default

    base_url = get_key("base_url", getattr(args, "base_url", None))
    model = get_key("model", getattr(args, "model", None))
    api = get_key("api", getattr(args, "api", None), "decisions") or "decisions"
    api_key = get_key("api_key", None, "dummy") or "dummy"
    workers_s = get_key("workers", str(args.workers) if getattr(args, "workers", None) else None, "16") or "16"
    if not base_url or not model:
        raise ValueError(
            "base_url and model are required (--base-url / SESSION_HISTORY_MINING_BASE_URL or GHC_DECISIONS_BASE_URL, "
            "--model / SESSION_HISTORY_MINING_MODEL or GHC_DECISIONS_MODEL)"
        )
    if api not in SUPPORTED_APIS:
        raise ValueError(f"api must be one of {SUPPORTED_APIS}, got {api!r}")
    parts = urlsplit(base_url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError(f"base_url must be an http(s) URL, got {base_url!r}")
    return base_url, model, api, api_key, max(1, int(workers_s))


def evaluate_state(
    base_url: str,
    model: str,
    api: str,
    api_key: str,
    questions: list[dict],
    state_text: str,
    *,
    retries: int = 2,
) -> dict:
    base = base_url.rstrip("/")
    if api == "decisions":
        url = base if base.endswith("/decisions") else f"{base}/decisions"
        payload = {"model": model, "input": state_text, "questions": questions}
    else:
        url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
        q_desc = []
        for q in questions:
            if q["type"] == "predicate":
                q_desc.append(f'- "{q["name"]}": boolean — {q["instructions"]}')
            elif q["type"] == "choice":
                opts = ", ".join(repr(c["value"]) for c in q["choices"])
                q_desc.append(f'- "{q["name"]}": one of [{opts}] — {q["instructions"]}')
            elif q["type"] == "score":
                lvls = ", ".join(f'{i}={l["label"]!r}' for i, l in enumerate(q["levels"]))
                q_desc.append(f'- "{q["name"]}": integer ({lvls}) — {q["instructions"]}')
        prompt = (
            f"State:\n{state_text}\n\nQuestions:\n"
            + "\n".join(q_desc)
            + "\n\nReply ONLY with a valid JSON object mapping each question name to its value."
        )
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 512,
        }

    raw_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    last_err = ""
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=raw_body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=35) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if api == "decisions":
                parsed: dict[str, dict] = {}
                by_name = {a.get("name"): a for a in data.get("answers", []) if isinstance(a, dict)}
                for idx, q in enumerate(questions):
                    qname = q["name"]
                    ans = by_name.get(qname) or data["answers"][idx]
                    atype = ans.get("type")
                    if atype == "refusal":
                        parsed[qname] = {"type": "refusal"}
                    elif q["type"] == "predicate":
                        p = float(ans["probability"])
                        parsed[qname] = {"type": "predicate", "probability": p, "value": p >= 0.5}
                    elif q["type"] == "choice":
                        probs = {p["value"]: float(p["probability"]) for p in ans.get("probabilities", [])}
                        parsed[qname] = {
                            "type": "choice",
                            "choice": ans["choice"],
                            "confidence": float(ans.get("confidence", 0.0)),
                            "probabilities": probs,
                        }
                    elif q["type"] == "score":
                        probs = {p["label"]: float(p["probability"]) for p in ans.get("probabilities", [])}
                        parsed[qname] = {
                            "type": "score",
                            "score": float(ans["score"]),
                            "confidence": float(ans.get("confidence", 0.0)),
                            "probabilities": probs,
                        }
                return {"ok": True, "answers": parsed}
            else:
                txt = data["choices"][0]["message"]["content"].strip()
                if txt.startswith("```"):
                    lines = txt.splitlines()
                    txt = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:]).strip()
                obj = json.loads(txt)
                parsed = {}
                for q in questions:
                    qname = q["name"]
                    val = obj[qname]
                    if q["type"] == "predicate":
                        b = bool(val)
                        parsed[qname] = {"type": "predicate", "probability": 1.0 if b else 0.0, "value": b}
                    elif q["type"] == "choice":
                        c = str(val)
                        probs = {opt["value"]: (1.0 if opt["value"] == c else 0.0) for opt in q["choices"]}
                        parsed[qname] = {"type": "choice", "choice": c, "confidence": 1.0, "probabilities": probs}
                    elif q["type"] == "score":
                        sc_v = float(val)
                        parsed[qname] = {"type": "score", "score": sc_v, "confidence": 1.0, "probabilities": {}}
                return {"ok": True, "answers": parsed}
        except Exception as exc:
            last_err = str(exc)
            time.sleep(0.3 * (attempt + 1))
    return {"ok": False, "error": last_err}


def _load_rubrics(path_str: str | None) -> dict:
    p = Path(path_str) if path_str else RUBRICS_PATH
    return json.loads(p.read_text(encoding="utf-8"))


def cmd_judge(args: argparse.Namespace) -> int:
    try:
        base_url, model, api, api_key, workers = _resolve_endpoint(args)
    except (sc.ConfigError, ValueError) as err:
        print(f"mine_sessions: {err}", file=sys.stderr)
        return 2

    rubrics = _load_rubrics(args.rubrics)
    stages = rubrics.get("stages", {})
    if args.stage not in stages:
        print(f"mine_sessions: unknown stage {args.stage!r}; expected one of {sorted(stages)}", file=sys.stderr)
        return 2
    questions = stages[args.stage]["questions"]

    baseline_prefix = ""
    if args.baseline_file:
        baseline_prefix = Path(args.baseline_file).read_text(encoding="utf-8").strip() + "\n\n---\n"

    records = [
        json.loads(ln)
        for ln in Path(args.input).read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [
            pool.submit(
                evaluate_state,
                base_url,
                model,
                api,
                api_key,
                questions,
                baseline_prefix + redact_text(rec["text"]),
            )
            for rec in records
        ]
        evals = [f.result() for f in futs]

    out_rows = []
    ok_count = 0
    for rec, ev in zip(records, evals):
        if ev["ok"]:
            ok_count += 1
        row = {k: v for k, v in rec.items() if k != "text"}
        row["judgment"] = ev
        out_rows.append(row)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in out_rows) + ("\n" if out_rows else ""), encoding="utf-8")
    summary = {
        "stage": args.stage,
        "total": len(records),
        "ok": ok_count,
        "failed": len(records) - ok_count,
        "elapsed_s": round(time.perf_counter() - t0, 2),
        "output": str(out_path),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if ok_count == len(records) else 1


def cmd_filter_spans(args: argparse.Namespace) -> int:
    l0_rows = [json.loads(ln) for ln in Path(args.l0).read_text(encoding="utf-8").splitlines() if ln.strip()]
    surviving_sessions: set[str] = set()
    pruned_audit: list[tuple[float, str]] = []

    for row in l0_rows:
        sid = row["id"]
        j = row.get("judgment") or {}
        if not j.get("ok"):
            surviving_sessions.add(sid)
            continue
        ans = j["answers"]
        p_anom = ans.get("anomaly_probe", {}).get("probability", 0.0)
        p_corr = ans.get("user_correction_probe", {}).get("probability", 0.0)
        dur = ans.get("durability", {}).get("score", 0.0)
        probs = ans.get("primary_axis", {}).get("probabilities", {})
        p_clean = probs.get("routine_clean", 0.0) + probs.get("one_off_code_bug", 0.0)
        if p_anom >= 0.20 or p_corr >= 0.20 or dur >= 0.45 or p_clean < 0.80 or row.get("hook_errors", 0) > 0:
            surviving_sessions.add(sid)
        else:
            pruned_audit.append((max(p_anom, dur / 2.0), sid))

    spans = [json.loads(ln) for ln in Path(args.spans).read_text(encoding="utf-8").splitlines() if ln.strip()]
    kept = [
        sp for sp in spans
        if sp["session_id"] in surviving_sessions and (sp.get("has_pivot") or args.include_non_pivot)
    ]
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(json.dumps(s, ensure_ascii=False) for s in kept) + ("\n" if kept else ""), encoding="utf-8")
    pruned_audit.sort(reverse=True)
    print(
        json.dumps(
            {
                "l0_total_sessions": len(l0_rows),
                "l0_surviving_sessions": len(surviving_sessions),
                "l0_pruned_sessions": len(l0_rows) - len(surviving_sessions),
                "top_pruned_boundary_sessions": [sid for _, sid in pruned_audit[:8]],
                "l1_selected_spans": len(kept),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _entropy(probs: dict[str, float]) -> float:
    return -sum(p * math.log2(p) for p in probs.values() if p > 1e-9)


def cmd_residuals(args: argparse.Namespace) -> int:
    rubrics = _load_rubrics(args.rubrics)
    stage_cfg = rubrics["stages"][args.stage]
    mech_q = stage_cfg["mech_question"]
    score_q = stage_cfg["score_question"]
    novel_lbl = stage_cfg["novel_label"]
    routine_lbls = set(stage_cfg["routine_labels"])

    spans_by_id = {
        obj["id"]: obj["text"]
        for ln in Path(args.spans).read_text(encoding="utf-8").splitlines()
        if ln.strip()
        for obj in (json.loads(ln),)
    }
    scored = [json.loads(ln) for ln in Path(args.scored).read_text(encoding="utf-8").splitlines() if ln.strip()]

    refusals: list[dict] = []
    ood_pool: list[dict] = []
    gray_pool: list[dict] = []
    strong_positives: list[dict] = []
    novel_top_count = 0

    for row in scored:
        sid = row["id"]
        j = row.get("judgment") or {}
        if not j.get("ok"):
            refusals.append({"id": sid, "reason": j.get("error", "request_failed"), "text": spans_by_id.get(sid, "")[:800]})
            continue
        ans = j["answers"]
        if any(v.get("type") == "refusal" for v in ans.values()):
            refusals.append({"id": sid, "reason": "model_refusal", "text": spans_by_id.get(sid, "")[:800]})
            continue

        p_anom = ans.get("anomaly_probe", {}).get("probability", 1.0)
        mech = ans[mech_q]
        probs = mech.get("probabilities", {})
        sc_val = ans[score_q]["score"]
        p_novel = probs.get(novel_lbl, 0.0)
        p_routine = sum(probs.get(k, 0.0) for k in routine_lbls)
        max_known = max((v for k, v in probs.items() if k not in routine_lbls and k != novel_lbl), default=0.0)
        ent = _entropy(probs)

        if mech["choice"] == novel_lbl:
            novel_top_count += 1

        ood_res = p_anom * (p_novel + 0.5 * max(0.0, 1.0 - p_routine - max_known))
        entry = {
            "id": sid,
            "choice": mech["choice"],
            "score": round(sc_val, 3),
            "p_anomaly": round(p_anom, 3),
            "p_novel": round(p_novel, 3),
            "entropy": round(ent, 3),
            "ood_residual": round(ood_res, 4),
            "excerpt": spans_by_id.get(sid, "")[:900],
        }
        if p_anom >= 0.45 and (ood_res >= 0.25 or mech["choice"] == novel_lbl):
            ood_pool.append(entry)
        if p_anom >= 0.80 and (0.50 <= sc_val <= 1.40 or ent >= 1.50):
            gray_pool.append(entry)
        if sc_val >= 1.35 and mech["choice"] not in routine_lbls:
            strong_positives.append(entry)

    ood_pool.sort(key=lambda x: (-x["ood_residual"], -x["entropy"]))
    gray_pool.sort(key=lambda x: -x["entropy"])
    strong_positives.sort(key=lambda x: (-x["score"], -x["p_anomaly"]))

    report = {
        "stage": args.stage,
        "total_scored": len(scored),
        "refusal_count": len(refusals),
        "novel_escape_top_choice_count": novel_top_count,
        "novel_escape_rate": round(novel_top_count / max(1, len(scored)), 4),
        "strong_positive_count": len(strong_positives),
        "ood_pool_top": ood_pool[: args.top_k],
        "gray_zone_pool_top": gray_pool[: args.top_k],
        "refusals": refusals[: args.top_k],
        "strong_positives_top": strong_positives[: args.top_k * 2],
    }
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        json.dumps(
            {k: v for k, v in report.items() if not isinstance(v, list)},
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def _score_anchors_for_stage(
    base_url: str, model: str, api: str, api_key: str, workers: int, stage_cfg: dict, anchors: list[dict]
) -> dict:
    questions = stage_cfg["questions"]
    mech_q = stage_cfg["mech_question"]
    score_q = stage_cfg["score_question"]
    routine_lbls = set(stage_cfg["routine_labels"])

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(evaluate_state, base_url, model, api, api_key, questions, a["text"]) for a in anchors]
        res = [f.result() for f in futs]

    pos_vals: list[float] = []
    neg_vals: list[float] = []
    fn: list[str] = []
    fp: list[str] = []
    for anc, ev in zip(anchors, res):
        if not ev["ok"]:
            raise RuntimeError(f"anchor {anc['id']} failed: {ev.get('error')}")
        ans = ev["answers"]
        sc_norm = ans[score_q]["score"] / 2.0
        probs = ans[mech_q].get("probabilities", {})
        p_non_routine = 1.0 - sum(probs.get(k, 0.0) for k in routine_lbls)
        composite = 0.6 * sc_norm + 0.4 * p_non_routine
        if anc["expected"]:
            pos_vals.append(composite)
            if composite < 0.5:
                fn.append(anc["id"])
        else:
            neg_vals.append(composite)
            if composite >= 0.5:
                fp.append(anc["id"])

    return {
        "pos_min": round(min(pos_vals), 4),
        "pos_mean": round(sum(pos_vals) / len(pos_vals), 4),
        "neg_max": round(max(neg_vals), 4),
        "neg_mean": round(sum(neg_vals) / len(neg_vals), 4),
        "mean_margin": round((sum(pos_vals) / len(pos_vals)) - (sum(neg_vals) / len(neg_vals)), 4),
        "worst_case_gap": round(min(pos_vals) - max(neg_vals), 4),
        "false_negatives": fn,
        "false_positives": fp,
    }


def cmd_anchor_check(args: argparse.Namespace) -> int:
    try:
        base_url, model, api, api_key, workers = _resolve_endpoint(args)
    except (sc.ConfigError, ValueError) as err:
        print(f"mine_sessions: {err}", file=sys.stderr)
        return 2

    rubrics = _load_rubrics(args.rubrics)
    anchors = rubrics.get("anchors", [])
    stages = rubrics.get("stages", {})
    m_base = _score_anchors_for_stage(base_url, model, api, api_key, workers, stages[args.baseline_stage], anchors)
    m_cand = _score_anchors_for_stage(base_url, model, api, api_key, workers, stages[args.candidate_stage], anchors)

    passed = (
        len(m_cand["false_negatives"]) == 0
        and len(m_cand["false_positives"]) == 0
        and m_cand["worst_case_gap"] >= m_base["worst_case_gap"] - 1e-6
    )
    out = {
        "passed": passed,
        "baseline_stage": args.baseline_stage,
        "candidate_stage": args.candidate_stage,
        "baseline": m_base,
        "candidate": m_cand,
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if passed else 1


def cmd_show(args: argparse.Namespace) -> int:
    wanted = set(args.ids)
    spans: dict[str, dict] = {}
    with open(args.spans, encoding="utf-8") as stream:
        for ln in stream:
            if ln.strip():
                sp = json.loads(ln)
                if sp["id"] in wanted:
                    spans[sp["id"]] = sp

    def clip(text: str) -> str:
        extra = len(text) - args.max_line_chars
        return text if extra <= 0 else f"{text[: args.max_line_chars]} ... [+{extra} chars]"

    for span_id in args.ids:
        sp = spans.get(span_id)
        if sp is None:
            print(f"show: span id not found in {args.spans}: {span_id}", file=sys.stderr)
            return 1
        db_path, sep, thread_id = sp["path"].partition("#thread=")
        start, end = max(0 if sep else 1, sp["l_start"] - args.context), sp["l_end"] + args.context
        print(f"== {span_id} | {sp['path']} | {'ordinal' if sep else 'L'}{start}-{end}")
        if sep:
            with ExitStack() as stack:
                rows = _open_codex_db(stack, Path(db_path)).execute(
                    "SELECT rollout_ordinal, item_type, item_json FROM thread_items "
                    "WHERE thread_id = ? AND rollout_ordinal BETWEEN ? AND ? ORDER BY rollout_ordinal",
                    (thread_id, start, end),
                )
                for ordinal, item_type, item_json in rows:
                    print(clip(f"{ordinal}\t{item_type}\t{item_json}"))
        else:
            with open(sp["path"], encoding="utf-8", errors="replace") as stream:
                for line_no, raw in enumerate(islice(stream, start - 1, end), start=start):
                    print(clip(f"L{line_no}\t{raw.rstrip()}"))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    p_ext = sub.add_parser("extract", help="extract redacted L0 skeletons and L1 causal spans")
    p_ext.add_argument("--claude-root", action="append", default=[], help="Claude Code projects root (repeatable)")
    p_ext.add_argument("--omp-root", action="append", default=[], help="OMP sessions root (repeatable)")
    p_ext.add_argument("--codex-root", action="append", default=[], help="Codex history root (repeatable)")
    p_ext.add_argument("--include-codex-subagents", action="store_true", help="include all Codex subagent roles")
    p_ext.add_argument("--allow-regex", default=None, help="include matching project names or Codex working directories")
    p_ext.add_argument("--deny-regex", default=None, help="exclude matching project names or Codex working directories")
    p_ext.add_argument("--redact-regex", action="append", default=[], help="extra regex to redact before output")
    p_ext.add_argument(
        "--since", type=datetime.datetime.fromisoformat, default=None,
        help="ISO date or datetime (naive = local time); keep sessions last modified at or after it",
    )
    p_ext.add_argument("--max-span-chars", type=int, default=4600, help="target max chars per L1 span")
    p_ext.add_argument("--out-dir", required=True, help="scratch output directory")
    p_ext.set_defaults(func=cmd_extract)

    def add_endpoint_flags(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--base-url", default=None, help="OpenAI-compatible /v1 base URL")
        sp.add_argument("--model", default=None, help="decision model ID")
        sp.add_argument("--api", default=None, help="wire API: decisions or chat-completions")
        sp.add_argument("--workers", type=int, default=None, help="concurrent HTTP workers")
        sp.add_argument("--rubrics", default=None, help="path to rubrics JSON file")

    p_jdg = sub.add_parser("judge", help="score JSONL skeletons or spans with /v1/decisions")
    add_endpoint_flags(p_jdg)
    p_jdg.add_argument("--stage", required=True, help="stage key in rubrics JSON (l0, l1-v1, l1-v2, l3-novelty)")
    p_jdg.add_argument("--baseline-file", default=None, help="optional markdown baseline prepended for l3-novelty")
    p_jdg.add_argument("--input", required=True, help="input JSONL (skeletons or spans)")
    p_jdg.add_argument("--output", required=True, help="output scored JSONL")
    p_jdg.set_defaults(func=cmd_judge)

    p_flt = sub.add_parser("filter-spans", help="filter L1 spans to L0-surviving sessions")
    p_flt.add_argument("--l0", required=True, help="L0 scored JSONL")
    p_flt.add_argument("--spans", required=True, help="extracted spans.jsonl")
    p_flt.add_argument("--include-non-pivot", action="store_true", help="keep spans without user/error pivots")
    p_flt.add_argument("--output", required=True, help="filtered spans JSONL")
    p_flt.set_defaults(func=cmd_filter_spans)

    p_res = sub.add_parser("residuals", help="extract OOD, gray-zone, and refusal pools from scored spans")
    p_res.add_argument("--stage", default="l1-v1", help="stage key used to score")
    p_res.add_argument("--rubrics", default=None, help="path to rubrics JSON")
    p_res.add_argument("--scored", required=True, help="scored spans JSONL")
    p_res.add_argument("--spans", required=True, help="candidate spans JSONL with text")
    p_res.add_argument("--top-k", type=int, default=12, help="max items per residual pool")
    p_res.add_argument("--output", required=True, help="output residuals JSON")
    p_res.set_defaults(func=cmd_residuals)

    p_anc = sub.add_parser("anchor-check", help="verify candidate rubric monotonicity on locked gold anchors")
    add_endpoint_flags(p_anc)
    p_anc.add_argument("--baseline-stage", default="l1-v1", help="baseline stage name")
    p_anc.add_argument("--candidate-stage", default="l1-v2", help="candidate stage name")
    p_anc.set_defaults(func=cmd_anchor_check)

    p_show = sub.add_parser("show", help="print the raw session lines or Codex SQLite items behind span ids")
    p_show.add_argument("--spans", required=True, help="spans JSONL containing the ids (spans.jsonl or l1-candidates)")
    p_show.add_argument("--context", type=int, default=0, help="extra lines or ordinals on each side")
    p_show.add_argument("--max-line-chars", type=int, default=2000, help="truncate each printed line")
    p_show.add_argument("ids", nargs="+", help="span ids, as printed in residual pools and scored ledgers")
    p_show.set_defaults(func=cmd_show)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
