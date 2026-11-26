"""Compare rubric candidates on labeled data and queue unlabeled items for review."""

import json
import random
from collections import Counter, defaultdict
from collections.abc import Callable
from heapq import nsmallest
from pathlib import Path
from typing import Literal

from hoa_cli.config import Endpoint
from hoa_cli.decisions.rubric import confusion_pairs, load_stage, overlap, stage_from_document
from hoa_cli.io import write_jsonl

from .hillclimb_data import output_paths, read_anchors, read_records, record_step
from .hillclimb_scoring import (
    OVERLAP_CUTOFF,
    Prediction,
    excerpt,
    predict,
    score_anchors,
    score_rows,
    validate_scoring,
    validate_threshold,
)

# CLI callers can defer config lookup until their local inputs have been validated.
type EndpointSource = Endpoint | Callable[[], Endpoint]


def stratified_split(
    source: Path, train_out: Path, holdout_out: Path, *,
    holdout_ratio: float = 0.25, seed: int = 42, out_dir: Path | None = None,
) -> dict:
    """Split each class reproducibly, keeping singletons in training."""
    if not 0 < holdout_ratio < 1:
        raise ValueError("--holdout-ratio must be between 0 and 1, exclusive")
    train_out, holdout_out = output_paths(out_dir, (source,), train_out, holdout_out)
    groups = defaultdict(list)
    for row in read_records(source, labeled=True):
        groups[row["expected"]].append(row)
    rng = random.Random(seed)
    train, holdout = [], []
    for label in sorted(groups):
        group = groups[label]
        group.sort(key=lambda row: row["id"])
        rng.shuffle(group)
        count = min(len(group) - 1, max(1, round(holdout_ratio * len(group))))
        holdout.extend(group[:count])
        train.extend(group[count:])
    if not holdout:
        raise ValueError("cannot build a holdout: no label has at least two items")
    write_jsonl(train_out, train)
    write_jsonl(holdout_out, holdout)
    return {"train_count": len(train), "holdout_count": len(holdout)}


def evaluate_dataset(
    rubric: Path, dataset: Path, *, endpoint: EndpointSource, stage: str | None = None,
    mode: Literal["train", "holdout"] = "train", max_errors: int = 10, threshold: float = 0.5,
    beta: float = 0.5, anchors: Path | None = None, check_anchors: bool = False,
) -> tuple[dict, int]:
    """Return metrics and the anchor gate status, hiding all holdout diagnostics."""
    if mode not in ("train", "holdout"):
        raise ValueError("--mode must be train or holdout")
    train = mode == "train"
    try:
        validate_scoring(threshold, beta)
        if max_errors < 0:
            raise ValueError("--max-errors must be non-negative")
        config = load_stage(rubric, stage, require_axes=True)
        rows = read_records(dataset, labeled=True)
        anchor_rows = read_anchors(rubric, config["anchors"], anchors, check_anchors)
        resolved = endpoint() if callable(endpoint) else endpoint
        result = score_rows(rows, config, resolved, threshold=threshold, beta=beta,
                            max_errors=max_errors if train else None)
        if anchor_rows is None:
            return result, 0
        gate = score_anchors(anchor_rows, config, resolved, threshold=threshold, beta=beta)
        if train:
            result["anchors"] = gate
        return result, 0 if gate["passed"] else 1
    except Exception:
        if train:
            raise
    # Do not keep a holdout- or endpoint-bearing exception as context.
    raise ValueError("invalid input or endpoint failure; no holdout diagnostics disclosed")


def run_step(
    baseline: Path, candidate: Path, train: Path, best_out: Path, ledger: Path, *, endpoint: EndpointSource,
    stage: str | None = None, baseline_stage: str | None = None, candidate_stage: str | None = None,
    threshold: float = 0.5, beta: float = 0.5, anchors: Path | None = None, check_anchors: bool = False,
    out_dir: Path | None = None, note: str = "",
) -> dict:
    """Record one training comparison and promote only a strict, anchor-safe improvement."""
    validate_scoring(threshold, beta)
    inputs = (baseline, candidate, train) + ((anchors,) if anchors is not None else ())
    best_out, ledger = output_paths(out_dir, inputs, best_out, ledger)
    candidate_bytes = candidate.read_bytes()
    before_stage = load_stage(baseline, baseline_stage or stage, require_axes=True)
    # Score the same bytes we hash and promote, even if the source is edited during evaluation.
    after_stage = stage_from_document(json.loads(candidate_bytes.decode("utf-8")), candidate_stage or stage,
                                      str(candidate), require_axes=True)
    rows = read_records(train, labeled=True)
    anchor_rows = read_anchors(baseline, before_stage["anchors"], anchors, check_anchors)
    if check_anchors and anchors is None and after_stage["anchors"] != before_stage["anchors"]:
        raise ValueError("candidate changed the locked embedded anchors; use an external --anchors file instead")
    resolved = endpoint() if callable(endpoint) else endpoint
    before = score_rows(rows, before_stage, resolved, threshold=threshold, beta=beta)
    after = score_rows(rows, after_stage, resolved, threshold=threshold, beta=beta)
    passed = True
    if anchor_rows is not None:
        for config, result in ((before_stage, before), (after_stage, after)):
            result["anchors"] = score_anchors(anchor_rows, config, resolved, threshold=threshold, beta=beta)
        passed = after["anchors"]["passed"]
    accepted = passed and after["f_beta"] > before["f_beta"]
    return record_step(ledger, best_out, candidate_bytes, before, after, accepted=accepted, note=note)


def _disagreement(before: Prediction, after: Prediction, threshold: float) -> tuple[float, dict] | None:
    before_binary = before.score >= threshold
    after_binary = after.score >= threshold
    choice_changed = before.choice != after.choice
    if not choice_changed and before_binary == after_binary:
        return None
    choice_gap = min(before.probs.get(before.choice, 0), after.probs.get(after.choice, 0)) if choice_changed else 0
    binary_gap = abs(before.score - after.score) if before_binary != after_binary else 0.0
    return max(choice_gap, binary_gap), {
        "baseline_choice": before.choice, "candidate_choice": after.choice,
        "baseline_positive": before_binary, "candidate_positive": after_binary,
    }


def sample_unlabeled(
    baseline: Path, candidate: Path, pool: Path, *, endpoint: EndpointSource, stage: str | None = None,
    baseline_stage: str | None = None, candidate_stage: str | None = None,
    threshold: float = 0.5, max_items: int = 10,
) -> dict:
    """Rank unlabeled items for review without producing expected labels or evaluation scores."""
    validate_threshold(threshold)
    if max_items < 0:
        raise ValueError("--max-items must be non-negative")
    before_stage = load_stage(baseline, baseline_stage or stage, require_axes=True)
    after_stage = load_stage(candidate, candidate_stage or stage, require_axes=True)
    rows = read_records(pool, labeled=False)
    resolved = endpoint() if callable(endpoint) else endpoint
    left = predict(rows, before_stage, resolved)
    right = predict(rows, after_stage, resolved)
    disagreement, confusion, ood = [], [], []
    pairs = Counter()
    for row, before, after in zip(rows, left, right, strict=True):
        if before is not None and after is not None:
            change = _disagreement(before, after, threshold)
            if change is not None:
                rank, detail = change
                disagreement.append((rank, row, detail))
        item_pairs = {}
        residual = 0.0
        for config, prediction in ((before_stage, before), (after_stage, after)):
            if prediction is None:
                continue
            pair = overlap(prediction.probs, config["routine_labels"], config["novel_label"])
            if pair is not None and pair[1] >= OVERLAP_CUTOFF:
                item_pairs[pair[0]] = max(item_pairs.get(pair[0], 0), pair[1])
            if prediction.anomaly is not None:
                residual = max(residual, prediction.anomaly * prediction.probs.get(config["novel_label"], 0))
        if item_pairs:
            pairs.update(item_pairs.keys())
            pair, strength = min(item_pairs.items(), key=lambda item: (-item[1], item[0]))
            confusion.append((strength, row, {"labels": list(pair)}))
        if residual > 0:
            ood.append((residual, row, {}))

    def packet(items: list) -> list[dict]:
        ranked = nsmallest(max_items, items, key=lambda item: (-item[0], item[1]["id"]))
        return [{**excerpt(row), "priority": rank, **detail} for rank, row, detail in ranked]

    return {
        "disagreement_pool": packet(disagreement),
        "confusion_pool": packet(confusion),
        "ood_pool": packet(ood),
        "confusion_pairs": confusion_pairs(pairs),
    }
