"""pi CLI route for gdd's shared runner."""
from agent_run import Route, flags, fold_message_events, message_succeeded


def pi_argv(args, extra):
    """pi has no tool approvals; --no-approve ignores project-local files (repo extensions never run)."""
    return ["--mode", "json", "--no-approve",
            *flags(("--model", args.model), ("--thinking", args.thinking), ("--session", args.resume)), *extra]


ROUTE = Route("pi", "stdin", pi_argv, fold_message_events, "the last assistant message_end stopReason",
              message_succeeded)
