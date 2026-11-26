"""Register the rubric hillclimb command family."""

import argparse
import json
from functools import partial
from pathlib import Path

from hoa_cli.config import SUPPORTED_APIS, resolve_endpoint

from .hillclimb import evaluate_dataset, run_step, sample_unlabeled, stratified_split


def _endpoint(args: argparse.Namespace):
    return resolve_endpoint(
        "rubric-hillclimb", flag_base_url=args.base_url, flag_model=args.model,
        flag_api=args.api, flag_effort=args.effort, flag_workers=args.workers,
    )


def _emit(result: dict, status: int = 0) -> int:
    print(json.dumps(result, allow_nan=False))
    return status


def _split(args: argparse.Namespace) -> int:
    return _emit(stratified_split(args.input, args.train_out, args.holdout_out,
                                  holdout_ratio=args.holdout_ratio, seed=args.seed, out_dir=args.out_dir))


def _evaluate(args: argparse.Namespace) -> int:
    result, status = evaluate_dataset(
        args.rubric, args.dataset, endpoint=partial(_endpoint, args), stage=args.stage,
        mode=args.mode, max_errors=args.max_errors, threshold=args.threshold, beta=args.beta,
        anchors=args.anchors, check_anchors=args.check_anchors,
    )
    return _emit(result, status)


def _step(args: argparse.Namespace) -> int:
    return _emit(run_step(
        args.baseline, args.candidate, args.train, args.best_out, args.ledger,
        endpoint=partial(_endpoint, args), stage=args.stage, baseline_stage=args.baseline_stage,
        candidate_stage=args.candidate_stage, threshold=args.threshold, beta=args.beta,
        anchors=args.anchors, check_anchors=args.check_anchors, out_dir=args.out_dir, note=args.note,
    ))


def _sample(args: argparse.Namespace) -> int:
    return _emit(sample_unlabeled(
        args.baseline, args.candidate, args.pool, endpoint=partial(_endpoint, args), stage=args.stage,
        baseline_stage=args.baseline_stage, candidate_stage=args.candidate_stage,
        threshold=args.threshold, max_items=args.max_items,
    ))


def _endpoint_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base-url", help="OpenAI-compatible /v1 base URL")
    parser.add_argument("--model", help="endpoint model identifier")
    parser.add_argument("--api", choices=SUPPORTED_APIS, help="wire API (default: decisions)")
    parser.add_argument("--effort", help="chat-completions reasoning effort (default: low)")
    parser.add_argument("--workers", type=int, help="concurrent requests (default: 16)")
    parser.add_argument("--stage", help="stage key for a multi-stage rubric")
    parser.add_argument("--threshold", type=float, default=0.5, help="binary score threshold (default: 0.5)")


def _scoring_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--beta", type=float, default=0.5, help="F-beta weight (default: 0.5)")
    parser.add_argument("--anchors", type=Path, help="locked anchor JSONL or JSON file")
    parser.add_argument("--check-anchors", action="store_true", help="gate on embedded anchors unless --anchors is set")


def _comparison_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--baseline", type=Path, required=True, help="current rubric JSON")
    parser.add_argument("--candidate", type=Path, required=True, help="proposed rubric JSON")
    parser.add_argument("--baseline-stage", help="override --stage for baseline")
    parser.add_argument("--candidate-stage", help="override --stage for candidate")


def _scratch_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--out-dir", type=Path, help="scratch root; resolve relative outputs inside it and reject escapes")


def register(subparsers: argparse._SubParsersAction) -> None:
    group = subparsers.add_parser(
        "hillclimb", help="compare rubric candidates and prioritize unlabeled examples",
        epilog="Exit codes: 0 completed (including a reverted step); "
               "1 anchor gate failed in eval; 2 invalid input or endpoint failure.",
    )
    commands = group.add_subparsers(dest="command", required=True)

    split = commands.add_parser("split", help="stratify a labeled JSONL dataset into train and holdout files")
    split.add_argument("--input", type=Path, required=True)
    split.add_argument("--train-out", type=Path, required=True)
    split.add_argument("--holdout-out", type=Path, required=True)
    split.add_argument("--holdout-ratio", type=float, default=0.25)
    split.add_argument("--seed", type=int, default=42)
    _scratch_flag(split)
    split.set_defaults(func=_split)

    for name, help_text in (("eval", "evaluate labeled data"), ("eval-holdout", "evaluate a blind holdout (aggregates only)")):
        evaluator = commands.add_parser(name, help=help_text)
        _endpoint_flags(evaluator)
        _scoring_flags(evaluator)
        evaluator.add_argument("--rubric", type=Path, required=True)
        evaluator.add_argument("--dataset", type=Path, required=True)
        if name == "eval":
            evaluator.add_argument("--mode", choices=("train", "holdout"), default="train")
            evaluator.add_argument("--max-errors", type=int, default=10,
                                   help="maximum training error excerpts (default: 10)")
        else:
            evaluator.set_defaults(mode="holdout", max_errors=0)
        evaluator.set_defaults(func=_evaluate)

    step = commands.add_parser("step", help="keep a strictly improving training candidate and append a ledger record")
    _endpoint_flags(step)
    _scoring_flags(step)
    _comparison_flags(step)
    _scratch_flag(step)
    step.add_argument("--train", type=Path, required=True)
    step.add_argument("--ledger", type=Path, required=True)
    step.add_argument("--best-out", type=Path, required=True, help="scratch output distinct from baseline and candidate")
    step.add_argument("--note", default="", help="short hypothesis for the ledger")
    step.set_defaults(func=_step)

    sample = commands.add_parser("sample", help="prioritize an unlabeled JSONL pool for human labeling; no scoring")
    _endpoint_flags(sample)
    _comparison_flags(sample)
    sample.add_argument("--pool", type=Path, required=True)
    sample.add_argument("--max-items", type=int, default=10, help="maximum excerpts in each pool (default: 10)")
    sample.set_defaults(func=_sample)
