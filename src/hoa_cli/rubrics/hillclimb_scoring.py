"""Turn shared decision answers into hillclimb predictions and metrics."""

import math
from collections import Counter
from dataclasses import dataclass
from heapq import nsmallest

from hoa_cli.config import Endpoint
from hoa_cli.decisions.client import evaluate_batch
from hoa_cli.decisions.rubric import choice_probabilities, composite_score, confusion_pairs, overlap

EXCERPT_CHARS = 300
OVERLAP_CUTOFF = 0.18


@dataclass(frozen=True, slots=True)
class Prediction:
    choice: str
    score: float
    probs: dict[str, float]
    anomaly: float | None


def validate_threshold(threshold: float) -> None:
    if not 0 <= threshold <= 1:
        raise ValueError("--threshold must be in [0, 1]")


def validate_scoring(threshold: float, beta: float) -> None:
    validate_threshold(threshold)
    if not math.isfinite(beta) or beta <= 0:
        raise ValueError("--beta must be positive and finite")


def predict(rows: list[dict], stage: dict, endpoint: Endpoint) -> list[Prediction | None]:
    results = evaluate_batch(
        endpoint.base_url, endpoint.model, stage["questions"], (row["text"] for row in rows),
        workers=endpoint.workers, retries=0, **endpoint.request_options(),
    )
    predictions = []
    for result in results:
        if not result["ok"]:
            raise ValueError(result["error"])
        answers = result["answers"]
        score = composite_score(answers, stage)
        if score is None:
            predictions.append(None)
            continue
        mechanism = answers[stage["mech_question"]]
        probe = answers.get("anomaly_probe")
        predictions.append(Prediction(
            mechanism["value"], score, choice_probabilities(mechanism),
            probe["probability"] if probe is not None else None,
        ))
    return predictions


def excerpt(row: dict) -> dict:
    return {"id": row["id"], "text": row["text"][:EXCERPT_CHARS]}


def _f_beta(precision: float, recall: float, beta: float) -> float:
    if not precision or not recall:
        return 0.0
    beta_squared = beta * beta
    if beta_squared > 1:
        # Divide through by beta squared to keep otherwise finite inputs finite.
        weight = 1 / beta_squared
        return (1 + weight) * precision * recall / (precision + weight * recall)
    return (1 + beta_squared) * precision * recall / (beta_squared * precision + recall)


def score_rows(
    rows: list[dict], stage: dict, endpoint: Endpoint, *, threshold: float, beta: float, max_errors: int | None = None,
) -> dict:
    predictions = predict(rows, stage, endpoint)
    binary = isinstance(rows[0]["expected"], bool)
    tp = fp = fn = refusals = 0
    low_positive = high_negative = None
    pairs = Counter()
    errors = []
    for row, prediction in zip(rows, predictions, strict=True):
        want = row["expected"]
        if prediction is None:
            actual = None
            refusals += 1
        else:
            actual = prediction.score >= threshold if binary else prediction.choice
        wrong = actual != want
        if binary:
            tp += want and actual is True
            fn += want and wrong
            fp += not want and wrong
            score = prediction.score if prediction is not None else float(not want)
            if want:
                low_positive = score if low_positive is None else min(low_positive, score)
            else:
                high_negative = score if high_negative is None else max(high_negative, score)
        else:
            tp += not wrong
            fn += wrong
            fp += wrong and prediction is not None
        if prediction is not None:
            pair = overlap(prediction.probs, stage["routine_labels"], stage["novel_label"])
            if pair and (wrong or pair[1] >= OVERLAP_CUTOFF):
                pairs[pair[0]] += 1
        if max_errors and wrong:
            if prediction is None:
                severity = 1.0
            elif binary:
                severity = abs(prediction.score - threshold)
            else:
                severity = prediction.probs.get(actual, 0)
            errors.append((severity, row["id"], row, actual, prediction))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    result = {
        "precision": precision,
        "recall": recall,
        "f_beta": _f_beta(precision, recall, beta),
        "worst_case_gap": low_positive - high_negative if low_positive is not None and high_negative is not None else None,
        "false_negatives": fn,
        "false_positives": fp,
        "confusion_pairs": confusion_pairs(pairs),
        "refusal_count": refusals,
    }
    if max_errors is not None:
        result["error_samples"] = [
            {**excerpt(row), "expected": row["expected"], "predicted": actual,
             **({"reason": "model_refusal"} if prediction is None else {"score": prediction.score})}
            for _, _, row, actual, prediction in nsmallest(max_errors, errors, key=lambda item: (-item[0], item[1]))
        ]
    return result


def score_anchors(rows: list[dict], stage: dict, endpoint: Endpoint, *, threshold: float, beta: float) -> dict:
    gate = score_rows(rows, stage, endpoint, threshold=threshold, beta=beta)
    gate["passed"] = not any(gate[key] for key in ("false_negatives", "false_positives", "refusal_count"))
    return gate
