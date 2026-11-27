import argparse
import json
from pathlib import Path
from time import perf_counter

from ..config import Endpoint, resolve_endpoint
from ..decisions.rubric import DEFAULT_MINING_RUBRICS, load_stage, stage_from_document
from ..io import iter_jsonl, read_json, read_jsonl, write_json, write_jsonl
from .mining import (
    DEFAULT_BASELINE_FILE_CHARS, DEFAULT_BASELINE_MAX_CHARS, MIN_STRONG_SCORE,
    anchor_check, build_baseline, compute_residuals, filter_spans, judge_records, select_survivors,
)
from .comparison import (
    DEFAULT_HEAD_CONFLICT_PREDICATE, DEFAULT_MIN_PRIORITY, DEFAULT_TAXONOMY_MIN_INCIDENT,
    compute_disagreements,
)


def _endpoint(args: argparse.Namespace) -> Endpoint:
    return resolve_endpoint(
        "hoa-practice-mine", args.base_url, args.model, args.api, args.effort, args.workers,
        fallback_prefixes=("SESSION_HISTORY_MINING", "RUBRIC_JUDGE", "GHC_DECISIONS", "EVALS"),
    )


def _report(value: dict) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def _judge(args: argparse.Namespace) -> int:
    endpoint = _endpoint(args)
    stage = load_stage(args.rubrics, args.stage)
    baseline = args.baseline_file.read_text(encoding="utf-8").strip() + "\n\n---\n" if args.baseline_file else ""
    records = read_jsonl(args.input)
    start = perf_counter()
    rows = judge_records(records, stage, endpoint, baseline)
    write_jsonl(args.output, rows)
    ok = sum(row["judgment"].get("ok") and row["judgment"].get("reason") != "model_refusal" for row in rows)
    refused = sum(row["judgment"].get("reason") == "model_refusal" for row in rows)
    failed = sum(not row["judgment"].get("ok") for row in rows)
    _report({"stage": args.stage, "total": len(rows), "ok": ok, "refused": refused, "failed": failed,
             "elapsed_s": round(perf_counter() - start, 2), "output": str(args.output)})
    return int(failed != 0)


def _filter(args: argparse.Namespace) -> int:
    stage = load_stage(args.rubrics, args.stage, require_axes=True)
    rows, report = filter_spans(
        read_jsonl(args.l0), iter_jsonl(args.spans), stage,
        include_non_pivot=args.include_non_pivot,
        min_anomaly=args.min_anomaly, min_correction=args.min_correction,
        min_durability=args.min_durability, max_clean=args.max_clean,
        strict=args.strict,
    )
    write_jsonl(args.output, rows)
    _report(report)
    return 0


def _select(args: argparse.Namespace) -> int:
    if not 0 <= args.min_score <= 1:
        raise ValueError("--min-score must be in [0, 1]")
    if args.min_anomaly is not None and not 0 <= args.min_anomaly <= 1:
        raise ValueError("--min-anomaly must be in [0, 1]")
    stage = load_stage(args.rubrics, args.stage, require_axes=True)
    rows = select_survivors(
        iter_jsonl(args.scored), iter_jsonl(args.spans), stage,
        min_score=args.min_score, min_anomaly=args.min_anomaly,
    )
    write_jsonl(args.output, rows)
    _report({"stage": args.stage, "selected_spans": len(rows), "output": str(args.output)})
    return 0


def _residuals(args: argparse.Namespace) -> int:
    if args.top_k < 0:
        raise ValueError("--top-k must be non-negative")
    stage = load_stage(args.rubrics, args.stage, require_axes=True)
    report = compute_residuals(read_jsonl(args.scored), iter_jsonl(args.spans), stage, stage=args.stage, top_k=args.top_k)
    write_json(args.output, report)
    _report({key: value for key, value in report.items() if not isinstance(value, list)})
    return 0


def _anchors(args: argparse.Namespace) -> int:
    root = read_json(args.rubrics)
    before, after = (stage_from_document(root, stage, str(args.rubrics), require_axes=True)
                     for stage in (args.baseline_stage, args.candidate_stage))
    anchors = before.get("anchors")
    report = anchor_check(before, after, anchors, _endpoint(args))
    _report({"baseline_stage": args.baseline_stage, "candidate_stage": args.candidate_stage, **report})
    return int(not report["passed"])


def _baseline(args: argparse.Namespace) -> int:
    text, report = build_baseline(args.repo, max_chars=args.max_chars, per_file_chars=args.per_file_chars)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8", newline="\n")
    _report({**report, "output": str(args.output)})
    return 0


def _disagreements(args: argparse.Namespace) -> int:
    predicate_question = args.predicate
    choice_question = args.choice
    routine_labels = args.routine_label or []
    score_question = args.score
    score_max = args.score_max
    if args.stage:
        stage = load_stage(args.rubrics, args.stage, require_axes=True)
        by_name = {q["name"]: q for q in stage["questions"]}
        if predicate_question is None and "anomaly_probe" in by_name:
            predicate_question = "anomaly_probe"
        choice_question = choice_question or stage["mech_question"]
        if not routine_labels:
            routine_labels = list(stage["routine_labels"])
        if score_question is None:
            score_question = stage["score_question"]
        if score_max is None and score_question in by_name:
            score_max = float(max(1, len(by_name[score_question]["levels"]) - 1))
    if not choice_question:
        raise ValueError("supply --stage or --choice to identify the mechanism choice head")
    if not routine_labels:
        raise ValueError("supply --stage or at least one --routine-label")
    if score_max is None:
        score_max = 2.0
    spans = iter_jsonl(args.spans) if args.spans else ()
    report = compute_disagreements(
        read_jsonl(args.left),
        read_jsonl(args.right),
        predicate_question=predicate_question,
        choice_question=choice_question,
        routine_labels=routine_labels,
        score_question=score_question,
        score_max=score_max,
        spans=spans,
        left_label=args.left_label or args.left.stem,
        right_label=args.right_label or args.right.stem,
        min_priority=args.min_priority,
        head_conflict_predicate=args.head_conflict_predicate,
        taxonomy_min_incident=args.taxonomy_min_incident,
        top_k=args.top_k,
    )
    write_json(args.output, report)
    _report({
        "labels": report["labels"],
        "coverage": report["coverage"],
        "pool_counts": report["pool_counts"],
        "profiles": report["profiles"],
        "output": str(args.output),
    })
    return 0


def _rubric_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--rubrics", type=Path, default=DEFAULT_MINING_RUBRICS, help="override the bundled mining rubrics")


def _endpoint_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base-url", help="OpenAI-compatible /v1 base URL")
    parser.add_argument("--model", help="endpoint model identifier")
    parser.add_argument("--api", help="decisions or chat-completions (default: decisions)")
    parser.add_argument("--effort", help="chat-completions reasoning effort (default: low)")
    parser.add_argument("--workers", type=int, help="concurrent requests (default: 16)")
    _rubric_flag(parser)


def register(subparsers: argparse._SubParsersAction) -> None:
    mine = subparsers.add_parser("mine", help="judge and filter mined session data")
    commands = mine.add_subparsers(dest="command", required=True)
    judge = commands.add_parser("judge", help="score JSONL skeletons or spans")
    _endpoint_flags(judge)
    judge.add_argument("--stage", required=True, help="rubric stage (l0, l1-v1, l1-v2, l3-novelty)")
    judge.add_argument("--baseline-file", type=Path, help="baseline to prepend for novelty scoring")
    judge.add_argument("--input", type=Path, required=True, help="input JSONL with text")
    judge.add_argument("--output", type=Path, required=True, help="scored JSONL output")
    judge.set_defaults(func=_judge)

    filter_cmd = commands.add_parser("filter-spans", help="keep pivot spans from L0-surviving sessions")
    _rubric_flag(filter_cmd)
    filter_cmd.add_argument("--stage", default="l0", help="stage used to score L0")
    filter_cmd.add_argument("--l0", type=Path, required=True, help="L0 scored JSONL")
    filter_cmd.add_argument("--spans", type=Path, required=True, help="extracted spans JSONL")
    filter_cmd.add_argument("--include-non-pivot", action="store_true", help="also keep spans without evidence pivots")
    filter_cmd.add_argument("--min-anomaly", type=float, default=0.20, help="minimum anomaly_probe probability")
    filter_cmd.add_argument("--min-correction", type=float, default=0.20, help="minimum user_correction_probe probability")
    filter_cmd.add_argument("--min-durability", type=float, default=0.225, help="minimum normalized durability score")
    filter_cmd.add_argument("--max-clean", type=float, default=0.80, help="retain when routine probability is below this")
    filter_cmd.add_argument("--strict", action="store_true",
                            help="require (anomaly AND durability) OR correction OR hook_errors for stronger L0 pruning")
    filter_cmd.add_argument("--output", type=Path, required=True, help="filtered spans JSONL output")
    filter_cmd.set_defaults(func=_filter)

    for name, description, stage, handler in (
        ("select-survivors", "restore source text to strong non-routine survivors", "l1-v2", _select),
        ("residuals", "rank OOD, gray-zone, refusal and confusion pools", "l1-v1", _residuals),
    ):
        command = commands.add_parser(name, help=description)
        _rubric_flag(command)
        command.add_argument("--stage", default=stage, help="stage used to score the spans")
        command.add_argument("--scored", type=Path, required=True, help="scored spans JSONL")
        command.add_argument("--spans", type=Path, required=True, help="source spans JSONL with text")
        command.add_argument("--output", type=Path, required=True)
        if name == "select-survivors":
            command.add_argument("--min-score", type=float, default=MIN_STRONG_SCORE, help="minimum normalized score")
            command.add_argument("--min-anomaly", type=float, default=None,
                                 help="override minimum anomaly_probe probability (default: stage survivor_min_anomaly if declared)")
        else:
            command.add_argument("--top-k", type=int, default=12, help="maximum items per residual pool")
        command.set_defaults(func=handler)

    disagree = commands.add_parser(
        "disagreements",
        help="offline cross-model or cross-rubric disagreement pool over two scored JSONL ledgers",
    )
    _rubric_flag(disagree)
    disagree.add_argument("--stage", help="rubric stage to infer head names, routine labels, and score scale")
    disagree.add_argument("--left", type=Path, required=True, help="left scored JSONL ledger")
    disagree.add_argument("--right", type=Path, required=True, help="right scored JSONL ledger")
    disagree.add_argument("--spans", type=Path, help="optional source spans JSONL to attach excerpts")
    disagree.add_argument("--left-label", help="display label for left ledger (default: left filename stem)")
    disagree.add_argument("--right-label", help="display label for right ledger (default: right filename stem)")
    disagree.add_argument("--predicate", help="predicate question name (inferred from stage anomaly_probe if omitted)")
    disagree.add_argument("--choice", help="choice question name (inferred from stage mech_question if omitted)")
    disagree.add_argument("--routine-label", action="append", help="routine/negative choice label (repeatable; inferred from stage)")
    disagree.add_argument("--score", help="optional score question name (inferred from stage score_question if omitted)")
    disagree.add_argument("--score-max", type=float, help="maximum raw score value for normalization (inferred from stage or 2.0)")
    disagree.add_argument("--min-priority", type=float, default=DEFAULT_MIN_PRIORITY,
                          help="minimum max(|delta_incident|, |delta_survivor|) to enter directional pools")
    disagree.add_argument("--head-conflict-predicate", type=float, default=DEFAULT_HEAD_CONFLICT_PREDICATE,
                          help="predicate threshold for head-conflict diagnostic pool")
    disagree.add_argument("--taxonomy-min-incident", type=float, default=DEFAULT_TAXONOMY_MIN_INCIDENT,
                          help="minimum incident mass on both sides for taxonomy_split_top")
    disagree.add_argument("--top-k", type=int, default=20, help="maximum items per disagreement pool")
    disagree.add_argument("--output", type=Path, required=True, help="output disagreement report JSON")
    disagree.set_defaults(func=_disagreements)

    anchors = commands.add_parser("anchor-check", help="check rubric monotonicity on locked anchors")
    _endpoint_flags(anchors)
    anchors.add_argument("--baseline-stage", default="l1-v1")
    anchors.add_argument("--candidate-stage", default="l1-v2")
    anchors.set_defaults(func=_anchors)

    baseline = commands.add_parser("baseline", help="assemble a redacted rules baseline from target repos for l3-novelty")
    baseline.add_argument("--repo", type=Path, action="append", required=True, help="target repository root (repeatable)")
    baseline.add_argument("--max-chars", type=int, default=DEFAULT_BASELINE_MAX_CHARS, help="total character budget")
    baseline.add_argument("--per-file-chars", type=int, default=DEFAULT_BASELINE_FILE_CHARS, help="max chars per file")
    baseline.add_argument("--output", type=Path, required=True, help="output baseline markdown path")
    baseline.set_defaults(func=_baseline)
