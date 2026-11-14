#!/usr/bin/env python3
"""Exhaustive verdict matrix for the merge gate's check-fetch surface.

The matrix is generated from what `pr-merge-check.py` declares plus what `gh` prints, not from
what the implementation happens to answer:

* the rows come from the gate's single declared `CHECK_VOCABULARY` (every verdict token each read
  surface can print) and from the raw `state` vocabulary beside them in
  `tests/gh_checks_fixtures.py` — captured live from `gh pr checks` on three open PRs;
* the expectation for each row is computed from the invariants stated once below: only a completed
  success or the skipping/neutral conventions are ok, a waiting conclusion is pending, everything
  else blocks, an undeclared verdict blocks, and `--allow-no-checks` forgives only a successfully
  read zero-check result;
* the comparison is exact — the whole verdict line plus the printed `checks:` tally — so a cell
  cannot accept one classification in place of another.

Cells that cannot be expressed this way (the JSON shapes, the non-zero-exit fallback rules) are
listed explicitly, each with its expected tally and its reason. `subprocess.run()` is mocked and
every cell is driven through `main()`, so the matrix is end to end.

Run: python3 skills/gdd/scripts/tests/test_verdict_matrix.py
"""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
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


def load_gate(path=None):
    """Import pr-merge-check.py (or a mutated in-memory variant via the harness) as a module."""
    path = Path(path or (SCRIPTS / "pr-merge-check.py"))
    spec = importlib.util.spec_from_file_location("pr_merge_check_matrix", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The gate as shipped. The vocabulary is read once, here, so the expectations below are those of the
# declared artefact: a mutation that reclassifies a token in memory changes the gate's behaviour
# without changing what this matrix expects, which is what makes the mutation visible.
GATE = load_gate()
VOCABULARY = dict(GATE.CHECK_VOCABULARY)


def vocabulary(surface):
    """The `<surface>` slice of the declared vocabulary, as {token: conclusion}."""
    prefix = surface + "/"
    return {key[len(prefix):]: value for key, value in VOCABULARY.items()
            if key.startswith(prefix)}


# --- the invariants, stated once --------------------------------------------
# Only a completed success, or the skipping/neutral conventions, is ok. A waiting conclusion is
# pending. Everything else blocks, and a verdict no surface declares is not permission either: a
# table row falls back to FAILURE, a JSON bucket to pending.
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

# --- fixtures ---------------------------------------------------------------

TABLE_HEADER = "NAME\tSTATUS\tELAPSED\tURL\tDESCRIPTION\n"
GREEN_TABLE = "lint\tskipping\t8s\thttps://example/1\t\nunit\tpass\t1m0s\thttps://example/2\t\n"
MIXED_TABLE = ("verify\tfail\t4m9s\thttps://example/1\t\n"
               "foreign-notes\tpass\t20s\thttps://example/2\t\n"
               "docs\tpending\t1m2s\thttps://example/3\t\n")
IN_FLIGHT_TABLE = ("foreign-notes\tpass\t20s\thttps://example/2\t\n"
                   "docs\tpending\t1m2s\thttps://example/3\t\n")
NAME_PREFIXED_TABLE = (TABLE_HEADER + "build\tpass\t1m0s\thttps://example/1\t\n"
                       "NAME-required\tfail\t4m9s\thttps://example/2\t\n")
NAME_PREFIXED_PENDING_TABLE = (TABLE_HEADER + "build\tpass\t1m0s\thttps://example/1\t\n"
                               "NAME-required\tpending\t2m0s\thttps://example/2\t\n")
REAL_GH_TABLE = ("release\tskipping\t0\thttps://example/runs/1/job/2\t\n"
                 "test\tpass\t1m52s\thttps://example/runs/1/job/3\t\n")
# A truncated row: the trailing line carries no tab, so it is not a row and disappears.
TRUNCATED_TABLE = "build\tpass\t1s\thttps://example/1\t\nrequired\n"
# The unordered-header shape that used to vanish: `STATUS\tNAME` is a row, not the header.
UNORDERED_HEADER_TABLE = "build\tpass\nSTATUS\tNAME\n"

TABLE_UNUSED = (0, "", "")
JSON_ABSENT = (1, "", 'Unknown JSON field: "conclusion"')
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

Cell = namedtuple("Cell", "id json_result table_result allow_no_checks exit_code verdict reason "
                          "checks why")
StreamCell = namedtuple("StreamCell", "id stdout stderr exit_code why")


def cell(cid, json_result, table_result, allow_no_checks, exit_code, verdict, reason, checks, why):
    """One verdict cell. `checks` is the expected `checks:` tally, or None when there is no read."""
    return Cell(cid, json_result, table_result, allow_no_checks, exit_code, verdict, reason,
                checks, why)


# --- the matrix -------------------------------------------------------------

CELLS = [
    # --- JSON path: the bucket x state dimension (invariant 3, 4) -----------
    cell("json-green", JSON_GREEN, TABLE_UNUSED, False, 0, "MERGE-OK", None, (1, 1, 0, 0),
         "the only ok bucket is pass/skipping/neutral on a completed check"),
    cell("json-green-flag", JSON_GREEN, TABLE_UNUSED, True, 0, "MERGE-OK", None, (1, 1, 0, 0),
         "the flag changes nothing when checks are actually green"),
    cell("json-pending", JSON_PENDING, TABLE_UNUSED, False, 1, "BLOCKED", "checks pending",
         (1, 0, 1, 0), "a pending check blocks and the reason names it"),
    cell("json-pending-flag", JSON_PENDING, TABLE_UNUSED, True, 1, "BLOCKED", "checks pending",
         (1, 0, 1, 0), "the flag forgives zero checks, not a reported pending check"),
    cell("json-fail", JSON_FAIL, TABLE_UNUSED, False, 1, "BLOCKED", "checks", (1, 0, 0, 1),
         "a failed check blocks"),
    cell("json-fail-flag", JSON_FAIL, TABLE_UNUSED, True, 1, "BLOCKED", "checks", (1, 0, 0, 1),
         "the flag forgives zero checks, not a reported failure"),
    cell("json-pass-plus-pending", JSON_PASS_PENDING, TABLE_UNUSED, False, 1, "BLOCKED",
         "checks pending", (2, 1, 1, 0), "one pending check beside a passing one still blocks"),
    cell("json-pass-plus-pending-flag", JSON_PASS_PENDING, TABLE_UNUSED, True, 1, "BLOCKED",
         "checks pending", (2, 1, 1, 0), "a passing neighbour does not make pending forgivable"),

    # --- JSON path: shapes (invariants 1, 2) -------------------------------
    cell("json-empty-list", JSON_EMPTY, TABLE_UNUSED, False, 1, "BLOCKED", "no checks", (0, 0, 0, 0),
         "a successfully read empty list is the zero-check state and blocks"),
    cell("json-empty-list-flag", JSON_EMPTY, TABLE_UNUSED, True, 0, "MERGE-OK", None, (0, 0, 0, 0),
         "the flag is exactly the opt-out for a genuinely zero-check read"),
    cell("json-malformed-mixed", JSON_MALFORMED_MIXED, TABLE_UNUSED, False, 2, "ERROR", None, None,
         "a non-object entry beside a valid one is not permission: exit 2"),
    cell("json-malformed-mixed-flag", JSON_MALFORMED_MIXED, TABLE_UNUSED, True, 2, "ERROR", None,
         None, "the flag forgives zero checks, never an unreadable list"),
    cell("json-malformed-only", JSON_MALFORMED_ONLY, TABLE_UNUSED, False, 2, "ERROR", None, None,
         "a list of only non-objects is unreadable: exit 2"),
    cell("json-malformed-only-flag", JSON_MALFORMED_ONLY, TABLE_UNUSED, True, 2, "ERROR", None,
         None, "the flag cannot rescue a malformed list"),
    cell("json-nonlist-empty-table", JSON_NONLIST, (0, "", ""), False, 1, "BLOCKED", "no checks",
         (0, 0, 0, 0), "a non-list payload is not a check list; the table is the fallback and empty"),
    cell("json-nonlist-empty-table-flag", JSON_NONLIST, (0, "", ""), True, 0, "MERGE-OK", None,
         (0, 0, 0, 0), "the fallback read succeeded and is genuinely empty, so the flag forgives it"),
    cell("json-nonlist-green-table", JSON_NONLIST, (0, GREEN_TABLE, ""), False, 0, "MERGE-OK", None,
         (2, 2, 0, 0), "a non-list payload falls back to the table, which here is green"),
    cell("json-garbage-green-table", JSON_GARBAGE, (0, GREEN_TABLE, ""), False, 0, "MERGE-OK", None,
         (2, 2, 0, 0), "unparseable JSON falls back to the table"),
    cell("json-absent-green-table", JSON_ABSENT, (0, GREEN_TABLE, ""), False, 0, "MERGE-OK", None,
         (2, 2, 0, 0), "a non-zero JSON exit falls back to the table, which here is green"),
    cell("json-absent-empty-table", JSON_ABSENT, (0, "", ""), False, 1, "BLOCKED", "no checks",
         (0, 0, 0, 0), "the fallback is reached and reports zero checks"),

    # --- table path: exit codes (invariant 6) ------------------------------
    cell("table-green-exit-0", JSON_ABSENT, (0, GREEN_TABLE, ""), False, 0, "MERGE-OK", None,
         (2, 2, 0, 0), "every row ok and the read exited 0"),
    cell("table-green-exit-1", JSON_ABSENT, (1, GREEN_TABLE, ""), False, 2, "ERROR", None, None,
         "a non-zero exit with an all-green table is an incomplete read, never permission"),
    cell("table-green-exit-8", JSON_ABSENT, (8, GREEN_TABLE, ""), False, 2, "ERROR", None, None,
         "a non-zero exit with an all-green table is an incomplete read, never permission"),
    cell("table-green-exit-1-flag", JSON_ABSENT, (1, GREEN_TABLE, ""), True, 2, "ERROR", None, None,
         "the flag cannot turn an incomplete read into a verdict"),
    cell("table-green-exit-8-flag", JSON_ABSENT, (8, GREEN_TABLE, ""), True, 2, "ERROR", None, None,
         "the flag cannot turn an incomplete read into a verdict"),
    cell("table-truncated-exit-8", JSON_ABSENT, (8, TRUNCATED_TABLE, ""), False, 2, "ERROR", None,
         None, "a dropped truncated row leaves an all-green table under a non-zero exit"),
    cell("table-truncated-exit-8-flag", JSON_ABSENT, (8, TRUNCATED_TABLE, ""), True, 2, "ERROR",
         None, None, "a dropped row is not a zero-check read"),

    # --- table path: reported CI state (invariants 4, 6) -------------------
    cell("table-mixed-exit-8", JSON_ABSENT, (8, MIXED_TABLE, ""), False, 1, "BLOCKED", "checks",
         (3, 1, 1, 1), "a failed row blocks; the non-zero exit is the CI state it reports"),
    cell("table-mixed-exit-1", JSON_ABSENT, (1, MIXED_TABLE, ""), False, 1, "BLOCKED", "checks",
         (3, 1, 1, 1), "a failed row blocks"),
    cell("table-mixed-exit-0", JSON_ABSENT, (0, MIXED_TABLE, ""), False, 1, "BLOCKED", "checks",
         (3, 1, 1, 1), "the rows decide even at a zero exit"),
    cell("table-inflight-exit-8", JSON_ABSENT, (8, IN_FLIGHT_TABLE, ""), False, 1, "BLOCKED",
         "checks pending", (2, 1, 1, 0), "an unfinished run reports pending and blocks"),
    cell("table-inflight-exit-0", JSON_ABSENT, (0, IN_FLIGHT_TABLE, ""), False, 1, "BLOCKED",
         "checks pending", (2, 1, 1, 0), "a pending row blocks whatever the exit code"),
    cell("table-inflight-exit-8-flag", JSON_ABSENT, (8, IN_FLIGHT_TABLE, ""), True, 1, "BLOCKED",
         "checks pending", (2, 1, 1, 0), "the flag does not forgive a reported pending check"),
    cell("table-inflight-exit-0-flag", JSON_ABSENT, (0, IN_FLIGHT_TABLE, ""), True, 1, "BLOCKED",
         "checks pending", (2, 1, 1, 0), "the flag does not forgive a reported pending check"),

    # --- table path: zero-check and error shapes (invariants 1, 2) ---------
    cell("table-header-only", JSON_ABSENT, (0, TABLE_HEADER, ""), False, 1, "BLOCKED", "no checks",
         (0, 0, 0, 0), "a header is not a check; zero rows read successfully is the empty state"),
    cell("table-header-only-flag", JSON_ABSENT, (0, TABLE_HEADER, ""), True, 0, "MERGE-OK", None,
         (0, 0, 0, 0), "a header-only table is a genuinely zero-check read, which the flag forgives"),
    cell("table-header-only-exit-1", JSON_ABSENT, (1, TABLE_HEADER, ""), False, 2, "ERROR", None,
         None, "a non-zero exit with no rows is not the recognized 'no checks reported' state"),
    cell("table-empty-exit-0", JSON_ABSENT, (0, "", ""), False, 1, "BLOCKED", "no checks",
         (0, 0, 0, 0), "an empty successful read is zero checks"),
    cell("table-empty-exit-0-flag", JSON_ABSENT, (0, "", ""), True, 0, "MERGE-OK", None,
         (0, 0, 0, 0), "the flag forgives a genuinely empty successful read"),
    cell("table-no-checks-reported", JSON_ABSENT,
         (1, "", "no checks reported on the 'feature' branch"), False, 1, "BLOCKED", "no checks",
         (0, 0, 0, 0), "gh's own 'no checks reported' is the empty state, not a CLI failure"),
    cell("table-no-checks-reported-flag", JSON_ABSENT,
         (1, "", "no checks reported on the 'feature' branch"), True, 0, "MERGE-OK", None,
         (0, 0, 0, 0), "the recognized empty state is exactly what the flag forgives"),
    cell("table-garbage-exit-1", JSON_ABSENT, (1, "gh: Not Found (HTTP 404)\n", ""), False, 2,
         "ERROR", None, None, "unparseable output is not zero checks: exit 2"),
    cell("table-garbage-exit-1-flag", JSON_ABSENT, (1, "gh: Not Found (HTTP 404)\n", ""), True, 2,
         "ERROR", None, None, "a command error is never an allowed zero-check result"),
    cell("table-stderr-only-exit-1", JSON_ABSENT, (1, "", "HTTP 401: Bad credentials"), False, 2,
         "ERROR", None, None, "an error on stderr with no table is a command error"),
    cell("table-blank-exit-8", JSON_ABSENT, (8, "", "checks pending"), False, 2, "ERROR", None,
         None, "a bare error message with no rows is not parsable evidence"),
    cell("table-blank-exit-8-flag", JSON_ABSENT, (8, "", "checks pending"), True, 2, "ERROR", None,
         None, "the flag cannot make an unparseable read a zero-check read"),

    # --- table path: rows that must not be dropped (invariant 5) -----------
    cell("table-two-column-green", JSON_ABSENT, (0, "build\tpass\n", ""), False, 0, "MERGE-OK",
         None, (1, 1, 0, 0), "the two-column form parses to one ok row"),
    cell("table-two-column-pending", JSON_ABSENT, (0, "build\tpending\n", ""), False, 1, "BLOCKED",
         "checks pending", (1, 0, 1, 0), "the two-column form parses to one pending row"),
    cell("table-unknown-verdict", JSON_ABSENT, (0, "mystery\tunreleased\n", ""), False, 1,
         "BLOCKED", "checks", (1, 0, 0, 1), "an unrecognized verdict word is never ok"),
    cell("table-name-prefixed-fail", JSON_ABSENT, (1, NAME_PREFIXED_TABLE, ""), False, 1, "BLOCKED",
         "checks", (2, 1, 0, 1), "a check named NAME-required is a row, not the header"),
    cell("table-name-prefixed-pending", JSON_ABSENT, (8, NAME_PREFIXED_PENDING_TABLE, ""), False, 1,
         "BLOCKED", "checks pending", (2, 1, 1, 0), "a pending row named NAME-required still blocks"),
    cell("table-name-prefixed-flag", JSON_ABSENT, (1, NAME_PREFIXED_TABLE, ""), True, 1, "BLOCKED",
         "checks", (2, 1, 0, 1), "the flag cannot forgive a reported failure"),
    cell("table-check-named-name", JSON_ABSENT,
         (0, TABLE_HEADER + "NAME\tpass\t1s\thttps://example/0\t\n", ""), False, 0, "MERGE-OK", None,
         (1, 1, 0, 0), "a row named NAME with a pass verdict is a row, not the header"),
    cell("table-real-gh-shape", JSON_ABSENT, (0, REAL_GH_TABLE, ""), False, 0, "MERGE-OK", None,
         (2, 2, 0, 0), "the shape gh emits on this host parses to its verdicts"),

    # --- the unordered header (invariant 5, the fail-open this pins) --------
    # `gh pr checks` prints NAME then STATUS, the full five column names in print order. A set
    # comparison accepted `STATUS\tNAME` as the header, so the row — whose verdict word is unknown
    # — vanished and an all-green remainder printed MERGE-OK. Only the exact header is skipped;
    # every other line is a row, and a row whose verdict word is unknown blocks.
    cell("table-unordered-header-row", JSON_ABSENT, (0, UNORDERED_HEADER_TABLE, ""), False, 1,
         "BLOCKED", "checks", (2, 1, 0, 1),
         "`STATUS\tNAME` is a row with the unknown verdict NAME, beside a passing row"),
    cell("table-unordered-header-row-flag", JSON_ABSENT, (0, UNORDERED_HEADER_TABLE, ""), True, 1,
         "BLOCKED", "checks", (2, 1, 0, 1),
         "the flag forgives zero checks, never a row it could not classify"),
    cell("table-unordered-header-alone-flag", JSON_ABSENT, (0, "STATUS\tNAME\n", ""), True, 1,
         "BLOCKED", "checks", (1, 0, 0, 1),
         "with `STATUS\tNAME` alone the flag must not turn the unread row into permission"),
    cell("table-unordered-full-header", JSON_ABSENT,
         (0, "STATUS\tNAME\tELAPSED\tURL\tDESCRIPTION\n", ""), False, 1, "BLOCKED", "checks",
         (1, 0, 0, 1),
         "a permutation of every column name is a row, not the header; its unknown verdict blocks"),
    cell("table-reordered-header", JSON_ABSENT,
         (0, "NAME\tELAPSED\tSTATUS\tURL\tDESCRIPTION\n", ""), False, 1, "BLOCKED", "checks",
         (1, 0, 0, 1),
         "the column names out of print order are a row, whose verdict word ELAPSED is unknown"),
    cell("table-partial-header", JSON_ABSENT, (0, "NAME\tSTATUS\n", ""), False, 1, "BLOCKED",
         "checks", (1, 0, 0, 1),
         "the leading two column names are not the printed header, so the line is a row and its "
         "unknown verdict blocks"),
    cell("table-partial-header-flag", JSON_ABSENT, (0, "NAME\tSTATUS\n", ""), True, 1, "BLOCKED",
         "checks", (1, 0, 0, 1),
         "the flag forgives zero checks, never a row it could not classify"),

    # --- the captured live shapes, end to end ------------------------------
    # tests/gh_checks_fixtures.py: real `gh pr checks` output from three open PRs.
    cell("live-pending-json", (captured.PENDING["json_rc"], captured.PENDING["json"], ""),
         TABLE_UNUSED, False, 1, "BLOCKED", "checks pending", (1, 0, 1, 0),
         "a live run in flight blocks through the bucket gh reports"),
    cell("live-pending-table", JSON_ABSENT,
         (captured.PENDING["table_rc"], captured.PENDING["table"], ""), False, 1, "BLOCKED",
         "checks pending", (1, 0, 1, 0),
         "the live pending table (exit 8) is CI state, not a CLI failure"),
    cell("live-failing-json", (captured.FAILING["json_rc"], captured.FAILING["json"], ""),
         TABLE_UNUSED, False, 1, "BLOCKED", "checks", (3, 2, 0, 1),
         "a live failing run blocks"),
    cell("live-failing-table", JSON_ABSENT,
         (captured.FAILING["table_rc"], captured.FAILING["table"], ""), False, 1, "BLOCKED",
         "checks", (3, 2, 0, 1), "the live failing table (exit 1) parses to its verdicts"),
    cell("live-finished-json", (captured.FINISHED["json_rc"], captured.FINISHED["json"], ""),
         TABLE_UNUSED, False, 0, "MERGE-OK", None, (7, 7, 0, 0),
         "a finished all-green run passes"),
    cell("live-finished-table", JSON_ABSENT,
         (captured.FINISHED["table_rc"], captured.FINISHED["table"], ""), False, 0, "MERGE-OK",
         None, (7, 7, 0, 0), "the live finished table (exit 0) parses to its verdicts"),
]


# --- reserved column names as check names (invariant 5) ---------------------
for _name in ("STATUS", "NAME", "ELAPSED", "URL", "DESCRIPTION"):
    for _verdict, _exit_code, _pending, _failing, _reason in (("fail", 1, 0, 1, "checks"),
                                                              ("pending", 8, 1, 0,
                                                               "checks pending")):
        CELLS.append(cell(
            "table-reserved-%s-%s" % (_name.lower(), _verdict), JSON_ABSENT,
            (_exit_code, TABLE_HEADER + GREEN_TABLE
             + "%s\t%s\t2m0s\thttps://example/2\t\n" % (_name, _verdict), ""),
            False, 1, "BLOCKED", _reason, (3, 2, _pending, _failing),
            "a check named %s is a row, not the header; it is counted and blocks" % _name))
for _name, _verdict, _exit_code, _reason in (("STATUS", "pending", 8, "checks pending"),
                                             ("NAME", "fail", 1, "checks"),
                                             ("NAME", "pending", 8, "checks pending")):
    CELLS.append(cell(
        "table-two-column-reserved-%s-%s" % (_name.lower(), _verdict), JSON_ABSENT,
        (_exit_code, "%s\t%s\n" % (_name, _verdict), ""),
        False, 1, "BLOCKED", _reason,
        (1, 0, 1 if _verdict == "pending" else 0, 0 if _verdict == "pending" else 1),
        "the two-column form of a reserved column name is still a row"))


# --- the declared vocabulary, one cell per entry (both surfaces) ------------
# The rows are the declared tokens and the expectations are computed from the invariants above, so
# a token added to CHECK_VOCABULARY arrives with a cell and cannot be added unpinned.
def vocabulary_cells():
    cells = []
    for key in sorted(VOCABULARY):
        surface, token = key.split("/", 1)
        conclusion = VOCABULARY[key]
        code, reason, tally = _VERDICT[classification(conclusion)]
        if surface == "bucket":
            json_result = _json([{"name": "row", "state": "COMPLETED", "bucket": token}])
            table_result = TABLE_UNUSED
        else:
            json_result = JSON_ABSENT
            table_result = (0, "check\t%s\n" % token, "")
        for flag in (False, True):
            cells.append(cell(
                "%s-vocabulary-%s%s" % (surface, token, "-flag" if flag else ""),
                json_result, table_result, flag, code,
                "MERGE-OK" if reason is None else "BLOCKED", reason, tally,
                "the declared %s token %r classifies as %s; the flag cannot change a reported row"
                % (surface, token, classification(conclusion))))
    return cells


# --- the bucket x state dimension: the bucket governs -----------------------
# Every declared bucket token against every raw state gh reports (gh_checks_fixtures.py). The queue
# is decided by the bucket alone, so each expectation depends on the bucket and not on the state; a
# cell where the raw state disagrees is what tells the bucket from the state.
def dimension_cells():
    cells = []
    for token in sorted(vocabulary("bucket")):
        conclusion = VOCABULARY["bucket/" + token]
        code, reason, tally = _VERDICT[classification(conclusion)]
        for state in captured.STATE_VOCABULARY:
            row = {"name": "row", "state": state, "bucket": token}
            for flag in (False, True):
                cells.append(cell(
                    "bucket-%s-%s%s" % (state, token, "-flag" if flag else ""),
                    _json([row]), TABLE_UNUSED, flag, code,
                    "MERGE-OK" if reason is None else "BLOCKED", reason, tally,
                    "the %s bucket is %s whatever raw state %s says; the flag cannot change a "
                    "bucket" % (token, classification(conclusion), state)))
    return cells


CELLS.extend(vocabulary_cells())
CELLS.extend(dimension_cells())

# --- an undeclared or absent bucket, and an absent raw state ----------------
for _label, _row in (("unknown", {"name": "row", "state": "SUCCESS", "bucket": "unreleased"}),
                     ("missing", {"name": "row", "state": "SUCCESS"}),
                     ("null", {"name": "row", "state": "SUCCESS", "bucket": None}),
                     ("empty", {"name": "row", "bucket": ""}),
                     ("no-state-no-bucket", {"name": "row"})):
    for _flag in (False, True):
        CELLS.append(cell(
            "bucket-%s-token%s" % (_label, "-flag" if _flag else ""), _json([_row]), TABLE_UNUSED,
            _flag, 1, "BLOCKED", "checks pending", (1, 0, 1, 0),
            "a bucket no surface declares is pending: never ok, never a claimed failure"))
for _label, _row in (("absent", {"name": "row", "bucket": "pass"}),
                     ("null", {"name": "row", "state": None, "bucket": "pass"})):
    CELLS.append(cell(
        "bucket-state-%s-pass" % _label, _json([_row]), TABLE_UNUSED, False, 0, "MERGE-OK", None,
        (1, 1, 0, 0),
        "the bucket is the verdict; a raw state that is absent or null cannot change it"))


# --- stream fidelity (invariant 7) ------------------------------------------
# A verdict cell cannot express this: sh_raw's padding is invisible to every verdict because
# parse_text_checks strips each line and json.loads tolerates surrounding whitespace. These cells
# compare the exact bytes sh_raw hands back instead of dropping the invariant silently.
STREAM_CELLS = [
    StreamCell("stream-padded-stdout", "  leading\nbody\n\n", "err", 7,
               "sh_raw must return stdout unchanged, padding and newlines included"),
    StreamCell("stream-padded-stderr", "out", "\ttrailing space \n\n", 7,
               "sh_raw must return stderr unchanged, padding and newlines included"),
    StreamCell("stream-both-padded", "\n\n  x  \n\n", "\n  y  \n", 8,
               "both streams survive a non-zero exit verbatim"),
]


# --- the captured vocabulary ------------------------------------------------

def fixture_problems():
    """Every value the captured `gh` output prints must be declared, or the fixtures fail.

    A new value in a fresh capture that the vocabulary does not know fails here instead of reaching
    the gate as an unknown token.
    """
    problems = []
    for name, capture in sorted(captured.CAPTURES.items()):
        # The table's STATUS column is parsed by the table vocabulary, so every word gh prints
        # there must be a `table/` token — a bucket-only declaration would fall back to FAILURE and
        # block a green run.
        for line in capture["table"].splitlines():
            cells = line.split("\t")
            token = cells[1].strip().lower() if len(cells) > 1 else ""
            if "table/%s" % token not in VOCABULARY:
                problems.append(("capture-%s-table" % name,
                                 "the table prints the undeclared verdict %r" % token))
        for row in json.loads(capture["json"]):
            if "bucket/%s" % str(row.get("bucket") or "").lower() not in VOCABULARY:
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

def _fake_run_for(cell_):
    view = {"state": "OPEN", "isDraft": False, "headRefOid": HEAD, "headRefName": "feature"}
    threads = json.dumps({"data": {"repository": {"pullRequest": {"reviewThreads": {
        "pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": []}}}}})

    def fake_run(cmd, cwd=None, capture_output=False, text=False):
        if cmd[:1] == ["git"]:
            branch = "--abbrev-ref" in cmd
            return subprocess.CompletedProcess(cmd, 0, "feature" if branch else HEAD, "")
        if cmd[:3] == ["gh", "pr", "checks"]:
            returncode, stdout, stderr = (cell_.json_result if "--json" in cmd
                                          else cell_.table_result)
            return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)
        if cmd[:3] == ["gh", "pr", "view"]:
            return subprocess.CompletedProcess(cmd, 0, json.dumps(view), "")
        if cmd[:3] == ["gh", "repo", "view"]:
            return subprocess.CompletedProcess(cmd, 0, "fixture-owner/fixture-repo", "")
        if cmd[:3] == ["gh", "api", "graphql"]:
            return subprocess.CompletedProcess(cmd, 0, threads, "")
        if cmd[:2] == ["gh", "api"]:
            return subprocess.CompletedProcess(cmd, 0, "[]", "")
        raise AssertionError("unexpected command: %s" % (cmd,))

    return fake_run


def run_cell(module, cell_):
    """Drive one verdict cell through the real entry point. Returns (code, stdout, stderr)."""
    argv = ["pr-merge-check.py", "7", "--repo", ".", "--verified-head", HEAD,
            "--gates-rc", "0", "--allow-no-machine-review"]
    if cell_.allow_no_checks:
        argv.append("--allow-no-checks")
    out, err = io.StringIO(), io.StringIO()
    with patch.object(module.subprocess, "run", side_effect=_fake_run_for(cell_)), \
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
    return None


def run_stream_cell(module, stream_cell):
    """sh_raw() with subprocess.run() faked: returns the forwarded (code, stdout, stderr)."""

    def fake_run(cmd, cwd=None, capture_output=False, text=False):
        return subprocess.CompletedProcess(cmd, stream_cell.exit_code,
                                           stream_cell.stdout, stream_cell.stderr)

    with patch.object(module.subprocess, "run", side_effect=fake_run):
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


def evaluate(module):
    """Every cell that the module under test violates, as (cell id, problem)."""
    problems = []
    for cell_ in CELLS:
        problem = check_cell(module, cell_)
        if problem is not None:
            problems.append((cell_.id, problem))
    for stream_cell in STREAM_CELLS:
        problem = check_stream_cell(module, stream_cell)
        if problem is not None:
            problems.append((stream_cell.id, problem))
    return problems


def main():
    start = time.monotonic()
    problems = fixture_problems()
    problems.extend(evaluate(GATE))
    for cell_id, problem in problems:
        print("  FAIL  %s: %s" % (cell_id, problem))
    elapsed = time.monotonic() - start
    total = len(CELLS) + len(STREAM_CELLS)
    print("verdict-matrix: %d verdict cells + %d stream cells = %d cells, %d failed, %.2fs"
          % (len(CELLS), len(STREAM_CELLS), total, len(problems), elapsed))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
