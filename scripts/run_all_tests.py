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
signal killed it (a negative exit status, `settle`).  That teardown terminates the one process this
run spawned — the process whose identity the run recorded itself (`_spawned`) — and reports, without
touching them, what that command left behind: the members of the group the command led
(`_group_report`), and the processes still holding the suite's task-local scratch, found by the cwd
they were started in or the scratch paths in their environment (`_scratch_processes`; both reports
read `/proc`).  No other process is ever signalled — not a same-group member, not a scratch holder,
not a descendant — because a process this run did not spawn is not one it can prove it may signal:
such a process is left running, and the suite's teardown is `unverified` whenever one is found, with
the note that names it saying so.  Nothing is ever broadcast to a process group either, and no
signal ever goes through a bare pid or group number: the only target is the pid this run recorded at
spawn, signalled through a handle that carries that target's identity.

Identity is pinned at delivery, not sampled before it.  The one process this run signals carries an
identity recorded at spawn: its pid and the start time `/proc/<pid>/stat` field 22 reported then
(`_spawned`).  At delivery a pidfd is opened for that pid, the start time is re-read and must equal
the recorded one, and only then is the signal sent through `signal.pidfd_send_signal(fd, signum)`
(`_pin_identity`, `_signal_spawned`).  The pidfd pins that process instance, so a pid someone else's
reap recycled cannot receive this run's signal, a target that is gone before the signal
(`ProcessLookupError`) is reported as gone instead of being signalled, and a process that has
already terminated takes no signal at all — a delivery to a corpse would be a claim, not a
delivery.  Escalation is TERM, a bounded grace, KILL (`_stop_spawned`), and every round re-pins: a
proof taken earlier, or a handle opened earlier, is never authority for a later delivery.  The
escalation is resolved from the signal names this platform defines, and the capability refusal is
completed before any of them is resolved, so a platform that has no `SIGKILL` records its refusal
and the group it reports instead of raising while the sequence is built.

Before anything is spawned the run also puts its own `SIGCHLD` disposition in `SIG_DFL`
(`establish_exit_disposition`) — under an inherited `SIG_IGN` the kernel reaps a child inside its
own exit and takes the status, and with it the reservation, before the run can see it — and the
exit is observed without reaping the command (`waitid(P_PID, pid, WEXITED | WNOWAIT | WNOHANG)`,
probed once as `WAITID_WNOWAIT`), which is what keeps the pid from being recycled while the teardown
still needs it.  Where any of that proof cannot be held — no established or still-live disposition,
no kernel probe, no pidfd, no `/proc` to read the identity from, a start-time re-check that fails, a
target reaped by someone else — nothing is signalled and the record says teardown is unverified;
there is no weaker fallback, because `Popen`'s cached `returncode` cannot see a reap the kernel
performed and a bare pid or group number can name anything by the time it is used.  The group is
read before a command is reaped, so the members a clean exit left behind are reported while the
number is still the command's own, and the teardown's record — what it terminated, what it found and
left alone, and what it could not verify — is carried into the settled outcome and the result record
on every exit path, clean, timed out or signalled, so a limit is readable by whoever reads the run
and not only by the helper that found it.  A command whose exit can no longer be waited for settles
as an error with an unverified teardown instead of escaping the run.  The gates are ordered and all
of them must hold where a signal is delivered (`_ownership_limit`): the live `SIGCHLD` disposition,
`os.waitid` with `WNOWAIT`, pidfds, and `/proc`; where one does not — macOS and Windows have no
pidfds at all — every teardown refuses and records its limit, and the processes the suite left
behind are left running.  The residual limit, stated plainly: the runner signals only the process it
spawned, so whatever else a suite leaves behind outlives the run.  A scratch tree too long to hold
the toolkit's AF_UNIX socket — given the deepest `socket_tail` the scheduled suites declare in the
manifest — is reported as that suite's ERROR before it runs (`socket_path_length`).
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
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_RELATIVE = Path("scripts") / "test_manifest.toml"
DEFAULT_TIMEOUT = 120.0
LOG_TAIL_BYTES = 128 * 1024
KILL_GRACE_SECONDS = 10.0
EXIT_POLL_SECONDS = 0.05
# The teardown escalation, weakest first, by name rather than by constant: `signal.SIGKILL` is not
# defined on every platform (Windows has none), so the sequence is resolved from the names this
# platform defines, after the capability refusal in `_stop_spawned` has been settled.
ESCALATION_NAMES = ("SIGTERM", "SIGKILL")
# The delivery record's wording, shared with the tests that assert what the run claims about itself:
# one source, so a reworded line cannot silently turn a "no delivery to X" assertion into a check of
# nothing.  The pattern reads the target pid out of a delivery line rather than searching a line for a
# pid's digits, which its start time or another delivery can also contain.
DELIVERY_MARKER = "delivered to pid"
DELIVERY_TARGET_RE = re.compile(rf"\b{re.escape(DELIVERY_MARKER)} (\d+)\b")
# `/proc` is how teardown reads the evidence every delivery is justified by: a process's start time
# (its identity) and the live members of the group the command leads; it is also how the scratch
# sweep finds the holders a suite left behind, since a detached worker (`start_new_session`) leaves
# the suite's process group.
PROC_ROOT = Path("/proc")
# Where Python exposes `waitid` with `WNOWAIT`, a command's exit can be observed without reaping it,
# which is what keeps its pid — and the group that pid names — reserved for the teardown.  The
# exit-state constants are probed with it because they come together; a host without them (macOS
# before Python 3.13) reaps inside the observation instead (module docstring).
WAITID_WNOWAIT = all(hasattr(os, name)
                     for name in ("waitid", "WNOWAIT", "WEXITED", "WNOHANG", "CLD_EXITED"))
# Where Python exposes pidfds, a signal is delivered through a handle that carries the target's
# identity, never through a bare pid or a group number (module docstring).
PIDFD_PINNING = hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal")
NO_ENUMERATION = "this platform cannot enumerate processes"
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
    teardown: Teardown | None = None   # what the suite's teardown established, and its limits


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

    `clauses` names the steps that really terminated their target — "the spawned process" is the
    only one this run ever terminates — so a record cannot claim a termination that never ran or
    never signalled; `survivors` are pids that actually received SIGKILL and outlived it, never a
    process that was merely found (a process this run does not signal is not a survivor); and
    `unverified` names, one note per limit, what the teardown could not observe or justify — no
    process enumeration on this platform, a process found and deliberately left alone because this
    run signals only the process it spawned, a delivery refused because the target's identity could
    not be pinned, a group that could not be read before a reap.  A record is `verified` only when
    it carries neither a limit note nor a survivor.
    """

    survivors: tuple[int, ...] = ()
    clauses: tuple[str, ...] = ()
    unverified: tuple[str, ...] = ()

    @property
    def verified(self) -> bool:
        return not self.unverified and not self.survivors

    def merge(self, other: "Teardown") -> "Teardown":
        return Teardown(
            survivors=tuple(sorted(set(self.survivors) | set(other.survivors))),
            clauses=tuple(dict.fromkeys(self.clauses + other.clauses)),
            unverified=tuple(dict.fromkeys(self.unverified + other.unverified)),
        )

    def describe(self) -> str:
        """What the teardown could establish, for the suite's record."""
        claims: list[str] = []
        if self.clauses:
            claims.append(" and ".join(self.clauses) + " terminated")
        claims.extend(self.unverified)
        if self.survivors:
            claims.append("teardown incomplete: pids "
                          + ", ".join(str(pid) for pid in self.survivors) + " survived SIGKILL")
        return "; ".join(claims) if claims else "no processes remained to be terminated"


def _unverified(statement: str) -> str:
    """One `Teardown` limit note: what could not be established, then the consequence it has."""
    return f"{statement}; teardown is unverified"


def _proc_stat(pid: int) -> list[bytes] | None:
    """The `/proc/<pid>/stat` fields after the command name, or None when the pid is unreadable.

    Field 3 of the file (index 0 here) is the state letter, field 22 (index 19) is the start time;
    the command name is cut off first with `rsplit(b") ", 1)` because it may itself contain spaces
    and parentheses.
    """
    try:
        with open(PROC_ROOT / str(pid) / "stat", "rb") as handle:
            return handle.read().rsplit(b") ", 1)[-1].split()
    except OSError:
        return None


def _proc_state(pid: int) -> str | None:
    """The state letter of `pid` (`Z` for a zombie), or None when it is gone or unreadable."""
    fields = _proc_stat(pid)
    return fields[0].decode() if fields else None


def _start_time(pid: int) -> str | None:
    """`/proc/<pid>/stat` field 22 — when this process instance started, in clock ticks — or None.

    The value is only ever compared with another reading of the same field: it is what tells two
    instances that shared a process id apart, so the pid of a process someone else's reap released
    can never be pinned as the instance the evidence was read from (module docstring).
    """
    fields = _proc_stat(pid)
    return fields[19].decode() if fields and len(fields) > 19 else None


@dataclass(frozen=True)
class Spawned:
    """A command this run spawned, with the identity it recorded at spawn (`_spawned`)."""

    process: subprocess.Popen
    start: str | None  # `/proc/<pid>/stat` field 22 read at spawn; None where unreadable

    @property
    def pid(self) -> int:
        return self.process.pid


def _spawned(process: subprocess.Popen) -> Spawned:
    """Record the identity of a freshly spawned command: its pid and its start time, read now."""
    return Spawned(process=process, start=_start_time(process.pid))


def _proc_scan() -> list[tuple[int, list[bytes]]] | None:
    """Every live process this platform can see, each with its `/proc/<pid>/stat` fields — or None.

    One read per candidate, and the single source the reports below are built from.  Zombies are
    left out: a zombie is terminated, holds no scratch and cannot be signalled again — only its
    parent's `wait` is outstanding, and that parent may not be the runner.  None where nothing can
    be enumerated.
    """
    if not PROC_ROOT.is_dir():
        return None
    try:
        names = os.listdir(PROC_ROOT)
    except OSError:
        return None
    live: list[tuple[int, list[bytes]]] = []
    for name in sorted(names):
        if not name.isdigit():
            continue
        pid = int(name)
        fields = _proc_stat(pid)
        if fields is None or len(fields) <= 19 or fields[0] == b"Z":
            continue
        live.append((pid, fields))
    return live


def _group_members(group: int) -> list[tuple[int, str]] | None:
    """Live members of `group`, each with the start time read in the same pass — or None.

    A report, never a list of signal targets: this run signals only the process it spawned (module
    docstring).  Membership comes from the group field (`pgrp`) of the same `/proc/<pid>/stat` read
    the start time comes from, and zombies are left out as everywhere (`_proc_scan`).  None where
    nothing can be enumerated.
    """
    scan = _proc_scan()
    if scan is None:
        return None
    members: list[tuple[int, str]] = []
    for pid, fields in scan:
        try:
            in_group = int(fields[2]) == group
        except ValueError:
            continue
        if in_group:
            members.append((pid, fields[19].decode()))
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


def _scratch_processes(scratch: Path) -> list[tuple[int, str]] | None:
    """Live pids, other than the runner itself, that still point into `scratch` — with each one's
    start time — or None where nothing can be enumerated.

    A detached worker (`start_new_session`) leaves the suite's process group, so the group report
    cannot reach it; it does keep the task-local paths it inherited, and that is what identifies it
    from outside — the cwd it was started in, or the HOME/TMPDIR/XDG root the suite's environment put
    in its environment.  The start time is taken from the same `/proc` read that found the pid, and
    is carried for the report's sake: this is a report, never a list of signal targets — this run
    signals only the process it spawned (module docstring).
    """
    scan = _proc_scan()
    if scan is None:
        return None
    needle = os.fsencode(str(scratch))
    own = os.getpid()
    found: list[tuple[int, str]] = []
    for pid, fields in scan:
        if pid == own or not _refers_to_scratch(pid, needle):
            continue
        found.append((pid, fields[19].decode()))
    return found


def _left_alone(log, found: list[tuple[int, str]], subject: str) -> Teardown:
    """A record note for processes this run found and deliberately did not touch.

    `subject` says what they were found by (the group's membership, the scratch they still hold);
    each note names the pids, because a report nobody can act on is not a report.  This run signals
    only the process it spawned (module docstring), so what is found here is left running and the
    teardown is unverified — never a survivor, which is a process that took a delivered SIGKILL.
    """
    if not found:
        return Teardown()
    pids = sorted(pid for pid, _start in found)
    log.write(f"[discoverer] teardown: {len(found)} process(es) {subject} left alone (pids "
              f"{pids})\n".encode())
    log.flush()
    return Teardown(unverified=(_unverified(
        f"{len(found)} process(es) {subject} were found and left alone, because this run signals "
        f"only the process it spawned (pids {pids})"),))


def _group_report(spawned: Spawned, log, limit: str) -> Teardown:
    """Report what the group the command led still holds, the command's own process excluded.

    Read while that process is still this run's unreaped child — the caller runs it before any
    reap — so the number being read is still the command's own; what is found is reported and left
    alone (module docstring).  `limit` is the note for a platform that cannot enumerate at all.
    """
    members = _group_members(spawned.pid)
    if members is None:
        return Teardown(unverified=(_unverified(limit),))
    return _left_alone(log, [member for member in members if member[0] != spawned.pid],
                       "in the group the command led")


def _report_scratch(scratch: Path, log_path: Path) -> Teardown:
    """Report the processes still holding `scratch`, before the runner deletes that tree.

    Deleting the tree first would leave a launcher's watcher polling records that no longer exist;
    the report names what still holds it and leaves it alone (module docstring).
    """
    with log_path.open("ab") as log:
        found = _scratch_processes(scratch)
        if found is None:
            return Teardown(unverified=(_unverified(NO_ENUMERATION),))
        return _left_alone(log, found, "still holding the suite's task-local scratch")


@dataclass(frozen=True)
class Pin:
    """A pidfd that still refers to the process instance its start time identified."""

    fd: int
    start: str

    def close(self) -> None:
        with contextlib.suppress(OSError):
            os.close(self.fd)


def _pin_identity(pid: int, expected: str) -> tuple[Pin | None, str | None]:
    """Pin `pid` to the start time `expected` — this run's evidence for that target — or refuse
    with the reason: a pidfd opened for `pid` whose start-time re-read equals `expected`, or no
    handle and a note (`_ownership_limit` gates the pin itself, module docstring).
    """
    limit = _ownership_limit()
    if limit is not None:
        return None, limit
    try:
        fd = os.pidfd_open(pid)
    except ProcessLookupError:
        return None, f"pid {pid} was gone before a pidfd for it could be opened"
    except OSError as exc:
        return None, f"a pidfd for pid {pid} could not be opened ({exc.strerror or exc})"
    confirmed = _start_time(pid)
    if confirmed is None:
        note = f"the start time of pid {pid} could not be read after its pidfd was opened"
    elif confirmed != expected:
        note = (f"pid {pid} no longer names the process instance the evidence identified (start "
                f"time {expected} then, {confirmed} now)")
    else:
        return Pin(fd=fd, start=confirmed), None
    os.close(fd)
    return None, note


def _spawned_target(spawned: Spawned) -> str:
    """How the record names the one process this run may signal."""
    return f"the process this run spawned (pid {spawned.pid})"


def _not_sent(target: str, name: str, why: str) -> str:
    """The record note for a delivery that was refused: what was not sent, and why."""
    return _unverified(f"{target} was not sent {name}: {why}")


def _signal_spawned(spawned: Spawned, signum: int, log) -> tuple[bool, str | None]:
    """Deliver `signum` to the process this run spawned, or send nothing and return the reason.

    The only signal this run ever sends (module docstring): the target is the pid recorded at
    spawn, its identity is pinned at delivery (`_pin_identity` with that recorded start time), and
    the signal goes through the pidfd.  `(True, None)` means it was delivered; `(False, None)`
    means there was nothing to deliver (the process has already terminated, so a signal would be a
    claim rather than a delivery); `(False, note)` is a refusal, and the note carries the reason.
    """
    name = signal.Signals(signum).name
    target = _spawned_target(spawned)
    limit = _ownership_limit()
    if limit is not None:
        return False, _not_sent(target, name, limit)
    if spawned.start is None:
        return False, _unverified(
            f"{target} has no start time recorded at spawn, so its identity cannot be pinned and "
            f"it was not sent {name}")
    pin, why = _pin_identity(spawned.pid, spawned.start)
    if pin is None:
        return False, _unverified(f"{target} was not sent {name} ({why})")
    try:
        if _proc_state(spawned.pid) == "Z":
            return False, None  # already terminated: nothing to deliver, nothing to claim
        signal.pidfd_send_signal(pin.fd, signum)
    except ProcessLookupError:
        return False, _unverified(
            f"{target} was gone before the {name} could be delivered through its pidfd")
    except OSError as exc:
        return False, _unverified(
            f"the {name} could not be delivered through the pidfd of {target} "
            f"({exc.strerror or exc})")
    finally:
        pin.close()
    log.write(f"[discoverer] teardown: {name} {DELIVERY_MARKER} {spawned.pid}, the process this run"
              f" spawned (pinned at delivery, start time {pin.start})\n".encode())
    log.flush()
    return True, None


def _command_stopped(spawned: Spawned, seconds: float) -> bool:
    """Whether the process this run spawned stopped within `seconds`, observed without reaping it.

    One escalation round's bounded grace (`_stop_spawned`): the exit is observed with
    `_observe_exit`, never by a blocking wait that could outlive the deadline, and where the
    non-reaping observation is unavailable it reports the loss instead (`_observe_exit`).
    """
    code, lost = _observe_exit(spawned.process, seconds)
    return code is not None or lost


def _stop_spawned(spawned: Spawned, log) -> Teardown:
    """Terminate the process this run spawned — the only process it may signal — and report the rest.

    Escalation is TERM, a bounded grace, KILL, and it applies to that one process only; the grace
    runs on a real delivery, never on a round that delivered nothing, and each round re-pins the
    target at delivery (`_signal_spawned`).  Everything else the command left is enumerated and
    reported, never touched (`_group_report`): a member or holder this run did not spawn is left
    running and the teardown is unverified.  Only a process that took a delivered SIGKILL and
    outlived the grace is a survivor; the group is read before the command is reaped, so the number
    read is still the command's own.

    The capability refusal is completed before any escalation signal is resolved: the platform may
    not define every constant in the sequence (`signal.SIGKILL` on Windows), and a refused delivery
    is a record entry, not an exception — the group report below still runs and the settled result
    still carries the limit.
    """
    signalled: tuple[int, ...] = ()
    refused: tuple[str, ...] = ()
    stopped = False
    limit = _ownership_limit()
    if limit is not None:
        refused = (_not_sent(_spawned_target(spawned), ESCALATION_NAMES[0], limit),)
    else:
        for signum in (getattr(signal, name) for name in ESCALATION_NAMES if hasattr(signal, name)):
            delivered, note = _signal_spawned(spawned, signum, log)
            if not delivered:
                if note is not None:
                    refused = (*refused, note)
                break
            signalled = (*signalled, signum)
            if _command_stopped(spawned, KILL_GRACE_SECONDS):
                stopped = True
                break
    # A survivor is a process that took a delivered SIGKILL and outlived the grace; where nothing was
    # delivered — a refused run, or a platform without KILL — there is no survivor to name, and the
    # constant is read only when a round actually ran (it does not exist everywhere).
    survivors = ((spawned.pid,) if signalled and not stopped
                 and signalled[-1] == getattr(signal, "SIGKILL", None) else ())
    teardown = _group_report(spawned, log, NO_ENUMERATION)
    spawned.process.poll()  # reconcile `Popen` with an exit observed without reaping
    return teardown.merge(Teardown(
        clauses=("the spawned process",) if signalled and stopped else (),
        survivors=survivors,
        unverified=refused,
    ))


# Whether this run put its own `SIGCHLD` disposition in the state ownership rests on (`SIG_DFL`),
# established once at startup (`establish_exit_disposition`); `_ownership_limit` re-checks it live,
# so a disposition changed after startup refuses instead of being trusted (module docstring).
EXIT_DISPOSITION: bool = False


def establish_exit_disposition() -> bool:
    """Put this run's own `SIGCHLD` disposition in `SIG_DFL`; False where that cannot be done.

    Called once at startup, before anything is spawned (module docstring).
    """
    global EXIT_DISPOSITION
    try:
        signal.signal(signal.SIGCHLD, signal.SIG_DFL)
    except (AttributeError, ValueError, OSError, RuntimeError):
        EXIT_DISPOSITION = False
        return False
    EXIT_DISPOSITION = True
    return True


def _ownership_limit() -> str | None:
    """Why nothing may be signalled under this run's policy, or None when every gate holds.

    The gates are ordered and all of them must hold where a signal is delivered: this run's live
    `SIGCHLD` disposition, the non-reaping exit observation, pidfds, and `/proc` — the identity
    (start times) every delivery is justified by.
    """
    if not EXIT_DISPOSITION or signal.getsignal(signal.SIGCHLD) != signal.SIG_DFL:
        return ("this run has no child-reaping SIGCHLD disposition of its own, so no process can "
                "be proven this run's")
    if not WAITID_WNOWAIT:
        return ("this platform cannot observe a child's exit without reaping it, so the pid this "
                "run spawned cannot be proven still its own")
    if not PIDFD_PINNING:
        return ("this platform cannot open a pidfd, so a signal's target identity cannot be "
                "pinned at delivery")
    if not PROC_ROOT.is_dir():
        return ("this platform has no /proc, so a process's start time (its identity) cannot be "
                "read")
    return None


def _observe_exit(process: subprocess.Popen, timeout: float) -> tuple[int | None, bool]:
    """The exit code `process` reaches within `timeout`, or None at the deadline — plus whether
    the status was lost instead of observed (the child is not waitable any more).

    Where Python exposes `os.waitid` with `WNOWAIT` (probed once as `WAITID_WNOWAIT`), the exit is
    observed without reaping the child, which is what keeps the pid reserved for a teardown that
    still needs the identity recorded at spawn — and the loss is reported rather than raised when
    the child is not waitable any more.  Where the non-reaping observation is unavailable,
    `subprocess`'s own wait is used; it reaps the child, and it absorbs the same loss as an exit
    status of 0, which is why the cached `returncode` is never this run's evidence.  The value
    follows `subprocess`: a negative number is the killing signal.
    """
    if not WAITID_WNOWAIT:
        try:
            return process.wait(timeout=timeout), False
        except subprocess.TimeoutExpired:
            return None, False
    deadline = time.monotonic() + timeout
    while True:
        try:
            info = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOWAIT | os.WNOHANG)
        except ChildProcessError:
            return None, True
        if info is not None:
            code = info.si_status if info.si_code == os.CLD_EXITED else -info.si_status
            return code, False
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None, False
        time.sleep(min(EXIT_POLL_SECONDS, remaining))


def _run_commands(commands: tuple[tuple[str, ...], ...], *, cwd: Path, env: dict[str, str],
                  timeout: float, log_path: Path,
                  appending: bool = False) -> tuple[int | None, bool, float, Teardown, bool]:
    """Run argv vectors in order into one log file.

    Returns the exit code, whether the deadline hit, the seconds taken, the teardown record and
    whether an exit was observed at all.  A command that timed out or died by a signal is torn
    down before this returns, while its own instance can still be pinned — the identity recorded at
    spawn (`_spawned`, read right after `Popen` returns); a command that exited on its own has the
    members of the group it led reported before it is reaped (`_teardown_before_reap`), and every
    command's teardown merges into the record this returns.  `observed` is False where the exit
    status was lost (`_observe_exit`): the suite then settles as an error on an unverified teardown
    rather than on a status the kernel discarded.
    """
    started = time.monotonic()
    last_code: int | None = 0
    teardown = Teardown()
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
                return None, False, time.monotonic() - started, teardown, True
            spawned = _spawned(process)
            remaining = max(timeout - (time.monotonic() - started), 0.1)
            code, lost = _observe_exit(process, remaining)
            if lost:
                # The child is no longer in the kernel's (or this run's) bookkeeping: reconcile
                # the `Popen` object — CPython reads the `ECHILD` that "we can't get the status"
                # as 0 — but never settle on that value: the record below says the status was
                # lost, and the teardown was not provable.
                process.poll()
                log.write(b"\n[discoverer] the suite process is no longer waitable: its exit "
                          b"status is gone, so nothing can be proven about it\n")
                log.flush()
                return None, False, time.monotonic() - started, teardown.merge(Teardown(
                    unverified=(_unverified(
                        "the process this run spawned could no longer be waited for, so nothing "
                        "about what it left behind was established"),))), False
            if code is None:
                teardown = teardown.merge(_stop_spawned(spawned, log))
                return process.poll(), True, time.monotonic() - started, teardown, True
            last_code = code
            if code < 0:
                # A signal killed the command: its own cleanup callbacks did not run, and, where
                # the exit was observed without reaping, its identity is still pinnable.
                teardown = teardown.merge(_stop_spawned(spawned, log))
                return last_code, False, time.monotonic() - started, teardown, True
            teardown = teardown.merge(_teardown_before_reap(spawned, log))
            if code != 0:
                break
    return last_code, False, time.monotonic() - started, teardown, True


def _display(argv: tuple[str, ...]) -> str:
    return " ".join(argv)


def _teardown_before_reap(spawned: Spawned, log) -> Teardown:
    """Report what a command that exited under its own control left in its process group, and reap it.

    A command can exit — 0 or not — and still leave same-group members behind, and one whose
    environment is empty and whose cwd is outside the scratch matches no scratch report; once the
    command is reaped its pid is no evidence at all, so the group is read while its own unreaped
    instance still holds the number.  What is found is reported and left alone — this run signals
    only the process it spawned (module docstring) — and where the group cannot be read at all, the
    record says the check could not run instead of claiming the group emptied.
    """
    teardown = _group_report(
        spawned, log,
        f"the process group of a command that exited could not be checked before the reap "
        f"({NO_ENUMERATION})")
    spawned.process.wait()
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
           teardown: Teardown | None = None, exit_observed: bool = True) -> tuple[str, dict, str]:
    """Settle one scheduled suite as PASS, FAIL, ERROR or TIMEOUT.

    The teardown's own account is appended to the reason wherever the suite did not finish under
    its own control: a timeout, a lost exit and a death by signal name what teardown established
    whether or not the record is verified, and every other outcome appends it when there is a
    limit or a survivor to report (`_teardown_note`, module docstring).
    """
    if timed_out:
        effective = suite.timeout if timeout is None else timeout
        return "TIMEOUT", {}, f"timeout after {effective:g}s; {_teardown_note(teardown)}"
    if not provisioned:
        return "ERROR", {}, "provisioning failed"
    if not exit_observed:
        # The kernel discarded the status (an inherited SIGCHLD disposition reaped the child, or
        # another reaper took it): there is no exit to settle on and no identity was pinnable.
        return "ERROR", {}, (f"the suite process is no longer waitable, so its exit status is "
                             f"unknown; {_teardown_note(teardown)}")

    counts: dict = {}
    if exit_code is None:
        state, reason = "ERROR", "the suite process could not be started"
    elif exit_code < 0:
        return "ERROR", {}, f"terminated by signal {-exit_code}; {_teardown_note(teardown)}"
    else:
        state, reason = ("PASS", "ok") if exit_code == 0 else ("FAIL", f"exit {exit_code}")
        if suite.assertion == "unittest":
            counts = parse_unittest_counts(output)
            shortfall = _unittest_shortfall(counts)
            if shortfall:
                state, reason = "ERROR", shortfall
        elif suite.assertion == "counter":
            counts = parse_counter_counts(output, suite.count_regexes)
            if exit_code != 0:
                state = "FAIL"
                reason = ("suite reported a failing case" if counts
                          else "no counter line in the output")
            elif not counts:
                state, counts, reason = "ERROR", {}, "no counter line matching count_regexes"
            elif counts.get("passed", 0) < 1:
                state, reason = "ERROR", "zero executed checks"
            elif not _counts_consistent(counts):
                state, reason = "ERROR", "counter line disagrees with the exit status"
        state, counts, reason = _apply_require_regex(suite, state, reason, counts, output)
    if teardown is not None and not teardown.verified:
        reason = f"{reason}; {teardown.describe()}"
    return state, counts, reason


def _apply_require_regex(suite: Suite, state: str, reason: str, counts: dict,
                         output: str) -> tuple[str, dict, str]:
    if state == "PASS" and suite.require_regex:
        if not re.search(suite.require_regex, _plain(output), re.MULTILINE):
            return "ERROR", counts, f"required output missing: /{suite.require_regex}/"
    return state, counts, reason


def run_suite(suite: Suite, *, root: Path, scratch_root: Path, log_root: Path,
              environment: dict[str, str], timeout_override: float | None = None,
              socket_tail: str = "") -> Outcome:
    """Run one suite in its own process, group and task-local scratch tree.

    The startup step (`establish_exit_disposition`) belongs to `main`: a caller that starts suites
    without it gets refusals, never a weaker proof (module docstring).
    """
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
    teardown = Teardown()
    provisioned = True
    if suite.provision:
        code, timed_out, _, teardown, observed = _run_commands(suite.provision, cwd=suite.cwd,
                                                               env=env, timeout=timeout,
                                                               log_path=log_path)
        provisioned = not timed_out and code == 0
        if not provisioned:
            reason = "provisioning failed: " + _display(suite.provision[0])
            if timed_out or not observed or (code is not None and code < 0):
                teardown = teardown.merge(_report_scratch(suite_scratch, log_path))
            if not teardown.verified:
                reason += "; " + teardown.describe()
            outcome = Outcome(
                suite_id=suite.id, state="ERROR", duration=0.0, exit_code=code,
                reason=reason, teardown=teardown,
                log=str(log_path), tail=_read_log(log_path, 25), covered_by=suite.covered_by,
            )
            shutil.rmtree(suite_scratch, ignore_errors=True)
            return outcome

    code, timed_out, duration, command_teardown, observed = _run_commands(
        suite.commands, cwd=suite.cwd, env=env, timeout=timeout, log_path=log_path,
        appending=bool(suite.provision))
    # What successful provisioning's own run established stays in the record: the command vector
    # merges into it, never replaces it (a provisioning worker's teardown limit is a limit of this
    # suite's run, wherever the worker was started).
    teardown = teardown.merge(command_teardown)
    if timed_out or not observed or (code is not None and code < 0):
        # The suite's own cleanup callbacks did not run — the runner timed it out, a signal killed
        # it, or its exit was lost — so report what still holds its scratch before that tree is
        # deleted, and leave those processes alone (the run signals only what it spawned).
        teardown = teardown.merge(_report_scratch(suite_scratch, log_path))
    output = _read_log(log_path)
    state, counts, reason = settle(suite, exit_code=code, timed_out=timed_out, output=output,
                                   provisioned=provisioned, timeout=timeout, teardown=teardown,
                                   exit_observed=observed)
    outcome = Outcome(
        suite_id=suite.id, state=state, duration=round(duration, 3), exit_code=code,
        reason=reason, counts=counts, log=str(log_path), teardown=teardown,
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


def _teardown_record(teardown: Teardown | None) -> dict | None:
    """The published account of a teardown, or None where no command teardown was ever observed.

    A record is published for every suite whose command vector ran — a clean `PASS` whose group was
    read before its reap, a `Popen` that could not be started, a provisioning failure — and it
    is None only where `run_suite` returned before execution or the suite never executed at all (a
    covered child, a condition-skipped suite, an unusable scratch root).  `verified` is False
    wherever the record carries a limit note or a pid that took a SIGKILL and outlived it;
    `clauses` names the steps that really terminated their target, `unverified` one note per limit
    (module docstring).
    """
    if teardown is None:
        return None
    return {
        "verified": teardown.verified,
        "clauses": list(teardown.clauses),
        "survivors": list(teardown.survivors),
        "unverified": list(teardown.unverified),
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
        "teardown": _teardown_record(outcome.teardown),
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
    # Before anything is spawned (module docstring); where it cannot be established, the run
    # continues and every teardown records that limit.
    establish_exit_disposition()
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
