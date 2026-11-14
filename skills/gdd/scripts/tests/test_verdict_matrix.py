#!/usr/bin/env python3
"""Exhaustive verdict matrix for the merge gate's check-fetch surface.

The oracle is a literal, test-side declaration — never the artefact it pins:

* `DECLARED_VOCABULARY` writes out, here, the meaning of every verdict token each read surface can
  print; the gate's own `CHECK_VOCABULARY` is checked token by token against it, so a swapped or
  silently added token fails loudly instead of moving the expectation along with the gate (round-5
  finding F2);
* the expectation for each row is computed from the invariants stated once below: only a completed
  success or the skipping/neutral conventions are ok, a waiting conclusion is pending, everything
  else blocks, an undeclared verdict blocks, and `--allow-no-checks` forgives only a *structured*
  zero-check read;
* the class-closing rule is a dimension of its own: the structured read is authoritative, and a
  table-only read may never authorise a merge — an all-green or empty table blocks with
  `checks unreadable` unless the operator passes `--allow-table-only-checks`, which bypasses
  neither the exact-header rule nor the unknown-verdict rule; with that opt-in an *empty* table is
  the zero-check state, which only `--allow-no-checks` forgives, so the two opt-ins are independent;
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
    "bucket/pass": "SUCCESS",
    "bucket/skipping": "SKIPPED",
    "bucket/neutral": "NEUTRAL",
    "bucket/fail": "FAILURE",
    "bucket/cancel": "CANCELLED",
    "bucket/pending": "PENDING",
    "table/pass": "SUCCESS",
    "table/skipping": "SKIPPED",
    "table/skip": "SKIPPED",
    "table/neutral": "NEUTRAL",
    "table/failing": "FAILURE",
    "table/fail": "FAILURE",
    "table/cancelled": "CANCELLED",
    "table/canceled": "CANCELLED",
    "table/timed_out": "TIMED_OUT",
    "table/pending": "PENDING",
}


def vocabulary(surface):
    """The `<surface>` slice of the *declared* vocabulary, as {token: conclusion}."""
    prefix = surface + "/"
    return {key[len(prefix):]: value for key, value in DECLARED_VOCABULARY.items()
            if key.startswith(prefix)}


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

# The class-closing rule: a table-only read is advisory and may never authorise a merge. An
# all-green or empty table is unverifiable evidence, so it blocks with `checks unreadable`; a
# non-green table blocks with its own classification's reason. (exit code, verdict reason) per
# classification, for the table surface without `--allow-table-only-checks`.
_TABLE_ONLY_VERDICT = {
    "ok": (1, "checks unreadable"),
    "pending": (1, "checks pending"),
    "failing": (1, "checks"),
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
                          "checks why allow_table_only")
StreamCell = namedtuple("StreamCell", "id stdout stderr exit_code why")


def cell(cid, json_result, table_result, allow_no_checks, exit_code, verdict, reason, checks, why,
         allow_table_only=False):
    """One verdict cell. `checks` is the expected `checks:` tally, or None when there is no read."""
    return Cell(cid, json_result, table_result, allow_no_checks, exit_code, verdict, reason,
                checks, why, allow_table_only)


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
    cell("json-nonlist-empty-table", JSON_NONLIST, (0, "", ""), False, 1, "BLOCKED",
         "checks unreadable", (0, 0, 0, 0),
         "a non-list payload is not a check list; the empty fallback table cannot authorise"),
    cell("json-nonlist-empty-table-flag", JSON_NONLIST, (0, "", ""), True, 1, "BLOCKED",
         "checks unreadable", (0, 0, 0, 0),
         "a table-only read is advisory even with --allow-no-checks: the flag cannot authorise it"),
    cell("json-nonlist-green-table", JSON_NONLIST, (0, GREEN_TABLE, ""), False, 1, "BLOCKED",
         "checks unreadable", (2, 2, 0, 0),
         "a non-list payload falls back to a table-only read, which may never report MERGE-OK"),
    cell("json-garbage-green-table", JSON_GARBAGE, (0, GREEN_TABLE, ""), False, 1, "BLOCKED",
         "checks unreadable", (2, 2, 0, 0),
         "unparseable JSON falls back to a table-only read, which may never report MERGE-OK"),
    cell("json-absent-green-table", JSON_ABSENT, (0, GREEN_TABLE, ""), False, 1, "BLOCKED",
         "checks unreadable", (2, 2, 0, 0),
         "a non-zero JSON exit falls back to a table-only read, which may never report MERGE-OK"),
    cell("json-absent-empty-table", JSON_ABSENT, (0, "", ""), False, 1, "BLOCKED",
         "checks unreadable", (0, 0, 0, 0),
         "the empty fallback table is unverifiable, so it blocks with the structured-read reason"),

    # --- table path: exit codes (invariant 6) ------------------------------
    cell("table-green-exit-0", JSON_ABSENT, (0, GREEN_TABLE, ""), False, 1, "BLOCKED",
         "checks unreadable", (2, 2, 0, 0),
         "every row ok but the read was table-only, and that may never report MERGE-OK"),
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
    cell("table-header-only", JSON_ABSENT, (0, TABLE_HEADER, ""), False, 1, "BLOCKED",
         "checks unreadable", (0, 0, 0, 0),
         "a header-only table is an empty table-only read, which cannot authorise a merge"),
    cell("table-header-only-flag", JSON_ABSENT, (0, TABLE_HEADER, ""), True, 1, "BLOCKED",
         "checks unreadable", (0, 0, 0, 0),
         "--allow-no-checks forgives a zero-check *structured* read, never a table-only one"),
    cell("table-header-only-exit-1", JSON_ABSENT, (1, TABLE_HEADER, ""), False, 2, "ERROR", None,
         None, "a non-zero exit with no rows is not the recognized 'no checks reported' state"),
    cell("table-empty-exit-0", JSON_ABSENT, (0, "", ""), False, 1, "BLOCKED",
         "checks unreadable", (0, 0, 0, 0),
         "an empty table-only read is unverifiable, not a successful zero-check read"),
    cell("table-empty-exit-0-flag", JSON_ABSENT, (0, "", ""), True, 1, "BLOCKED",
         "checks unreadable", (0, 0, 0, 0),
         "the empty table-only read blocks with and without --allow-no-checks"),
    cell("table-no-checks-reported", JSON_ABSENT,
         (1, "", "no checks reported on the 'feature' branch"), False, 1, "BLOCKED",
         "checks unreadable", (0, 0, 0, 0),
         "gh's own 'no checks reported' is a table-only read, so the list is unverifiable"),
    cell("table-no-checks-reported-flag", JSON_ABSENT,
         (1, "", "no checks reported on the 'feature' branch"), True, 1, "BLOCKED",
         "checks unreadable", (0, 0, 0, 0),
         "the structured read is what --allow-no-checks forgives, and it did not produce rows"),
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
    cell("table-two-column-green", JSON_ABSENT, (0, "build\tpass\n", ""), False, 1, "BLOCKED",
         "checks unreadable", (1, 1, 0, 0),
         "the two-column form parses to one ok row, but the read is table-only"),
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
         (0, TABLE_HEADER + "NAME\tpass\t1s\thttps://example/0\t\n", ""), False, 1, "BLOCKED",
         "checks unreadable", (1, 1, 0, 0),
         "a row named NAME with a pass verdict is a row, not the header, and the read is table-only"),
    cell("table-real-gh-shape", JSON_ABSENT, (0, REAL_GH_TABLE, ""), False, 1, "BLOCKED",
         "checks unreadable", (2, 2, 0, 0),
         "the shape gh emits on this host parses to its verdicts, but the read is table-only"),

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
         (captured.FINISHED["table_rc"], captured.FINISHED["table"], ""), False, 1, "BLOCKED",
         "checks unreadable", (7, 7, 0, 0),
         "a finished live table is still a table-only read, so it may not authorise a merge"),
]


# --- the class-closing rule: a table-only read may never authorise ----------
# The structured read is authoritative; the human table is advisory. These cells pin both paths —
# the default (a table-only read blocks) and the documented opt-in that restores the table's
# authority. Without the opt-in an all-green or empty table must block with `checks unreadable`,
# and a non-green one still blocks with its own reason; with it a green table merges but a
# non-green row, an unknown verdict word and a non-header are unchanged (the opt-in bypasses
# neither the exact-header rule nor the unknown-verdict rule).
CELLS += [
    cell("rule-structured-read-authoritative", JSON_GREEN, TABLE_UNUSED, False, 0, "MERGE-OK", None,
         (1, 1, 0, 0), "the structured read is authoritative: a green bucket is MERGE-OK"),
    cell("rule-table-only-blocks-without-opt-in", JSON_ABSENT, (0, GREEN_TABLE, ""), False, 1,
         "BLOCKED", "checks unreadable", (2, 2, 0, 0),
         "an all-green table-only read blocks: it cannot be verified in structured form"),
    cell("rule-table-only-empty-blocks", JSON_ABSENT, (0, "", ""), False, 1, "BLOCKED",
         "checks unreadable", (0, 0, 0, 0),
         "an empty table-only read blocks: unverifiable, not a reported zero-check state"),
    cell("rule-table-only-opt-in-restores-green", JSON_ABSENT, (0, GREEN_TABLE, ""), False, 0,
         "MERGE-OK", None, (2, 2, 0, 0),
         "--allow-table-only-checks restores the table's authority, so the green table merges",
         allow_table_only=True),
    cell("rule-table-only-opt-in-empty-with-flag", JSON_ABSENT, (0, "", ""), True, 0, "MERGE-OK",
         None, (0, 0, 0, 0),
         "with the table authoritative an empty read is the zero-check state --allow-no-checks "
         "forgives", allow_table_only=True),
    cell("rule-table-only-opt-in-empty-needs-the-no-checks-flag", JSON_ABSENT, (0, "", ""), False,
         1, "BLOCKED", "no checks", (0, 0, 0, 0),
         "the two opt-ins are independent: the table opt-in makes an empty read the zero-check "
         "state, which only --allow-no-checks forgives", allow_table_only=True),
    cell("rule-table-only-opt-in-still-blocks-failing", JSON_ABSENT, (1, MIXED_TABLE, ""), False,
         1, "BLOCKED", "checks", (3, 1, 1, 1),
         "the opt-in does not make a failing row green", allow_table_only=True),
    cell("rule-table-only-opt-in-still-blocks-pending", JSON_ABSENT, (8, IN_FLIGHT_TABLE, ""),
         False, 1, "BLOCKED", "checks pending", (2, 1, 1, 0),
         "the opt-in does not make a pending row green", allow_table_only=True),
    cell("rule-table-only-opt-in-cannot-bypass-unknown-verdict", JSON_ABSENT,
         (0, "mystery\tunreleased\n", ""), False, 1, "BLOCKED", "checks", (1, 0, 0, 1),
         "the opt-in cannot bypass the unknown-verdict rule: an unknown word is never ok",
         allow_table_only=True),
    cell("rule-table-only-opt-in-cannot-bypass-header", JSON_ABSENT, (0, "STATUS\tNAME\n", ""),
         False, 1, "BLOCKED", "checks", (1, 0, 0, 1),
         "the opt-in cannot bypass the exact-header rule: `STATUS\\tNAME` is a row, not a header",
         allow_table_only=True),
]

# --- the negative header fixtures (round-5 finding F1) ----------------------
# The header is matched exactly: field count, empty fields and case preserved. A comparison that
# strips empty fields and uppercases turned both of these data rows into the header, so the row
# vanished and the remaining passing row could report MERGE-OK. Each is counted, its unknown
# verdict blocks, and neither flag variant — nor the opt-in — can forgive it.
EMPTY_FIELD_HEADER_ROW = "build\tpass\nNAME\t\tSTATUS\tELAPSED\tURL\tDESCRIPTION\n"
LOWER_CASE_HEADER_ROW = "build\tpass\nname\tstatus\telapsed\turl\tdescription\n"
for _label, _table in (("empty-field", EMPTY_FIELD_HEADER_ROW),
                       ("lower-case", LOWER_CASE_HEADER_ROW)):
    CELLS += [
        cell("table-%s-header-row" % _label, JSON_ABSENT, (0, _table, ""), False, 1, "BLOCKED",
             "checks", (2, 1, 0, 1),
             "the %s header-shaped data row is counted and its unknown verdict blocks" % _label),
        cell("table-%s-header-row-allow-no-checks" % _label, JSON_ABSENT, (0, _table, ""), True, 1,
             "BLOCKED", "checks", (2, 1, 0, 1),
             "--allow-no-checks cannot forgive the %s header-shaped data row" % _label),
        cell("table-%s-header-row-opt-in" % _label, JSON_ABSENT, (0, _table, ""), False, 1,
             "BLOCKED", "checks", (2, 1, 0, 1),
             "the opt-in cannot bypass the exact-header rule for the %s row" % _label,
             allow_table_only=True),
    ]


# --- the edge empty fields the whole-line strip erased (round-6 finding F1) --
# Header recognition and the field split read the original line, so a field boundary at either edge
# survives: a data row with a leading empty field — and the five-column header carrying one extra
# trailing tab — are each counted, and each one's unknown verdict blocks. Stripping the line first
# collapsed both onto the exact header, so the row vanished and an all-green remainder reported
# MERGE-OK. Neither flag variant, including the opt-in, can forgive them.
LEADING_EMPTY_FIELD_ROW = "build\tpass\n\tNAME\tSTATUS\tELAPSED\tURL\tDESCRIPTION\n"
TRAILING_EMPTY_FIELD_ROW = "build\tpass\nNAME\tSTATUS\tELAPSED\tURL\tDESCRIPTION\t\n"
for _label, _table in (("leading", LEADING_EMPTY_FIELD_ROW),
                       ("trailing", TRAILING_EMPTY_FIELD_ROW)):
    CELLS += [
        cell("table-%s-empty-field-row" % _label, JSON_ABSENT, (0, _table, ""), False, 1,
             "BLOCKED", "checks", (2, 1, 0, 1),
             "the %s-empty-field header-shaped row is counted and its unknown verdict blocks"
             % _label),
        cell("table-%s-empty-field-row-allow-no-checks" % _label, JSON_ABSENT, (0, _table, ""),
             True, 1, "BLOCKED", "checks", (2, 1, 0, 1),
             "--allow-no-checks cannot forgive the %s-empty-field row" % _label),
        cell("table-%s-empty-field-row-opt-in" % _label, JSON_ABSENT, (0, _table, ""), False, 1,
             "BLOCKED", "checks", (2, 1, 0, 1),
             "the opt-in cannot bypass the exact-header rule for the %s-empty-field row" % _label,
             allow_table_only=True),
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


# --- the declared vocabulary, one cell per declared entry (both surfaces) ---
# The rows enumerate the *declaration* above, never the gate: the expectation is the declared
# conclusion's classification, so a token the gate reclassifies — or swaps with another — fails
# here against a fixed expectation. On the table surface the class-closing rule applies as well:
# without the opt-in the token's row is advisory, so an ok token blocks as `checks unreadable`.
def vocabulary_cells():
    cells = []
    for key in sorted(DECLARED_VOCABULARY):
        surface, token = key.split("/", 1)
        cls = classification(DECLARED_VOCABULARY[key])
        code, reason, tally = _VERDICT[cls]
        if surface == "bucket":
            cells.append(cell(
                "bucket-vocabulary-%s" % token,
                _json([{"name": "row", "state": "COMPLETED", "bucket": token}]), TABLE_UNUSED,
                False, code, "MERGE-OK" if reason is None else "BLOCKED", reason, tally,
                "the declared bucket token %r classifies as %s through the structured read"
                % (token, cls)))
            continue
        table_result = (0, "check\t%s\n" % token, "")
        advisory_code, advisory_reason = _TABLE_ONLY_VERDICT[cls]
        cells.append(cell(
            "table-vocabulary-%s" % token, JSON_ABSENT, table_result, False,
            advisory_code, "BLOCKED", advisory_reason, tally,
            "the declared table token %r classifies as %s; with no structured read the table is "
            "advisory, so an ok token never merges" % (token, cls)))
        cells.append(cell(
            "table-vocabulary-%s-opt-in" % token, JSON_ABSENT, table_result, False,
            code, "MERGE-OK" if reason is None else "BLOCKED", reason, tally,
            "with --allow-table-only-checks the declared table token %r classifies as %s"
            % (token, cls), allow_table_only=True))
    return cells


# --- the bucket x state dimension: the bucket governs -----------------------
# Every declared bucket token against every raw state gh reports (gh_checks_fixtures.py). The queue
# is decided by the bucket alone, so each expectation depends on the bucket and not on the state; a
# cell where the raw state disagrees is what tells the bucket from the state.
def dimension_cells():
    cells = []
    buckets = vocabulary("bucket")
    for token in sorted(buckets):
        cls = classification(buckets[token])
        code, reason, tally = _VERDICT[cls]
        for state in captured.STATE_VOCABULARY:
            row = {"name": "row", "state": state, "bucket": token}
            for flag in (False, True):
                cells.append(cell(
                    "bucket-%s-%s%s" % (state, token, "-flag" if flag else ""),
                    _json([row]), TABLE_UNUSED, flag, code,
                    "MERGE-OK" if reason is None else "BLOCKED", reason, tally,
                    "the %s bucket is %s whatever raw state %s says; the flag cannot change a "
                    "bucket" % (token, cls, state)))
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
    if cell_.allow_table_only:
        argv.append("--allow-table-only-checks")
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
    """Every cell that the module under test violates, as (id, problem)."""
    problems = declaration_problems(module)
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
