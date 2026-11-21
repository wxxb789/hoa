"""omo CLI route for gdd's shared runner."""
from agent_run import Route, flags, fold_message_events, message_succeeded


def omo_argv(args, extra):
    return ["--print", "--mode", "json", "--no-extensions", "--no-ask-user",
            *flags(("--model", args.model), ("--thinking", args.thinking), ("--session", args.resume)), *extra]


ROUTE = Route("omo", "stdin", omo_argv, fold_message_events, "the last assistant message_end stopReason",
              message_succeeded, windows_native=True)
