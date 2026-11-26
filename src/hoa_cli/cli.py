import argparse
import re
import sqlite3
import sys

from . import __version__
from .decisions import commands as decisions
from .history import commands as history
from .rubrics import hillclimb_commands as hillclimb
from .rubrics import mining_commands as mining


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hoa", description="Decision rubrics, history mining, and rubric evaluation")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    groups = parser.add_subparsers(dest="group", required=True)
    for module in (decisions, history, mining, hillclimb):
        module.register(groups)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, sqlite3.Error, re.PatternError) as exc:
        label = " ".join(part for part in (args.group, getattr(args, "command", None)) if part)
        detail = ("invalid input or endpoint failure; no holdout diagnostics disclosed"
                  if getattr(args, "mode", None) == "holdout" else str(exc))
        print(f"hoa {label}: {detail}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
