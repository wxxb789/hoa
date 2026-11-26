import math
from collections import Counter
from collections.abc import Iterable

from ..config import Endpoint
from ..decisions.client import evaluate_batch
from ..decisions.responses import is_refusal
from ..decisions.rubric import (
    choice_probabilities, composite_score, confusion_pairs, has_refusal, normalize_score, overlap,
)
from ..history.redact import redact_text

MIN_STRONG_SCORE = 0.675


def _status(judgment: dict) -> str | None:
    if is_refusal(judgment) or is_refusal(judgment.get("error")) or has_refusal(judgment.get("answers") or {}):
        return "model_refusal"
    if not judgment.get("ok"):
        return judgment.get("error") or "request_failed"
    return None


def judge_records(records: list[dict], stage_cfg: dict, endpoint: Endpoint, baseline: str = "") -> list[dict]:
    states = (baseline + redact_text(row["text"]) for row in records)
    results = evaluate_batch(endpoint.base_url, endpoint.model, stage_cfg["questions"], states,
                             workers=endpoint.workers, **endpoint.request_options())
    rows = []
    for row, result in zip(records, results, strict=True):
        if result["ok"]:
            answers = result["answers"]
            for answer in answers.values():
                kind = answer["type"]
                if kind in ("score", "choice"):
                    answer[kind] = answer.pop("value")
            result = {"ok": True, "answers": answers}
            if has_refusal(answers):
                result["reason"] = "model_refusal"
        rows.append({**{key: value for key, value in row.items() if key != "text"}, "judgment": result})
    return rows


def filter_spans(l0_rows: list[dict], spans: Iterable[dict], stage_cfg: dict, *, include_non_pivot: bool = False
                 ) -> tuple[list[dict], dict]:
    score_name = stage_cfg["score_question"]
    question = next(q for q in stage_cfg["questions"] if q["name"] == score_name)
    surviving = set()
    refusals = set()
    pruned = []
    for row in l0_rows:
        sid, judgment = row["id"], row.get("judgment") or {}
        status = _status(judgment)
        if status is not None:
            surviving.add(sid)
            if status == "model_refusal":
                refusals.add(sid)
            continue
        answers = judgment["answers"]
        anomaly = answers.get("anomaly_probe", {}).get("probability", 0.0)
        correction = answers.get("user_correction_probe", {}).get("probability", 0.0)
        answer = answers.get(score_name, {})
        durability = normalize_score(answer.get("value", answer.get("score", 0)), question)
        probs = answers.get(stage_cfg["mech_question"], {}).get("probabilities", {})
        clean = sum(probs.get(label, 0.0) for label in stage_cfg["routine_labels"])
        if anomaly >= 0.20 or correction >= 0.20 or durability >= 0.225 or clean < 0.80 or row.get("hook_errors", 0) > 0:
            surviving.add(sid)
        else:
            pruned.append((max(anomaly, durability), sid))
    selected = [span for span in spans if span["session_id"] in surviving and (span.get("has_pivot") or include_non_pivot)]
    return selected, {"l0_total_sessions": len(l0_rows), "l0_surviving_sessions": len(surviving),
                      "l0_pruned_sessions": len(l0_rows) - len(surviving), "l0_refusal_sessions": len(refusals),
                      "top_pruned_boundary_sessions": [sid for _, sid in sorted(pruned, reverse=True)[:8]],
                      "l1_selected_spans": len(selected)}


def _span_answers(answers: dict, stage: dict, score_question: dict) -> tuple[str, dict, float, float]:
    mechanism = answers[stage["mech_question"]]
    score_answer = answers[score_question["name"]]
    raw_score = score_answer["value"] if "value" in score_answer else score_answer["score"]
    choice = mechanism["value"] if "value" in mechanism else mechanism["choice"]
    return choice, choice_probabilities(mechanism), raw_score, normalize_score(raw_score, score_question)


def select_survivors(scored: Iterable[dict], spans: Iterable[dict], stage_cfg: dict, *, min_score: float = MIN_STRONG_SCORE
                     ) -> list[dict]:
    source = {span["id"]: span for span in spans}
    score_question = next(q for q in stage_cfg["questions"] if q["name"] == stage_cfg["score_question"])
    routine = set(stage_cfg["routine_labels"])
    rows = []
    for row in scored:
        judgment = row.get("judgment") or {}
        if _status(judgment) is not None:
            continue
        choice, _, _, score = _span_answers(judgment["answers"], stage_cfg, score_question)
        if choice not in routine and score >= min_score:
            if row["id"] not in source:
                raise ValueError(f"missing source span for survivor {row['id']!r}")
            rows.append(source[row["id"]])
    return rows


def compute_residuals(scored: list[dict], spans: Iterable[dict], stage_cfg: dict, *, stage: str | None = None,
                      top_k: int = 12) -> dict:
    texts = {span["id"]: span["text"] for span in spans}
    question = next(q for q in stage_cfg["questions"] if q["name"] == stage_cfg["score_question"])
    routine, novel = set(stage_cfg["routine_labels"]), stage_cfg["novel_label"]
    refusals, ood, gray, strong = [], [], [], []
    overlaps = Counter()
    novel_count = 0
    for row in scored:
        sid, judgment = row["id"], row.get("judgment") or {}
        text = texts.get(sid, "")
        if (status := _status(judgment)) is not None:
            refusals.append({"id": sid, "reason": status, "text": text[:800]})
            continue
        answers = judgment["answers"]
        choice, probs, raw_score, score = _span_answers(answers, stage_cfg, question)
        anomaly = answers.get("anomaly_probe", {}).get("probability", 1.0)
        novel_prob = probs.get(novel, 0.0)
        routine_prob = sum(probs.get(label, 0.0) for label in routine)
        best_known = max((value for label, value in probs.items() if label not in routine and label != novel), default=0.0)
        entropy = -sum(p * math.log2(p) for p in probs.values() if p > 1e-9)
        residual = anomaly * (novel_prob + 0.5 * max(0.0, 1.0 - routine_prob - best_known))
        novel_count += choice == novel
        pair = overlap(probs, routine, novel)
        if pair and pair[1] >= 0.18:
            overlaps[pair[0]] += 1
        entry = {"id": sid, "choice": choice, "score": round(raw_score, 3), "p_anomaly": round(anomaly, 3),
                 "p_novel": round(novel_prob, 3), "entropy": round(entropy, 3), "ood_residual": round(residual, 4),
                 "excerpt": text[:900]}
        if anomaly >= 0.45 and (residual >= 0.25 or choice == novel):
            ood.append(entry)
        if anomaly >= 0.80 and (0.25 <= score <= 0.70 or entropy >= 1.50):
            gray.append(entry)
        if score >= MIN_STRONG_SCORE and choice not in routine:
            strong.append(entry)
    ood.sort(key=lambda entry: (-entry["ood_residual"], -entry["entropy"]))
    gray.sort(key=lambda entry: -entry["entropy"])
    strong.sort(key=lambda entry: (-entry["score"], -entry["p_anomaly"]))
    return {"stage": stage, "total_scored": len(scored), "refusal_count": len(refusals),
            "novel_escape_top_choice_count": novel_count, "novel_escape_rate": round(novel_count / max(1, len(scored)), 4),
            "strong_positive_count": len(strong), "ood_pool_top": ood[:top_k], "gray_zone_pool_top": gray[:top_k],
            "refusals": refusals[:top_k], "strong_positives_top": strong[:top_k * 2],
            "confusion_pairs": confusion_pairs(overlaps, top_k)}


def _anchor_scores(stage: dict, anchors: list[dict], endpoint: Endpoint) -> dict:
    results = evaluate_batch(endpoint.base_url, endpoint.model, stage["questions"], (row["text"] for row in anchors),
                             workers=endpoint.workers, **endpoint.request_options())
    positives, negatives, false_negatives, false_positives = [], [], [], []
    refusals, failed = [], []
    for row, result in zip(anchors, results, strict=True):
        status = _status(result)
        if status is not None:
            (refusals if status == "model_refusal" else failed).append(row["id"])
            continue
        score = composite_score(result["answers"], stage)
        if row["expected"]:
            positives.append(score)
            if score < 0.5:
                false_negatives.append(row["id"])
        else:
            negatives.append(score)
            if score >= 0.5:
                false_positives.append(row["id"])
    pos_mean = sum(positives) / len(positives) if positives else None
    neg_mean = sum(negatives) / len(negatives) if negatives else None
    pos_min, neg_max = min(positives, default=None), max(negatives, default=None)
    summary = {"pos_min": pos_min, "pos_mean": pos_mean, "neg_max": neg_max, "neg_mean": neg_mean,
               "mean_margin": pos_mean - neg_mean if positives and negatives else None,
               "worst_case_gap": pos_min - neg_max if positives and negatives else None}
    return {**{key: round(val, 4) if val is not None else None for key, val in summary.items()},
            "false_negatives": false_negatives, "false_positives": false_positives,
            "refusal_count": len(refusals), "refused_anchors": refusals, "failed_anchors": failed}


def anchor_check(baseline: dict, candidate: dict, anchors: list[dict], endpoint: Endpoint) -> dict:
    if not isinstance(anchors, list) or not anchors or not all(
        isinstance(row, dict) and isinstance(row.get("id"), str) and isinstance(row.get("text"), str)
        and type(row.get("expected")) is bool for row in anchors
    ) or {row["expected"] for row in anchors} != {False, True}:
        raise ValueError("anchors must include positive and negative labeled records with an id and text")
    before, after = (_anchor_scores(stage, anchors, endpoint) for stage in (baseline, candidate))
    valid = not any(result[key] for result in (before, after) for key in ("refusal_count", "failed_anchors"))
    passed = (valid and not after["false_negatives"] and not after["false_positives"]
              and after["worst_case_gap"] >= before["worst_case_gap"] - 1e-6)
    return {"passed": passed, "baseline": before, "candidate": after}
