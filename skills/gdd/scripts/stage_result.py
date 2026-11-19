# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""The gdd stage-result contract: references/stage-result.schema.json, how a result is found in an
agent's answer, and the stdlib subset validator for exactly the keywords that schema uses
(type, enum, required, properties, additionalProperties: false, items).

A result never changes a run's state; gates stay operator-run.
"""
import json
import os
import re

SCHEMA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "references",
                      "stage-result.schema.json")
JSON_TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "object": dict,
              "array": list, "null": type(None)}


def extract(answer, structured):
    """Native structured output, else the whole answer as JSON, else its last ```json block."""
    blocks = re.findall(r"```json[ \t]*\r?\n(.*?)```", answer, re.S)
    for candidate in (structured, answer, *blocks[-1:]):
        try:
            value = candidate if isinstance(candidate, dict) else json.loads(candidate)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            return value
    return None


def error(value, schema, path="$"):
    """The first violation as "<json path>: <problem>", or ""."""
    types = schema.get("type", [])
    types = [types] if isinstance(types, str) else types
    if types and not any(isinstance(value, JSON_TYPES[t]) and not (isinstance(value, bool) and t in ("integer", "number"))
                         for t in types):
        return f"{path}: expected {' or '.join(types)}, got {json.dumps(value)}"
    if "enum" in schema and value not in schema["enum"]:
        return f"{path}: {json.dumps(value)} is not one of {', '.join(map(str, schema['enum']))}"
    problems = []
    if isinstance(value, dict):
        props = schema.get("properties", {})
        problems += [f"{path}: missing {key}" for key in schema.get("required", []) if key not in value]
        if schema.get("additionalProperties") is False:
            problems += [f"{path}: unexpected {key}" for key in value if key not in props]
        problems += [error(item, props[key], f"{path}.{key}") for key, item in value.items() if key in props]
    elif isinstance(value, list) and "items" in schema:
        problems += [error(item, schema["items"], f"{path}[{index}]") for index, item in enumerate(value)]
    return next((problem for problem in problems if problem), "")


def record(run_dir, answer, structured, schema_path):
    """state fields {result: valid|invalid|missing[, result_error]}; writes result.json only when valid."""
    try:
        with open(schema_path, encoding="utf-8") as handle:
            schema = json.load(handle)
    except (OSError, ValueError) as exc:
        return {"result": "invalid", "result_error": f"schema {schema_path} is unreadable: {exc}"}
    result = extract(answer, structured)
    if result is None:
        return {"result": "missing"}
    if problem := error(result, schema):
        return {"result": "invalid", "result_error": problem}
    tmp = os.path.join(run_dir, "result.json.tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, ensure_ascii=False)
    os.replace(tmp, os.path.join(run_dir, "result.json"))
    return {"result": "valid"}
