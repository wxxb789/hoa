"""dsh CLI route for gdd's shared runner."""
import os

from agent_run import Route, die


def fold_dsh(acc, event):
    kind = event.get("type")
    if kind == "session":
        acc["session_id"] = event.get("sessionId") or acc["session_id"]
    elif kind == "tool_call":
        acc["tool_calls"] += 1
    elif kind == "status":
        acc["turns"] += event.get("phase") == "turn_end"
        usage = event.get("usage")
        if isinstance(usage, dict):
            acc["usage"] = {key: int(usage.get(source) or 0) for key, source in (
                ("input_tokens", "inputTokens"), ("output_tokens", "outputTokens"),
                ("cache_read_tokens", "cacheReadTokens"), ("total_tokens", "totalTokens"))}
    elif kind == "text" and acc["success_marker"] is None and event.get("text"):
        acc["answer"] = str(event["text"])
    elif kind == "final":
        acc["answer"] = str(event.get("text") or acc["answer"])
        acc["success_marker"] = (event.get("reason") or {}).get("kind")
    elif kind == "error":
        acc["error"] = str(event.get("message") or "error event")


def dsh_argv(args, extra):
    policy = os.environ.get("DSH_APPROVAL_POLICY") or "never"
    if policy != "never":
        die(f"start: DSH_APPROVAL_POLICY={policy!r} is refused: a detached run has no approval channel")
    argv = ["--profile", os.environ.get("DSH_RUN_PROFILE") or "headless", *extra, "--json"]
    argv += ["--session-id", args.resume] if args.resume else []
    mode = os.environ.get("DSH_PERMISSION_MODE") or "workspace-write"
    return argv + ["--permission-mode", mode, "--approval-policy", "never", "-"]


def prepare(args):
    for field in ("model", "thinking"):
        if getattr(args, field):
            die(f"start: --{field} is not supported on the DSH route")


ROUTE = Route("dsh", "stdin", dsh_argv, fold_dsh, "the last final.reason.kind", lambda marker: marker == "completed",
              scrub_env=("DSH_PROFILE", "DSH_PROFILE_DIR", "DSH_SESSION_ID"),
              prepare=prepare, legacy=("session_id",))
