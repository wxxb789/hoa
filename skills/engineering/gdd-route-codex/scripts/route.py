"""codex CLI route for gdd's shared runner."""
from agent_run import Route, flags, tokens


def fold_codex(acc, event):
    kind, item = event.get("type"), event.get("item") if isinstance(event.get("item"), dict) else {}
    if kind == "thread.started":
        acc["session_id"] = event.get("thread_id") or acc["session_id"]
    elif kind == "item.completed":
        if item.get("type") == "agent_message":  # under --output-schema the last one is the JSON
            acc["report"], acc["answer"] = acc["answer"] or acc["report"], str(item.get("text") or "")
        acc["tool_calls"] += item.get("type") in ("command_execution", "file_change", "mcp_tool_call", "web_search")
    elif kind == "turn.completed":
        acc["turns"], acc["success_marker"] = acc["turns"] + 1, kind
        usage = tokens(event.get("usage"), "input_tokens", "output_tokens", "cached_input_tokens")
        acc["usage"] = {key: acc["usage"][key] + usage[key] for key in usage}
    elif kind in ("turn.failed", "error"):
        acc["success_marker"] = kind
        acc["error"] = str(event.get("message") or (event.get("error") or {}).get("message") or kind)


DISABLED_FEATURES = (
    "computer_use", "browser_use", "browser_use_external", "in_app_browser", "remote_plugin",
    "image_generation", "skill_search", "plugins", "apps", "memories",
)


def codex_argv(args, extra):
    """Unquoted -c values parse as literal strings, so a Windows `.cmd` shim can carry them too."""
    effort = args.thinking and f"model_reasoning_effort={args.thinking}"
    disabled = [token for feature in DISABLED_FEATURES for token in ("--disable", feature)]
    return ["exec", *(["resume"] if args.resume else []), "--json", "--dangerously-bypass-approvals-and-sandbox",
            *disabled, *flags(("-m", args.model), ("-c", effort), ("--output-schema", args.schema)), *extra,
            *([args.resume] if args.resume else []), "-"]


ROUTE = Route("codex", "stdin", codex_argv, fold_codex, "the last turn event",
              lambda marker: marker == "turn.completed")
