"""claude CLI route for gdd's shared runner."""
import json
import uuid

from agent_run import Route, flags, read_json, text_parts, tokens


def fold_claude(acc, event):
    kind, message = event.get("type"), event.get("message") if isinstance(event.get("message"), dict) else {}
    if kind == "system" and event.get("subtype") == "init":
        acc["session_id"] = event.get("session_id") or acc["session_id"]
    elif kind == "assistant":
        blocks = [b for b in message.get("content") or [] if isinstance(b, dict)]
        acc["tool_calls"] += sum(b.get("type") == "tool_use" and b.get("name") != "StructuredOutput" for b in blocks)
        acc["answer"] = acc["report"] = text_parts(blocks) or acc["answer"]
    elif kind == "result":
        ok = event.get("subtype") == "success" and event.get("is_error") is False
        acc["success_marker"] = "success" if ok else str(event.get("terminal_reason") or event.get("subtype"))
        acc["answer"], acc["structured"] = str(event.get("result") or acc["answer"]), event.get("structured_output")
        acc["turns"], acc["error"] = int(event.get("num_turns") or 0), "" if ok else acc["answer"]
        acc["usage"] = tokens(event.get("usage"), "input_tokens", "output_tokens", "cache_read_input_tokens",
                              "cache_read_input_tokens", "cache_creation_input_tokens")
        cost = event.get("total_cost_usd")
        acc["cost_usd"] = round(cost, 6) if isinstance(cost, (int, float)) else acc["cost_usd"]


def claude_argv(args, extra):
    session = ["--resume", args.resume] if args.resume else ["--session-id", str(uuid.uuid4())]
    schema = args.schema and json.dumps(read_json(args.schema), separators=(",", ":"))
    return ["-p", "--output-format", "stream-json", "--verbose", "--permission-mode", "bypassPermissions", *session,
            *flags(("--model", args.model), ("--effort", args.thinking), ("--json-schema", schema)), *extra]


ROUTE = Route("claude", "stdin", claude_argv, fold_claude, "the result event outcome",
              lambda marker: marker == "success")
