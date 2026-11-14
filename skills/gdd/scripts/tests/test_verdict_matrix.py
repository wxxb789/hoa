#!/usr/bin/env python3
"""Exhaustive verdict matrix for the merge gate's check-fetch surface.

The surface is small and closed: a JSON result, a fallback table result, and one flag decide the
verdict. This artefact enumerates that space and asserts the verdict for every cell — JSON shapes
(valid list, non-list, empty list, malformed entry mixed with valid, malformed only, absent, partial
garbage) x fallback table shapes (absent, header only, mixed, every reserved column name as a check
name, two-column, empty, garbage, truncated row) x exit codes (0, 1, 8) x `--allow-no-checks` (off,
on), plus the bucket x state dimension for the JSON path.

Every expectation is written from the invariants, never copied from what the implementation prints:

  1. Fail closed. Anything unrecognized — malformed or absent JSON, a non-object array entry, a
     non-list payload, unparseable table text, a missing binary — exits 2 or blocks; none is
     MERGE-OK, with or without `--allow-no-checks`.
  2. `--allow-no-checks` only forgives a genuinely zero-check read that succeeded.
  3. The bucket governs. A recognized bucket decides the verdict whatever the raw state says; an
     unrecognized bucket is pending — never ok, never a claimed failure.
  4. Only completed-success (and the skipping/neutral conventions) is ok; pending, failing and
     cancelled block.
  5. The table fallback parses every real row, including a row named after a printed column; only a
     row whose every field is a column name is the header.
  6. A non-zero `gh pr checks` exit is CI state only while the parsed rows report it. A non-zero
     exit whose parsed table is entirely green is an incomplete read — never permission.
  7. `sh_raw` hands back the exit code and both streams byte-for-byte.

The cells are driven through the real entry point (`main()` with `subprocess.run` mocked), so the
matrix is end-to-end. `mutate_verdict_matrix.py` imports `CELLS`, `STREAM_CELLS` and `check_cell`
and requires that each mutation of the module flips at least one cell.

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
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

HEAD = "a1b2c3d4" + "0" * 32

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

Cell = namedtuple("Cell", "id json_result table_result allow_no_checks exit_code verdict reason why")
StreamCell = namedtuple("StreamCell", "id stdout stderr exit_code why")


def cell(cid, json_result, table_result, allow_no_checks, exit_code, verdict, reason, why):
    return Cell(cid, json_result, table_result, allow_no_checks, exit_code, verdict, reason, why)


# --- the matrix -------------------------------------------------------------

CELLS = [
    # --- JSON path: the bucket x state dimension (invariant 3, 4) -----------
    cell("json-green", JSON_GREEN, TABLE_UNUSED, False, 0, "MERGE-OK", None,
         "the only ok bucket is pass/skipping/neutral on a completed check"),
    cell("json-green-flag", JSON_GREEN, TABLE_UNUSED, True, 0, "MERGE-OK", None,
         "the flag changes nothing when checks are actually green"),
    cell("json-pending", JSON_PENDING, TABLE_UNUSED, False, 1, "BLOCKED", "checks pending",
         "a pending check blocks and the reason names it"),
    cell("json-pending-flag", JSON_PENDING, TABLE_UNUSED, True, 1, "BLOCKED", "checks pending",
         "the flag forgives zero checks, not a reported pending check"),
    cell("json-fail", JSON_FAIL, TABLE_UNUSED, False, 1, "BLOCKED", "checks",
         "a failed check blocks"),
    cell("json-fail-flag", JSON_FAIL, TABLE_UNUSED, True, 1, "BLOCKED", "checks",
         "the flag forgives zero checks, not a reported failure"),
    cell("json-pass-plus-pending", JSON_PASS_PENDING, TABLE_UNUSED, False, 1, "BLOCKED",
         "checks pending", "one pending check beside a passing one still blocks"),
    cell("json-pass-plus-pending-flag", JSON_PASS_PENDING, TABLE_UNUSED, True, 1, "BLOCKED",
         "checks pending", "a passing neighbour does not make pending forgivable"),

    # --- JSON path: shapes (invariants 1, 2) -------------------------------
    cell("json-empty-list", JSON_EMPTY, TABLE_UNUSED, False, 1, "BLOCKED", "no checks",
         "a successfully read empty list is the zero-check state and blocks"),
    cell("json-empty-list-flag", JSON_EMPTY, TABLE_UNUSED, True, 0, "MERGE-OK", None,
         "the flag is exactly the opt-out for a genuinely zero-check read"),
    cell("json-malformed-mixed", JSON_MALFORMED_MIXED, TABLE_UNUSED, False, 2, "ERROR", None,
         "a non-object entry beside a valid one is not permission: exit 2"),
    cell("json-malformed-mixed-flag", JSON_MALFORMED_MIXED, TABLE_UNUSED, True, 2, "ERROR", None,
         "the flag forgives zero checks, never an unreadable list"),
    cell("json-malformed-only", JSON_MALFORMED_ONLY, TABLE_UNUSED, False, 2, "ERROR", None,
         "a list of only non-objects is unreadable: exit 2"),
    cell("json-malformed-only-flag", JSON_MALFORMED_ONLY, TABLE_UNUSED, True, 2, "ERROR", None,
         "the flag cannot rescue a malformed list"),
    cell("json-nonlist-empty-table", JSON_NONLIST, (0, "", ""), False, 1, "BLOCKED", "no checks",
         "a non-list payload is not a check list; the table is the fallback and it is empty"),
    cell("json-nonlist-empty-table-flag", JSON_NONLIST, (0, "", ""), True, 0, "MERGE-OK", None,
         "the fallback read succeeded and is genuinely empty, so the flag forgives it"),
    cell("json-nonlist-green-table", JSON_NONLIST, (0, GREEN_TABLE, ""), False, 0, "MERGE-OK", None,
         "a non-list payload falls back to the table, which here is green"),
    cell("json-garbage-green-table", JSON_GARBAGE, (0, GREEN_TABLE, ""), False, 0, "MERGE-OK", None,
         "unparseable JSON falls back to the table"),
    cell("json-absent-green-table", JSON_ABSENT, (0, GREEN_TABLE, ""), False, 0, "MERGE-OK", None,
         "a non-zero JSON exit falls back to the table, which here is green"),
    cell("json-absent-empty-table", JSON_ABSENT, (0, "", ""), False, 1, "BLOCKED", "no checks",
         "the fallback is reached and reports zero checks"),

    # --- table path: exit codes (invariant 6) ------------------------------
    cell("table-green-exit-0", JSON_ABSENT, (0, GREEN_TABLE, ""), False, 0, "MERGE-OK", None,
         "every row ok and the read exited 0"),
    cell("table-green-exit-1", JSON_ABSENT, (1, GREEN_TABLE, ""), False, 2, "ERROR", None,
         "a non-zero exit with an all-green table is an incomplete read, never permission"),
    cell("table-green-exit-8", JSON_ABSENT, (8, GREEN_TABLE, ""), False, 2, "ERROR", None,
         "a non-zero exit with an all-green table is an incomplete read, never permission"),
    cell("table-green-exit-1-flag", JSON_ABSENT, (1, GREEN_TABLE, ""), True, 2, "ERROR", None,
         "the flag cannot turn an incomplete read into a verdict"),
    cell("table-green-exit-8-flag", JSON_ABSENT, (8, GREEN_TABLE, ""), True, 2, "ERROR", None,
         "the flag cannot turn an incomplete read into a verdict"),
    cell("table-truncated-exit-8", JSON_ABSENT, (8, TRUNCATED_TABLE, ""), False, 2, "ERROR", None,
         "a dropped truncated row leaves an all-green table under a non-zero exit"),
    cell("table-truncated-exit-8-flag", JSON_ABSENT, (8, TRUNCATED_TABLE, ""), True, 2, "ERROR",
         None, "a dropped row is not a zero-check read"),

    # --- table path: reported CI state (invariants 4, 6) -------------------
    cell("table-mixed-exit-8", JSON_ABSENT, (8, MIXED_TABLE, ""), False, 1, "BLOCKED", "checks",
         "a failed row blocks; the non-zero exit is the CI state it reports"),
    cell("table-mixed-exit-1", JSON_ABSENT, (1, MIXED_TABLE, ""), False, 1, "BLOCKED", "checks",
         "a failed row blocks"),
    cell("table-mixed-exit-0", JSON_ABSENT, (0, MIXED_TABLE, ""), False, 1, "BLOCKED", "checks",
         "the rows decide even at a zero exit"),
    cell("table-inflight-exit-8", JSON_ABSENT, (8, IN_FLIGHT_TABLE, ""), False, 1, "BLOCKED",
         "checks pending", "an unfinished run reports pending and blocks"),
    cell("table-inflight-exit-0", JSON_ABSENT, (0, IN_FLIGHT_TABLE, ""), False, 1, "BLOCKED",
         "checks pending", "a pending row blocks whatever the exit code"),
    cell("table-inflight-exit-8-flag", JSON_ABSENT, (8, IN_FLIGHT_TABLE, ""), True, 1, "BLOCKED",
         "checks pending", "the flag does not forgive a reported pending check"),
    cell("table-inflight-exit-0-flag", JSON_ABSENT, (0, IN_FLIGHT_TABLE, ""), True, 1, "BLOCKED",
         "checks pending", "the flag does not forgive a reported pending check"),

    # --- table path: zero-check and error shapes (invariants 1, 2) ---------
    cell("table-header-only", JSON_ABSENT, (0, TABLE_HEADER, ""), False, 1, "BLOCKED", "no checks",
         "a header is not a check; zero rows read successfully is the empty state"),
    cell("table-header-only-flag", JSON_ABSENT, (0, TABLE_HEADER, ""), True, 0, "MERGE-OK", None,
         "a header-only table is a genuinely zero-check read, which the flag forgives"),
    cell("table-header-only-exit-1", JSON_ABSENT, (1, TABLE_HEADER, ""), False, 2, "ERROR", None,
         "a non-zero exit with no rows is not the recognized 'no checks reported' state"),
    cell("table-empty-exit-0", JSON_ABSENT, (0, "", ""), False, 1, "BLOCKED", "no checks",
         "an empty successful read is zero checks"),
    cell("table-empty-exit-0-flag", JSON_ABSENT, (0, "", ""), True, 0, "MERGE-OK", None,
         "the flag forgives a genuinely empty successful read"),
    cell("table-no-checks-reported", JSON_ABSENT,
         (1, "", "no checks reported on the 'feature' branch"), False, 1, "BLOCKED", "no checks",
         "gh's own 'no checks reported' is the empty state, not a CLI failure"),
    cell("table-no-checks-reported-flag", JSON_ABSENT,
         (1, "", "no checks reported on the 'feature' branch"), True, 0, "MERGE-OK", None,
         "the recognized empty state is exactly what the flag forgives"),
    cell("table-garbage-exit-1", JSON_ABSENT, (1, "gh: Not Found (HTTP 404)\n", ""), False, 2,
         "ERROR", None, "unparseable output is not zero checks: exit 2"),
    cell("table-garbage-exit-1-flag", JSON_ABSENT, (1, "gh: Not Found (HTTP 404)\n", ""), True, 2,
         "ERROR", None, "a command error is never an allowed zero-check result"),
    cell("table-stderr-only-exit-1", JSON_ABSENT, (1, "", "HTTP 401: Bad credentials"), False, 2,
         "ERROR", None, "an error on stderr with no table is a command error"),
    cell("table-blank-exit-8", JSON_ABSENT, (8, "", "checks pending"), False, 2, "ERROR", None,
         "a bare error message with no rows is not parsable evidence"),
    cell("table-blank-exit-8-flag", JSON_ABSENT, (8, "", "checks pending"), True, 2, "ERROR", None,
         "the flag cannot make an unparseable read a zero-check read"),

    # --- table path: rows that must not be dropped (invariant 5) -----------
    cell("table-two-column-green", JSON_ABSENT, (0, "build\tpass\n", ""), False, 0, "MERGE-OK",
         None, "the two-column form parses to one ok row"),
    cell("table-two-column-pending", JSON_ABSENT, (0, "build\tpending\n", ""), False, 1, "BLOCKED",
         "checks pending", "the two-column form parses to one pending row, which blocks"),
    cell("table-unknown-verdict", JSON_ABSENT, (0, "mystery\tunreleased\n", ""), False, 1,
         "BLOCKED", "checks", "an unrecognized verdict word is never ok"),
    cell("table-name-prefixed-fail", JSON_ABSENT, (1, NAME_PREFIXED_TABLE, ""), False, 1, "BLOCKED",
         "checks", "a check named NAME-required is a row, not the header"),
    cell("table-name-prefixed-pending", JSON_ABSENT, (8, NAME_PREFIXED_PENDING_TABLE, ""), False, 1,
         "BLOCKED", "checks pending", "a pending row whose name begins with NAME still blocks"),
    cell("table-name-prefixed-flag", JSON_ABSENT, (1, NAME_PREFIXED_TABLE, ""), True, 1, "BLOCKED",
         "checks", "the flag cannot forgive a reported failure"),
    cell("table-check-named-name", JSON_ABSENT,
         (0, TABLE_HEADER + "NAME\tpass\t1s\thttps://example/0\t\n", ""), False, 0, "MERGE-OK", None,
         "a row named NAME with a pass verdict is a row, not the header"),
    cell("table-real-gh-shape", JSON_ABSENT, (0, REAL_GH_TABLE, ""), False, 0, "MERGE-OK", None,
         "the shape gh emits on this host parses to its verdicts"),
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
            False, 1, "BLOCKED", _reason,
            "a check named %s is a row, not the header; it is counted and blocks" % _name))
for _name, _verdict, _exit_code, _reason in (("STATUS", "pending", 8, "checks pending"),
                                             ("NAME", "fail", 1, "checks"),
                                             ("NAME", "pending", 8, "checks pending")):
    CELLS.append(cell(
        "table-two-column-reserved-%s-%s" % (_name.lower(), _verdict), JSON_ABSENT,
        (_exit_code, "%s\t%s\n" % (_name, _verdict), ""),
        False, 1, "BLOCKED", _reason,
        "the two-column form of a reserved column name is still a row"))


# --- the bucket x state dimension (invariant 3) -----------------------------
# Expected verdict per (raw state, bucket): ok -> MERGE-OK, pending -> BLOCKED checks pending,
# failing -> BLOCKED checks. Written from the invariants, not from the implementation.
BUCKET_DIMENSION = [
    ("SUCCESS", "pass", "ok", "the pass bucket is the ok bucket"),
    ("SKIPPED", "skipping", "ok", "the skipping bucket is ok by the existing convention"),
    ("NEUTRAL", "neutral", "ok", "the neutral bucket is ok by the existing convention"),
    ("FAILURE", "fail", "failing", "the fail bucket is a failure"),
    ("CANCELLED", "cancel", "failing", "the cancel bucket is a failure"),
    ("PENDING", "pending", "pending", "the pending bucket is pending"),
    ("SUCCESS", "pending", "pending", "the bucket decides; a raw SUCCESS under pending still waits"),
    ("SUCCESS", "unreleased", "pending", "an unknown bucket is never ok, whatever the raw state"),
    ("FAILURE", "unreleased", "pending", "an unknown bucket is never a claimed failure either"),
    ("SUCCESS", "fail", "failing", "a recognized bucket governs a contradictory raw state"),
    ("FAILURE", "pass", "ok", "a recognized bucket governs in the other direction too"),
    ("PENDING", "skipping", "ok", "the bucket governs a pending raw state"),
    ("SUCCESS", None, "pending", "no bucket means nothing is known, so the row is pending"),
    (None, "pass", "ok", "the bucket is the only verdict source; a missing raw state is irrelevant"),
    (None, None, "pending", "neither field is a verdict here, so the row is pending"),
]
_VERDICT = {"ok": (0, "MERGE-OK", None),
            "pending": (1, "BLOCKED", "checks pending"),
            "failing": (1, "BLOCKED", "checks")}
for _state, _bucket, _expected, _why in BUCKET_DIMENSION:
    _row = {"name": "row", "state": _state, "bucket": _bucket}
    _code, _verdict_name, _reason = _VERDICT[_expected]
    CELLS.append(cell("bucket-%s-%s-off" % (_state, _bucket), _json([_row]), TABLE_UNUSED, False,
                      _code, _verdict_name, _reason, _why))
    CELLS.append(cell("bucket-%s-%s-flag" % (_state, _bucket), _json([_row]), TABLE_UNUSED, True,
                      _code, _verdict_name, _reason, _why + "; the flag cannot change a bucket"))


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


# --- the harness ------------------------------------------------------------

def load_gate(path=None):
    """Import pr-merge-check.py (or a mutated in-memory variant via the harness) as a module."""
    path = Path(path or (SCRIPTS / "pr-merge-check.py"))
    spec = importlib.util.spec_from_file_location("pr_merge_check_matrix", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    if "verdict: " + cell_.verdict not in out:
        return "expected verdict %s, got %r" % (cell_.verdict, out.strip())
    if cell_.reason is not None and "verdict: BLOCKED: " + cell_.reason not in out:
        return "expected reason %r, got %r" % (cell_.reason, out.strip())
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
    gate = load_gate()
    problems = evaluate(gate)
    for cell_id, problem in problems:
        print("  FAIL  %s: %s" % (cell_id, problem))
    elapsed = time.monotonic() - start
    total = len(CELLS) + len(STREAM_CELLS)
    print("verdict-matrix: %d verdict cells + %d stream cells = %d cells, %d failed, %.2fs"
          % (len(CELLS), len(STREAM_CELLS), total, len(problems), elapsed))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
