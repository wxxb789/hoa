#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Manual merge verdict matrix driven through main() with a fake subprocess boundary.

The test-side bucket declaration, negative coverage dimensions, and golden
call log are independent of the gate. Review any change to the expected
call set against the production diff before updating it.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections import namedtuple
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
for _path in (str(SCRIPTS), str(HERE)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import gh_checks_fixtures as captured  # noqa: E402

HEAD = "a1b2c3d4" + "0" * 32
# A head that cannot denote HEAD, so `--verified-head MISMATCHED_HEAD` is a head mismatch against
# the fixture's `headRefOid` and blocks.
MISMATCHED_HEAD = "deadbeef" + "0" * 32
# The PR number every cell requests, and the token the recorded call log folds any repository path
# onto (the verdict cells' `--repo .` and the boundary cells' scratch directory). Both are named
# here so the boundary assertions below can require the *requested* PR and the repository pair.
REQUESTED_PR = "7"
REPO_TOKEN = "<repo>"


# --- the golden call log ----------------------------------------------------
# One recorder, off unless a run turns it on. `_fake_run_for()` appends every invocation the gate
# issues through `main()`; `evaluate_with_calls()` turns recording on around a matrix run and
# compares the distinct set with `GOLDEN_CALLS` below.
_calls_seen = None


def _record_call(argv, cwd, has_env):
    if _calls_seen is not None:
        _calls_seen.add((argv, cwd, has_env))


def _normalize_argv(argv, repo_token):
    """The command with the repository the operator named folded onto `REPO_TOKEN`."""
    if repo_token is None:
        return tuple(argv)
    return tuple(REPO_TOKEN if part == repo_token else part for part in argv)


def _normalize_cwd(cwd, repo_token):
    """The working directory, `None` kept as `None` and the named repository folded like argv."""
    if cwd is None:
        return None
    return REPO_TOKEN if repo_token is not None and cwd == repo_token else cwd


def load_gate(path=None):
    """Import pr-merge-check.py (or a mutated in-memory variant via the harness) as a module."""
    path = Path(path or (SCRIPTS / "pr-merge-check.py"))
    spec = importlib.util.spec_from_file_location("pr_merge_check_matrix", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The gate as shipped. Its vocabulary is read once here and used only to *enumerate inputs* and to
# check that the gate still declares exactly what the matrix declares below. It is never the source
# of an expectation: reading the artefact for what is correct is what made a two-token swap
# invisible (round-5 finding F2).
GATE = load_gate()
VOCABULARY = dict(GATE.CHECK_VOCABULARY)

# --- the oracle: the declared meaning of every vocabulary token -------------
# Written out here, literally and test-side, independent of the gate it pins. The cells derive
# their expected classification from *this* declaration, never from `CHECK_VOCABULARY`, so
# exchanging two production values — or adding one silently — fails against a fixed expectation
# instead of moving the expectation along with the artefact.
DECLARED_VOCABULARY = {
    "pass": "SUCCESS",
    "skipping": "SKIPPED",
    "neutral": "NEUTRAL",
    "fail": "FAILURE",
    "cancel": "CANCELLED",
    "pending": "PENDING",
}



def declaration_problems(module):
    """Every way `module.CHECK_VOCABULARY` departs from the literal declaration above.

    Token by token: a missing or extra token fails, and a token whose production value is not the
    declared conclusion fails. A swap — two tokens present with their meanings exchanged — is
    therefore a loud failure rather than a silent one, which is exactly what the oracle must catch.
    """
    problems = []
    production = dict(getattr(module, "CHECK_VOCABULARY", {}) or {})
    for key in sorted(set(DECLARED_VOCABULARY) - set(production)):
        problems.append((key, "the declaration names a token the gate does not declare"))
    for key in sorted(set(production) - set(DECLARED_VOCABULARY)):
        problems.append((key, "the gate declares a token the declaration does not name"))
    for key in sorted(set(production) & set(DECLARED_VOCABULARY)):
        if production[key] != DECLARED_VOCABULARY[key]:
            problems.append((key, "declared %r, the gate maps it to %r"
                             % (DECLARED_VOCABULARY[key], production[key])))
    return problems


# --- the invariants, stated once --------------------------------------------
# Only success, skipping and neutral pass. An unknown JSON bucket is pending.
OK_CONCLUSIONS = frozenset({"SUCCESS", "SKIPPED", "NEUTRAL"})
PENDING_CONCLUSIONS = frozenset({"PENDING"})


def classification(conclusion):
    """ok / pending / failing for one conclusion, from the invariants above."""
    if conclusion in OK_CONCLUSIONS:
        return "ok"
    if conclusion is None or conclusion in PENDING_CONCLUSIONS:
        return "pending"
    return "failing"


# (exit code, verdict reason, tally for a single row) per classification.
_VERDICT = {
    "ok": (0, None, (1, 1, 0, 0)),
    "pending": (1, "checks pending", (1, 0, 1, 0)),
    "failing": (1, "checks", (1, 0, 0, 1)),
}

JSON_ABSENT = (1, "", 'Unknown JSON field: "bucket"')
NO_CHECKS_MESSAGE = "no checks reported on the 'feature' branch"
JSON_NO_CHECKS = (1, "", NO_CHECKS_MESSAGE + "\n")
JSON_EMPTY = (0, "[]", "")
JSON_NONLIST = (0, '{"message": "not a list"}', "")
JSON_GARBAGE = (0, "<html>proxy</html>", "")
JSON_MALFORMED_MIXED = (0, json.dumps([{"name": "build", "state": "SUCCESS", "bucket": "pass"},
                                       None]), "")
JSON_MALFORMED_ONLY = (0, json.dumps([None]), "")


def _json(rows):
    return (0, json.dumps(rows), "")


JSON_GREEN = _json([{"name": "build", "state": "SUCCESS", "bucket": "pass"}])
JSON_PENDING = _json([{"name": "gates", "state": "PENDING", "bucket": "pending"}])
JSON_FAIL = _json([{"name": "verify", "state": "FAILURE", "bucket": "fail"}])
JSON_PASS_PENDING = _json([{"name": "build", "state": "SUCCESS", "bucket": "pass"},
                           {"name": "gates", "state": "PENDING", "bucket": "pending"}])

Cell = namedtuple("Cell", "id json_result allow_no_checks exit_code verdict reason "
                          "checks why error_contains comment_pages thread_pages "
                          "verified_head gates_rc")
StreamCell = namedtuple("StreamCell", "id stdout stderr exit_code why")
ShCell = namedtuple("ShCell", "id stdout stderr exit_code expected why")


def cell(cid, json_result, allow_no_checks, exit_code, verdict, reason, checks, why,
         error_contains=None, comment_pages=None, thread_pages=None,
         verified_head=HEAD, gates_rc=0):
    return Cell(cid, json_result, allow_no_checks, exit_code, verdict, reason,
                checks, why, error_contains, comment_pages, thread_pages,
                verified_head, gates_rc)


EXIT_CATEGORIES = (0, 1, 8, 2, 4, -15, 127)
NON_ZERO_EXITS = EXIT_CATEGORIES[1:]


# --- the matrix -------------------------------------------------------------

CELLS = [
    # --- JSON path: the bucket x state dimension (invariant 3, 4) -----------
    cell("json-green", JSON_GREEN, False, 0, "MERGE-OK", None, (1, 1, 0, 0),
         "the only ok bucket is pass/skipping/neutral on a completed check"),
    cell("json-green-flag", JSON_GREEN, True, 0, "MERGE-OK", None, (1, 1, 0, 0),
         "the flag changes nothing when checks are actually green"),
    cell("json-pending", JSON_PENDING, False, 1, "BLOCKED", "checks pending",
         (1, 0, 1, 0), "a pending check blocks and the reason names it"),
    cell("json-pending-flag", JSON_PENDING, True, 1, "BLOCKED", "checks pending",
         (1, 0, 1, 0), "the flag forgives zero checks, not a reported pending check"),
    cell("json-fail", JSON_FAIL, False, 1, "BLOCKED", "checks", (1, 0, 0, 1),
         "a failed check blocks"),
    cell("json-fail-flag", JSON_FAIL, True, 1, "BLOCKED", "checks", (1, 0, 0, 1),
         "the flag forgives zero checks, not a reported failure"),
    cell("json-pass-plus-pending", JSON_PASS_PENDING, False, 1, "BLOCKED",
         "checks pending", (2, 1, 1, 0), "one pending check beside a passing one still blocks"),
    cell("json-pass-plus-pending-flag", JSON_PASS_PENDING, True, 1, "BLOCKED",
         "checks pending", (2, 1, 1, 0), "a passing neighbour does not make pending forgivable"),

    # --- JSON path: shapes (invariants 1, 2) -------------------------------
    cell("json-empty-list", JSON_EMPTY, False, 1, "BLOCKED", "no checks", (0, 0, 0, 0),
         "a successfully read empty list is the zero-check state and blocks"),
    cell("json-empty-list-flag", JSON_EMPTY, True, 0, "MERGE-OK", None, (0, 0, 0, 0),
         "the flag is exactly the opt-out for a genuinely zero-check read"),
    cell("json-malformed-mixed", JSON_MALFORMED_MIXED, False, 2, "ERROR", None, None,
         "a non-object entry beside a valid one is not permission: exit 2"),
    cell("json-malformed-mixed-flag", JSON_MALFORMED_MIXED, True, 2, "ERROR", None,
         None, "the flag forgives zero checks, never an unreadable list"),
    cell("json-malformed-only", JSON_MALFORMED_ONLY, False, 2, "ERROR", None, None,
         "a list of only non-objects is unreadable: exit 2"),
    cell("json-malformed-only-flag", JSON_MALFORMED_ONLY, True, 2, "ERROR", None,
         None, "the flag cannot rescue a malformed list"),
    cell("json-no-checks-reported", JSON_NO_CHECKS, False, 1, "BLOCKED", "no checks",
         (0, 0, 0, 0), "gh reports zero checks before exporting JSON"),
    cell("json-no-checks-reported-flag", JSON_NO_CHECKS, True, 0, "MERGE-OK", None,
         (0, 0, 0, 0), "an explicit no-CI opt-out accepts gh's confirmed zero-check result"),
    cell("manual-head-mismatch", JSON_GREEN, False, 1, "BLOCKED",
         "head mismatch, verified head missing", (1, 1, 0, 0),
         "green CI does not verify a mismatched head", verified_head=MISMATCHED_HEAD),
    cell("manual-head-abbreviated", JSON_GREEN, False, 1, "BLOCKED",
         "head mismatch, verified head missing", (1, 1, 0, 0),
         "green CI does not verify an abbreviated head", verified_head=HEAD[:8]),
    cell("manual-local-gate-failed", JSON_GREEN, False, 1, "BLOCKED", "gates unverified",
         (1, 1, 0, 0), "green CI does not forgive a failed local gate", gates_rc=1),
    cell("live-pending-json", (captured.PENDING["json_rc"], captured.PENDING["json"], ""),
         False, 1, "BLOCKED", "checks pending", (1, 0, 1, 0), "a live run in flight blocks"),
    cell("live-failing-json", (captured.FAILING["json_rc"], captured.FAILING["json"], ""),
         False, 1, "BLOCKED", "checks", (3, 2, 0, 1), "a live failing run blocks"),
    cell("live-finished-json", (captured.FINISHED["json_rc"], captured.FINISHED["json"], ""),
         False, 0, "MERGE-OK", None, (7, 7, 0, 0), "a finished all-green run passes"),
    cell("json-pending-and-failing", _json([{"bucket": "pending"}, {"bucket": "fail"}]),
         True, 1, "BLOCKED", "checks", (2, 0, 1, 1), "a failure takes precedence over pending"),
]

for _flag in (False, True):
    for _label, _payload in (("nonlist", JSON_NONLIST), ("garbage", JSON_GARBAGE),
                             ("absent", JSON_ABSENT), ("blank-success", (0, "", ""))):
        CELLS.append(cell("json-%s-%s" % (_label, _flag), _payload, _flag, 2, "ERROR", None,
                          None, "unreadable CI cannot authorize a merge"))

for _exit in NON_ZERO_EXITS:
    for _label, _payload, _flag in (("green", JSON_GREEN[1], False), ("empty", "[]", True)):
        CELLS.append(cell(
            "json-exit-%s-%s" % (_exit, _label), (_exit, _payload, ""), _flag, 2, "ERROR",
            None, None, "a non-zero read never authorizes regardless of JSON",
            error_contains=("exit %s" % _exit,)))

for _label, _result in (
    ("generic-1", (1, "", "HTTP 404")),
    ("lookalike", (1, "", "API error: " + NO_CHECKS_MESSAGE)),
    ("extra-error", (1, "", NO_CHECKS_MESSAGE + "\nunexpected EOF")),
    ("wrong-stream", (1, NO_CHECKS_MESSAGE, "")),
    ("with-payload", (1, JSON_GREEN[1], NO_CHECKS_MESSAGE)),
    ("wrong-exit", (4, "", NO_CHECKS_MESSAGE)),
):
    CELLS.append(cell("json-no-checks-" + _label, _result, True, 2, "ERROR", None, None,
                      "only the exact gh zero-check result can be opted out"))



# --- row retention, as a family rather than case by case (round-7 note) -----
# Distinct check rows must survive even when gh reports the same name.
_ROW_RETENTION_NAMES = (("colliding", "build"), ("empty", ""), ("padded", "  "),
                        ("column-name", "NAME"))
_ROW_RETENTION_PAIRS = (("fail-pass", "fail", "pass", 1, 0, 1, "checks"),
                        ("pass-fail", "pass", "fail", 1, 0, 1, "checks"),
                        ("pending-pass", "pending", "pass", 1, 1, 0, "checks pending"),
                        ("pass-pending", "pass", "pending", 1, 1, 0, "checks pending"))
_RETENTION_BUCKET_STATE = {"pass": "SUCCESS", "fail": "FAILURE", "pending": "PENDING"}
for _name_label, _name in _ROW_RETENTION_NAMES:
    for _label, _first, _second, _ok, _pending, _failing, _reason in _ROW_RETENTION_PAIRS:
        CELLS.append(cell(
            "json-row-retention-%s-%s" % (_name_label, _label),
            _json([{"name": _name, "state": _RETENTION_BUCKET_STATE[_first], "bucket": _first},
                   {"name": _name, "state": _RETENTION_BUCKET_STATE[_second], "bucket": _second}]),
            False, 1, "BLOCKED", _reason, (2, _ok, _pending, _failing),
            "two structured rows named %r differing only by verdict are two rows, and the "
            "non-green one blocks" % _name))

# Drive every declared bucket, independent of production's mapping.
for _token, _conclusion in sorted(DECLARED_VOCABULARY.items()):
    _code, _reason, _tally = _VERDICT[classification(_conclusion)]
    CELLS.append(cell(
        "bucket-vocabulary-%s" % _token,
        _json([{"name": "row", "state": "COMPLETED", "bucket": _token}]),
        False, _code, "MERGE-OK" if _reason is None else "BLOCKED", _reason, _tally,
        "the declared bucket determines the verdict"))

# --- the bucket x state dimension: the bucket governs -----------------------
# Every declared bucket token against every raw state gh reports (gh_checks_fixtures.py). The queue
# is decided by the bucket alone, so each expectation depends on the bucket and not on the state; a
# cell where the raw state disagrees is what tells the bucket from the state.
def dimension_cells():
    cells = []
    buckets = DECLARED_VOCABULARY
    for token in sorted(buckets):
        cls = classification(buckets[token])
        code, reason, tally = _VERDICT[cls]
        for state in captured.STATE_VOCABULARY:
            row = {"name": "row", "state": state, "bucket": token}
            for flag in (False, True):
                cells.append(cell(
                    "bucket-%s-%s%s" % (state, token, "-flag" if flag else ""),
                    _json([row]), flag, code,
                    "MERGE-OK" if reason is None else "BLOCKED", reason, tally,
                    "the %s bucket is %s whatever raw state %s says; the flag cannot change a "
                    "bucket" % (token, cls, state)))
    return cells


CELLS.extend(dimension_cells())

# --- an undeclared or absent bucket, and an absent raw state ----------------
for _label, _row in (("unknown", {"name": "row", "state": "SUCCESS", "bucket": "unreleased"}),
                     ("missing", {"name": "row", "state": "SUCCESS"}),
                     ("null", {"name": "row", "state": "SUCCESS", "bucket": None}),
                     ("empty", {"name": "row", "bucket": ""}),
                     ("no-state-no-bucket", {"name": "row"})):
    for _flag in (False, True):
        CELLS.append(cell(
            "bucket-%s-token%s" % (_label, "-flag" if _flag else ""), _json([_row]),
            _flag, 1, "BLOCKED", "checks pending", (1, 0, 1, 0),
            "a bucket no surface declares is pending: never ok, never a claimed failure"))
for _label, _row in (("absent", {"name": "row", "bucket": "pass"}),
                     ("null", {"name": "row", "state": None, "bucket": "pass"})):
    CELLS.append(cell(
        "bucket-state-%s-pass" % _label, _json([_row]), False, 0, "MERGE-OK", None,
        (1, 1, 0, 0),
        "the bucket is the verdict; a raw state that is absent or null cannot change it"))


# --- paginated evidence: the continuation pages the gate exists to follow ----
# Both evidence readers paginate, and every other fake hands back a single terminal page — 100
# comments then a stop, or `hasNextPage: false`. So neither continuation rule was exercised and
# either could be broken invisibly: `fetch_issue_comments()`'s `if len(batch) < 100: return` read as
# `<= 100` stops at a full page *before* the page 2 that carries the machine-review marker, and
# `fetch_review_threads()`'s `cursor = page.get("endCursor")` read as `None` stops the thread loop
# before the page 2 that carries an unresolved thread. Each turns a blocked verdict into MERGE-OK
# once the blocking evidence lives on page 2, so each cell drives `main()` with a two-page fixture
# whose page 2 is what changes the verdict, and both continuation calls — the comment page 2 read
# and the cursor-carrying GraphQL request — are pinned in the golden call log below.
CLEAN_COMMENT = {"id": 0, "body": "no marker in this one"}
FINDINGS_MARKER_BODY = ('machine-review-state:v1 '
                        '{"code_review": {"status": "completed", "has_any_findings": true}}')
# A full first page, so only the continuation rule (not the batch size) decides whether page 2 is
# read; the marker lives on the newest page, which `evaluate_review()` reaches first after reversal.
COMMENT_PAGES_WITH_MARKER = [
    [dict(CLEAN_COMMENT, id=100 + index) for index in range(100)],
    [{"id": 200, "body": FINDINGS_MARKER_BODY}],
]
UNRESOLVED_THREAD = {"isResolved": False, "path": "skills/gdd/SKILL.md", "line": 3}
THREAD_PAGES_WITH_UNRESOLVED = [([], True, "THREAD-CURSOR-2"),
                                ([UNRESOLVED_THREAD], False, None)]

CELLS += [
    cell("comments-page-2-marker-blocks", JSON_GREEN, False, 1, "BLOCKED", "review",
         (1, 1, 0, 0),
         "the machine-review marker on comment page 2 is read, so a stale page-1 read cannot "
         "report MERGE-OK over newer findings", comment_pages=COMMENT_PAGES_WITH_MARKER),
    cell("threads-page-2-unresolved-blocks", JSON_GREEN, False, 1, "BLOCKED",
         "threads", (1, 1, 0, 0),
         "an unresolved review thread on page 2 is counted, so stopping after page 1 cannot "
         "report MERGE-OK with a thread still open", thread_pages=THREAD_PAGES_WITH_UNRESOLVED),
]


JSON_ABSENT_SHAPE = "(empty stdout)"
STATE_ABSENT = "(state absent, null or undeclared)"
BUCKET_UNDECLARED = "(undeclared bucket)"


def _json_shape(result):
    """The structural shape of one structured-read (`--json`) fixture's stdout."""
    _returncode, stdout, _stderr = result
    if stdout == "":
        return JSON_ABSENT_SHAPE
    try:
        data = json.loads(stdout)
    except ValueError:
        return "unparseable"
    if isinstance(data, list):
        return ("list-of-objects" if all(isinstance(entry, dict) for entry in data)
                else "list-with-non-object")
    return "non-list"


def _structured_rows(cell_):
    """The `--json` rows a cell's fixture yields, or `[]` when its stdout is not a JSON list."""
    _returncode, stdout, _stderr = cell_.json_result
    try:
        data = json.loads(stdout or "[]")
    except ValueError:
        return []
    return data if isinstance(data, list) else []


def _cell_buckets(cell_):
    """The bucket tokens a cell's structured rows carry, with an undeclared sentinel."""
    values = set()
    for row in _structured_rows(cell_):
        if isinstance(row, dict):
            token = str(row.get("bucket") or "").lower()
            values.add(token if token in DECLARED_VOCABULARY else BUCKET_UNDECLARED)
    return values


def _cell_states(cell_):
    """The raw states a cell's structured rows carry, with an absent/undeclared sentinel."""
    values = set()
    for row in _structured_rows(cell_):
        if isinstance(row, dict):
            state = row.get("state")
            values.add(state if state in captured.STATE_VOCABULARY else STATE_ABSENT)
    return values


Dimension = namedtuple("Dimension", "name values negative_values extract")

# The declared value lists. `values` is every value the cells must represent; `negative_values` is
# the subset that must appear in at least one negative (BLOCKED or ERROR) cell, i.e. the values
# whose presence has a verdict consequence — an ok bucket need only appear, it has no negative.
DIMENSIONS = (
    Dimension("structured-exit", EXIT_CATEGORIES, EXIT_CATEGORIES,
              lambda cell_: {cell_.json_result[0]}),
    Dimension("allow-no-checks", (False, True), (False, True),
              lambda cell_: {cell_.allow_no_checks}),
    Dimension("json-shape",
              (JSON_ABSENT_SHAPE, "unparseable", "list-of-objects", "list-with-non-object",
               "non-list"),
              (JSON_ABSENT_SHAPE, "unparseable", "list-of-objects", "list-with-non-object",
               "non-list"),
              lambda cell_: {_json_shape(cell_.json_result)}),
    Dimension("bucket", tuple(sorted(DECLARED_VOCABULARY)) + (BUCKET_UNDECLARED,),
              ("fail", "cancel", "pending", BUCKET_UNDECLARED), _cell_buckets),
    # Every raw state gh prints, plus the absent/undeclared sentinel — each paired with a non-green
    # bucket somewhere, so each has a negative cell.
    Dimension("state", tuple(captured.STATE_VOCABULARY) + (STATE_ABSENT,),
              tuple(captured.STATE_VOCABULARY) + (STATE_ABSENT,), _cell_states),
    Dimension("verified-head/gates-rc",
              ((HEAD, 0), (MISMATCHED_HEAD, 0), (HEAD[:8], 0), (HEAD, 1)),
              ((MISMATCHED_HEAD, 0), (HEAD[:8], 0), (HEAD, 1)),
              lambda cell_: {(cell_.verified_head, cell_.gates_rc)}),
)


def dimension_problems(cells):
    """Every declared dimension value no cell represents, or represents only positively.

    A value with a verdict consequence that appears in no negative cell is as invisible as a value
    that appears in no cell: in both cases a mutation that only that value can catch survives the
    matrix. The failure names the value and its dimension so the gap is fixed where it belongs.
    """
    problems = []
    for dimension in DIMENSIONS:
        seen, seen_negative = set(), set()
        for cell_ in cells:
            values = dimension.extract(cell_)
            if not values:
                continue
            seen |= values
            if cell_.verdict != "MERGE-OK":
                seen_negative |= values
        for value in dimension.values:
            if value not in seen:
                problems.append((
                    "dimension-%s" % dimension.name,
                    "the value %r of the %s dimension is represented by no cell"
                    % (value, dimension.name)))
            elif value in dimension.negative_values and value not in seen_negative:
                problems.append((
                    "dimension-%s" % dimension.name,
                    "the value %r of the %s dimension has no negative (BLOCKED or ERROR) cell"
                    % (value, dimension.name)))
    return problems


# --- stream fidelity (invariant 7) ------------------------------------------
# A verdict cell cannot express this: sh_raw's padding is invisible to every verdict because
# parse_text_checks strips each data field and json.loads tolerates surrounding whitespace. These
# cells compare the exact bytes sh_raw hands back instead of dropping the invariant silently.
STREAM_CELLS = [
    StreamCell("stream-padded-stdout", "  leading\nbody\n\n", "err", 7,
               "sh_raw must return stdout unchanged, padding and newlines included"),
    StreamCell("stream-padded-stderr", "out", "\ttrailing space \n\n", 7,
               "sh_raw must return stderr unchanged, padding and newlines included"),
    StreamCell("stream-both-padded", "\n\n  x  \n\n", "\n  y  \n", 8,
               "both streams survive a non-zero exit verbatim"),
]


# --- sh()'s required trimming (round-10 F2) ---------------------------------
# Every fake above feeds the gate a child that prints exactly `feature`/`HEAD` with no trailing
# newline, so the final `stdout.strip()` in sh() never had to remove anything and deleting it
# survived the whole matrix. A real child prints `feature\n`; handed on unchanged,
# `resolve_head()` compares "feature\n" against the PR's `headRefName` ("feature"), fails the
# local-branch test and reports `head not verified` for a branch that did verify. Pin the value
# sh() returns from newline-terminated output, compared against the literal and never a
# normalised copy of it.
SH_TRIM_CELLS = [
    ShCell("sh-trims-trailing-newline", "feature\n", "", 0, "feature",
           "sh() must return the child's value with the trailing newline removed, or a verified "
           "local branch reads as unverified"),
]


# --- the subprocess boundary: the repository actually reaches the child ------
# No verdict cell can express this: the fake that drives them accepts `cwd` and ignores it, so
# replacing `cwd=repo` at any call site — or `cwd=cwd` inside sh_raw with `cwd=None` — left all of
# them green while the child inspected the caller's repository instead of the one `--repo` names,
# silently invalidating the evidence the gate exists to collect. The repository is the one input
# the gate forwards to *both* surfaces, and each surface forwards it a different way: `gh` through
# the working directory, `git` through `-C <path>` in argv. Each cell runs the gate from a
# repository directory distinct from the runner's and reads back what the fake actually handed to
# subprocess.run(), so a dropped directory is a failure and not an invisible rename.

BoundaryCell = namedtuple("BoundaryCell", "id surface")
BOUNDARY_CELLS = [
    BoundaryCell("boundary-repo-gh-cwd", "gh"),
    BoundaryCell("boundary-repo-git-flag", "git"),
]
STRUCTURED_CHECKS_ARGV = ("gh", "pr", "checks", REQUESTED_PR, "--json", "name,state,bucket")


# --- the captured vocabulary ------------------------------------------------

def fixture_problems():
    """Every value the captured `gh` output prints must be declared, or the fixtures fail.

    A new value in a fresh capture that the vocabulary does not know fails here instead of reaching
    the gate as an unknown token.
    """
    problems = []
    for name, capture in sorted(captured.CAPTURES.items()):
        for row in json.loads(capture["json"]):
            if str(row.get("bucket") or "").lower() not in VOCABULARY:
                problems.append(("capture-%s-bucket" % name,
                                 "the JSON prints the undeclared bucket %r" % row.get("bucket")))
            state = row.get("state")
            if state not in captured.STATE_VOCABULARY:
                problems.append(("capture-%s-state" % name,
                                 "the JSON prints the undeclared state %r" % state))
            elif captured.STATE_BUCKETS[state] != row.get("bucket"):
                problems.append(("capture-%s-pairing" % name,
                                 "state %s should group into bucket %s, got %r"
                                 % (state, captured.STATE_BUCKETS[state], row.get("bucket"))))
    return problems


# --- the harness ------------------------------------------------------------

def _threads_page(nodes, has_next, end_cursor):
    """One `reviewThreads` page, as the JSON `gh api graphql` prints."""
    return json.dumps({"data": {"repository": {"pullRequest": {"reviewThreads": {
        "pageInfo": {"hasNextPage": has_next, "endCursor": end_cursor},
        "nodes": nodes}}}}})


# The single terminal page every cell without a `thread_pages` fixture sees: no nodes to follow.
TERMINAL_THREADS = _threads_page([], False, None)


def _fake_run_for(cell_, records=None, repo_token=None):
    view = {"state": "OPEN", "isDraft": False, "headRefOid": HEAD, "headRefName": "feature"}

    def fake_run(cmd, cwd=None, capture_output=False, text=False, env=None, **_options):
        # The golden call log keeps what the gate forwards to the child: the command, the working
        # directory and whether it passed an environment. capture_output/text describe how the gate
        # reads the streams, not what the child is asked to run.
        _record_call(_normalize_argv(cmd, repo_token), _normalize_cwd(cwd, repo_token),
                     env is not None)
        if records is not None:
            records.append((list(cmd), cwd))
        if cmd[:1] == ["git"]:
            branch = "--abbrev-ref" in cmd
            return subprocess.CompletedProcess(cmd, 0, "feature" if branch else HEAD, "")
        if cmd[:3] == ["gh", "pr", "checks"]:
            returncode, stdout, stderr = cell_.json_result
            return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)
        if cmd[:3] == ["gh", "pr", "view"]:
            return subprocess.CompletedProcess(cmd, 0, json.dumps(view), "")
        if cmd[:3] == ["gh", "repo", "view"]:
            return subprocess.CompletedProcess(cmd, 0, "fixture-owner/fixture-repo", "")
        if cmd[:3] == ["gh", "api", "graphql"]:
            # Without a fixture the thread read is terminal; with one, the page the request's
            # cursor names decides — so a gate that drops the cursor is served page 1 again and
            # cannot see the page-2 thread.
            pages = cell_.thread_pages
            if not pages:
                return subprocess.CompletedProcess(cmd, 0, TERMINAL_THREADS, "")
            cursor = next((part[len("cursor="):] for part in cmd
                           if isinstance(part, str) and part.startswith("cursor=")), None)
            index = 0
            if cursor is not None:
                index = next((position + 1 for position, page in enumerate(pages)
                              if page[2] == cursor), None)
                if index is None:
                    raise AssertionError("unexpected review-threads cursor: %r" % (cursor,))
            nodes, has_next, end_cursor = pages[index]
            return subprocess.CompletedProcess(cmd, 0,
                                              _threads_page(nodes, has_next, end_cursor), "")
        if cmd[:2] == ["gh", "api"]:
            pages = cell_.comment_pages
            if not pages:
                return subprocess.CompletedProcess(cmd, 0, "[]", "")
            page = int(cmd[2].split("&page=")[1])
            return subprocess.CompletedProcess(cmd, 0, json.dumps(pages[page - 1]), "")
        raise AssertionError("unexpected command: %s" % (cmd,))

    return fake_run


def run_cell(module, cell_):
    """Drive one verdict cell through the real entry point. Returns (code, stdout, stderr)."""
    argv = ["pr-merge-check.py", REQUESTED_PR, "--repo", ".", "--verified-head",
            cell_.verified_head, "--gates-rc", str(cell_.gates_rc), "--allow-no-machine-review"]
    if cell_.allow_no_checks:
        argv.append("--allow-no-checks")
    out, err = io.StringIO(), io.StringIO()
    with patch.object(subprocess, "run",
                      side_effect=_fake_run_for(cell_, repo_token=".")), \
            patch.object(sys, "argv", argv), redirect_stdout(out), redirect_stderr(err):
        code = module.main()
    return code, out.getvalue(), err.getvalue()


def checks_line(checks):
    """The exact `checks:` line the gate prints for a (total, ok, pending, failing) tally."""
    total, ok, pending, failing = checks
    return "checks: %d total, %d ok, %d pending, %d failing%s" % (
        total, ok, pending, failing, " (no checks)" if total == 0 else "")


def expected_verdict_line(cell_):
    return "verdict: MERGE-OK" if cell_.reason is None else "verdict: BLOCKED: " + cell_.reason


def lines_with_prefix(out, prefix):
    return [line for line in out.splitlines() if line.startswith(prefix)]


def check_cell(module, cell_):
    """None when the cell matches its invariant-written expectation, else a problem string."""
    try:
        code, out, err = run_cell(module, cell_)
    except Exception as exc:  # a mutant may crash where the rule says it must not
        return "raised %s: %s" % (type(exc).__name__, exc)
    if cell_.verdict == "ERROR":
        if code != 2:
            return "expected exit 2, got %s (stdout=%r)" % (code, out.strip())
        if out.strip():
            return "expected no verdict on stdout, got %r" % (out.strip(),)
        if not err.startswith("pr-merge-check:"):
            return "expected a one-line stderr error, got %r" % (err.strip(),)
        for fragment in cell_.error_contains or ():
            if fragment not in err:
                return "expected the error to carry %r, got %r" % (fragment, err.strip())
        if len(err.splitlines()) != 1:
            return "expected exactly one diagnostic line, got %r" % err
        return None
    if code != cell_.exit_code:
        return ("expected exit %s, got %s (stdout=%r stderr=%r)"
                % (cell_.exit_code, code, out.strip(), err.strip()))
    # The complete verdict line, never a substring of it: "BLOCKED: checks" is a prefix of
    # "BLOCKED: checks pending", so a substring test accepted a failing read as a pending one.
    verdict_lines = lines_with_prefix(out, "verdict: ")
    expected_verdict = expected_verdict_line(cell_)
    if verdict_lines != [expected_verdict]:
        return "expected verdict line %r, got %r" % (expected_verdict, verdict_lines)
    # The printed tally, exactly: the classification of every row, not just the verdict word.
    expected_checks = checks_line(cell_.checks)
    observed_checks = lines_with_prefix(out, "checks: ")
    if observed_checks != [expected_checks]:
        return "expected checks line %r, got %r" % (expected_checks, observed_checks)
    if err:
        return "unexpected stderr beside verdict: %r" % err
    return None


def run_stream_cell(module, stream_cell):
    """sh_raw() with subprocess.run() faked: returns the forwarded (code, stdout, stderr)."""

    def fake_run(cmd, cwd=None, capture_output=False, text=False, **_options):
        return subprocess.CompletedProcess(cmd, stream_cell.exit_code,
                                           stream_cell.stdout, stream_cell.stderr)

    with patch.object(subprocess, "run", side_effect=fake_run):
        return module.sh_raw(["gh", "pr", "checks", "7"])


def check_stream_cell(module, stream_cell):
    try:
        observed = run_stream_cell(module, stream_cell)
    except Exception as exc:
        return "raised %s: %s" % (type(exc).__name__, exc)
    expected = (stream_cell.exit_code, stream_cell.stdout, stream_cell.stderr)
    if observed != expected:
        return "expected %r, got %r" % (expected, observed)
    return None


def run_sh_cell(module, sh_cell):
    """sh() with subprocess.run() faked: returns the value sh() handed back."""

    def fake_run(cmd, cwd=None, capture_output=False, text=False, **_options):
        return subprocess.CompletedProcess(cmd, sh_cell.exit_code, sh_cell.stdout, sh_cell.stderr)

    with patch.object(subprocess, "run", side_effect=fake_run):
        return module.sh(["git", "-C", ".", "rev-parse", "--abbrev-ref", "HEAD"])


def check_sh_cell(module, sh_cell):
    """The value sh() returns must equal the pinned literal — never a normalised copy of it, which
    would agree with the mutant that skips the trimming."""
    try:
        observed = run_sh_cell(module, sh_cell)
    except Exception as exc:
        return "raised %s: %s" % (type(exc).__name__, exc)
    if observed != sh_cell.expected:
        return "expected the returned value %r, got %r" % (sh_cell.expected, observed)
    return None


def run_boundary_cell(module, boundary_cell, repo, records):
    """Drive main() from `repo` over the cell's read, recording every raw (cmd, cwd)."""
    driver = cell(boundary_cell.id, JSON_GREEN, False, 0, "MERGE-OK", None,
                  (1, 1, 0, 0), "green manual check read")
    argv = ["pr-merge-check.py", REQUESTED_PR, "--repo", repo, "--verified-head", HEAD,
            "--gates-rc", "0", "--allow-no-machine-review"]
    out, err = io.StringIO(), io.StringIO()
    with patch.object(subprocess, "run",
                      side_effect=_fake_run_for(driver, records, repo_token=repo)), \
            patch.object(sys, "argv", argv), redirect_stdout(out), redirect_stderr(err):
        module.main()


def check_boundary_cell(module, boundary_cell):
    """The named repository and exact structured check argv reach the child."""
    repo = os.path.realpath(tempfile.mkdtemp(prefix="gdd-boundary-repo-"))
    try:
        if repo == os.path.realpath(os.getcwd()):
            return "the boundary repository must differ from the runner's directory"
        records = []
        try:
            run_boundary_cell(module, boundary_cell, repo, records)
        except Exception as exc:  # a mutant may crash where the gate must run
            return "raised %s: %s" % (type(exc).__name__, exc)
        calls = [(cmd, cwd) for cmd, cwd in records if cmd[:1] == [boundary_cell.surface]]
        if not calls:
            return "the gate issued no %s call to inspect" % boundary_cell.surface
        if boundary_cell.surface == "gh":
            wrong = [(cmd, cwd) for cmd, cwd in calls if cwd != repo]
            if wrong:
                return ("%d gh call(s) ran outside the repository: cwd=%r, expected %r "
                        "(first: %r)" % (len(wrong), wrong[0][1], repo, wrong[0][0]))
            shapes = {tuple(cmd) for cmd, _ in calls if cmd[:3] == ["gh", "pr", "checks"]}
            if shapes != {STRUCTURED_CHECKS_ARGV}:
                return "expected only %r, saw %r" % (STRUCTURED_CHECKS_ARGV, sorted(shapes))
        else:
            for cmd, _ in calls:
                # The pair must be adjacent: `["git", repo, ...]` keeps the path in argv while Git
                # no longer has a valid repository selection.
                if cmd[1:3] != ["-C", repo]:
                    return ("a git call did not carry the adjacent [\"-C\", repo] pair (first: %r)"
                            % (cmd,))
        return None
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def evaluate(module):
    """Every cell that the module under test violates, as (id, problem).

    When recording is on (see `evaluate_with_calls`) the golden call-log comparison is part of this,
    so the invocations the module issued are judged alongside the cells.
    """
    problems = declaration_problems(module)
    for cell_ in CELLS:
        problem = check_cell(module, cell_)
        if problem is not None:
            problems.append((cell_.id, problem))
    for stream_cell in STREAM_CELLS:
        problem = check_stream_cell(module, stream_cell)
        if problem is not None:
            problems.append((stream_cell.id, problem))
    for sh_cell in SH_TRIM_CELLS:
        problem = check_sh_cell(module, sh_cell)
        if problem is not None:
            problems.append((sh_cell.id, problem))
    for boundary_cell in BOUNDARY_CELLS:
        problem = check_boundary_cell(module, boundary_cell)
        if problem is not None:
            problems.append((boundary_cell.id, problem))
    if _calls_seen is not None:
        problems.extend(call_log_problems(set(_calls_seen)))
    return problems


def evaluate_with_calls(module):
    """`evaluate` over one instrumented run: every call the module issues is compared with the log.

    The mutation harness drives each mutant through this, so the snapshot is mutation-tested too: a
    change no cell happens to name still has to change the recorded call set.
    """
    global _calls_seen
    _calls_seen = set()
    try:
        return evaluate(module)
    finally:
        _calls_seen = None


# --- the golden snapshot ----------------------------------------------------
# One entry per distinct invocation the gate issues through main(), in canonical `repr` order, each
# with the reason it is there. Any change to a command, an argument, a flag, the PR number, the
# repository pair or a call's working directory changes this set and fails the matrix, so the
# forwarding obligations are pinned by construction rather than by a hand-written assertion per
# obligation. The existing cells and the boundary assertions stay: they give better failure
# messages; this snapshot is the backstop that catches what no assertion happens to name.
#
# To update: read the gate diff, decide the change is intended, then edit this set by hand. Never
# paste back the set the failure printed — that turns "the gate invokes something new" into "the
# test agrees with the mutation", which is the failure mode this snapshot exists to prevent.
GOLDEN_CALLS = frozenset({
    # The review-thread read: one graphql call, paged, carrying owner/name/pr for the requested PR.
    (("gh", "api", "graphql",
      "-f",
      "query=query($owner:String!,$repo:String!,$pr:Int!,$cursor:String){"
      "repository(owner:$owner,name:$repo){pullRequest(number:$pr){"
      "reviewThreads(first:100,after:$cursor){pageInfo{hasNextPage endCursor}"
      "nodes{isResolved path line}}}}}",
      "-f", "owner=fixture-owner", "-f", "repo=fixture-repo", "-F", "pr=7"),
     REPO_TOKEN, False),
    # The review-thread read's second page: the same GraphQL query with the `endCursor` page 1
    # returned, issued only for a cell whose thread fixture has a page 2.
    (("gh", "api", "graphql",
      "-f",
      "query=query($owner:String!,$repo:String!,$pr:Int!,$cursor:String){"
      "repository(owner:$owner,name:$repo){pullRequest(number:$pr){"
      "reviewThreads(first:100,after:$cursor){pageInfo{hasNextPage endCursor}"
      "nodes{isResolved path line}}}}}",
      "-f", "owner=fixture-owner", "-f", "repo=fixture-repo", "-F", "pr=7",
      "-f", "cursor=THREAD-CURSOR-2"),
     REPO_TOKEN, False),
    # The issue-comment read: the REST endpoint for the requested PR, in the named repository.
    (("gh", "api", "repos/fixture-owner/fixture-repo/issues/7/comments?per_page=100&page=1"),
     REPO_TOKEN, False),
    # The issue-comment read's second page, issued only for a cell whose comment fixture fills
    # page 1 — the continuation the marker's own page depends on.
    (("gh", "api", "repos/fixture-owner/fixture-repo/issues/7/comments?per_page=100&page=2"),
     REPO_TOKEN, False),
    # The structured check read: the requested PR, the bucket field list, in the named repository.
    (("gh", "pr", "checks", "7", "--json", "name,state,bucket"), REPO_TOKEN, False),
    # The PR state/head read: the requested PR and the four fields it needs.
    (("gh", "pr", "view", "7", "--json", "headRefOid,headRefName,state,isDraft"),
     REPO_TOKEN, False),
    # The repository identity read that names owner/name for the two api calls above.
    (("gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"),
     REPO_TOKEN, False),
    # The local branch read; `--repo` travels as the adjacent `-C <repo>` pair, not as a cwd.
    (("git", "-C", REPO_TOKEN, "rev-parse", "--abbrev-ref", "HEAD"), None, False),
    # The local head read; same `-C <repo>` forwarding.
    (("git", "-C", REPO_TOKEN, "rev-parse", "HEAD"), None, False),
})


def _format_call(entry):
    """One recorded invocation as a copyable line: the argv, the working directory, the env flag."""
    argv, cwd, has_env = entry
    return "argv=%r cwd=%r passed_env=%s" % (list(argv), cwd, has_env)


def call_log_problems(observed):
    """Every way the invocations the gate issued differ from `GOLDEN_CALLS`.

    A *set* comparison, so a call issued by one cell more or fewer times is not a change — the
    cells are enumerated elsewhere; the claim pinned here is which commands the gate runs, with
    which arguments, in which directory.
    """
    golden = set(GOLDEN_CALLS)
    problems = []
    for entry in sorted(golden - set(observed), key=repr):
        problems.append((
            "call-log-removed",
            "the gate no longer issues %s; if removing it is intended, review the gate diff and "
            "update GOLDEN_CALLS deliberately (do not paste the observed set back)"
            % _format_call(entry)))
    for entry in sorted(set(observed) - golden, key=repr):
        problems.append((
            "call-log-added",
            "the gate now issues %s, which GOLDEN_CALLS does not name; if the new invocation is "
            "intended, review the gate diff and add it deliberately" % _format_call(entry)))
    return problems


def main():
    start = time.monotonic()
    problems = fixture_problems()
    problems.extend(dimension_problems(CELLS))
    problems.extend(evaluate_with_calls(GATE))
    for cell_id, problem in problems:
        print("  FAIL  %s: %s" % (cell_id, problem))
    elapsed = time.monotonic() - start
    total = len(CELLS) + len(STREAM_CELLS) + len(SH_TRIM_CELLS) + len(BOUNDARY_CELLS)
    print("verdict-matrix: %d verdict cells + %d stream cells + %d sh cells + %d boundary cells "
          "= %d cells, %d dimensions, %d golden calls, %d failed, %.2fs"
          % (len(CELLS), len(STREAM_CELLS), len(SH_TRIM_CELLS), len(BOUNDARY_CELLS), total,
             len(DIMENSIONS), len(GOLDEN_CALLS), len(problems), elapsed))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
