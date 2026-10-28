#!/usr/bin/env python3
"""Read custom-skill catalog metadata and losslessly update metadata.version.

PyYAML supplies the parsed nodes and scalar token source spans. Only the
selected scalar is replaced; the rest of the frontmatter and document is
never serialized. Install dependencies with scripts/requirements.txt.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml
from yaml.nodes import MappingNode, ScalarNode
from yaml.tokens import AliasToken, AnchorToken, ScalarToken

SEMVER = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
STRING = "tag:yaml.org,2002:str"
MAPPING = "tag:yaml.org,2002:map"


def validate_version(value: str, source: Path) -> None:
    if SEMVER.fullmatch(value) is None:
        raise ValueError(f"invalid stable numeric version {value!r} in {source}")


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


def _version_metadata(text: str, source: Path):
    """Return the editable version span together with its parsed metadata nodes."""
    frontmatter, offset = _frontmatter(text, source)
    try:
        root = yaml.compose(frontmatter, Loader=yaml.SafeLoader)
        tokens = list(yaml.scan(frontmatter, Loader=yaml.SafeLoader))
    except yaml.YAMLError as error:
        raise ValueError(f"invalid YAML frontmatter in {source}: {error}") from error
    fields = _mapping(root, "frontmatter", source)
    if "version" in fields:
        raise ValueError(f"top-level version is not supported; use metadata.version in {source}")
    metadata_key, metadata = _value(root, fields, "metadata", "frontmatter", source)
    metadata_fields = _mapping(metadata, "metadata", source)
    version_key, version = _value(metadata, metadata_fields, "version", "metadata", source)
    if not isinstance(version, ScalarNode) or version.tag != STRING:
        raise ValueError(f"metadata.version must be a YAML string in {source}")
    validate_version(version.value, source)

    # An anchor/alias on either edited value can share the version elsewhere.
    # Unrelated YAML anchors outside these two value locations are untouched.
    root_head = root.value[0][0].start_mark.index
    metadata_head = metadata.value[0][0].start_mark.index
    for token in tokens:
        if not isinstance(token, (AliasToken, AnchorToken)):
            continue
        start = token.start_mark.index
        if (root.start_mark.index <= start < root_head
                or metadata_key.end_mark.index <= start < metadata_head
                or version_key.end_mark.index <= start < version.end_mark.index):
            raise ValueError(f"anchored/aliased metadata.version is not editable in {source}")
    scalars = [token for token in tokens if isinstance(token, ScalarToken)
               and version.start_mark.index <= token.start_mark.index
               and token.end_mark.index <= version.end_mark.index]
    if len(scalars) != 1 or scalars[0].style not in (None, "'", '"'):
        raise ValueError(f"metadata.version requires a plain or quoted scalar in {source}")
    scalar = scalars[0]
    if "\n" in frontmatter[scalar.start_mark.index:scalar.end_mark.index]:
        raise ValueError(f"multiline metadata.version is not editable in {source}")
    return ((version.value, offset + scalar.start_mark.index,
             offset + scalar.end_mark.index, scalar.style), metadata, metadata_fields)


def version_scalar(text: str, source: Path) -> tuple[str, int, int, str | None]:
    """Return the version string and its exact scalar-token span/style in text."""
    return _version_metadata(text, source)[0]


def catalog_metadata(text: str, source: Path) -> dict[str, str]:
    """Read only the custom catalog fields, preserving CSV scalar values verbatim."""
    version, metadata, fields = _version_metadata(text, source)
    values = {}
    for key in ("areas", "targets"):
        _, value = _value(metadata, fields, key, "metadata", source)
        if not isinstance(value, ScalarNode) or value.tag != STRING:
            raise ValueError(f"metadata.{key} must be a YAML string in {source}")
        values[key] = value.value
    values["version"] = version[0]
    return values


def replace_version(text: str, release: str, source: Path) -> str:
    validate_version(release, source)
    current, start, end, style = version_scalar(text, source)
    if current == release:
        return text
    quote = style or ""
    return text[:start] + quote + release + quote + text[end:]
