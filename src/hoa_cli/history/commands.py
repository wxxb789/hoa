"""Register local-history extraction and raw evidence commands."""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from .trajectory import SpanNotFound, extract_all, show_evidence


def _extract(args: argparse.Namespace) -> int:
    summary = extract_all(
        args.out_dir,
        claude_roots=args.claude_root or (),
        omp_roots=args.omp_root or (),
        codex_roots=args.codex_root or (),
        include_codex_subagents=args.include_codex_subagents,
        include_memories=args.include_memories,
        dedup_spans=not args.no_dedup_spans,
        min_lines=args.min_lines,
        cursor_file=args.cursor_file,
        allow_regex=args.allow_regex,
        deny_regex=args.deny_regex,
        redact_regexes=args.redact_regex or (),
        extra_high_signal=args.high_signal_regex or (),
        since=args.since,
        max_span_chars=args.max_span_chars,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def _show(args: argparse.Namespace) -> int:
    try:
        for line in show_evidence(
            args.spans, args.ids, context=args.context, max_line_chars=args.max_line_chars,
            output_format=args.format,
        ):
            print(line)
    except SpanNotFound as exc:
        print(f"show: {exc}", file=sys.stderr)
        return 1
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    group = subparsers.add_parser("history", help="extract and inspect local session history")
    history = group.add_subparsers(dest="command", required=True)

    extract = history.add_parser("extract", help="extract redacted L0 skeletons and L1 causal spans")
    extract.add_argument("--claude-root", type=Path, action="append", help="Claude Code projects root (repeatable)")
    extract.add_argument("--omp-root", type=Path, action="append", help="OMP sessions root (repeatable)")
    extract.add_argument("--codex-root", type=Path, action="append", help="Codex history root (repeatable)")
    extract.add_argument("--include-codex-subagents", action="store_true", help="include all Codex subagent roles")
    extract.add_argument("--include-memories", action="store_true",
                         help="also extract redacted Claude and Codex project memories into memories.jsonl")
    extract.add_argument("--no-dedup-spans", action="store_true",
                         help="disable content-hash deduplication of identical spans across branched sessions")
    extract.add_argument("--min-lines", type=int, default=2,
                         help="skip JSONL sessions with at most this many raw lines (default: 2)")
    extract.add_argument("--cursor-file", type=Path,
                         help="read/update an incremental ISO timestamp cursor when --since is omitted")
    extract.add_argument("--allow-regex", help="include matching project names or Codex working directories")
    extract.add_argument("--deny-regex", help="exclude matching project names or Codex working directories")
    extract.add_argument("--redact-regex", action="append", help="extra regex to redact before output")
    extract.add_argument("--high-signal-regex", action="append", help="keep output for additional matching tool commands")
    extract.add_argument(
        "--since", type=datetime.fromisoformat,
        help="ISO date or datetime (naive = local time); keep sessions last modified at or after it",
    )
    extract.add_argument("--max-span-chars", type=int, default=4600, help="target max chars per L1 span")
    extract.add_argument("--out-dir", type=Path, required=True, help="scratch output directory")
    extract.set_defaults(func=_extract)

    show = history.add_parser("show", help="print the raw session lines or Codex SQLite items behind span ids")
    show.add_argument("--spans", type=Path, required=True, help="spans JSONL containing the ids (spans.jsonl or l1-candidates)")
    show.add_argument("--context", type=int, default=0, help="extra lines or ordinals on each side")
    show.add_argument("--max-line-chars", type=int, default=2000, help="truncate each printed line")
    show.add_argument("--format", choices=("raw", "readable"), default="raw",
                      help="raw JSONL lines or readable user/assistant/error text (default: raw)")
    show.add_argument("ids", nargs="+", help="span ids, as printed in residual pools and scored ledgers")
    show.set_defaults(func=_show)
