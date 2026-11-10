#!/usr/bin/env python3
"""Check the composition contract declared by custom skills.

Every skill may declare `metadata.kind` (controller, stage, mechanism, entry)
plus comma-separated `metadata.consumes` / `metadata.produces` artifact names.
The graph is valid only when every consumed artifact has exactly one producer
(or is registered external) and every producer is unambiguous.

Usage:
    python scripts/check_contract_graph.py          # exit 1 on violations
    python scripts/check_contract_graph.py --list   # print the graph
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml
from yaml.nodes import ScalarNode

# A read-only check must not create an import cache beside the parser.
sys.dont_write_bytecode = True
import skill_metadata as sm

ROOT = Path(__file__).resolve().parent.parent
KINDS = ("controller", "stage", "mechanism", "entry")
REGISTRY = Path("scripts") / "contract_graph_registry.yaml"
TRIGGER_CASES = Path("evals") / "trigger-cases.json"
MAX_CONTROLLER_LINES = 120


@dataclass(frozen=True)
class Skill:
    name: str
    path: str
    kind: str | None
    consumes: tuple[str, ...]
    produces: tuple[str, ...]


@dataclass(frozen=True)
class Result:
    skills: tuple[Skill, ...]
    artifacts: frozenset[str]
    violations: tuple[str, ...]


def _artifacts(value: str) -> tuple[str, ...]:
    """Split a comma-separated artifact list, keeping declaration order."""
    return tuple(dict.fromkeys(part.strip() for part in value.split(",") if part.strip()))


def _contract_fields(text: str, source: Path) -> dict[str, str]:
    """Read the optional contract scalars through the shared YAML parser."""
    frontmatter, _ = sm._frontmatter(text, source)
    try:
        root = yaml.compose(frontmatter, Loader=yaml.SafeLoader)
    except yaml.YAMLError as error:
        raise ValueError(f"invalid YAML frontmatter in {source}: {error}") from error
    fields = sm._mapping(root, "frontmatter", source)
    _, metadata = sm._value(root, fields, "metadata", "frontmatter", source)
    metadata_fields = sm._mapping(metadata, "metadata", source)
    values = {}
    for key in ("kind", "consumes", "produces"):
        if key not in metadata_fields:
            continue
        _, value = sm._value(metadata, metadata_fields, key, "metadata", source)
        if not isinstance(value, ScalarNode) or value.tag != sm.STRING:
            raise ValueError(f"metadata.{key} must be a YAML string in {source}")
        values[key] = value.value
    return values


def _load_skills(root: Path) -> tuple[Skill, ...]:
    skills_dir = root / "skills"
    if not skills_dir.is_dir():
        return ()
    skills = []
    for entry in sorted(skills_dir.iterdir()):
        skill_md = entry / "SKILL.md"
        if not entry.is_dir() or entry.name.startswith(".") or not skill_md.is_file():
            continue
        text = skill_md.read_text(encoding="utf-8")
        sm.catalog_metadata(text, skill_md)  # required catalog fields and validation
        contract = _contract_fields(text, skill_md)
        kind = contract["kind"].strip() if "kind" in contract else None
        skills.append(Skill(
            name=entry.name,
            path=skill_md.relative_to(root).as_posix(),
            kind=kind,
            consumes=_artifacts(contract.get("consumes", "")),
            produces=_artifacts(contract.get("produces", "")),
        ))
    return tuple(skills)


def _registry(root: Path) -> tuple[frozenset[str], frozenset[str], tuple[str, ...]]:
    path = root / REGISTRY
    if not path.is_file():
        return frozenset(), frozenset(), ()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a YAML mapping")

    def names(key: str) -> tuple[str, ...]:
        value = data.get(key, [])
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"{path}: {key} must be a list of names")
        return tuple(dict.fromkeys(item.strip() for item in value if item.strip()))

    return (frozenset(names("external")), frozenset(names("shared")),
            names("required_kind"))


def _trigger_cases(root: Path) -> tuple[tuple[str, tuple[str, ...]], ...]:
    path = root / TRIGGER_CASES
    if not path.is_file():
        return ()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{path}: invalid JSON: {error}") from error
    cases = data.get("cases", []) if isinstance(data, dict) else []
    if not isinstance(cases, list):
        raise ValueError(f"{path}: cases must be a list")
    parsed = []
    for index, case in enumerate(cases):
        picks = case.get("must_pick", []) if isinstance(case, dict) else []
        if not isinstance(picks, list):
            raise ValueError(f"{path}: must_pick must be a list in case {index}")
        parsed.append((str(case.get("id", index)), tuple(str(pick) for pick in picks)))
    return tuple(parsed)


def analyze(root: Path | None = None) -> Result:
    root = ROOT if root is None else Path(root)
    skills = _load_skills(root)
    external, shared, required_kind = _registry(root)
    cases = _trigger_cases(root)
    by_name = {skill.name: skill for skill in skills}
    violations: list[str] = []

    for name in required_kind:
        skill = by_name.get(name)
        if skill is None:
            violations.append(f"{REGISTRY.as_posix()}: R7: required_kind names "
                              f"unknown skill {name!r}")
        elif skill.kind is None:
            violations.append(f"{skill.path}: R7: required skill does not declare kind")

    produced: dict[str, list[str]] = {}
    for skill in skills:
        for artifact in skill.produces:
            produced.setdefault(artifact, []).append(skill.name)

    for skill in skills:
        if skill.kind is not None and skill.kind not in KINDS:
            violations.append(f"{skill.path}: R1: invalid kind {skill.kind!r}; "
                              f"expected one of {', '.join(KINDS)}")
        if skill.kind is None and (skill.consumes or skill.produces):
            violations.append(f"{skill.path}: R2: consumes/produces declared without kind")

        known = set(produced) | external
        for artifact in skill.consumes:
            if artifact not in known:
                violations.append(f"{skill.path}: R3: consumed artifact {artifact!r} is neither "
                                  f"produced by a skill nor registered external")

        if skill.kind == "mechanism":
            for case_id, must_pick in cases:
                if skill.name in must_pick:
                    violations.append(f"{skill.path}: R4: mechanism is a must_pick in "
                                      f"trigger case {case_id!r}")

        if skill.kind == "controller":
            if "chain-plan" not in skill.produces:
                violations.append(f"{skill.path}: R5: controller must produce 'chain-plan'")
            for artifact in skill.produces:
                if artifact != "chain-plan":
                    violations.append(f"{skill.path}: R5: controller produces {artifact!r} "
                                      f"in addition to 'chain-plan'")
            line_count = len((root / skill.path).read_text(
                encoding="utf-8").splitlines())
            if line_count > MAX_CONTROLLER_LINES:
                violations.append(f"{skill.path}: R8: controller SKILL.md is "
                                  f"{line_count} lines; cap is {MAX_CONTROLLER_LINES}")

    for artifact, producers in produced.items():
        if len(producers) > 1 and artifact not in shared:
            violations.append(f"{by_name[producers[1]].path}: R6: artifact {artifact!r} "
                              f"produced by multiple skills: {', '.join(producers)}")

    artifacts = frozenset(produced) | external | {
        artifact for skill in skills for artifact in skill.consumes}
    return Result(skills=skills, artifacts=artifacts, violations=tuple(sorted(violations)))


def _shown(values: tuple[str, ...]) -> str:
    return ",".join(values) if values else "-"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="print the contract graph")
    args = parser.parse_args(argv)

    try:
        result = analyze()
    except ValueError as error:
        print(f"check_contract_graph: {error}", file=sys.stderr)
        return 1

    if args.list:
        for skill in result.skills:
            if skill.kind is not None:
                print(f"{skill.name} → {skill.kind} → "
                      f"{_shown(skill.consumes)} → {_shown(skill.produces)}")
        return 0
    if result.violations:
        for violation in result.violations:
            print(violation)
        return 1
    print(f"contract graph: {len(result.skills)} skills, "
          f"{len(result.artifacts)} artifacts, ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
