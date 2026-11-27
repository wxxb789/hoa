"""Offline cross-model or cross-rubric disagreement pool over two scored JSONL ledgers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from ..decisions.responses import is_refusal
from ..decisions.rubric import choice_probabilities, has_refusal, summarize_distribution

DEFAULT_MIN_PRIORITY = 0.25
DEFAULT_HEAD_CONFLICT_PREDICATE = 0.80
DEFAULT_TAXONOMY_MIN_INCIDENT = 0.50


def _extract_answers(row: Mapping[str, object]) -> tuple[dict | None, str | None]:
    """Return (answers_dict, failure_reason) supporting both mine-judge and flat-ledger rows."""
    judgment = row.get("judgment")
    if isinstance(judgment, Mapping):
        if is_refusal(judgment) or is_refusal(judgment.get("error")):
            return None, "model_refusal"
        if not judgment.get("ok"):
            return None, str(judgment.get("error") or "request_failed")
        answers = judgment.get("answers")
        if not isinstance(answers, Mapping):
            return None, "missing_answers"
        if has_refusal(answers):
            return None, "model_refusal"
        return dict(answers), None

    answers = row.get("answers")
    if isinstance(answers, Mapping):
        if has_refusal(answers):
            return None, "model_refusal"
        return dict(answers), None
    if row.get("ok") is False:
        return None, str(row.get("error") or "request_failed")
    return None, "missing_answers"


def _index_ledger(rows: Iterable[dict], side: str) -> dict[str, dict]:
    indexed: dict[str, dict] = {}
    for row in rows:
        sid = row.get("id")
        if not isinstance(sid, str) or not sid:
            raise ValueError(f"{side} ledger row missing non-empty string 'id'")
        if sid in indexed:
            raise ValueError(f"{side} ledger has duplicate id {sid!r}")
        indexed[sid] = row
    return indexed


def _side_metrics(
    answers: Mapping[str, dict],
    *,
    predicate_question: str | None,
    choice_question: str,
    routine_labels: set[str],
    score_question: str | None,
    score_max: float,
    side: str,
    sid: str,
) -> dict:
    if choice_question not in answers:
        raise ValueError(f"{side} row {sid!r} missing choice question {choice_question!r}")
    choice_ans = answers[choice_question]
    if choice_ans.get("type") not in (None, "choice"):
        raise ValueError(f"{side} row {sid!r} question {choice_question!r} is not a choice")
    choice_val = choice_ans["value"] if "value" in choice_ans else choice_ans.get("choice")
    if not isinstance(choice_val, str) or not choice_val:
        raise ValueError(f"{side} row {sid!r} choice {choice_question!r} missing label")
    probs = choice_probabilities(choice_ans)
    p_routine = sum(probs.get(label, 0.0) for label in routine_labels)
    p_nonroutine = min(1.0, max(0.0, 1.0 - p_routine))
    top_prob = probs.get(choice_val, 0.0)

    p_pred: float | None = None
    if predicate_question:
        if predicate_question not in answers:
            raise ValueError(f"{side} row {sid!r} missing predicate question {predicate_question!r}")
        pred_ans = answers[predicate_question]
        if pred_ans.get("type") not in (None, "predicate"):
            raise ValueError(f"{side} row {sid!r} question {predicate_question!r} is not a predicate")
        raw_p = pred_ans.get("probability")
        if not isinstance(raw_p, (int, float)):
            raise ValueError(f"{side} row {sid!r} predicate {predicate_question!r} missing numeric probability")
        p_pred = float(raw_p)

    raw_score: float | None = None
    norm_score: float | None = None
    if score_question:
        if score_question not in answers:
            raise ValueError(f"{side} row {sid!r} missing score question {score_question!r}")
        score_ans = answers[score_question]
        if score_ans.get("type") not in (None, "score"):
            raise ValueError(f"{side} row {sid!r} question {score_question!r} is not a score")
        val = score_ans["value"] if "value" in score_ans else score_ans.get("score")
        if not isinstance(val, (int, float)):
            raise ValueError(f"{side} row {sid!r} score {score_question!r} missing numeric value")
        raw_score = float(val)
        norm_score = min(1.0, max(0.0, raw_score / score_max))

    p_eff = p_pred if p_pred is not None else 1.0
    incident = p_eff * p_nonroutine
    survivor = incident * (norm_score if norm_score is not None else 1.0)
    return {
        "choice": choice_val,
        "choice_prob": round(top_prob, 4),
        "p_nonroutine": round(p_nonroutine, 4),
        "p_predicate": round(p_pred, 4) if p_pred is not None else None,
        "score": round(raw_score, 4) if raw_score is not None else None,
        "norm_score": round(norm_score, 4) if norm_score is not None else None,
        "incident_mass": incident,
        "survivor_mass": survivor,
    }


def _public_side(metrics: dict) -> dict:
    return {
        "choice": metrics["choice"],
        "choice_prob": metrics["choice_prob"],
        "p_nonroutine": metrics["p_nonroutine"],
        "p_predicate": metrics["p_predicate"],
        "score": metrics["score"],
        "incident_mass": round(metrics["incident_mass"], 4),
        "survivor_mass": round(metrics["survivor_mass"], 4),
    }


def compute_disagreements(
    left_rows: list[dict],
    right_rows: list[dict],
    *,
    predicate_question: str | None,
    choice_question: str,
    routine_labels: Iterable[str],
    score_question: str | None = None,
    score_max: float = 2.0,
    spans: Iterable[dict] = (),
    left_label: str = "left",
    right_label: str = "right",
    min_priority: float = DEFAULT_MIN_PRIORITY,
    head_conflict_predicate: float = DEFAULT_HEAD_CONFLICT_PREDICATE,
    taxonomy_min_incident: float = DEFAULT_TAXONOMY_MIN_INCIDENT,
    top_k: int = 20,
) -> dict:
    """Pair two scored ledgers by id and rank continuous mass disagreements + head conflicts."""
    if top_k < 0:
        raise ValueError("top_k must be non-negative")
    if score_max <= 0:
        raise ValueError("score_max must be positive")
    for name, value in (
        ("min_priority", min_priority),
        ("head_conflict_predicate", head_conflict_predicate),
        ("taxonomy_min_incident", taxonomy_min_incident),
    ):
        if not 0 <= value <= 1:
            raise ValueError(f"{name} must be in [0, 1]")
    routine = set(routine_labels)
    left_by_id = _index_ledger(left_rows, "left")
    right_by_id = _index_ledger(right_rows, "right")
    source = {span["id"]: span for span in spans}

    left_only_ids = sorted(left_by_id.keys() - right_by_id.keys())
    right_only_ids = sorted(right_by_id.keys() - left_by_id.keys())
    shared_ids = sorted(left_by_id.keys() & right_by_id.keys())

    left_refusals = right_refusals = left_failed = right_failed = valid_pairs = 0
    left_only_pool: list[tuple[float, str, dict]] = []
    right_only_pool: list[tuple[float, str, dict]] = []
    taxonomy_split_pool: list[tuple[float, str, dict]] = []
    head_conflict_pool: list[tuple[float, str, dict]] = []

    for sid in shared_ids:
        l_row, r_row = left_by_id[sid], right_by_id[sid]
        l_ans, l_err = _extract_answers(l_row)
        r_ans, r_err = _extract_answers(r_row)
        if l_err is not None:
            if l_err == "model_refusal":
                left_refusals += 1
            else:
                left_failed += 1
        if r_err is not None:
            if r_err == "model_refusal":
                right_refusals += 1
            else:
                right_failed += 1
        if l_ans is None or r_ans is None:
            continue

        valid_pairs += 1
        lm = _side_metrics(
            l_ans,
            predicate_question=predicate_question,
            choice_question=choice_question,
            routine_labels=routine,
            score_question=score_question,
            score_max=score_max,
            side="left",
            sid=sid,
        )
        rm = _side_metrics(
            r_ans,
            predicate_question=predicate_question,
            choice_question=choice_question,
            routine_labels=routine,
            score_question=score_question,
            score_max=score_max,
            side="right",
            sid=sid,
        )

        delta_inc = rm["incident_mass"] - lm["incident_mass"]
        delta_surv = rm["survivor_mass"] - lm["survivor_mass"]
        priority = max(abs(delta_inc), abs(delta_surv))
        signed_dom = delta_inc if abs(delta_inc) >= abs(delta_surv) else delta_surv

        span = source.get(sid) or {}
        base_entry = {
            "id": sid,
            "runtime": l_row.get("runtime") or r_row.get("runtime") or span.get("runtime"),
            "project": l_row.get("project") or r_row.get("project") or span.get("project"),
            "priority": round(priority, 4),
            "delta_incident": round(delta_inc, 4),
            "delta_survivor": round(delta_surv, 4),
            "left": _public_side(lm),
            "right": _public_side(rm),
        }
        if span.get("text"):
            base_entry["excerpt"] = span["text"][:900]

        if priority >= min_priority:
            if signed_dom > 0:
                right_only_pool.append((-priority, sid, base_entry))
            elif signed_dom < 0:
                left_only_pool.append((-priority, sid, base_entry))

        if (
            lm["incident_mass"] >= taxonomy_min_incident
            and rm["incident_mass"] >= taxonomy_min_incident
            and lm["choice"] != rm["choice"]
            and lm["choice"] not in routine
            and rm["choice"] not in routine
        ):
            split_rank = min(lm["choice_prob"], rm["choice_prob"])
            taxonomy_split_pool.append((-split_rank, sid, base_entry))

        l_conflict = lm["p_predicate"] is not None and lm["p_predicate"] >= head_conflict_predicate and lm["choice"] in routine
        r_conflict = rm["p_predicate"] is not None and rm["p_predicate"] >= head_conflict_predicate and rm["choice"] in routine
        if l_conflict or r_conflict:
            conflict_sides = [name for name, flag in ((left_label, l_conflict), (right_label, r_conflict)) if flag]
            conflict_p = max(
                lm["p_predicate"] if l_conflict and lm["p_predicate"] is not None else 0.0,
                rm["p_predicate"] if r_conflict and rm["p_predicate"] is not None else 0.0,
            )
            conflict_entry = {**base_entry, "conflict_sides": conflict_sides, "conflict_predicate": round(conflict_p, 4)}
            head_conflict_pool.append((-conflict_p, sid, conflict_entry))

    left_only_pool.sort(key=lambda item: (item[0], item[1]))
    right_only_pool.sort(key=lambda item: (item[0], item[1]))
    taxonomy_split_pool.sort(key=lambda item: (item[0], item[1]))
    head_conflict_pool.sort(key=lambda item: (item[0], item[1]))

    if (left_by_id or right_by_id) and valid_pairs == 0:
        raise ValueError("no valid paired rows between left and right ledgers")

    return {
        "labels": {"left": left_label, "right": right_label},
        "policy": {
            "predicate_question": predicate_question,
            "choice_question": choice_question,
            "routine_labels": sorted(routine),
            "score_question": score_question,
            "score_max": score_max,
            "min_priority": min_priority,
            "head_conflict_predicate": head_conflict_predicate,
            "taxonomy_min_incident": taxonomy_min_incident,
            "top_k": top_k,
        },
        "coverage": {
            "left_total": len(left_by_id),
            "right_total": len(right_by_id),
            "shared_ids": len(shared_ids),
            "valid_pairs": valid_pairs,
            "left_only_missing_ids": len(left_only_ids),
            "right_only_missing_ids": len(right_only_ids),
            "left_refusals": left_refusals,
            "right_refusals": right_refusals,
            "left_failed": left_failed,
            "right_failed": right_failed,
        },
        "profiles": {
            "left": summarize_distribution(
                left_rows,
                predicate_question=predicate_question,
                choice_question=choice_question,
                score_question_name=score_question,
                score_max=score_max,
                routine_labels=routine,
            ),
            "right": summarize_distribution(
                right_rows,
                predicate_question=predicate_question,
                choice_question=choice_question,
                score_question_name=score_question,
                score_max=score_max,
                routine_labels=routine,
            ),
        },
        "pool_counts": {
            "left_only": len(left_only_pool),
            "right_only": len(right_only_pool),
            "taxonomy_split": len(taxonomy_split_pool),
            "head_conflict": len(head_conflict_pool),
        },
        "left_only_top": [entry for _, _, entry in left_only_pool[:top_k]],
        "right_only_top": [entry for _, _, entry in right_only_pool[:top_k]],
        "taxonomy_split_top": [entry for _, _, entry in taxonomy_split_pool[:top_k]],
        "head_conflict_top": [entry for _, _, entry in head_conflict_pool[:top_k]],
    }
