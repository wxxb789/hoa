import math
from collections.abc import Collection, Mapping
from pathlib import Path

from ..io import read_json
from .responses import is_refusal

_DATA = Path(__file__).resolve().parents[1] / "data"
DEFAULT_PRESETS = _DATA / "presets.json"
DEFAULT_MINING_RUBRICS = _DATA / "mining.json"


def _object(obj: object, source: str) -> dict:
    if not isinstance(obj, dict):
        raise ValueError(f"{source}: expected an object")
    return obj


def _questions(config: dict, source: str) -> dict[str, dict]:
    questions = config.get("questions")
    if not isinstance(questions, list) or not questions:
        raise ValueError(f"{source}: questions must be a non-empty array")
    by_name = {}
    for question in questions:
        q = _object(question, f"{source}: question")
        name, kind = q.get("name"), q.get("type")
        if not isinstance(name, str) or not name or name in by_name:
            raise ValueError(f"{source}: question names must be non-empty and unique")
        if kind not in ("predicate", "choice", "score") or not isinstance(q.get("instructions"), str):
            raise ValueError(f"{source}: {name} needs a supported type and string instructions")
        if kind in ("choice", "score"):
            field, key = ("choices", "value") if kind == "choice" else ("levels", "label")
            options = q.get(field)
            if (not isinstance(options, list) or not options or any(
                not isinstance(opt, dict) or not isinstance(opt.get(key), str) or not opt[key] for opt in options
            ) or len({opt[key] for opt in options}) != len(options)):
                raise ValueError(f"{source}: {name}.{field} needs distinct, non-empty {key} strings")
        by_name[name] = q
    return by_name


def load_presets(path: Path | None = None) -> dict[str, dict]:
    path = path or DEFAULT_PRESETS
    root = _object(read_json(path), str(path))
    presets = _object(root.get("presets"), f"{path}: presets")
    if not presets:
        raise ValueError(f"{path}: presets must not be empty")
    for name, preset in presets.items():
        source = f"{path}: preset {name!r}"
        _questions(_object(preset, source), source)
    return presets


def _validate_axes(cfg: dict, by_name: dict[str, dict], source: str) -> None:
    mech = cfg.get("mech_question")
    for field, kind in (("mech_question", "choice"), ("score_question", "score")):
        name = cfg.get(field)
        if not isinstance(name, str) or by_name.get(name, {}).get("type") != kind:
            raise ValueError(f"{source}: {field} must name a {kind} question")
    if "anomaly_probe" in by_name and by_name["anomaly_probe"]["type"] != "predicate":
        raise ValueError(f"{source}: anomaly_probe must be a predicate")
    labels = [opt["value"] for opt in by_name[mech]["choices"]]
    routine, novel = cfg.get("routine_labels"), cfg.get("novel_label")
    if not isinstance(routine, list) or any(label not in labels for label in routine):
        raise ValueError(f"{source}: routine_labels must be an array of mechanism labels")
    if novel not in labels or novel in routine:
        raise ValueError(f"{source}: novel_label must name a non-routine mechanism label")


def stage_from_document(root: object, stage: str | None, source: str, *, require_axes: bool = False) -> dict:
    root = _object(root, source)
    config = root
    if "stages" in root:
        stages = _object(root["stages"], f"{source}: stages")
        if not stages:
            raise ValueError(f"{source}: stages must not be empty")
        if stage is None and len(stages) == 1:
            stage = next(iter(stages))
        if stage not in stages:
            raise ValueError(f"{source}: supply --stage with one of {', '.join(stages)}")
        config = _object(stages[stage], f"{source}: stage {stage!r}")
    by_name = _questions(config, source)
    if require_axes:
        _validate_axes(config, by_name, source)
        config = {**config, "routine_labels": list(dict.fromkeys(config["routine_labels"]))}
    return {**config, "anchors": config.get("anchors", root.get("anchors"))}


def load_stage(path: Path, stage: str | None = None, *, require_axes: bool = False) -> dict:
    return stage_from_document(read_json(path), stage, str(path), require_axes=require_axes)


def normalize_score(raw_score: float, question_def: dict) -> float:
    return float(raw_score) / max(1, len(question_def["levels"]) - 1)


def has_refusal(answers: Mapping[str, dict]) -> bool:
    return any(is_refusal(answer) for answer in answers.values())


def _value(answer: dict, old_key: str) -> object:
    return answer["value"] if "value" in answer else answer[old_key]


def choice_probabilities(answer: dict) -> dict[str, float]:
    probabilities = answer.get("probabilities") or {}
    total = sum(probabilities.values())
    if not total:
        return {_value(answer, "choice"): 1.0}
    return ({label: p / total for label, p in probabilities.items()} if total != 1 else probabilities)


def composite_score(answers: Mapping[str, dict], stage_cfg: dict) -> float | None:
    if has_refusal(answers):
        return None
    score_name = stage_cfg["score_question"]
    question = next(q for q in stage_cfg["questions"] if q["name"] == score_name)
    score = normalize_score(_value(answers[score_name], "score"), question)
    probs = choice_probabilities(answers[stage_cfg["mech_question"]])
    nonroutine = 1 - sum(probs.get(label, 0) for label in stage_cfg["routine_labels"])
    return min(1.0, max(0.0, 0.6 * score + 0.4 * nonroutine))


def overlap(probabilities: Mapping[str, float], routine_labels: Collection[str], novel_label: str
            ) -> tuple[tuple[str, str], float] | None:
    ranked = sorted(probabilities.items(), key=lambda item: (-item[1], item[0]))
    if len(ranked) < 2 or ranked[1][1] <= 0:
        return None
    (a, pa), (b, pb) = ranked[:2]
    if a in routine_labels or b in routine_labels or novel_label in (a, b):
        return None
    share = pb / (pa + pb)
    entropy = -share * math.log2(share) - (1 - share) * math.log2(1 - share)
    return tuple(sorted((a, b))), entropy * pb


def confusion_pairs(counts: Mapping[tuple[str, str], int], limit: int = 10) -> list[dict]:
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    return [{"labels": list(pair), "count": count} for pair, count in ranked]
