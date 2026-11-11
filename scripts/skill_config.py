#!/usr/bin/env python3
"""One resolver for the configuration chain every skill documents.

Resolution order, everywhere:

    CLI flag -> environment variable -> operator config file -> documented default

The operator config file is ``$XDG_CONFIG_HOME/<skill>/config.yaml``, falling back to
``~/.config/<skill>/config.yaml``. The file is a flat ``key: value`` document; it is parsed here, not
with PyYAML, so an unsupported construct is an error instead of a half-parsed guess.

Usage::

    from skill_config import resolve
    value = resolve("goal-driven-delivery", "GDD_STATE_FILE", default="/tmp/ledger.tsv")

    python scripts/skill_config.py --skill goal-driven-delivery --key GDD_STATE_FILE

CLI output is one provenance line: ``<KEY>=<value> (from flag|env VAR|config PATH|default)``.

Environment-variable name: a key already shaped like an environment variable
(``[A-Z][A-Z0-9_]*``) is used verbatim, so the existing ``GDD_STATE_FILE`` and friends keep their
documented names. Any other key becomes ``<SKILL_BIG_SNAKE>_<KEY_BIG_SNAKE>``.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

CONFIG_NAME = "config.yaml"
_ENV_KEY = re.compile(r"[A-Z][A-Z0-9_]*\Z")
_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*\Z")
_SKILL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_ESCAPES = {"\\": "\\", '"': '"', "/": "/", "n": "\n", "t": "\t", "r": "\r"}


class ConfigError(ValueError):
    """A config file that cannot be read or is outside the supported subset."""


@dataclass(frozen=True)
class Resolved:
    """A resolved value and the step that supplied it."""

    value: str | None
    source: str
    detail: str | None


def _supplied(value) -> bool:
    """None and "" mean "not supplied"; this mirrors gdd.py's existing `if value:` checks."""
    return value is not None and value != ""


def _validate_skill(skill: str) -> None:
    if not isinstance(skill, str) or not _SKILL.fullmatch(skill) or skill in (".", ".."):
        raise ConfigError(f"invalid skill name {skill!r}")


def _validate_key(key: str) -> None:
    if not isinstance(key, str) or not _KEY.fullmatch(key):
        raise ConfigError(f"invalid config key {key!r}")


def _big_snake(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").upper()


def env_name(skill: str, key: str) -> str:
    """The documented environment variable for one skill/key pair."""
    _validate_skill(skill)
    _validate_key(key)
    if _ENV_KEY.fullmatch(key):
        return key
    prefix = _big_snake(skill)
    return f"{prefix}_{_big_snake(key)}" if prefix else _big_snake(key)


def config_path(skill: str, *, root=None, env=None) -> Path:
    """``<root>/<skill>/config.yaml``; root defaults to XDG_CONFIG_HOME then ~/.config."""
    _validate_skill(skill)
    if root is not None:
        base = os.fspath(root)
    else:
        environ = os.environ if env is None else env
        base = environ.get("XDG_CONFIG_HOME")
        if not base:
            home = environ.get("HOME") or os.path.expanduser("~")
            base = os.path.join(home, ".config")
    return Path(base) / skill / CONFIG_NAME


def _line_error(path: Path, number: int, reason: str) -> ConfigError:
    return ConfigError(f"{path}:{number}: {reason}")


def _quoted(raw: str, path: Path, number: int) -> tuple[str, str]:
    """Parse one quoted scalar at the start of raw; return (value, remainder)."""
    quote = raw[0]
    out: list[str] = []
    index = 1
    while index < len(raw):
        char = raw[index]
        if quote == "'":
            if char == "'":
                if index + 1 < len(raw) and raw[index + 1] == "'":
                    out.append("'")
                    index += 2
                    continue
                return "".join(out), raw[index + 1:]
            out.append(char)
            index += 1
            continue
        if char == '"':
            return "".join(out), raw[index + 1:]
        if char == "\\":
            if index + 1 >= len(raw):
                raise _line_error(path, number, "unterminated escape in a double-quoted value")
            escaped = raw[index + 1]
            if escaped not in _ESCAPES:
                raise _line_error(path, number,
                                  f"unsupported escape \\{escaped} in a double-quoted value")
            out.append(_ESCAPES[escaped])
            index += 2
            continue
        out.append(char)
        index += 1
    raise _line_error(path, number, "unterminated quoted value")


def _comment_stripped(raw: str) -> str:
    """Drop an unquoted `` # comment`` from a plain scalar."""
    for index, char in enumerate(raw):
        if char == "#" and (index == 0 or raw[index - 1] in " \t"):
            return raw[:index]
    return raw


def _scalar(raw: str, path: Path, number: int) -> str:
    first = raw[0]
    if first in "&*":
        raise _line_error(path, number,
                          "anchors and aliases are not supported; write the value out")
    if first in "[{":
        raise _line_error(path, number,
                          "flow collections and nested mappings are not supported; use flat key: value")
    if first in "|>":
        raise _line_error(path, number, "block scalars are not supported; use one line")
    if first in "!%@`":
        raise _line_error(path, number,
                          f"{first!r} is not supported in a flat value")
    if first == "#":
        raise _line_error(path, number, "missing value (a comment alone is not a value)")
    if first in "'\"":
        value, remainder = _quoted(raw, path, number)
        remainder = remainder.strip()
        if remainder and not remainder.startswith("#"):
            raise _line_error(path, number, "trailing characters after a quoted value")
        return value
    value = _comment_stripped(raw).strip()
    if not value:
        raise _line_error(path, number, "missing value")
    if any(ord(char) < 0x20 for char in value):
        raise _line_error(path, number, "control characters are not supported in a value")
    return value


def read_config(path: Path) -> dict[str, str]:
    """Parse the flat YAML subset at path. A missing file is an empty mapping."""
    if not os.path.lexists(path):
        return {}
    if not path.is_file():
        raise ConfigError(f"{path}: not a regular file")
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as error:
        raise ConfigError(f"{path}: not valid UTF-8: {error}") from error
    except OSError as error:
        raise ConfigError(f"{path}: cannot read config file: {error}") from error

    values: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped in ("---", "..."):
            raise _line_error(path, number,
                              "document markers are not supported; write one flat document")
        if line[0] in " \t":
            raise _line_error(path, number,
                              "indentation is not supported; use flat key: value lines")
        if ":" not in line:
            raise _line_error(path, number, "expected 'key: value'")
        key, raw_value = line.split(":", 1)
        key = key.strip()
        if not _KEY.fullmatch(key):
            raise _line_error(path, number, f"invalid key {key!r}")
        if key in values:
            raise _line_error(path, number, f"duplicate key {key!r}")
        raw_value = raw_value.strip()
        if not raw_value:
            raise _line_error(path, number,
                              f"missing value for {key!r}; nested mappings and empty values "
                              f"are not supported")
        values[key] = _scalar(raw_value, path, number)
    return values


def explain(skill, key, *, flag=None, env=None, default=None, root=None) -> Resolved:
    """Resolve one key and report which step supplied it."""
    _validate_skill(skill)
    _validate_key(key)
    if _supplied(flag):
        return Resolved(str(flag), "flag", None)

    environ = os.environ if env is None else env
    name = env_name(skill, key)
    value = environ.get(name)
    if _supplied(value):
        return Resolved(str(value), "env", name)

    path = config_path(skill, root=root, env=environ)
    values = read_config(path)
    if key in values:
        return Resolved(values[key], "config", str(path))
    return Resolved(default, "default", None)


def resolve(skill, key, *, flag=None, env=None, default=None, root=None):
    """The value for one key: flag, then env var, then config file, then default."""
    return explain(skill, key, flag=flag, env=env, default=default, root=root).value


def _origin(resolved: Resolved) -> str:
    if resolved.source == "env":
        return f"env {resolved.detail}"
    if resolved.source == "config":
        return f"config {resolved.detail}"
    return resolved.source


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Resolve one skill configuration key and print its provenance.",
        epilog="Order: CLI flag -> environment variable -> "
               "$XDG_CONFIG_HOME/<skill>/config.yaml (fallback ~/.config) -> default.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--skill", required=True, help="skill directory name")
    parser.add_argument("--key", required=True, help="config-file key")
    parser.add_argument("--flag", default=None, help="simulate a CLI flag value")
    parser.add_argument("--default", default=None, help="documented default")
    parser.add_argument("--root", default=None,
                        help="config base directory (default: XDG_CONFIG_HOME or ~/.config)")
    args = parser.parse_args(argv)
    try:
        resolved = explain(args.skill, args.key, flag=args.flag,
                           default=args.default, root=args.root)
    except ConfigError as error:
        print(f"skill_config: {error}", file=sys.stderr)
        return 1
    value = "(unset)" if resolved.value is None else resolved.value
    print(f"{args.key}={value} (from {_origin(resolved)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
