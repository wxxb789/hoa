"""Redaction and frame detection for transcript snippets."""

import re
from collections.abc import Sequence
from datetime import datetime
from itertools import islice
from pathlib import Path

type RegexPatterns = Sequence[re.Pattern[str]]

SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"), "<REDACTED_GH_TOKEN>"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), "<REDACTED_GH_PAT>"),
    (re.compile(r"sk-[A-Za-z0-9_-]{20,}"), "<REDACTED_SK>"),
    (re.compile(r"AIza[0-9A-Za-z_-]{30,}"), "<REDACTED_API_KEY>"),
    (re.compile(r"(?i)(authorization:\s*bearer\s+)[A-Za-z0-9._-]+"), r"\1<REDACTED_BEARER>"),
    (
        re.compile(r"(?i)(api[_-]?key|token|secret|password)(\s*[:=]\s*['\"]?)[A-Za-z0-9._/-]{16,}"),
        r"\1\2<REDACTED_SECRET>",
    ),
)

HARNESS_FRAME_RE = re.compile(
    r"\[Workflow harness — computed task\].*?The computed task text follows:\s*",
    re.DOTALL,
)
OMP_REMINDER_RE = re.compile(
    r"<system-(?:reminder|notice)>.*?</system-(?:reminder|notice)>\s*",
    re.DOTALL,
)
CODEX_FRAME_RE = re.compile(
    r"^[ \t]*# AGENTS\.md instructions[^\n]*\n\s*(?=<INSTRUCTIONS>)"
    r"|<(INSTRUCTIONS|environment_context)>.*?(?:</\1>|\Z)"
    r"|^[ \t]*# AGENTS\.md instructions.*\Z",
    re.MULTILINE | re.DOTALL,
)
EXIT_ERR_RE = re.compile(r"(?:Exit code|exit status|exited with code)[:\s]+([1-9]\d*)")
HIGH_SIGNAL_CMD_RE = re.compile(
    r"(?i)(memory|AGENTS\.md|CLAUDE\.md|gh\s+pr|git\s+worktree|git\s+branch|"
    r"tmux|doctor|install|junction|symlink|wsl|hook)"
)


def redact_text(text: str, extra_patterns: RegexPatterns | None = None) -> str:
    if not text:
        return ""
    out = HARNESS_FRAME_RE.sub("[Delegated workflow task] ", text)
    for pattern, replacement in SECRET_PATTERNS:
        out = pattern.sub(replacement, out)
    for pattern in extra_patterns or ():
        out = pattern.sub("<REDACTED_SCOPE>", out)
    return out


def matches_high_signal(command: str, extra_high_signal: RegexPatterns = ()) -> bool:
    return bool(HIGH_SIGNAL_CMD_RE.search(command)) or any(pattern.search(command) for pattern in extra_high_signal)


def _text_blocks(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            item if isinstance(item, str) else str(item.get("text", ""))
            for item in content
            if isinstance(item, str) or (isinstance(item, dict) and item.get("type") == "text")
        )
    return str(content or "")


def _summarize_tool(name: str, inputs: object) -> str:
    if not isinstance(inputs, dict):
        return name
    low = name.lower()
    if low == "bash":
        cmd = str(inputs.get("command", "")).strip().replace("\n", " ; ")
        return f"{name}({cmd[:130]})"
    if low in ("read", "edit", "write", "multiedit"):
        path = str(inputs.get("file_path") or inputs.get("path") or "")
        return f"{name}({path[-85:]})"
    if low in ("agent", "task"):
        desc = str(inputs.get("description") or inputs.get("subagent_type") or inputs.get("context") or "")
        return f"{name}({desc[:85].replace(chr(10), ' ')})"
    return f"{name}({','.join(islice(inputs, 3))})"


def _dir_allowed(names: str | Sequence[str], allow_re: re.Pattern[str] | None, deny_re: re.Pattern[str] | None) -> bool:
    if isinstance(names, str):
        names = (names,)
    if deny_re and any(deny_re.search(name) for name in names):
        return False
    return allow_re is None or any(allow_re.search(name) for name in names)


def _modified_since(path: Path, since: datetime | None) -> bool:
    return since is None or path.stat().st_mtime >= since.timestamp()
