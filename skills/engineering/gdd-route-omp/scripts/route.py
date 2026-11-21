"""omp CLI route for gdd's shared runner."""
from agent_run import Route, flags, fold_message_events, message_succeeded


def omp_argv(args, extra):
    return ["-p", "--mode=json", "--approval-mode", "yolo",
            *flags(("--model", args.model), ("--thinking", args.thinking), ("-r", args.resume),
                   ("--profile", args.profile)), *extra]


ROUTE = Route("omp", "argv", omp_argv, fold_message_events, "the last assistant message_end stopReason",
              message_succeeded, legacy=("backend", "profile"))
