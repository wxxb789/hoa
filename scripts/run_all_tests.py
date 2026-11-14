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

  0  every scheduled suite settled PASS (declared condition SKIPs are not failures)
  1  at least one required suite settled FAIL, ERROR or TIMEOUT
  2  the plan itself is not trustworthy: manifest or schema error, an unmet discovery floor, an
     unknown or duplicate suite id, a stale refinement, or nothing left to run

Each suite runs in its own process and process group, with a task-local TMPDIR/HOME/XDG root under
the system temp directory (not inside the checkout, matching CI), a per-suite timeout, and
process-group teardown on timeout.  Per-suite logs and the JSON result record stay under
`.tmp-artifacts/test-runs/<UTC stamp>/` in the checkout.  A required suite that executed zero
checks is never PASS: unittest suites must collect at least one test, and suites with a declared
count adapter must report a positive executed-check count.
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
TERMINAL_STATES = ("PASS", "FAIL", "ERROR", "TIMEOUT", "SKIP")
FAILING_STATES = ("FAIL", "ERROR", "TIMEOUT")
RUNTIMES = ("python", "bash", "bun", "npm")
ASSERTION_KINDS = ("auto", "unittest", "counter", "exit")
CONDITIONS = ("always", "pull_request")
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
    path: str | None = None           # repo-relative entry point, when there is one
    replaced_discovery: bool = False   # declared entry that owns a discovered path


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
    runtime = entry.get("runtime", "python" if has_command else "python")
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
                      *, origin: str, path: str | None, replaced: bool) -> Suite:
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
        path=path,
        replaced_discovery=replaced,
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
                                 origin="declared", path=path, replaced=replaced)
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
                                  origin="discovered", path=path, replaced=False)
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
    )


# ── execution ────────────────────────────────────────────────────────────────


def base_environment(document: dict, python: str) -> dict[str, str]:
    """Environment copied into suite processes before task-local values are set.

    Only the manifest's allowlist is kept: an operator's GDD_*, OMP_*, PASEO_* or
    profile variables must not reach a suite.  PATH gets the running interpreter's
    directory prepended, so a suite's own `python3` is the interpreter that carries
    the repository dependencies.
    """
    allowed = list((document.get("env") or {}).get("passthrough") or ["PATH"])
    environment = {name: os.environ[name] for name in allowed if name in os.environ}
    interpreter_dir = str(Path(python).resolve().parent)
    existing = environment.get("PATH", "")
    environment["PATH"] = os.pathsep.join(
        part for part in (interpreter_dir, existing) if part
    )
    # Deterministic logs: no tool should colour a captured stream.
    environment.setdefault("NO_COLOR", "1")
    return environment


def scratch_root_for(override: str | None = None) -> Path:
    """Task-local scratch root for one run, outside the checkout.

    Suites reason about paths *inside* the repository — a working-tree PII gate refuses
    a tracked path, and tmux needs a unix socket path under 108 bytes — and in CI
    TMPDIR is /tmp, not the checkout.  The name is deliberately short for the same
    reason: `test_omp_run_python` puts a tmux socket three levels below TMPDIR.
    """
    if override:
        path = Path(override).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path
    return Path(tempfile.mkdtemp(prefix="hoa-t-"))


def _suite_slug(suite_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", suite_id).strip("-") or "suite"


def _write_report(report_path: Path | None, payload: dict) -> None:
    if report_path is None:
        return
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _run_commands(commands: tuple[tuple[str, ...], ...], *, cwd: Path, env: dict[str, str],
                  timeout: float, log_path: Path, appending: bool = False) -> tuple[int | None, bool, float]:
    """Run argv vectors in order into one log file; return (exit code, timed out, seconds)."""
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
                return None, False, time.monotonic() - started
            remaining = max(timeout - (time.monotonic() - started), 0.1)
            try:
                last_code = process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                _terminate_group(process, log)
                return process.poll(), True, time.monotonic() - started
            if last_code != 0:
                break
    return last_code, False, time.monotonic() - started


def _display(argv: tuple[str, ...]) -> str:
    return " ".join(argv)


def _terminate_group(process: subprocess.Popen, log) -> None:
    """Terminate a suite's whole process group, escalating to SIGKILL."""
    log.write(f"\n[discoverer] timeout: terminating process group {process.pid}\n".encode())
    log.flush()
    if not hasattr(os, "killpg"):
        process.kill()
        process.wait(timeout=KILL_GRACE_SECONDS)
        return
    try:
        group = os.getpgid(process.pid)
    except ProcessLookupError:
        process.wait(timeout=KILL_GRACE_SECONDS)
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(group, sig)
        except ProcessLookupError:
            break
        try:
            process.wait(timeout=KILL_GRACE_SECONDS)
            break
        except subprocess.TimeoutExpired:
            continue
    if process.poll() is None:
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=KILL_GRACE_SECONDS)
    if process.poll() is None:
        # SIGKILL was delivered; a group that still will not reap is recorded, not raised:
        # teardown must never take the whole run down with it.
        log.write(
            f"[discoverer] process group {group} still not reaped "
            f"{KILL_GRACE_SECONDS:g}s after SIGKILL\n".encode()
        )
        log.flush()


def _tail(path: Path, limit: int = 25) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(size - LOG_TAIL_BYTES, 0))
            text = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
    lines = _plain(text).splitlines()
    return "\n".join(lines[-limit:])


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

    `total` counts everything the suite says it executed; every check that did not
    pass must be a declared skip, or the exit status and the count disagree.
    """
    passed = counts.get("passed", 0)
    total = counts.get("total")
    if total is None:
        return True
    if total < passed:
        return False
    return total == passed or passed + counts.get("skipped", 0) == total


def settle(suite: Suite, *, exit_code: int | None, timed_out: bool, output: str,
           provisioned: bool = True, timeout: float | None = None) -> tuple[str, dict, str]:
    """Settle one scheduled suite as PASS, FAIL, ERROR or TIMEOUT."""
    if timed_out:
        effective = suite.timeout if timeout is None else timeout
        return "TIMEOUT", {}, f"timeout after {effective:g}s; process group terminated"
    if not provisioned:
        return "ERROR", {}, "provisioning failed"
    if exit_code is None:
        return "ERROR", {}, "the suite process could not be started"
    if exit_code < 0:
        return "ERROR", {}, f"terminated by signal {-exit_code}"

    counts: dict = {}
    if suite.assertion == "unittest":
        counts = parse_unittest_counts(output)
        if not counts:
            return "ERROR", {}, "no unittest summary in the output (`Ran N tests` absent)"
        if counts.get("executed", 0) < 1:
            return "ERROR", counts, "Ran 0 tests: the suite collected nothing"
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
              environment: dict[str, str], timeout_override: float | None = None) -> Outcome:
    """Run one suite in its own process, group and task-local scratch tree."""
    slug = _suite_slug(suite.id)
    # Short directory name: AF_UNIX paths (tmux) are capped at 108 bytes and suites put
    # their own temp trees below TMPDIR.
    scratch_root.mkdir(parents=True, exist_ok=True)  # never fail to isolate for want of a directory
    suite_scratch = Path(tempfile.mkdtemp(prefix=f"{slug[:12]}-", dir=scratch_root))
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
        code, timed_out, _ = _run_commands(suite.provision, cwd=suite.cwd, env=env,
                                           timeout=timeout, log_path=log_path)
        provisioned = not timed_out and code == 0
        if not provisioned:
            outcome = Outcome(
                suite_id=suite.id, state="ERROR", duration=0.0, exit_code=code,
                reason="provisioning failed: " + _display(suite.provision[0]),
                log=str(log_path), tail=_tail(log_path), covered_by=suite.covered_by,
            )
            shutil.rmtree(suite_scratch, ignore_errors=True)
            return outcome

    code, timed_out, duration = _run_commands(suite.commands, cwd=suite.cwd, env=env,
                                              timeout=timeout, log_path=log_path,
                                              appending=bool(suite.provision))
    output = _read_log(log_path)
    state, counts, reason = settle(suite, exit_code=code, timed_out=timed_out, output=output,
                                   provisioned=provisioned, timeout=timeout)
    outcome = Outcome(
        suite_id=suite.id, state=state, duration=round(duration, 3), exit_code=code,
        reason=reason, counts=counts, log=str(log_path),
        tail=_tail(log_path) if state != "PASS" else "", covered_by=suite.covered_by,
    )
    shutil.rmtree(suite_scratch, ignore_errors=True)
    return outcome


def _read_log(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(size - LOG_TAIL_BYTES, 0))
            return handle.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


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
    elif child.assertion == "unittest":
        counts = parse_unittest_counts(output)
        if counts.get("executed", 0) < 1:
            return Outcome(
                suite_id=child.id, state="ERROR", counts=counts,
                reason=f"parent {parent.id} shows no unittest summary for this suite",
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
    for suite in plan.skipped:
        print(f"  {'skipped':<10} {suite.id:<70} {suite.runtime:<6} condition={suite.condition}")
    for child in plan.covered:
        print(f"  {'covered':<10} {child.id:<70} covered_by={child.covered_by}")
    for problem in plan.problems:
        print(f"problem: {problem}")
    if not plan.filtered:
        print(f"floor: {len(plan.discovered)} discovered, "
              f"{len(plan.floor_missing)} pinned missing, {len(plan.unpinned)} unpinned")


def _payload(plan: Plan, outcomes: list[Outcome], *, event: str, root: Path, python: str,
             started: str, duration: float, exit_code: int, log_root: Path) -> dict:
    summary = {state: 0 for state in TERMINAL_STATES}
    for outcome in outcomes:
        summary[outcome.state] = summary.get(outcome.state, 0) + 1
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
        "suites": [
            {
                "id": outcome.suite_id,
                "state": outcome.state,
                "duration_seconds": outcome.duration,
                "exit_code": outcome.exit_code,
                "reason": outcome.reason,
                "counts": outcome.counts,
                "covered_by": outcome.covered_by,
                "log": outcome.log,
            }
            for outcome in outcomes
        ],
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
    parser.add_argument("--report", default=None, help="write the JSON result record here")
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

    stamp = f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{os.getpid()}"
    scratch_root = scratch_root_for(args.scratch)
    run_root = root / ".tmp-artifacts" / "test-runs" / stamp
    log_root = run_root / "logs"
    log_root.mkdir(parents=True, exist_ok=True)
    environment = base_environment(document, python)

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
                            environment=environment, timeout_override=args.timeout)
        outcomes.append(outcome)
        by_id[suite.id] = outcome
        print(f"[{index:>3}/{total}] {outcome.state:<7} {outcome.duration:>6.2f}s  {suite.id}"
              f"{'' if outcome.state == 'PASS' else '  ' + outcome.reason}")
        if outcome.tail and outcome.state != "PASS":
            for line in outcome.tail.splitlines()[-25:]:
                print(f"      | {line}")
    by_suite = {suite.id: suite for suite in plan.scheduled + plan.covered + plan.skipped}
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
    for problem in plan.problems:
        print(f"problem: {problem}")
    print(f"logs: {log_root}")
    if not args.scratch:
        with contextlib.suppress(OSError):
            scratch_root.rmdir()  # only when every suite cleaned up after itself

    exit_code = 2 if plan.problems else (1 if failed else 0)
    if failed:
        print("failed: " + ", ".join(failed))
    _write_report(Path(args.report).resolve() if args.report else None,
                  _payload(plan, outcomes, event=event, root=root, python=python,
                           started=started, duration=duration, exit_code=exit_code,
                           log_root=log_root))
    print(f"exit {exit_code}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
