"""opencode CLI route for gdd's shared runner."""
from agent_run import Route, die, flags, sanitize, tokens


def fold_opencode(acc, event):
    """`step_finish` per step; the answer is the text after the last `step_start`; an `error` sticks."""
    kind, part = event.get("type"), event.get("part") if isinstance(event.get("part"), dict) else {}
    acc["session_id"] = acc["session_id"] or str(event.get("sessionID") or "")
    if kind == "step_start":
        acc["answer"] = ""
    elif kind == "text":
        acc["answer"] += str(part.get("text") or "")
    elif kind == "tool_use":
        acc["tool_calls"] += 1
    elif kind == "step_finish":
        acc["turns"] += 1
        acc["success_marker"] = "error" if acc["success_marker"] == "error" else part.get("reason")
        count = part.get("tokens") if isinstance(part.get("tokens"), dict) else {}
        cache = count.get("cache") if isinstance(count.get("cache"), dict) else {}
        usage = tokens({**count, "cache_read": cache.get("read"), "cache_write": cache.get("write")}, "input",
                       "output", "cache_read", "reasoning", "cache_read", "cache_write")
        acc["usage"] = {key: acc["usage"][key] + usage[key] for key in usage}
        if isinstance(part.get("cost"), (int, float)):
            acc["cost_usd"] = round((acc["cost_usd"] or 0) + part["cost"], 6)
    elif kind == "error":
        error = event.get("error") if isinstance(event.get("error"), dict) else {}
        acc["success_marker"], acc["error"] = "error", str(error.get("message") or error.get("type") or "error event")


def opencode_argv(args, extra):
    """--standalone runs a private server inside this process tree, so kill and liveness reach the work."""
    if args.thinking and not args.model:
        die("start: --thinking on the opencode route needs --model (thinking is the #variant suffix)")
    model = args.model and (f"{args.model}#{args.thinking}" if args.thinking else args.model)
    return ["run", "--standalone", "--format", "json", "--auto", "--title", sanitize(args.name),
            *flags(("-s", args.resume), ("-m", model)), *extra]


ROUTE = Route("opencode", "argv", opencode_argv, fold_opencode, "the last step_finish reason",
              lambda marker: marker == "stop")
