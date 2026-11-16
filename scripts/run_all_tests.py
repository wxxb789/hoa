#!/usr/bin/env python3
"""Discover, isolate and settle every repository test suite.

Run:  python scripts/run_all_tests.py                      # discover, run, report
      python scripts/run_all_tests.py --list               # print the plan only
      python scripts/run_all_tests.py --event pull_request # include the PR gates
      python scripts/run_all_tests.py --suite gate:frontmatter --suite scripts/test_version.py

Discovery, invocation and coverage data live in `scripts/test_manifest.toml`; this script only
applies it.  It is stdlib-only so it can run before `scripts/requirements.txt` is installed, and it
uses the interpreter running it (`sys.executable`) for every Python suite, never a PATH `python3`.

Every suite settles as PASS, FAIL, ERROR, TIMEOUT or SKIP (see `settle`), and the run exits:

  0  no required suite settled FAIL, ERROR or TIMEOUT (declared condition SKIPs and non-required
     suites do not fail the run)
  1  at least one required suite settled FAIL, ERROR or TIMEOUT
  2  the plan itself is not trustworthy: manifest or schema error, an unmet discovery floor, an
     unknown or duplicate suite id, a stale refinement, or nothing left to run

Each suite runs in its own process and process group, with a task-local TMPDIR/HOME/XDG root under a
short `/tmp` directory of its own whenever `/tmp` can hold one — an inherited operator `TMPDIR` is
consulted only where it cannot, through `tempfile`'s own chain; the default location is outside the
checkout and `--scratch` names its own (`scratch_root_for`) — a per-suite timeout, and a teardown
that runs whenever the suite did not finish under its own control: the runner timed it out, or a
signal killed it (a negative exit status, `settle`).  That teardown terminates the process group of
the command that did not finish — POSIX only, through `os.killpg` — and then sweeps every process
still holding the suite's task-local scratch, found by the cwd it was started in or the scratch
paths in its environment (`_scratch_processes`; the sweep and every per-pid signal read `/proc`) —
before that scratch is deleted.  Both parts signal only what this run can prove is its own: a
process group is signalled only while the command's own process is still unreaped — the command was
spawned as a session leader (`start_new_session`), and the kernel does not recycle an unreaped
child's pid, so a group id that still equals that process's own group cannot be a recycled number —
and a scratch holder only while it still points into the suite's own task-local scratch.  Where
neither proof holds, no signal is sent and the record reports teardown as unverified.  A scratch tree
too long to hold the toolkit's AF_UNIX socket — given the deepest `socket_tail` the scheduled suites
declare in the manifest — is reported as that suite's ERROR before it runs (`socket_path_length`).
Per-suite logs stay under `.tmp-artifacts/test-runs/<UTC stamp>-<pid>/logs/`, and the JSON result
record is `result.json` in that same run directory (`--report` writes it elsewhere).  Suite processes also keep the shim
toolchain's absolute state directories (`shim_state_environment`), because a task-local HOME otherwise
makes a mise shim on PATH refuse to run.  A required suite that executed zero
checks is never PASS: a unittest suite must collect *and execute* at least one test (an all-skipped
summary is ERROR), and a suite with a declared count adapter must report a positive executed-check
count whose totals account for every check it did not pass — the same rule settles a covered child,
from its parent's log, so contradictory evidence cannot go green by not being scheduled.
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_RELATIVE = Path("scripts") / "test_manifest.toml"
DEFAULT_TIMEOUT = 120.0
LOG_TAIL_BYTES = 128 * 1024
KILL_GRACE_SECONDS = 10.0
TEARDOWN_POLL_SECONDS = 0.1
EXIT_POLL_SECONDS = 0.05
# `/proc` is how teardown sees what a suite left behind: a detached worker
# (`start_new_session`) leaves the suite's process group, so the group cannot show it.
PROC_ROOT = Path("/proc")
# POSIX lets a command's exit be observed without reaping it (`waitid` + `WNOWAIT`), which keeps
# the pid — and with it the teardown's ownership proof (`_owned_group`) — reserved.
WAITID_WNOWAIT = all(hasattr(os, name)
                     for name in ("waitid", "WNOWAIT", "WEXITED", "WNOHANG", "CLD_EXITED"))
NO_ENUMERATION = "this platform cannot enumerate processes, so teardown is unverified"
TERMINAL_STATES = ("PASS", "FAIL", "ERROR", "TIMEOUT", "SKIP")
FAILING_STATES = ("FAIL", "ERROR", "TIMEOUT")
RUNTIMES = ("python", "bash", "bun", "npm")
ASSERTION_KINDS = ("auto", "unittest", "counter", "exit")
CONDITIONS = ("always", "pull_request")

# Scratch lives in /tmp rather than under an inherited TMPDIR: `sun_path` in `struct
# sockaddr_un` caps AF_UNIX socket paths at 108 bytes including the terminating NUL, and a
# long operator TMPDIR used to push the suites' tmux sockets past it.
SHORT_TEMP_ROOT = Path("/tmp")
SCRATCH_PREFIX = "hoa-t-"
AF_UNIX_PATH_LIMIT = 108

# Shim toolchain state, pinned by absolute path for suite processes: a shim-managed tool
# on PATH resolves its trust database and installed tools through these, and suites run
# with a task-local HOME (see `shim_state_environment`).
SHIM_STATE_DEFAULTS = {
    "MISE_STATE_DIR": Path(".local") / "state" / "mise",
    "MISE_DATA_DIR": Path(".local") / "share" / "mise",
}

UNITTEST_SUMMARY = re.compile(r"^Ran (\d+) tests? in (?:\d|\.)", re.MULTILINE)
UNITTEST_SKIPPED = re.compile(r"skipped=(\d+)")
# Tools colour their output even when it is redirected to a file (vitest, npm, bun),
# so counts are parsed from the plain text (§4.6 adapters must not depend on colour).
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


class ManifestError(Exception):
    """The manifest cannot be read or contradicts the runner's schema."""


class PlanError(Exception):
    """The plan cannot be built from the manifest and the tree."""


@dataclass(frozen=True)
class Suite:
    """One logical suite: a discovered entry point or a declared command."""

    id: str
    origin: str                       # "declared" | "discovered"
    commands: tuple[tuple[str, ...], ...]
    cwd: Path
    runtime: str
    required: bool = True
    assertion: str = "exit"           # resolved kind: unittest | counter | exit
    count_regexes: tuple[str, ...] = ()
    require_regex: str | None = None
    condition: str = "always"
    skip_reason: str | None = None
    timeout: float = DEFAULT_TIMEOUT
    env: tuple[tuple[str, str], ...] = ()
    provision: tuple[tuple[str, ...], ...] = ()
    covered_by: str | None = None
    detached: str | None = None
    notes: str | None = None
    socket_tail: str | None = None    # declared AF_UNIX tree below the suite's scratch root
    path: str | None = None           # repo-relative entry point, when there is one


@dataclass
class Outcome:
    """Settled state of one suite, including accounted-and-not-scheduled children."""

    suite_id: str
    state: str
    duration: float = 0.0
    exit_code: int | None = None
    reason: str = ""
    counts: dict = field(default_factory=dict)
    log: str | None = None
    tail: str = ""
    covered_by: str | None = None


@dataclass
class Plan:
    scheduled: list[Suite]
    covered: list[Suite]
    skipped: list[Suite]
    problems: list[str]
    discovered: list[str]
    floor_missing: list[str]
    unpinned: list[str]
    filtered: bool
    socket_tail: str = ""  # deepest `socket_tail` declared by the suites this run settles

    @property
    def settled_total(self) -> int:
        return len(self.scheduled) + len(self.covered) + len(self.skipped)


# ── manifest ─────────────────────────────────────────────────────────────────


def load_manifest(path: Path) -> dict:
    """Read the manifest as data; every failure is a ManifestError."""
    try:
        with path.open("rb") as handle:
            document = tomllib.load(handle)
    except FileNotFoundError as exc:
        raise ManifestError(f"manifest not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ManifestError(f"manifest is not valid TOML ({path}): {exc}") from exc
    if not isinstance(document, dict):
        raise ManifestError(f"manifest is not a table ({path})")
    if document.get("schema") != 1:
        raise ManifestError(
            f"manifest schema is {document.get('schema')!r}, not the supported 1 ({path})"
        )
    return document


def _glob_regex(pattern: str) -> re.Pattern[str]:
    """Translate a repo-relative glob into a regex; `*` never crosses `/`."""
    out = ["^"]
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
            if pattern[index:index + 3] == "**/":
                out.append("(?:.*/)?")
                index += 3
                continue
            if pattern[index:index + 2] == "**":
                out.append(".*")
                index += 2
                continue
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(char))
        index += 1
    out.append("$")
    return re.compile("".join(out))


def _pruned(relative: str, prune: list[str]) -> bool:
    """True when a repo-relative path (file or directory) is excluded.

    A prune entry matches either the whole relative path or any single segment, so
    `node_modules` prunes at every depth and `skills/foo/scripts` prunes a subtree.
    """
    segments = relative.split("/")
    for pattern in prune:
        regex = _glob_regex(pattern)
        if regex.match(relative) or any(regex.match(segment) for segment in segments):
            return True
    return False


def discover(root: Path, patterns: list[str], prune: list[str]) -> list[str]:
    """Return sorted repo-relative paths matching the named entry-point patterns."""
    compiled = [_glob_regex(pattern) for pattern in patterns]
    found: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root):
        relative_dir = os.path.relpath(dirpath, root)
        prefix = "" if relative_dir == "." else relative_dir.replace(os.sep, "/") + "/"
        dirnames[:] = sorted(
            name for name in dirnames if not _pruned(prefix + name, prune)
        )
        for name in sorted(filenames):
            relative = prefix + name
            if _pruned(relative, prune):
                continue
            if any(regex.match(relative) for regex in compiled):
                found.add(relative)
    return sorted(found)


def _imports_unittest(source: str) -> bool:
    """True when a Python source imports unittest at any level."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[0] == "unittest" for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] == "unittest":
                return True
    return False


def _auto_assertion(commands: tuple[tuple[str, ...], ...], path: str | None,
                    root: Path) -> str:
    """Resolve `auto`: declared `-m unittest` or an entry point importing unittest."""
    for argv in commands:
        if "unittest" in argv and "-m" in argv:
            return "unittest"
    if path and path.endswith(".py"):
        candidate = root / path
        if candidate.is_file() and _imports_unittest(
            candidate.read_text(encoding="utf-8", errors="replace")
        ):
            return "unittest"
    return "exit"


def _resolve_command(argv: list[str], python: str, label: str, problems: list[str]) -> tuple[str, ...]:
    resolved = tuple(python if token == "{python}" else token for token in argv)
    if not resolved or not resolved[0]:
        problems.append(f"{label}: empty command")
    return resolved


def _entry_label(entry: dict, index: int) -> str:
    return str(entry.get("id") or entry.get("path") or f"suite #{index + 1}")


def _validate_entry(entry: dict, label: str, problems: list[str]) -> None:
    if not isinstance(entry, dict):
        problems.append(f"{label}: entry is not a table")
        return
    has_command = "command" in entry
    has_path = "path" in entry
    if not has_command and not has_path:
        problems.append(f"{label}: needs `command` (declared) or `path` (refinement)")
    if has_command and "id" not in entry and "path" not in entry:
        problems.append(f"{label}: a declared suite needs an `id` (or a `path` to take one from)")
    if has_command:
        for name in ("command", "provision"):
            for argv in entry.get(name) or []:
                if not isinstance(argv, list) or not all(isinstance(token, str) for token in argv):
                    problems.append(f"{label}: {name} must be a list of argv string lists")
                    break
    for field_name in ("count_regexes",):
        for pattern in entry.get(field_name) or []:
            try:
                re.compile(pattern)
            except re.error as exc:
                problems.append(f"{label}: {field_name} pattern does not compile ({exc})")
    assertion = entry.get("assertion", "auto")
    if assertion not in ASSERTION_KINDS:
        problems.append(f"{label}: assertion must be one of {', '.join(ASSERTION_KINDS)}")
    if assertion == "counter":
        patterns = entry.get("count_regexes") or []
        if not patterns:
            problems.append(f"{label}: assertion=counter needs count_regexes")
        for pattern in patterns:
            try:
                compiled = re.compile(pattern)
            except re.error:
                continue
            if "passed" not in compiled.groupindex:
                problems.append(f"{label}: count_regexes need a `passed` group ({pattern})")
    if "require_regex" in entry:
        try:
            re.compile(entry["require_regex"])
        except (re.error, TypeError) as exc:
            problems.append(f"{label}: require_regex does not compile ({exc})")
    runtime = entry.get("runtime", "python")
    if runtime not in RUNTIMES:
        problems.append(f"{label}: runtime must be one of {', '.join(RUNTIMES)}")
    condition = entry.get("condition", "always")
    if condition not in CONDITIONS:
        problems.append(f"{label}: condition must be one of {', '.join(CONDITIONS)}")
    if condition != "always" and not entry.get("skip_reason"):
        problems.append(f"{label}: condition={condition} needs a skip_reason")
    timeout = entry.get("timeout", DEFAULT_TIMEOUT)
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        problems.append(f"{label}: timeout must be a positive number")
    socket_tail = entry.get("socket_tail")
    if socket_tail is not None:
        if not isinstance(socket_tail, str):
            problems.append(f"{label}: socket_tail must be a string")
        else:
            try:
                socket_tail.format(uid=0)
            except (KeyError, IndexError, ValueError) as exc:
                problems.append(f"{label}: socket_tail is not a format template ({exc})")
    for key in ("env",):
        value = entry.get(key) or {}
        if not isinstance(value, dict) or not all(isinstance(v, str) for v in value.values()):
            problems.append(f"{label}: {key} must be a table of strings")


def _check_entry_points(label: str, commands: tuple[tuple[str, ...], ...], cwd: Path,
                        problems: list[str]) -> None:
    """A declared command that names a .py/.sh file must name one that exists.

    Without this the failure would look like a test failure instead of what it is: an
    unknown entry point (§4.5), which is a plan error.
    """
    seen: set[str] = set()
    for argv in commands:
        for token in argv[1:]:
            if token.startswith("-") or not token.endswith((".py", ".sh")):
                continue
            if token in seen:
                continue
            seen.add(token)
            candidate = Path(token) if Path(token).is_absolute() else cwd / token
            if not candidate.is_file():
                problems.append(f"{label}: entry point does not exist: {token}")


def _infer_runtime(commands: tuple[tuple[str, ...], ...]) -> str:
    """Name the runtime from the command itself when the entry does not declare one."""
    executable = Path(commands[0][0]).name if commands and commands[0] else ""
    if executable in ("bun",):
        return "bun"
    if executable in ("npm", "npx"):
        return "npm"
    if executable in ("bash", "sh", "dash"):
        return "bash"
    return "python"


def _suite_from_entry(entry: dict, label: str, root: Path, python: str, problems: list[str],
                      *, origin: str, path: str | None) -> Suite:
    if "command" in entry:
        commands = tuple(
            _resolve_command(argv, python, label, problems) for argv in entry["command"]
        )
        provision = tuple(
            _resolve_command(argv, python, label, problems) for argv in entry.get("provision") or []
        )
    else:
        argv = ("{python}", "-B", path) if path.endswith(".py") else ("bash", path)
        commands = (_resolve_command(list(argv), python, label, problems),)
        provision = ()
    cwd = root / str(entry.get("cwd", "."))
    if path and not (root / path).is_file():
        problems.append(f"{label}: entry point does not exist: {path}")
    if not cwd.is_dir():
        problems.append(f"{label}: cwd does not exist: {entry.get('cwd')}")
    elif "command" in entry:
        _check_entry_points(label, commands, cwd, problems)
    assertion_kind = str(entry.get("assertion", "auto"))
    resolved = (
        assertion_kind if assertion_kind != "auto"
        else _auto_assertion(commands, path, root)
    )
    return Suite(
        id=str(entry.get("id") or path),
        origin=origin,
        commands=commands,
        cwd=cwd,
        runtime=str(entry.get("runtime") or _infer_runtime(commands)),
        required=bool(entry.get("required", True)),
        assertion=resolved,
        count_regexes=tuple(entry.get("count_regexes") or ()),
        require_regex=entry.get("require_regex"),
        condition=str(entry.get("condition", "always")),
        skip_reason=entry.get("skip_reason"),
        timeout=float(entry.get("timeout", DEFAULT_TIMEOUT)),
        env=tuple(sorted((entry.get("env") or {}).items())),
        provision=provision,
        covered_by=entry.get("covered_by"),
        detached=entry.get("detached"),
        notes=entry.get("notes"),
        socket_tail=entry.get("socket_tail"),
        path=path,
    )


def _references_child(parent: Suite, child: Suite, root: Path) -> bool:
    """True when the parent's command text or script names the covered child."""
    needle = Path(child.path or child.id).name
    haystacks = [" ".join(argv) for argv in parent.commands + parent.provision]
    if parent.path:
        candidate = root / parent.path
        if candidate.is_file() and candidate.suffix in (".py", ".sh", ".bash"):
            haystacks.append(candidate.read_text(encoding="utf-8", errors="replace"))
    return any(needle in haystack for haystack in haystacks)


def build_plan(root: Path, document: dict, *, event: str, only: list[str] | None = None,
               python: str | None = None) -> Plan:
    """Resolve the manifest and the tree into the suites this run will settle."""
    problems: list[str] = []
    python = python or sys.executable
    discovery = document.get("discovery") or {}
    patterns = list(discovery.get("patterns") or [])
    prune = list(discovery.get("prune") or [])
    floor = list(discovery.get("floor") or [])
    if not patterns:
        problems.append("discovery.patterns is empty")

    entries = document.get("suite") or []
    if not isinstance(entries, list):
        raise ManifestError("`suite` must be an array of tables")
    declared_entries: list[tuple[dict, str]] = []
    refinements: dict[str, dict] = {}
    for index, entry in enumerate(entries):
        label = _entry_label(entry if isinstance(entry, dict) else {}, index)
        _validate_entry(entry, label, problems)
        if not isinstance(entry, dict):
            continue
        if "command" in entry:
            declared_entries.append((entry, label))
        elif "path" in entry:
            if entry["path"] in refinements:
                problems.append(f"{label}: duplicate refinement for {entry['path']}")
            refinements[entry["path"]] = entry

    found = discover(root, patterns, prune)
    unpinned = sorted(set(found) - set(floor))

    suites: dict[str, Suite] = {}
    declared_paths: set[str] = set()
    for entry, label in declared_entries:
        path = entry.get("path")
        replaced = bool(path and path in found)
        suite = _suite_from_entry(entry, label, root, python, problems,
                                 origin="declared", path=path)
        if suite.id in suites:
            problems.append(f"{label}: duplicate suite id {suite.id}")
            continue
        if replaced:
            declared_paths.add(str(path))
        suites[suite.id] = suite

    for path in found:
        if path in declared_paths:
            continue
        entry = refinements.get(path)
        label = str(entry.get("id") or path) if entry else path
        if entry and "id" in entry:
            problems.append(f"{label}: a refinement takes its id from its path")
        suite = _suite_from_entry(entry or {"assertion": "auto"}, label, root, python, problems,
                                  origin="discovered", path=path)
        if suite.id in suites:
            problems.append(f"{label}: duplicate suite id {suite.id}")
            continue
        suites[suite.id] = suite

    for path, entry in refinements.items():
        if path not in found and path not in declared_paths:
            problems.append(
                f"{_entry_label(entry, 0)}: refinement matches no discovered suite ({path})"
            )

    covered_children: dict[str, list[Suite]] = {}
    for suite in sorted(suites.values(), key=lambda item: item.id):
        if not suite.covered_by:
            continue
        parent = suites.get(suite.covered_by)
        if parent is None:
            problems.append(f"{suite.id}: covered_by names no known suite ({suite.covered_by})")
            continue
        if parent.covered_by:
            problems.append(f"{suite.id}: covered_by must name a scheduled suite, not {parent.id}")
            continue
        if not _references_child(parent, suite, root):
            problems.append(
                f"{suite.id}: covered_by={parent.id} but that suite never names {Path(suite.path or suite.id).name}"
            )
            continue
        covered_children.setdefault(parent.id, []).append(suite)

    scheduled = [suite for suite in suites.values() if not suite.covered_by]
    covered = sorted(
        (child for children in covered_children.values() for child in children),
        key=lambda item: item.id,
    )

    if only:
        wanted = set(only)
        known = {suite.id: suite for suite in suites.values()}
        covered_ids = {suite.id: suite for suite in covered}
        for name in sorted(wanted):
            if name in covered_ids:
                parent = covered_ids[name].covered_by
                if parent not in wanted:
                    problems.append(
                        f"--suite {name}: covered by {parent}; run that suite"
                    )
            elif name not in known:
                problems.append(f"--suite {name}: unknown suite id")
        scheduled = [suite for suite in scheduled if suite.id in wanted]
        kept = {suite.id for suite in scheduled}
        covered = [child for child in covered if child.covered_by in kept]
        if not scheduled:
            problems.append("--suite selected no schedulable suite")
    elif not scheduled:
        problems.append("discovery produced no suites; check discovery.patterns and the tree")

    skipped: list[Suite] = []
    if not only:
        floor_missing = sorted(set(floor) - set(found))
        if floor_missing:
            problems.append(
                "discovery floor unmet (pinned suites not found): " + ", ".join(floor_missing)
            )
    else:
        floor_missing = []

    runnable: list[Suite] = []
    for suite in scheduled:
        if suite.condition != "always" and suite.condition != event:
            skipped.append(suite)
        else:
            runnable.append(suite)

    return Plan(
        scheduled=runnable,
        covered=covered,
        skipped=skipped,
        problems=problems,
        discovered=found,
        floor_missing=floor_missing,
        unpinned=unpinned,
        filtered=bool(only),
        socket_tail=max(
            (suite.socket_tail or "" for suite in runnable + covered),
            key=lambda tail: len(_socket_tail_path(tail)), default="",
        ),
    )


# ── execution ────────────────────────────────────────────────────────────────


def base_environment(document: dict, python: str) -> dict[str, str]:
    """Environment copied into suite processes before task-local values are set.

    Only the manifest's allowlist is kept: an operator's GDD_*, OMP_*, PASEO_* or
    profile variables must not reach a suite.  PATH gets the running interpreter's
    directory — as selected, symlink and all — prepended, so a suite's own `python3` is
    the interpreter that carries the repository dependencies, and the shim toolchain's
    state directories are pinned by absolute path (`shim_state_environment`) so a
    task-local HOME cannot move them.
    """
    allowed = list((document.get("env") or {}).get("passthrough") or ["PATH"])
    environment = {name: os.environ[name] for name in allowed if name in os.environ}
    # Lexical on purpose: `Path(python).resolve()` would follow a POSIX virtual environment's
    # `bin/python3` symlink to the base interpreter and prepend *that* directory instead, so a
    # suite's own `python3`, `env python3` shebang and PATH lookup would stop using the
    # environment that carries the repository dependencies (§4.3).
    interpreter_dir = os.path.dirname(os.path.abspath(python))
    existing = environment.get("PATH", "")
    environment["PATH"] = os.pathsep.join(
        part for part in (interpreter_dir, existing) if part
    )
    environment.update(shim_state_environment(os.environ.get("HOME")))
    # Deterministic logs: no tool should colour a captured stream.
    environment.setdefault("NO_COLOR", "1")
    return environment


def shim_state_environment(operator_home: str | None = None) -> dict[str, str]:
    """Absolute state/data directories a PATH shim needs under a task-local HOME.

    mise is the shim manager here: `bun` on PATH resolves to `~/.local/share/mise/shims/bun`,
    and mise resolves its trust database and its installed tools through `MISE_STATE_DIR`
    (default `$HOME/.local/state/mise`) and `MISE_DATA_DIR` (default
    `$HOME/.local/share/mise`).  Suites run with a task-local HOME, so an un-pinned shim
    refuses to exec ("Config files in … are not trusted") or, with only the state directory
    pinned, silently re-installs the tool inside the scratch tree — measured on this host:
    with `MISE_STATE_DIR` alone mise downloaded bun again (7.6 s), with both it ran the
    existing 1.4.4 immediately.  Each variable comes from the operator's own setting when
    present, otherwise from the operator's HOME when that location exists.  This is
    deliberately *not* a general `MISE_*` passthrough, and the task-local HOME stays.
    """
    environment: dict[str, str] = {}
    for name, default in SHIM_STATE_DEFAULTS.items():
        configured = os.environ.get(name)
        if configured:
            environment[name] = str(Path(configured).expanduser().resolve())
            continue
        if not operator_home:
            continue
        candidate = Path(operator_home) / default
        if candidate.is_dir():
            environment[name] = str(candidate)
    return environment


def scratch_root_for(override: str | None = None) -> Path:
    """Task-local scratch root for one run: short, and outside the checkout by default.

    An explicit `--scratch` override is honoured as given, checkout included; only the default
    is placed outside it.  `/tmp` is preferred over `tempfile`'s default chain on purpose: the
    default honours an inherited `TMPDIR`, and an operator `TMPDIR` long enough pushes the
    suites' tmux sockets past the AF_UNIX `sun_path` limit (see `socket_path_length`).
    Platforms without a writable `/tmp` keep the standard chain — `TMPDIR`, `TEMP`, `TMP`,
    then the OS default — and any root that cannot hold a socket is reported per suite before
    it runs.
    """
    if override:
        path = Path(override).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path
    if SHORT_TEMP_ROOT.is_dir():
        created = _mkdtemp(str(SHORT_TEMP_ROOT))
        if created is not None:
            return created
    return Path(tempfile.mkdtemp(prefix=SCRATCH_PREFIX))


def _mkdtemp(parent: str) -> Path | None:
    """`mkdtemp` under `parent`, or None when that parent cannot hold a directory."""
    try:
        return Path(tempfile.mkdtemp(prefix=SCRATCH_PREFIX, dir=parent))
    except OSError:
        return None


def _socket_tail_path(tail: str) -> str:
    """A declared `socket_tail` with `{uid}` substituted; an unformattable tail as declared."""
    uid = os.getuid() if hasattr(os, "getuid") else 0
    try:
        return tail.format(uid=uid)
    except (KeyError, IndexError, ValueError):
        return tail


def socket_path_length(scratch: Path, tail: str = "") -> int | None:
    """Worst-case AF_UNIX socket path length (bytes) a suite can build below `scratch`.

    The bound comes from `sun_path` in `struct sockaddr_un`: 108 bytes on Linux *including*
    the terminating NUL, i.e. a 107-byte path.  tmux is the toolkit in this repository that
    needs it — its socket is `<TMUX_TMPDIR or /tmp>/tmux-<uid>/default` (tmux ignores `TMPDIR`)
    — and the deepest tree a suite builds below its task-local TMPDIR is that suite's own
    `socket_tail` declaration in `scripts/test_manifest.toml`, where `{uid}` is the running
    user's id.
    Returns None where AF_UNIX does not apply.
    """
    if os.name != "posix":
        return None
    return len(os.fsencode(str(scratch) + _socket_tail_path(tail)))


def _suite_slug(suite_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", suite_id).strip("-") or "suite"


def _write_report(report_path: Path | None, payload: dict) -> None:
    if report_path is None:
        return
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class Teardown:
    """What a teardown established, and what it could not.

    `clauses` names the steps that really terminated something — "process group" for a group
    teardown, "detached processes" for a scratch sweep — so a record cannot claim a termination
    that never ran or never signalled; `survivors` are the pids still running after SIGKILL;
    `verified` is False where the teardown could not observe or justify its own outcome — no
    process enumeration on this platform, or a group whose ownership could not be established and
    which is then not signalled at all — with `unverified` naming that limit.
    """

    survivors: tuple[int, ...] = ()
    verified: bool = True
    clauses: tuple[str, ...] = ()
    unverified: str = ""

    def merge(self, other: "Teardown") -> "Teardown":
        return Teardown(
            survivors=tuple(sorted(set(self.survivors) | set(other.survivors))),
            verified=self.verified and other.verified,
            clauses=tuple(dict.fromkeys(self.clauses + other.clauses)),
            unverified="; ".join(dict.fromkeys(
                part for part in (self.unverified, other.unverified) if part)),
        )

    def describe(self) -> str:
        """What the teardown could establish, for the suite's record."""
        claims: list[str] = []
        if self.clauses and not self.survivors:
            claims.append(" and ".join(self.clauses) + " terminated")
        if not self.verified:
            claims.append(self.unverified or "teardown is unverified")
        if self.survivors:
            claims.append("teardown incomplete: pids "
                          + ", ".join(str(pid) for pid in self.survivors) + " survived SIGKILL")
        return "; ".join(claims) if claims else "no processes remained to be terminated"


def _proc_state(pid: int) -> str | None:
    """The state letter of `pid` (`Z` for a zombie), or None when it is gone or unreadable."""
    try:
        with open(PROC_ROOT / str(pid) / "stat", "rb") as handle:
            fields = handle.read().rsplit(b") ", 1)[-1].split()
    except OSError:
        return None
    return fields[0].decode() if fields else None


def _proc_pids() -> list[int] | None:
    """Pids this platform can still see, or None when it cannot enumerate them.

    Zombies are left out: a zombie is terminated, holds no scratch and cannot be signalled again —
    only its parent's `wait` is outstanding, and that parent may not be the runner.
    """
    if not PROC_ROOT.is_dir():
        return None
    try:
        names = os.listdir(PROC_ROOT)
    except OSError:
        return None
    return [int(name) for name in names
            if name.isdigit() and _proc_state(int(name)) not in (None, "Z")]


def _group_members(group: int) -> list[int] | None:
    """Live pids still in process group `group`, or None where nothing can be enumerated.

    Group liveness is asked independently of the leader on purpose: `process.wait()` returning
    says the leader exited, not that its group is empty.
    """
    pids = _proc_pids()
    if pids is None:
        return None
    members: list[int] = []
    for pid in pids:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            if os.getpgid(pid) == group:
                members.append(pid)
    return members


def _refers_to_scratch(pid: int, needle: bytes) -> bool:
    """Whether `pid` still points into `needle` (a suite's scratch path, as bytes).

    `cwd` is a symlink, not a file, so it is read with `readlink` — a symlink into a deleted
    directory still carries the scratch path, with a trailing " (deleted)".  `environ` is a
    file and is read as bytes.  Either one is enough: a worker that sanitized its environment
    still carries the cwd it was started in, and one started outside the tree still inherited
    the scratch paths of its environment.
    """
    with contextlib.suppress(OSError):
        if needle in os.fsencode(os.readlink(PROC_ROOT / str(pid) / "cwd")):
            return True
    with contextlib.suppress(OSError):
        if needle in (PROC_ROOT / str(pid) / "environ").read_bytes():
            return True
    return False


def _scratch_processes(scratch: Path) -> list[int] | None:
    """Live pids, other than the runner itself, that still point into `scratch`.

    A detached worker (`start_new_session`) leaves the suite's process group, so no group signal can
    reach it; it does keep the task-local paths it inherited, and that is what identifies it from
    outside — the cwd it was started in, or the HOME/TMPDIR/XDG root the suite's environment put in
    its environment.  None where nothing can be enumerated.
    """
    pids = _proc_pids()
    if pids is None:
        return None
    needle = os.fsencode(str(scratch))
    own = os.getpid()
    return [pid for pid in pids if pid != own and _refers_to_scratch(pid, needle)]


def _wait_until_gone(match: Callable[[], list[int] | None], deadline: float) -> list[int] | None:
    """What `match` still finds at `deadline` (empty when nothing), or None when unenumerable."""
    while True:
        found = match()
        if not found or time.monotonic() >= deadline:
            return found
        time.sleep(TEARDOWN_POLL_SECONDS)


def _stop_matching(match: Callable[[], list[int] | None], log) -> Teardown:
    """SIGTERM then SIGKILL every process `match` accepts, re-checking between the rounds.

    The predicate is re-evaluated after each round, so a process that outlives its parent — a
    detached worker's own child — is found and signalled too.  A process that outlasts SIGKILL is
    recorded as a survivor, never assumed dead; a platform that cannot enumerate processes returns
    an unverified teardown rather than a clean one.  The caller is the scratch sweep, whose matches
    are the suite's detached holders, so a completed teardown records them as such.
    """
    found = match()
    if found is None:
        return Teardown(verified=False, unverified=NO_ENUMERATION)
    signalled = False
    for signum in (signal.SIGTERM, signal.SIGKILL):
        if not found:
            break
        log.write(f"[discoverer] teardown: {signal.Signals(signum).name} to "
                  f"{len(found)} process(es) {sorted(found)}\n".encode())
        log.flush()
        signalled = True
        for pid in found:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(pid, signum)
        found = _wait_until_gone(match, time.monotonic() + KILL_GRACE_SECONDS)
        if found is None:
            return Teardown(verified=False, unverified=NO_ENUMERATION)
    if found:
        log.write(f"[discoverer] teardown: pids {sorted(found)} survived SIGKILL\n".encode())
        log.flush()
        return Teardown(survivors=tuple(sorted(found)))
    return Teardown(clauses=("detached processes",) if signalled else ())


def _sweep_scratch(scratch: Path, log_path: Path) -> Teardown:
    """Stop the processes still holding `scratch`, before the runner deletes that tree.

    Deleting the tree first would leave a launcher's watcher polling records that no longer exist.
    """
    with log_path.open("ab") as log:
        return _stop_matching(lambda: _scratch_processes(scratch), log)


def _group_alive(group: int) -> bool:
    """Whether any process still names `group`, asked through the group API alone (no /proc)."""
    try:
        os.killpg(group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _group_running(group: int) -> bool:
    """Whether live processes remain in `group` (zombies excluded where /proc can say)."""
    members = _group_members(group)
    if members is not None:
        return bool(members)
    return _group_alive(group)


def _stop_group(group: int, log) -> Teardown:
    """SIGTERM then SIGKILL the process group `group`, re-checking between the rounds.

    The signal goes out through `os.killpg`, so a platform with the POSIX group API needs no /proc
    to reach the group; the re-check names live members from /proc where it can and otherwise falls
    back to the group's own signal-0 probe.  Called only for a group this run proved is its own
    (`_owned_group`).
    """
    signalled = False
    for signum in (signal.SIGTERM, signal.SIGKILL):
        if not _group_running(group):
            break
        log.write(f"[discoverer] teardown: {signal.Signals(signum).name} to process group "
                  f"{group}\n".encode())
        log.flush()
        signalled = True
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(group, signum)
        deadline = time.monotonic() + KILL_GRACE_SECONDS
        while time.monotonic() < deadline and _group_running(group):
            time.sleep(TEARDOWN_POLL_SECONDS)
    return Teardown(clauses=("process group",) if signalled else ())


def _owned_group(process: subprocess.Popen) -> int | None:
    """The group `process` provably leads, or None where ownership cannot be established.

    Two checks, each load-bearing: this run has not reaped the process (`returncode`), and its pid
    still names the group that process leads (`os.getpgid`) — the module docstring's ownership rule.
    """
    if process.returncode is not None:
        return None
    with contextlib.suppress(ProcessLookupError, PermissionError):
        if os.getpgid(process.pid) == process.pid:
            return process.pid
    return None


def _group_verdict(group: int) -> Teardown:
    """What remains of `group`, asked after the leader this run reaps is out of the way."""
    members = _group_members(group)
    if members is not None:
        return Teardown(survivors=tuple(sorted(members))) if members else Teardown()
    if _group_alive(group):
        return Teardown(verified=False, unverified=(
            "the group outlived SIGKILL and this platform cannot enumerate its members, "
            "so teardown is unverified"))
    return Teardown()


def _observe_exit(process: subprocess.Popen, timeout: float) -> int | None:
    """The exit code `process` reaches within `timeout` seconds, or None at the deadline.

    POSIX observes the exit without reaping the child (`waitid` with `WNOWAIT`) — the state the
    ownership proof reads (`_owned_group`); where that observation is unavailable, and with it any
    POSIX group to own, `subprocess`'s own wait is used.  The value follows `subprocess`: a negative
    number is the killing signal.
    """
    if not WAITID_WNOWAIT:
        try:
            return process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None
    deadline = time.monotonic() + timeout
    while True:
        info = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOWAIT | os.WNOHANG)
        if info is not None:
            return info.si_status if info.si_code == os.CLD_EXITED else -info.si_status
        if time.monotonic() >= deadline:
            return None
        time.sleep(min(EXIT_POLL_SECONDS, max(deadline - time.monotonic(), 0.001)))


def _run_commands(commands: tuple[tuple[str, ...], ...], *, cwd: Path, env: dict[str, str],
                  timeout: float, log_path: Path,
                  appending: bool = False) -> tuple[int | None, bool, float, Teardown]:
    """Run argv vectors in order into one log file; return code, timeout, seconds, teardown.

    A command that timed out or died by a signal is torn down before this returns, while its own
    process is still unreaped — the state the teardown's ownership proof reads (`_owned_group`).
    """
    started = time.monotonic()
    last_code: int | None = 0
    with log_path.open("ab" if appending else "wb") as log:
        for argv in commands:
            log.write(f"=== {_display(argv)}\n".encode())
            log.flush()
            try:
                process = subprocess.Popen(  # noqa: S603 - declared argv, no shell
                    list(argv),
                    cwd=str(cwd),
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            except OSError as exc:
                log.write(f"\n[discoverer] cannot start {_display(argv)}: {exc}\n".encode())
                return None, False, time.monotonic() - started, Teardown()
            remaining = max(timeout - (time.monotonic() - started), 0.1)
            last_code = _observe_exit(process, remaining)
            if last_code is None:
                teardown = _terminate_group(process, log)
                return process.poll(), True, time.monotonic() - started, teardown
            if last_code < 0:
                # A signal killed the command: its own cleanup callbacks did not run, and its
                # process may still be unreaped, so the teardown still has an ownership anchor.
                teardown = _terminate_group(process, log)
                return last_code, False, time.monotonic() - started, teardown
            process.wait()  # what `_observe_exit` saw is reaped here; teardown does not need it
            if last_code != 0:
                break
    return last_code, False, time.monotonic() - started, Teardown()


def _display(argv: tuple[str, ...]) -> str:
    return " ".join(argv)


def _terminate_group(process: subprocess.Popen, log) -> Teardown:
    """Terminate the process group of the command `process` was spawned for, escalating to SIGKILL.

    Ownership decides everything here (module docstring): the group is signalled only while
    `_owned_group` can still prove it is the run's own, and otherwise nothing is signalled and the
    record says teardown is unverified.  The leader itself is reaped here — it is the run's own
    child, and the one group member that no signal of ours can ever remove.
    """
    if not hasattr(os, "killpg"):
        # No POSIX groups: the command's own process is all that can be stopped, and nothing here
        # can be enumerated — the record must not claim a teardown nothing observed.
        unverified = "this platform has no process groups, so teardown is unverified"
        process.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=KILL_GRACE_SECONDS)
        if process.poll() is None:
            return Teardown(survivors=(process.pid,), verified=False, unverified=unverified)
        return Teardown(verified=False, unverified=unverified)
    group = _owned_group(process)
    if group is None:
        log.write(b"\n[discoverer] teardown: process group not signalled: ownership cannot be "
                  b"established\n")
        log.flush()
        teardown = Teardown(verified=False, unverified=(
            "the process group could not be proven to be the suite's, so teardown is unverified"))
    else:
        log.write(f"\n[discoverer] teardown: terminating process group {group}\n".encode())
        log.flush()
        teardown = _stop_group(group, log)
    if process.poll() is None:
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=KILL_GRACE_SECONDS)
    if process.poll() is None:
        # A leader still unreaped after its group is gone is recorded, not raised: teardown must
        # never take the whole run down with it.
        log.write(f"[discoverer] suite process {process.pid} still not reaped "
                  f"{KILL_GRACE_SECONDS:g}s after teardown\n".encode())
        log.flush()
        teardown = teardown.merge(Teardown(survivors=(process.pid,)))
    if group is not None:
        # Asked after the reap: a group whose members are all gone can still look occupied while
        # the run's own unreaped leader is a member of it.
        teardown = teardown.merge(_group_verdict(group))
    return teardown


def _read_log(path: Path, limit: int | None = None) -> str:
    """The log's tail (its last LOG_TAIL_BYTES), optionally cut to its last `limit` lines."""
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(size - LOG_TAIL_BYTES, 0))
            text = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
    if limit is None:
        return text
    return "\n".join(_plain(text).splitlines()[-limit:])


def _plain(output: str) -> str:
    """Output with ANSI colour sequences removed."""
    return ANSI_ESCAPE.sub("", output)


def parse_unittest_counts(output: str) -> dict:
    """Executed/skipped counts from a unittest summary, or {} when there is none."""
    output = _plain(output)
    summary = None
    for match in UNITTEST_SUMMARY.finditer(output):
        summary = match
    if summary is None:
        return {}
    counts = {"executed": int(summary.group(1))}
    skipped = UNITTEST_SKIPPED.search(output[summary.end():])
    if skipped:
        counts["skipped"] = int(skipped.group(1))
    return counts


def parse_counter_counts(output: str, patterns: tuple[str, ...]) -> dict:
    """Counts from the last line matching any declared pattern, or {}."""
    compiled = [re.compile(pattern) for pattern in patterns]
    match = None
    for line in _plain(output).splitlines():
        for regex in compiled:
            found = regex.search(line)
            if found is not None:
                match = found
    if match is None:
        return {}
    groups = match.groupdict()
    counts: dict[str, int] = {}
    if groups.get("passed") is not None:
        counts["passed"] = int(groups["passed"])
        counts["executed"] = int(groups.get("total") or groups["passed"])
    if groups.get("total") is not None:
        counts["total"] = int(groups["total"])
    if groups.get("skipped") is not None:
        counts["skipped"] = int(groups["skipped"])
    return counts


def _counts_consistent(counts: dict) -> bool:
    """A passing counter line may not hide unaccounted checks.

    `total` counts everything the suite says it executed; every check that did not pass must be a
    declared skip, or the exit status and the count disagree.
    """
    passed = counts.get("passed", 0)
    total = counts.get("total")
    if total is None:
        return True
    if total < passed:
        return False
    return total == passed or passed + counts.get("skipped", 0) == total


def _unittest_shortfall(counts: dict) -> str | None:
    """Why a unittest summary cannot support PASS, or None when at least one check really ran.

    `Ran N tests` is unittest's *collection* count: all N may be skipped, and an all-skipped summary
    would otherwise pass with nothing executed (§4.5).  A suite that runs some checks and skips
    others is still fine; zero non-skipped checks is not.
    """
    if not counts:
        return "no unittest summary in the output (`Ran N tests` absent)"
    collected = counts.get("executed", 0)
    if collected < 1:
        return "Ran 0 tests: the suite collected nothing"
    if counts.get("skipped", 0) >= collected:
        return f"Ran {collected} tests, all skipped: zero executed checks"
    return None


def _teardown_note(teardown: Teardown | None) -> str:
    """What the caller observed about teardown; None says so instead of naming one."""
    return teardown.describe() if teardown is not None else "teardown was not observed"


def settle(suite: Suite, *, exit_code: int | None, timed_out: bool, output: str,
           provisioned: bool = True, timeout: float | None = None,
           teardown: Teardown | None = None) -> tuple[str, dict, str]:
    """Settle one scheduled suite as PASS, FAIL, ERROR or TIMEOUT."""
    if timed_out:
        effective = suite.timeout if timeout is None else timeout
        return "TIMEOUT", {}, f"timeout after {effective:g}s; {_teardown_note(teardown)}"
    if not provisioned:
        return "ERROR", {}, "provisioning failed"
    if exit_code is None:
        return "ERROR", {}, "the suite process could not be started"
    if exit_code < 0:
        return "ERROR", {}, f"terminated by signal {-exit_code}; {_teardown_note(teardown)}"

    counts: dict = {}
    if suite.assertion == "unittest":
        counts = parse_unittest_counts(output)
        shortfall = _unittest_shortfall(counts)
        if shortfall:
            return "ERROR", counts, shortfall
    elif suite.assertion == "counter":
        counts = parse_counter_counts(output, suite.count_regexes)
        if exit_code != 0:
            reason = "suite reported a failing case" if counts else "no counter line in the output"
            return "FAIL", counts, reason
        if not counts:
            return "ERROR", {}, "no counter line matching count_regexes"
        if counts.get("passed", 0) < 1:
            return "ERROR", counts, "zero executed checks"
        if not _counts_consistent(counts):
            return "ERROR", counts, "counter line disagrees with the exit status"
        state, reason = "PASS", "ok"
        return _apply_require_regex(suite, state, reason, counts, output)
    else:
        if exit_code != 0:
            return "FAIL", {}, f"exit {exit_code}"

    state, reason = ("PASS", "ok") if exit_code == 0 else ("FAIL", f"exit {exit_code}")
    return _apply_require_regex(suite, state, reason, counts, output)


def _apply_require_regex(suite: Suite, state: str, reason: str, counts: dict,
                         output: str) -> tuple[str, dict, str]:
    if state == "PASS" and suite.require_regex:
        if not re.search(suite.require_regex, _plain(output), re.MULTILINE):
            return "ERROR", counts, f"required output missing: /{suite.require_regex}/"
    return state, counts, reason


def run_suite(suite: Suite, *, root: Path, scratch_root: Path, log_root: Path,
              environment: dict[str, str], timeout_override: float | None = None,
              socket_tail: str = "") -> Outcome:
    """Run one suite in its own process, group and task-local scratch tree."""
    slug = _suite_slug(suite.id)
    # Short directory name: AF_UNIX paths are capped (see `socket_path_length`).
    scratch_root.mkdir(parents=True, exist_ok=True)  # never fail to isolate for want of a directory
    suite_scratch = Path(tempfile.mkdtemp(prefix=f"{slug[:12]}-", dir=scratch_root))
    worst_case = socket_path_length(suite_scratch, socket_tail)
    if worst_case is not None and worst_case >= AF_UNIX_PATH_LIMIT:
        shutil.rmtree(suite_scratch, ignore_errors=True)
        return Outcome(
            suite_id=suite.id, state="ERROR", duration=0.0,
            reason=(f"task-local scratch is too long for an AF_UNIX socket: worst case "
                    f"{worst_case} bytes >= the {AF_UNIX_PATH_LIMIT}-byte sun_path limit "
                    f"(scratch root {scratch_root}); use a shorter TMPDIR or --scratch"),
            covered_by=suite.covered_by,
        )
    directories = {
        "tmp": suite_scratch / "tmp",
        "home": suite_scratch / "home",
        "xdg-config": suite_scratch / "xdg-config",
        "xdg-cache": suite_scratch / "xdg-cache",
        "xdg-data": suite_scratch / "xdg-data",
        "xdg-state": suite_scratch / "xdg-state",
    }
    for directory in directories.values():
        directory.mkdir(parents=True)

    env = dict(environment)
    env.update({
        "HOME": str(directories["home"]),
        "TMPDIR": str(directories["tmp"]),
        "TMP": str(directories["tmp"]),
        "TEMP": str(directories["tmp"]),
        "XDG_CONFIG_HOME": str(directories["xdg-config"]),
        "XDG_CACHE_HOME": str(directories["xdg-cache"]),
        "XDG_DATA_HOME": str(directories["xdg-data"]),
        "XDG_STATE_HOME": str(directories["xdg-state"]),
        "PYTHONPATH": str(root),
        "PYTHONDONTWRITEBYTECODE": "1",
        "GIT_TERMINAL_PROMPT": "0",
    })
    env.update(dict(suite.env))

    log_path = log_root / f"{slug}.log"
    timeout = float(timeout_override or suite.timeout)
    provisioned = True
    if suite.provision:
        code, timed_out, _, teardown = _run_commands(suite.provision, cwd=suite.cwd, env=env,
                                                     timeout=timeout, log_path=log_path)
        provisioned = not timed_out and code == 0
        if not provisioned:
            reason = "provisioning failed: " + _display(suite.provision[0])
            if timed_out or (code is not None and code < 0):
                teardown = teardown.merge(_sweep_scratch(suite_scratch, log_path))
                reason += "; " + teardown.describe()
            outcome = Outcome(
                suite_id=suite.id, state="ERROR", duration=0.0, exit_code=code,
                reason=reason,
                log=str(log_path), tail=_read_log(log_path, 25), covered_by=suite.covered_by,
            )
            shutil.rmtree(suite_scratch, ignore_errors=True)
            return outcome

    code, timed_out, duration, teardown = _run_commands(suite.commands, cwd=suite.cwd, env=env,
                                                       timeout=timeout, log_path=log_path,
                                                       appending=bool(suite.provision))
    if timed_out or (code is not None and code < 0):
        # The suite's own cleanup callbacks did not run — the runner timed it out, or a signal
        # killed it — so stop what still holds its scratch before that tree is deleted.
        teardown = teardown.merge(_sweep_scratch(suite_scratch, log_path))
    output = _read_log(log_path)
    state, counts, reason = settle(suite, exit_code=code, timed_out=timed_out, output=output,
                                   provisioned=provisioned, timeout=timeout, teardown=teardown)
    outcome = Outcome(
        suite_id=suite.id, state=state, duration=round(duration, 3), exit_code=code,
        reason=reason, counts=counts, log=str(log_path),
        tail=_read_log(log_path, 25) if state != "PASS" else "", covered_by=suite.covered_by,
    )
    shutil.rmtree(suite_scratch, ignore_errors=True)
    return outcome


def settle_covered(child: Suite, parent: Suite, parent_outcome: Outcome,
                   parent_log: Path) -> Outcome:
    """Derive a covered child's state from the parent that executes it."""
    if parent_outcome.state == "SKIP":
        return Outcome(
            suite_id=child.id, state="SKIP", duration=0.0,
            reason=f"not attempted: parent {parent.id} skipped ({parent_outcome.reason})",
            log=str(parent_log), covered_by=parent.id,
        )
    if parent_outcome.state != "PASS":
        return Outcome(
            suite_id=child.id, state="ERROR", duration=0.0,
            reason=f"parent {parent.id} settled {parent_outcome.state}",
            log=str(parent_log), covered_by=parent.id,
        )
    output = _read_log(parent_log)
    counts: dict = {}
    if child.assertion == "counter":
        counts = parse_counter_counts(output, child.count_regexes)
        if not counts:
            return Outcome(
                suite_id=child.id, state="ERROR",
                reason=f"parent {parent.id} ran but shows no evidence for this suite "
                       f"(count_regexes unmatched)",
                log=str(parent_log), covered_by=parent.id,
            )
        if counts.get("passed", 0) < 1:
            return Outcome(
                suite_id=child.id, state="ERROR", counts=counts,
                reason="zero executed checks in the parent's evidence",
                log=str(parent_log), covered_by=parent.id,
            )
        if not _counts_consistent(counts):
            return Outcome(
                suite_id=child.id, state="ERROR", counts=counts,
                reason="counter line disagrees with the parent's exit status",
                log=str(parent_log), covered_by=parent.id,
            )
    elif child.assertion == "unittest":
        counts = parse_unittest_counts(output)
        shortfall = _unittest_shortfall(counts)
        if shortfall:
            return Outcome(
                suite_id=child.id, state="ERROR", counts=counts,
                reason=f"parent {parent.id}: {shortfall}",
                log=str(parent_log), covered_by=parent.id,
            )
    return Outcome(
        suite_id=child.id, state="PASS", counts=counts,
        reason=f"covered by {parent.id}", log=str(parent_log), covered_by=parent.id,
    )


# ── reporting ────────────────────────────────────────────────────────────────


def _print_plan(plan: Plan) -> None:
    print(f"plan: {len(plan.scheduled)} scheduled, {len(plan.covered)} covered child(ren), "
          f"{len(plan.skipped)} condition-skipped, {len(plan.discovered)} discovered paths")
    for suite in plan.scheduled:
        print(f"  {suite.origin:<10} {suite.id:<70} {suite.runtime:<6} "
              f"{_display(suite.commands[0])}  assertion={suite.assertion}")
        _print_declarations(suite)
    for suite in plan.skipped:
        print(f"  {'skipped':<10} {suite.id:<70} {suite.runtime:<6} condition={suite.condition}")
        _print_declarations(suite)
    for child in plan.covered:
        print(f"  {'covered':<10} {child.id:<70} covered_by={child.covered_by}")
        _print_declarations(child)
    for problem in plan.problems:
        print(f"problem: {problem}")
    if not plan.filtered:
        print(f"floor: {len(plan.discovered)} discovered, "
              f"{len(plan.floor_missing)} pinned missing, {len(plan.unpinned)} unpinned")


def _print_declarations(suite: Suite) -> None:
    """Print the manifest declarations of one planned suite.

    `detached` and `socket_tail` are declarative boundaries (teardown, AF_UNIX room); both are
    also carried per suite in the JSON record, and printing them here is what keeps them from
    drifting unseen.  `socket_tail` additionally bounds the run: `build_plan` carries the
    deepest declared tail and `run_suite` settles a suite ERROR before spawning it when that
    tail cannot fit below its scratch root.
    """
    if suite.detached:
        print(f"      detached: {suite.detached}")
    if suite.socket_tail:
        print(f"      socket_tail: {suite.socket_tail}")
    if suite.notes:
        print(f"      notes: {suite.notes}")


def _payload(plan: Plan, outcomes: list[Outcome], *, event: str, root: Path, python: str,
             started: str, duration: float, exit_code: int, log_root: Path,
             scratch_root: Path, shim_state: dict[str, str], summary: dict[str, int],
             suites: dict[str, Suite]) -> dict:
    return {
        "schema": 1,
        "event": event,
        "root": str(root),
        "python": python,
        "revision": os.environ.get("GITHUB_SHA") or None,
        "started_at": started,
        "duration_seconds": round(duration, 3),
        "filtered": plan.filtered,
        "logs": str(log_root),
        "scratch_root": str(scratch_root),
        "shim_state": shim_state,
        "discovery": {
            "pattern_matches": len(plan.discovered),
            "floor_missing": plan.floor_missing,
            "unpinned": plan.unpinned,
        },
        "planned": {
            "scheduled": len(plan.scheduled),
            "covered": len(plan.covered),
            "condition_skipped": len(plan.skipped),
        },
        "settled": len(outcomes),
        "summary": summary,
        "problems": plan.problems,
        "exit_code": exit_code,
        "suites": [_suite_record(outcome, suites.get(outcome.suite_id))
                   for outcome in outcomes],
    }


def _suite_record(outcome: Outcome, suite: Suite | None) -> dict:
    """The record's per-suite entry: how it settled plus its manifest declarations."""
    return {
        "id": outcome.suite_id,
        "state": outcome.state,
        "duration_seconds": outcome.duration,
        "exit_code": outcome.exit_code,
        "reason": outcome.reason,
        "counts": outcome.counts,
        "covered_by": outcome.covered_by,
        "detached": suite.detached if suite else None,
        "socket_tail": suite.socket_tail if suite else None,
        "notes": suite.notes if suite else None,
        "log": outcome.log,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Discover, isolate and settle every repository test suite.")
    parser.add_argument("--root", default=None, help="repository root (default: this checkout)")
    parser.add_argument("--manifest", default=None, help="manifest path (default: scripts/test_manifest.toml)")
    parser.add_argument("--suite", action="append", default=None, metavar="ID",
                        help="run only this suite id (repeatable)")
    parser.add_argument("--event", default=None,
                        help="CI event name; defaults to $GITHUB_EVENT_NAME, else 'local'")
    parser.add_argument("--timeout", type=float, default=None,
                        help=f"override every suite timeout (default: {DEFAULT_TIMEOUT:g}s)")
    parser.add_argument("--scratch", default=None,
                        help="task-local scratch root (default: a fresh directory in the "
                             "system temp directory, outside the checkout)")
    parser.add_argument("--report", default=None,
                        help="write the JSON result record here (default: <run root>/result.json)")
    parser.add_argument("--list", action="store_true", dest="list_only", help="print the plan only")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve() if args.root else REPO_ROOT
    manifest_path = Path(args.manifest).resolve() if args.manifest \
        else root / MANIFEST_RELATIVE
    event = args.event or os.environ.get("GITHUB_EVENT_NAME") or "local"
    python = sys.executable
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    try:
        document = load_manifest(manifest_path)
        plan = build_plan(root, document, event=event, only=args.suite, python=python)
    except ManifestError as exc:
        print(f"discoverer: {exc}", file=sys.stderr)
        return 2

    _print_plan(plan)
    if args.list_only:
        return 2 if plan.problems else 0
    by_suite = {suite.id: suite for suite in plan.scheduled + plan.covered + plan.skipped}

    stamp = f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{os.getpid()}"
    scratch_root = scratch_root_for(args.scratch)
    run_root = root / ".tmp-artifacts" / "test-runs" / stamp
    log_root = run_root / "logs"
    log_root.mkdir(parents=True, exist_ok=True)
    report_path = Path(args.report).resolve() if args.report else run_root / "result.json"
    environment = base_environment(document, python)
    shim_state = {name: environment[name] for name in SHIM_STATE_DEFAULTS if name in environment}

    outcomes: list[Outcome] = []
    by_id: dict[str, Outcome] = {}
    started_clock = time.monotonic()
    total = plan.settled_total
    index = 0
    for suite in plan.skipped:
        index += 1
        outcome = Outcome(suite_id=suite.id, state="SKIP",
                          reason=suite.skip_reason or f"condition {suite.condition} not met")
        print(f"[{index:>3}/{total}] {'SKIP':<7} {'-':>7}  {suite.id} ({outcome.reason})")
        outcomes.append(outcome)
        by_id[suite.id] = outcome
    for suite in plan.scheduled:
        index += 1
        outcome = run_suite(suite, root=root, scratch_root=scratch_root, log_root=log_root,
                            environment=environment, timeout_override=args.timeout,
                            socket_tail=plan.socket_tail)
        outcomes.append(outcome)
        by_id[suite.id] = outcome
        print(f"[{index:>3}/{total}] {outcome.state:<7} {outcome.duration:>6.2f}s  {suite.id}"
              f"{'' if outcome.state == 'PASS' else '  ' + outcome.reason}")
        if outcome.tail and outcome.state != "PASS":
            for line in outcome.tail.splitlines()[-25:]:
                print(f"      | {line}")
    for child in plan.covered:
        index += 1
        parent = by_suite[child.covered_by]
        parent_outcome = by_id.get(parent.id)
        if parent_outcome is None:
            outcome = Outcome(suite_id=child.id, state="ERROR",
                              reason=f"parent {parent.id} did not run in this selection")
        else:
            outcome = settle_covered(child, parent, parent_outcome,
                                     Path(parent_outcome.log or ""))
        outcomes.append(outcome)
        by_id[child.id] = outcome
        print(f"[{index:>3}/{total}] {outcome.state:<7} {'-':>7}  {outcome.suite_id} ({outcome.reason})")

    duration = time.monotonic() - started_clock
    summary: dict[str, int] = {state: 0 for state in TERMINAL_STATES}
    for outcome in outcomes:
        summary[outcome.state] = summary.get(outcome.state, 0) + 1
    failed = [
        outcome.suite_id for outcome in outcomes
        if outcome.state in FAILING_STATES
        and by_suite[outcome.suite_id].required
    ]
    print(f"summary: " + " ".join(f"{state} {summary[state]}" for state in TERMINAL_STATES)
          + f" (settled {len(outcomes)}/{total}; {duration:.1f}s)")
    if plan.floor_missing:
        print(f"floor: unmet ({len(plan.floor_missing)} pinned suites missing)")
    if plan.unpinned:
        print(f"floor: ok; {len(plan.unpinned)} unpinned discoveries: "
              + ", ".join(plan.unpinned))
    print(f"logs: {log_root}")
    if not args.scratch:
        with contextlib.suppress(OSError):
            scratch_root.rmdir()  # only when every suite cleaned up after itself

    exit_code = 2 if plan.problems else (1 if failed else 0)
    if failed:
        print("failed: " + ", ".join(failed))
    _write_report(report_path,
                  _payload(plan, outcomes, event=event, root=root, python=python,
                           started=started, duration=duration, exit_code=exit_code,
                           log_root=log_root, scratch_root=scratch_root,
                           shim_state=shim_state, summary=summary, suites=by_suite))
    print(f"exit {exit_code}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
