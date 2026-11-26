import json
import math


class ModelRefusal(ValueError):
    pass


def is_refusal(obj: object) -> bool:
    if isinstance(obj, dict):
        return any(is_refusal(obj.get(key)) for key in ("type", "code", "reason"))
    return obj in ("refusal", "model_refusal", "content_filter")


def _check_payload(payload: dict, source: str) -> None:
    if not isinstance(payload, dict):
        raise ValueError(f"{source} response is not a JSON object")
    error = payload.get("error")
    if is_refusal(payload) or is_refusal(error):
        raise ModelRefusal("model_refusal")
    if error:
        raise ValueError(f"{source} endpoint returned an error payload")


def _number(value: object, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"expected a number in [0, {maximum}]") from exc
    if isinstance(value, bool) or not math.isfinite(number) or not 0 <= number <= maximum:
        raise ValueError(f"expected a number in [0, {maximum}]")
    return number


def _probabilities(answer: dict, key: str, allowed: set[str]) -> dict[str, float]:
    probabilities = {}
    entries = answer.get("probabilities", [])
    if not isinstance(entries, list):
        raise ValueError("probabilities must be an array")
    for entry in entries:
        label = entry.get(key) if isinstance(entry, dict) else None
        if not isinstance(label, str) or label not in allowed or label in probabilities:
            raise ValueError("probabilities contain invalid or duplicate labels")
        probabilities[label] = _number(entry.get("probability"), 1)
    if probabilities and not any(probabilities.values()):
        raise ValueError("probabilities have no mass")
    return probabilities


def _decision_answer(question: dict, answer: dict) -> dict:
    if is_refusal(answer):
        return {"type": "refusal", "value": None}
    kind = question["type"]
    if answer.get("type", kind) != kind:
        raise ValueError(f"answer type does not match question {question['name']!r}")
    if kind == "predicate":
        prob = _number(answer.get("probability"), 1)
        return {"type": kind, "value": prob >= 0.5, "probability": prob}
    confidence = _number(answer.get("confidence", 0), 1)
    if kind == "choice":
        options = {choice["value"] for choice in question["choices"]}
        value = answer.get("choice")
        if not isinstance(value, str) or value not in options:
            raise ValueError(f"invalid choice for question {question['name']!r}")
        return {"type": kind, "value": value, "confidence": confidence,
                "probabilities": _probabilities(answer, "value", options)}
    if kind == "score":
        levels = question["levels"]
        probs = _probabilities(answer, "label", {level["label"] for level in levels})
        return {"type": kind, "value": _number(answer.get("score"), len(levels) - 1),
                "top_label": max(probs, key=probs.get, default=None), "confidence": confidence,
                "probabilities": probs}
    raise ValueError(f"unsupported question type {kind!r}")


def parse_decisions_response(payload: dict, questions: list[dict]) -> dict[str, dict]:
    _check_payload(payload, "decisions")
    raw = payload.get("answers")
    if not isinstance(raw, list) or len(raw) != len(questions):
        actual = len(raw) if isinstance(raw, list) else "no answer array"
        raise ValueError(f"expected {len(questions)} answers, got {actual}")
    if not all(isinstance(answer, dict) for answer in raw):
        raise ValueError("each decision answer must be an object")
    names = [question["name"] for question in questions]
    if any("name" in answer for answer in raw):
        named = {}
        for name, answer in zip(names, raw, strict=True):
            answer_name = answer.get("name", name if is_refusal(answer) else None)
            if not isinstance(answer_name, str) or answer_name in named:
                raise ValueError("decision answers must have unique question names or be positional")
            named[answer_name] = answer
        if named.keys() != set(names):
            raise ValueError("decision answer names do not match questions")
        raw = [named[name] for name in names]
    return {name: _decision_answer(question, answer)
            for name, question, answer in zip(names, questions, raw, strict=True)}


def _chat_answer(question: dict, value: object) -> dict:
    kind, name = question["type"], question["name"]
    if isinstance(value, dict) and is_refusal(value):
        return {"type": "refusal", "value": None}
    if kind == "predicate":
        if not isinstance(value, bool):
            raise ValueError(f"chat answer for {name!r} must be a boolean")
        return {"type": kind, "value": value, "probability": float(value)}
    if kind == "choice":
        if value not in [option["value"] for option in question["choices"]]:
            raise ValueError(f"invalid choice for question {name!r}")
        return {"type": kind, "value": value, "confidence": 1.0, "probabilities": {value: 1.0}}
    if kind == "score":
        levels = [level["label"] for level in question["levels"]]
        if isinstance(value, str) and value in levels:
            value = levels.index(value)
        if type(value) is not int or not 0 <= value < len(levels):
            raise ValueError(f"chat answer for {name!r} must be a valid level index or label")
        return {"type": kind, "value": float(value), "top_label": levels[value], "confidence": 1.0,
                "probabilities": {levels[value]: 1.0}}
    raise ValueError(f"unsupported question type {kind!r}")


def parse_chat_response(payload: dict, questions: list[dict]) -> dict[str, dict]:
    _check_payload(payload, "chat")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ValueError("chat response has no choices")
    first = choices[0]
    message = first.get("message")
    if is_refusal(first.get("finish_reason")) or (isinstance(message, dict) and message.get("refusal")):
        raise ModelRefusal("model_refusal")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise ValueError("chat response has no message content")
    content = content.strip()
    if content.startswith("```"):
        lines = content.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines.pop()
        content = "\n".join(lines)
    try:
        obj = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError("chat response content is not valid JSON") from exc
    _check_payload(obj, "chat content")
    if obj.keys() != {question["name"] for question in questions}:
        raise ValueError("chat answer names do not match questions")
    return {question["name"]: _chat_answer(question, obj[question["name"]]) for question in questions}
