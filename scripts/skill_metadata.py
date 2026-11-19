#!/usr/bin/env python3
"""Read custom-skill catalog metadata from SKILL.md YAML frontmatter.

PyYAML supplies the parsed nodes, so duplicate, merge and aliased keys are
rejected instead of silently resolved. Install dependencies with
scripts/requirements.txt.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml
from yaml.nodes import MappingNode, ScalarNode

REVISION = re.compile(r"[1-9][0-9]*")
STRING = "tag:yaml.org,2002:str"
MAPPING = "tag:yaml.org,2002:map"


def _frontmatter(text: str, source: Path) -> tuple[str, int]:
    start = 1 if text.startswith("\ufeff") else 0
    lines = text[start:].splitlines(keepends=True)
    if not lines or lines[0].rstrip() != "---":
        raise ValueError(f"missing YAML frontmatter in {source}")
    offset = start + len(lines[0])
    end = offset
    for line in lines[1:]:
        if line.rstrip() == "---":
            return text[offset:end], offset
        end += len(line)
    raise ValueError(f"unterminated YAML frontmatter in {source}")


def _mapping(node, location: str, source: Path) -> dict:
    if not isinstance(node, MappingNode) or node.tag != MAPPING:
        raise ValueError(f"{location} must be a YAML mapping in {source}")
    fields = {}
    previous = -1
    for key, value in node.value:
        if not isinstance(key, ScalarNode) or key.tag != STRING or key.value == "<<":
            raise ValueError(f"ambiguous/merge key in {location} in {source}")
        if key.value in fields:
            raise ValueError(f"duplicate {location}.{key.value} in {source}")
        if key.start_mark.index < previous:
            raise ValueError(f"aliased key in {location} in {source}")
        previous = key.end_mark.index
        fields[key.value] = (key, value)
    return fields


def _value(mapping, fields: dict, key: str, location: str, source: Path):
    if key not in fields:
        raise ValueError(f"missing {location}.{key} in {source}")
    key_node, value = fields[key]
    position = next(i for i, (candidate, _) in enumerate(mapping.value)
                    if candidate is key_node)
    limit = (mapping.value[position + 1][0].start_mark.index
             if position + 1 < len(mapping.value) else mapping.end_mark.index)
    if value.start_mark.index < key_node.end_mark.index or value.end_mark.index > limit:
        raise ValueError(f"aliased {location}.{key} is not editable in {source}")
    return key_node, value


def catalog_metadata(text: str, source: Path) -> dict[str, str]:
    """Read the custom catalog fields, preserving CSV scalar values verbatim."""
    frontmatter, _ = _frontmatter(text, source)
    try:
        root = yaml.compose(frontmatter, Loader=yaml.SafeLoader)
    except yaml.YAMLError as error:
        raise ValueError(f"invalid YAML frontmatter in {source}: {error}") from error
    fields = _mapping(root, "frontmatter", source)
    _, metadata = _value(root, fields, "metadata", "frontmatter", source)
    metadata_fields = _mapping(metadata, "metadata", source)
    if "version" in fields or "version" in metadata_fields:
        raise ValueError(f"version is retired; "
                         f"use metadata.revision in {source}")
    values = {}
    for key in ("revision", "areas", "targets", "summary", "summary_zh"):
        if key in ("summary", "summary_zh") and key not in metadata_fields:
            continue
        _, value = _value(metadata, metadata_fields, key, "metadata", source)
        if not isinstance(value, ScalarNode) or value.tag != STRING:
            raise ValueError(f"metadata.{key} must be a YAML string in {source}")
        values[key] = value.value
    if REVISION.fullmatch(values["revision"]) is None:
        raise ValueError(f"metadata.revision must be a positive integer string, "
                         f"got {values['revision']!r} in {source}")
    return values
