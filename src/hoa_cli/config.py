import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

CONFIG_NAME = "config.yaml"
SUPPORTED_APIS = ("decisions", "chat-completions")
_ENV_KEY = re.compile(r"[A-Z][A-Z0-9_]*\Z")
_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*\Z")
_SKILL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_ESCAPES = {"\\": "\\", '"': '"', "/": "/", "n": "\n", "t": "\t", "r": "\r"}
_UNSUPPORTED = {
    "&": "anchors and aliases are not supported; write the value out",
    "[": "flow collections and nested mappings are not supported; use flat key: value",
    "|": "block scalars are not supported; use one line",
    "#": "missing value (a comment alone is not a value)",
}


class ConfigError(ValueError):
    pass


class EndpointNotConfigured(ConfigError):
    pass


@dataclass(frozen=True)
class Resolved:
    value: str | None
    source: str
    detail: str | None


@dataclass(frozen=True)
class Endpoint:
    base_url: str
    model: str
    api: str
    effort: str
    api_key: str
    workers: int

    def request_options(self) -> dict:
        return {"api": self.api, "effort": self.effort, "api_key": self.api_key}


def _validate_skill(skill: str) -> None:
    if not isinstance(skill, str) or not _SKILL.fullmatch(skill):
        raise ConfigError(f"invalid skill name {skill!r}")


def _big_snake(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").upper()


def env_name(skill: str, key: str) -> str:
    _validate_skill(skill)
    if not isinstance(key, str) or not _KEY.fullmatch(key):
        raise ConfigError(f"invalid config key {key!r}")
    return key if _ENV_KEY.fullmatch(key) else f"{_big_snake(skill)}_{_big_snake(key)}"


def config_path(skill: str, *, root: Path | None = None, env: Mapping[str, str] | None = None) -> Path:
    _validate_skill(skill)
    if root is None:
        environ = os.environ if env is None else env
        xdg = environ.get("XDG_CONFIG_HOME")
        root = Path(xdg) if xdg else Path(environ.get("HOME") or Path.home()) / ".config"
    return Path(root) / skill / CONFIG_NAME


def _line_error(path: Path, number: int, reason: str) -> ConfigError:
    return ConfigError(f"{path}:{number}: {reason}")


def _quoted(raw: str, path: Path, number: int) -> str:
    quote = raw[0]
    result = []
    index = 1
    while index < len(raw):
        char = raw[index]
        index += 1
        if char == quote:
            if quote == "'" and raw[index:index + 1] == "'":
                index += 1
            else:
                remainder = raw[index:].strip()
                if remainder and not remainder.startswith("#"):
                    raise _line_error(path, number, "trailing characters after a quoted value")
                return "".join(result)
        elif quote == '"' and char == "\\":
            if index >= len(raw):
                raise _line_error(path, number, "unterminated escape in a double-quoted value")
            escaped = raw[index]
            index += 1
            if escaped not in _ESCAPES:
                raise _line_error(path, number, f"unsupported escape \\{escaped} in a double-quoted value")
            char = _ESCAPES[escaped]
        result.append(char)
    raise _line_error(path, number, "unterminated quoted value")


def _scalar(raw: str, path: Path, number: int) -> str:
    first = raw[0]
    kind = {"*": "&", "{": "[", ">": "|"}.get(first, first)
    if kind in _UNSUPPORTED:
        raise _line_error(path, number, _UNSUPPORTED[kind])
    if first in "!%@`":
        raise _line_error(path, number, f"{first!r} is not supported in a flat value")
    if first in "'\"":
        return _quoted(raw, path, number)
    value = re.split(r"[ \t]+#", raw, maxsplit=1)[0].strip()
    if any(ord(char) < 0x20 for char in value):
        raise _line_error(path, number, "control characters are not supported in a value")
    return value


def read_config(path: Path) -> dict[str, str]:
    if not os.path.lexists(path):
        return {}
    if not path.is_file():
        raise ConfigError(f"{path}: not a regular file")
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (UnicodeError, OSError) as exc:
        raise ConfigError(f"{path}: cannot read UTF-8 config file: {exc}") from exc
    values: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped in ("---", "..."):
            raise _line_error(path, number, "document markers are not supported; write one flat document")
        if line[0] in " \t":
            raise _line_error(path, number, "indentation is not supported; use flat key: value lines")
        key, sep, raw_value = line.partition(":")
        if not sep:
            raise _line_error(path, number, "expected 'key: value'")
        key, raw_value = key.strip(), raw_value.strip()
        if not _KEY.fullmatch(key):
            raise _line_error(path, number, f"invalid key {key!r}")
        if key in values:
            raise _line_error(path, number, f"duplicate key {key!r}")
        if not raw_value:
            raise _line_error(path, number, f"missing value for {key!r}")
        values[key] = _scalar(raw_value, path, number)
    return values


def _supplied(value: object) -> bool:
    return value is not None and value != ""


def explain(skill: str, key: str, *, flag: object = None, env: Mapping[str, str] | None = None,
            default: str | None = None, root: Path | None = None) -> Resolved:
    name = env_name(skill, key)
    if _supplied(flag):
        return Resolved(str(flag), "flag", None)
    environ = os.environ if env is None else env
    if value := environ.get(name):
        return Resolved(value, "env", name)
    path = config_path(skill, root=root, env=environ)
    values = read_config(path)
    if key in values:
        return Resolved(values[key], "config", str(path))
    return Resolved(default, "default", None)


def resolve(skill: str, key: str, *, flag: object = None, env: Mapping[str, str] | None = None,
            default: str | None = None, root: Path | None = None) -> str | None:
    return explain(skill, key, flag=flag, env=env, default=default, root=root).value


def resolve_endpoint(
    skill: str, flag_base_url: str | None = None, flag_model: str | None = None,
    flag_api: str | None = None, flag_effort: str | None = None, flag_workers: int | str | None = None,
    fallback_prefixes: tuple[str, ...] = ("GHC_DECISIONS", "EVALS"), *, flag_api_key: str | None = None,
    env: Mapping[str, str] | None = None, root: Path | None = None,
) -> Endpoint:
    environ = os.environ if env is None else env
    values = None

    def get(key: str, flag: object = None, default: str = "") -> str:
        nonlocal values
        if _supplied(flag):
            return str(flag)
        if value := environ.get(env_name(skill, key)):
            return value
        if values is None:
            values = read_config(config_path(skill, root=root, env=environ))
        if key in values:
            return values[key]
        for prefix in fallback_prefixes:
            if value := environ.get(f"{prefix}_{key.upper()}"):
                return value
        return default

    base_url, model = get("base_url", flag_base_url), get("model", flag_model)
    if not base_url or not model:
        raise EndpointNotConfigured(
            f"base_url and model are required (--base-url / {env_name(skill, 'base_url')}, "
            f"--model / {env_name(skill, 'model')})"
        )
    api = get("api", flag_api, SUPPORTED_APIS[0])
    if api not in SUPPORTED_APIS:
        raise ConfigError(f"api must be one of {SUPPORTED_APIS}, got {api!r}")
    parts = urlsplit(base_url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.query or parts.fragment:
        raise ConfigError("base_url must be an HTTP(S) base URL without a query or fragment")
    try:
        workers = int(get("workers", flag_workers, "16"))
    except ValueError as exc:
        raise ConfigError("workers must be a positive integer") from exc
    if workers < 1:
        raise ConfigError("workers must be a positive integer")
    return Endpoint(base_url, model, api, get("effort", flag_effort, "low"),
                    get("api_key", flag_api_key, "dummy"), workers)
