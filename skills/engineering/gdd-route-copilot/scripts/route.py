"""GitHub Copilot CLI route for gdd's shared runner."""
from agent_run import Route, flags


def fold_copilot(acc, event):
    kind, data = event.get("type"), event.get("data") or {}
    if kind in ("session.start", "session.resume"):
        acc["session_id"] = data.get("sessionId") or acc["session_id"]
    elif kind == "assistant.message":
        acc["answer"] = str(data.get("content") or "") or acc["answer"]
    elif kind == "assistant.turn_end":
        acc["turns"] += 1
    elif kind == "tool.execution_start":
        acc["tool_calls"] += 1
    elif kind == "session.error":
        acc["error"] = str(data.get("message") or kind)
    elif kind == "result":
        acc["session_id"] = event.get("sessionId") or acc["session_id"]
        acc["success_marker"] = event.get("exitCode")


def copilot_argv(args, extra):
    return ["--output-format", "json", "--allow-all", "--no-ask-user",
            "--no-eager-powershell-resolution", "--no-auto-update",
            *flags(("--model", args.model), ("--reasoning-effort", args.thinking), ("--resume", args.resume)),
            *extra, "--prompt"]


ROUTE = Route("copilot", "argv", copilot_argv, fold_copilot, "result.exitCode",
              lambda marker: type(marker) is int and marker == 0, windows_native=True)
