#!/usr/bin/env python3
"""Exhaustive verdict matrix for the merge gate's check-fetch surface.

The oracle is a literal, test-side declaration — never the artefact it pins:

* `DECLARED_VOCABULARY` writes out, here, the meaning of every verdict token each read surface can
  print; the gate's own `CHECK_VOCABULARY` is checked token by token against it, so a swapped or
  silently added token fails loudly instead of moving the expectation along with the gate (round-5
  finding F2);
* the expectation for each row is computed from the invariants stated once below: only a completed
  success or the skipping/neutral conventions are ok, a waiting conclusion is pending, everything
  else blocks, an undeclared verdict blocks, and `--allow-no-checks` forgives a zero-check read —
  the structured one always, and the *table* one too once `--allow-table-only-checks` has made the
  table authoritative, so neither opt-in alone forgives a table-only read;
* the class-closing rule is a dimension of its own: the structured read is authoritative, and a
  table-only read may never authorise a merge — an all-green or empty table blocks with
  `checks unreadable` unless the operator passes `--allow-table-only-checks`, which bypasses
  neither the exact-header rule nor the unknown-verdict rule; with that opt-in an *empty* table is
  the zero-check state, which only `--allow-no-checks` forgives, so the two opt-ins are independent;
* the comparison is exact — the whole verdict line plus the printed `checks:` tally, and, where a
  cell names it, its exact stderr line list with no other line beside it — so a cell cannot accept
  one classification in place of another, and a report that truncates, de-duplicates or re-orders
  fails;

Every dimension the cells vary over (the read source, the structured and table exit codes, the flag
combinations, the JSON and table shapes, the bucket and the raw state, and the fixed
`--verified-head`/`--gates-rc` pair) is declared once as a constant list, and `dimension_problems()`
asserts that every declared value is represented by at least one cell — and by at least one
*negative* cell where the value has a verdict consequence — naming the missing value and dimension
otherwise. Rounds 11 and 12 both slipped through as a value of a declared dimension (a structured
exit code) that no cell represented; this guard turns that class of gap into a loud failure. The two
read surfaces share one exit domain (`EXIT_CATEGORIES`), so both exit dimensions are driven from
that single declaration and `cross_surface_exit_problems()` fails on a category represented on one
surface but missing from the other — round 13 slipped through as exactly that asymmetry (the
structured dimension named four exits, the table one seven). Both exit dimensions count only
*executed* reads: a cell whose structured read succeeded never consults the table, so its
`TABLE_UNUSED` fixture cannot stand in for a table that ran (round 14). Two cells drive the table
opt-in beside a mismatched verified head and a failing local gate, so the opt-in cannot silently
override a blocker decided before the checks read; `guard_self_check()` proves the guards fire when
a consumed table exit disappears, the reproduction that round 14 found them blind to, and
`comparator_self_check()` runs the weakened forms of the exact-list stderr comparison over every
pinned list, so neither the comparison nor a fixture can silently stop discriminating (round 17).

Cells that cannot be expressed this way (the JSON shapes, the non-zero-exit fallback rules) are
listed explicitly, each with its expected tally and its reason. `subprocess.run()` is mocked and
every cell is driven through `main()`, so the matrix is end to end.

The **golden call log** pins the whole forwarding surface at once. Every `subprocess.run()`
invocation the gate issues while a cell drives `main()` is recorded as `(argv, cwd, has_env)`,
normalised only by folding the repository the operator named — `"."` here, the boundary cells'
scratch directory there — onto the single token `<repo>` (nothing the module relies on is dropped;
`capture_output` and `text` are not recorded because they are invisible to the child's command, and
cwd/env are because the gate forwards them). The collected *set* of distinct invocations is compared
with `GOLDEN_CALLS` below, so any change to a command, an argument, a flag, the PR number, the
`-C <repo>` pair or a call's working directory — or a new call — is a loud failure that names the
added or removed entry.

To update the snapshot deliberately: read the diff of this file's gate source (`git diff
skills/gdd/scripts/pr-merge-check.py`), confirm every command change is intended, and only then edit
`GOLDEN_CALLS`. A blind update — pasting the observed set the failure printed — deletes the exact
obligation the snapshot exists to hold: it converts "the gate now invokes something new" into "the
test agrees with the mutation", which is what every round of findings in this file was about.

Scope: the log records the calls the gate itself issues through `main()` (the `_fake_run_for()`
fake). The stream cells' `sh_raw()` probe and the sh-trim cell's `sh()` probe are direct unit calls
whose argv the *test* chooses, so each is pinned by its own cell rather than here.

Run: python3 skills/gdd/scripts/tests/test_verdict_matrix.py
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
# the fixture's `headRefOid` and blocks. Used by the cells that prove the table opt-in does not
# waive the verified-head requirement.
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
# Truncated rows: the trailing lines carry no tab, so they are not rows — they are ignored, and
# `report_ignored_table_lines()` names each on stderr, which is the only trace a truncated row
# leaves. Three distinct lines with one repeat (`a, b, a, c`) and *not* a palindrome: a report that
# stops at the first line, de-duplicates, or reverses its iteration order collapses or re-orders
# this list, and the cells below pin the exact one, in order (round-16 F1, round-17 C1). The
# order-sensitivity is load bearing twice over: `comparator_self_check()` fails by name if this
# list ever becomes a palindrome or loses its repeat again.
TRUNCATED_TABLE = ("build\tpass\t1s\thttps://example/1\t\n"
                   "required-a\n"
                   "required-b\n"
                   "required-a\n"
                   "required-c\n")
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
                          "checks why allow_table_only error_contains comment_pages thread_pages "
                          "verified_head gates_rc stderr_lines",
                  defaults=(None, None, None, HEAD, 0, None))
StreamCell = namedtuple("StreamCell", "id stdout stderr exit_code why")
ShCell = namedtuple("ShCell", "id stdout stderr exit_code expected why")


def cell(cid, json_result, table_result, allow_no_checks, exit_code, verdict, reason, checks, why,
         allow_table_only=False, error_contains=None, comment_pages=None, thread_pages=None,
         verified_head=HEAD, gates_rc=0, stderr_lines=None):
    """One verdict cell. `checks` is the expected `checks:` tally, or None when there is no read.

    `error_contains` is the fragments the one-line stderr of an ERROR cell must carry — so an
    operator error's own exit code and diagnostic are pinned, not merely its exit status.
    `stderr_lines` is the *exact* stderr a non-ERROR cell must print: the whole line list, in
    order, with no other line beside them — the observability the gate prints beside a verdict,
    which a mutant could otherwise drop silently (round-15 F1). The default is the empty list, so
    a cell that names none must print none, and a report that truncates, de-duplicates, re-orders
    or adds lines fails (round-16 F1, round-17 C1). A non-empty list must carry a repeat and must
    not be a palindrome, or `comparator_self_check()` fails by name — a list that
    de-duplication or reversal reproduces cannot pin either against a rewrite.
    `comment_pages` and `thread_pages` are the multi-page evidence the fake serves: a list of
    comment batches (page 1 first) and a list of `(nodes, hasNextPage, endCursor)` thread pages.
    `None` keeps the single terminal page every other cell uses, so only a cell that names them
    observes the pagination continuation.
    `verified_head` and `gates_rc` are the `--verified-head`/`--gates-rc` pair the cell is driven
    with; the defaults are the matching head and a passing local gate, so only a cell that names
    them exercises a head mismatch or a failing gate.
    """
    return Cell(cid, json_result, table_result, allow_no_checks, exit_code, verdict, reason,
                checks, why, allow_table_only, error_contains, comment_pages, thread_pages,
                verified_head, gates_rc, stderr_lines)


# --- the exit-code domain, declared once for both read surfaces -------------
# `gh pr checks` uses the same exit codes whichever surface the gate reads, so the domain is
# written down *once* here and the structured-exit and table-exit dimensions are both driven from
# it. Declaring the two surfaces separately is what let one copy fall behind (round 13: the
# structured dimension named four exits, the table one seven), so a category could be represented
# on one surface and missing from the other; `cross_surface_exit_problems()` below fails by name
# on exactly that asymmetry.
#
# gh's check-result exits carry CI state; every other non-zero exit is an operator/transport
# failure (see `fetch_checks()`) that the gate must treat as no read at all:
#   0 all concluded · 1 a check failed · 8 a check is pending
#   2 cancellation · 4 authentication · -15 signal termination · 127 binary not found
CHECK_RESULT_EXITS = (0, 1, 8)
OPERATOR_FAILURE_EXITS = (2, 4, -15, 127)
EXIT_CATEGORIES = CHECK_RESULT_EXITS + OPERATOR_FAILURE_EXITS
NON_ZERO_EXITS = tuple(code for code in EXIT_CATEGORIES if code != 0)


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

    # --- the structured read's exit code is required (round-11 F1) ---------
    # Every non-zero structured fixture above pairs its exit with *empty* stdout, so it cannot tell
    # "require exit 0" from "trust any parseable stdout": `if returncode == 0:` read as
    # `if returncode == 0 or stdout:` survived every cell, the golden call log, the evidence tests
    # and the selftest. These cells hand the structured read a non-zero exit *and* a parseable
    # payload — a passing array, and (with the opt-out) an empty one — so trusting the stdout
    # reports MERGE-OK where the real gate falls back to the table and its operator error, and the
    # fallback-table cell shows the fallback actually ran.
    #
    # Round-12 F1: every one of those non-zero exits is 4, which is *not* a check-result exit, so a
    # narrower mutant — `if returncode == 0 or (returncode in (1, 8) and stdout):`, trusting a
    # parseable stdout only at the two exits `gh pr checks` uses for CI state — survived all 382
    # cells. The next three cells pair a structured exit **1** and **8** carrying a parseable
    # payload with a *non-green* fallback table, so the fallback verdict (and its exact tally) is
    # asserted and the mutant reports MERGE-OK where the real gate blocks.
    cell("json-nonzero-exit-passing-array-falls-back", (4, JSON_GREEN[1], ""),
         (4, "", "authentication failed"), False, 2, "ERROR", None, None,
         "a non-zero structured exit is not a read: the passing array on its stdout is not "
         "permission, and the fallback's operator error (exit 4) is preserved",
         error_contains=("exit 4", "authentication failed")),
    cell("json-nonzero-exit-empty-array-allow-no-checks-falls-back", (4, "[]", ""),
         (4, "", "authentication failed"), True, 2, "ERROR", None, None,
         "with --allow-no-checks a non-zero structured exit carrying an empty array is still not a "
         "zero-check read; the fallback's operator error survives",
         error_contains=("exit 4", "authentication failed")),
    cell("json-nonzero-exit-passing-array-fallback-table", (4, JSON_GREEN[1], ""),
         (0, GREEN_TABLE, ""), False, 1, "BLOCKED", "checks unreadable", (2, 2, 0, 0),
         "a non-zero structured exit falls back to the table even when the stdout parses: the "
         "all-green table is then table-only and may not authorise"),
    cell("json-nonzero-check-exit-1-passing-array-falls-back", (1, JSON_GREEN[1], ""),
         (1, MIXED_TABLE, ""), False, 1, "BLOCKED", "checks", (3, 1, 1, 1),
         "exit 1 is a check-result exit, but a non-zero *structured* exit is still not a read: the "
         "passing array on its stdout is not permission, and the failing fallback table decides"),
    cell("json-nonzero-check-exit-8-passing-array-falls-back", (8, JSON_GREEN[1], ""),
         (8, IN_FLIGHT_TABLE, ""), False, 1, "BLOCKED", "checks pending", (2, 1, 1, 0),
         "exit 8 is a check-result exit, but a non-zero structured exit carrying a passing array "
         "is still not the read; the pending fallback table decides"),
    cell("json-nonzero-check-exit-8-empty-array-allow-no-checks-falls-back", (8, "[]", ""),
         (8, IN_FLIGHT_TABLE, ""), True, 1, "BLOCKED", "checks pending", (2, 1, 1, 0),
         "with --allow-no-checks a non-zero structured exit at a check exit carrying an empty "
         "array is still not a zero-check read; the pending fallback table decides"),

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

    # --- an ignored tab-less line leaves a trace (round-15 F1) -------------
    # `parse_text_checks` cannot read a nonblank line with no tab as a row — it has no STATUS field
    # — and a truncated row has exactly that shape. The parser keeps ignoring it, so the merge
    # decision is unchanged, but the skip is no longer silent: the diagnostic names the line, and
    # with the table opt-in it adds that the ignored line could conceal a check.
    #
    # The fixture carries four ignored lines (three distinct, one repeated) and each cell names
    # the *exact* line list it expects, in order (round-16 F1): with a one-line fixture the report
    # could stop at the first line — `for line in lines[:1]:` — and with distinct lines only, a
    # de-duplicating rewrite survived too, each keeping every artefact green while a truncated row
    # vanished; a palindromic list (`a, b, a`) left the reversed order surviving as well, because
    # `reversed(lines)` reproduced it exactly (round-17 C1). The whole list is asserted, in order,
    # repeats included, and nothing else beside it.
    cell("table-truncated-line-opt-in", JSON_ABSENT, (0, TRUNCATED_TABLE, ""), False, 0,
         "MERGE-OK", None, (1, 1, 0, 0),
         "with --allow-table-only-checks the truncated tab-less lines are still ignored and the "
         "green row merges unchanged, but each one gets its diagnostic, naming the line and what "
         "it could conceal", allow_table_only=True,
         stderr_lines=(
             "pr-merge-check: ignored table line without a tab (not a row): 'required-a'; "
             "--allow-table-only-checks accepts the table as authoritative, so this ignored line "
             "could conceal a check",
             "pr-merge-check: ignored table line without a tab (not a row): 'required-b'; "
             "--allow-table-only-checks accepts the table as authoritative, so this ignored line "
             "could conceal a check",
             "pr-merge-check: ignored table line without a tab (not a row): 'required-a'; "
             "--allow-table-only-checks accepts the table as authoritative, so this ignored line "
             "could conceal a check",
             "pr-merge-check: ignored table line without a tab (not a row): 'required-c'; "
             "--allow-table-only-checks accepts the table as authoritative, so this ignored line "
             "could conceal a check")),
    cell("table-truncated-line", JSON_ABSENT, (0, TRUNCATED_TABLE, ""), False, 1, "BLOCKED",
         "checks unreadable", (1, 1, 0, 0),
         "without the opt-in the same ignored lines are reported beside the table-only verdict, so "
         "the diagnostic is not conditional on the opt-in, and a repeated line is reported per "
         "occurrence rather than per distinct line",
         stderr_lines=(
             "pr-merge-check: ignored table line without a tab (not a row): 'required-a'",
             "pr-merge-check: ignored table line without a tab (not a row): 'required-b'",
             "pr-merge-check: ignored table line without a tab (not a row): 'required-a'",
             "pr-merge-check: ignored table line without a tab (not a row): 'required-c'")),

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
         "--allow-no-checks forgives a zero-check *structured* read, and an empty table only once "
         "--allow-table-only-checks has made it authoritative: neither alone forgives this read"),
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
         "the structured read is what --allow-no-checks forgives directly, and it did not produce "
         "rows; the table is not authoritative without --allow-table-only-checks"),
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
    # every other *tab-delimited* line is a row, and a row whose verdict word is unknown blocks. A
    # nonblank line without a tab is not a row either — it is ignored, with a stderr diagnostic
    # (`table-truncated-line*`).
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


# --- every exit the domain names, on the structured surface too (round-13 F1) ----------------
# Round 13 found the structured-exit dimension declaring `0, 1, 4, 8` while the table one declared
# `0, 1, 8, 2, 4, -15, 127` — the same domain written twice, one copy behind. Two mutants survived
# the whole matrix through that gap: `if returncode == 0:` read as `if returncode <= 0:` (trusting
# a signal-terminated read, exit -15) and as `if returncode in (0, 2):` (trusting a cancelled one,
# exit 2). Each turns a structured `(<non-zero>, <passing array>, "")` over a non-green fallback
# from BLOCKED `checks pending` (2/1/1/0) into MERGE-OK (1/1/0/0). One cell per *declared* non-zero
# exit hands the structured read a parseable **passing** array — the payload a trusting mutant
# would report green — beside a parsing, pending fallback table, so the fallback verdict and its
# exact tally are asserted for every exit the domain names, not only the four the old copy listed.
for _exit in NON_ZERO_EXITS:
    CELLS.append(cell(
        "json-exit-%s-passing-array-falls-back" % _exit, (_exit, JSON_GREEN[1], ""),
        (8, IN_FLIGHT_TABLE, ""), False, 1, "BLOCKED", "checks pending", (2, 1, 1, 0),
        "structured exit %s is not a read whatever its stdout parses: the non-zero exit falls "
        "back to the table, whose pending row blocks" % _exit))


# --- a non-check-result exit is an operator error, not CI data (round-7 F1) --
# gh exits 1 when a check failed and 8 while one is pending; only those two carry check state.
# Every other non-zero exit is an operator error — gh documents 2 as cancellation and 4 as an
# authentication failure, and a signal's status is negative — so a parseable pending or failing
# table beside it must not launder it into `BLOCKED: checks pending`/`checks` (exit 1) while stderr
# is discarded. It is exit 2, and the operator error keeps its own exit code and message.
for _exit in (2, 4, -15, 127):
    CELLS += [
        cell("table-operator-error-exit-%s" % _exit, JSON_ABSENT,
             (_exit, IN_FLIGHT_TABLE, "operation cancelled"), False, 2, "ERROR", None, None,
             "exit %s is not a check result (1 failing, 8 pending), so a pending table beside it "
             "is an operator error, not CI data" % _exit,
             error_contains=("exit %s" % _exit, "operation cancelled")),
        cell("table-operator-error-exit-%s-allow-no-checks" % _exit, JSON_ABSENT,
             (_exit, IN_FLIGHT_TABLE, "operation cancelled"), True, 2, "ERROR", None, None,
             "--allow-no-checks cannot turn an operator error into CI data",
             error_contains=("exit %s" % _exit,)),
        cell("table-operator-error-exit-%s-opt-in" % _exit, JSON_ABSENT,
             (_exit, IN_FLIGHT_TABLE, "operation cancelled"), False, 2, "ERROR", None, None,
             "the table opt-in cannot turn an operator error into CI data",
             allow_table_only=True, error_contains=("exit %s" % _exit,)),
    ]
CELLS.append(cell(
    "table-operator-error-exit-4-with-failing-rows", JSON_ABSENT,
    (4, MIXED_TABLE, "authentication failed"), False, 2, "ERROR", None, None,
    "a failing table beside an operator-error exit is still the operator error, not `checks`",
    error_contains=("exit 4", "authentication failed")))


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

# --- both opt-ins together, against non-green evidence (round-7 F2) ---------
# The two opt-ins each cover one read: --allow-table-only-checks makes the parsed table
# authoritative, --allow-no-checks forgives a zero-check read (the structured one always, the
# empty table once the table opt-in has made it authoritative). Neither forgives a
# reported pending or failing check, and the two together are still two narrow opt-ins, not a
# general bypass — so a pending or failing verdict must survive both. The single cell that used
# both flags only exercised an *empty* table, so `not (allow_no_checks and allow_table_only_checks)`
# guarding the non-green branch survived every cell and reported MERGE-OK over a pending run.
CELLS += [
    cell("rule-both-flags-json-pending", JSON_PENDING, TABLE_UNUSED, True, 1, "BLOCKED",
         "checks pending", (1, 0, 1, 0),
         "with both opt-ins a reported pending check still blocks and the reason names it",
         allow_table_only=True),
    cell("rule-both-flags-json-fail", JSON_FAIL, TABLE_UNUSED, True, 1, "BLOCKED", "checks",
         (1, 0, 0, 1), "with both opt-ins a reported failure still blocks", allow_table_only=True),
    cell("rule-both-flags-json-pass-plus-pending", JSON_PASS_PENDING, TABLE_UNUSED, True, 1,
         "BLOCKED", "checks pending", (2, 1, 1, 0),
         "with both opt-ins a passing neighbour does not make the pending row forgivable",
         allow_table_only=True),
    cell("rule-both-flags-table-pending", JSON_ABSENT, (8, IN_FLIGHT_TABLE, ""), True, 1,
         "BLOCKED", "checks pending", (2, 1, 1, 0),
         "both opt-ins do not forgive a pending table row", allow_table_only=True),
    cell("rule-both-flags-table-failing", JSON_ABSENT, (1, MIXED_TABLE, ""), True, 1, "BLOCKED",
         "checks", (3, 1, 1, 1), "both opt-ins do not forgive a failing table row",
         allow_table_only=True),
]

# --- the table opt-in does not waive the head/gate blockers (round-14 F1) ---
# `--allow-table-only-checks` decides only whether the *table* read is authoritative; the verified
# head and the local gate are decided before the checks read, and the opt-in must not touch them.
# Every other cell that enables the opt-in supplies a matching verified head and `--gates-rc 0`, so
# a mutant that drops the reasons already accumulated at the `table_only = …` assignment —
# `if allow_table_only_checks: reasons = []` — survived every cell: with a green fallback table a
# mismatched head or a failing local gate reached MERGE-OK. These cells enable the opt-in and give
# each blocker its own negative context, so the reason must survive it.
CELLS += [
    cell("rule-table-opt-in-head-mismatch-blocks", JSON_ABSENT, (0, GREEN_TABLE, ""), False, 1,
         "BLOCKED", "head mismatch, verified head missing", (2, 2, 0, 0),
         "the table opt-in does not waive the verified-head requirement: a mismatched head still "
         "blocks", allow_table_only=True, verified_head=MISMATCHED_HEAD),
    cell("rule-table-opt-in-gates-rc-blocks", JSON_ABSENT, (0, GREEN_TABLE, ""), False, 1,
         "BLOCKED", "gates unverified", (2, 2, 0, 0),
         "the table opt-in does not waive the local-gate result: a failing --gates-rc still "
         "blocks", allow_table_only=True, gates_rc=1),
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


# --- row retention, as a family rather than case by case (round-7 note) -----
# Three consecutive rounds each found a *row-retention* hole: a row dropped (a NAME prefix, an
# unordered header), a row normalised (an empty field, lower case), a row collapsed onto another.
# `gh` check names are not unique identifiers, so a generator that indexes rows by name — the
# round-7 dedup mutation, `{entry["name"]: bucket_check(entry)}` — silently loses a row and can
# report MERGE-OK over a failing run. Pin the family by construction: two rows that differ only by
# verdict, under a name that collides with the other row's name (the repeated name), is empty, is
# whitespace-only, or equals a printed column name; in both orders; on both the structured and the
# table surface. Every row must survive into the tally, and any non-green row must block.
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
            TABLE_UNUSED, False, 1, "BLOCKED", _reason, (2, _ok, _pending, _failing),
            "two structured rows named %r differing only by verdict are two rows, and the "
            "non-green one blocks" % _name))
        CELLS.append(cell(
            "table-row-retention-%s-%s" % (_name_label, _label), JSON_ABSENT,
            (0, "%s\t%s\n%s\t%s\n" % (_name, _first, _name, _second), ""), False, 1, "BLOCKED",
            _reason, (2, _ok, _pending, _failing),
            "two table rows named %r differing only by verdict are two rows, and the non-green "
            "one blocks" % _name))


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
    cell("comments-page-2-marker-blocks", JSON_GREEN, TABLE_UNUSED, False, 1, "BLOCKED", "review",
         (1, 1, 0, 0),
         "the machine-review marker on comment page 2 is read, so a stale page-1 read cannot "
         "report MERGE-OK over newer findings", comment_pages=COMMENT_PAGES_WITH_MARKER),
    cell("threads-page-2-unresolved-blocks", JSON_GREEN, TABLE_UNUSED, False, 1, "BLOCKED",
         "threads", (1, 1, 0, 0),
         "an unresolved review thread on page 2 is counted, so stopping after page 1 cannot "
         "report MERGE-OK with a thread still open", thread_pages=THREAD_PAGES_WITH_UNRESOLVED),
]


# --- the table opt-in does not waive the evidence blockers (round-15 F2) ----
# `--allow-table-only-checks` decides only whether the *table* read is authoritative: the
# machine-review marker and the review threads are read and judged after it, on their own evidence.
# Every cell that enabled the opt-in beside blocking evidence paired it with a blocking *checks*
# read, so a mutant that skips those clauses when the opt-in is set — `if not review["pass"] and
# not allow_table_only_checks:` / `if unresolved and not allow_table_only_checks:` — reported
# MERGE-OK over a green table while the shipped gate blocks. Each cell pairs the opt-in and a green
# exit-0 fallback table with one blocker whose evidence lives on a continuation page.
CELLS += [
    cell("rule-table-opt-in-does-not-waive-review", JSON_ABSENT, (0, GREEN_TABLE, ""), False, 1,
         "BLOCKED", "review", (2, 2, 0, 0),
         "the table opt-in does not waive the machine-review clause: the blocking marker on "
         "comment page 2 still blocks, though the authoritative table is green",
         allow_table_only=True, comment_pages=COMMENT_PAGES_WITH_MARKER),
    cell("rule-table-opt-in-does-not-waive-threads", JSON_ABSENT, (0, GREEN_TABLE, ""), False, 1,
         "BLOCKED", "threads", (2, 2, 0, 0),
         "the table opt-in does not waive the unresolved-thread clause: the thread on page 2 is "
         "still counted, though the authoritative table is green",
         allow_table_only=True, thread_pages=THREAD_PAGES_WITH_UNRESOLVED),
]


# --- the dimensions the cells vary over, declared once ----------------------
# Round 11's finding was "the non-zero structured-exit fixture only used exit 4"; round 12's was
# "…and only exit 4, not 1 or 8" — the same shape a third time (an unrecognised verdict word, flag
# combinations and table shapes before them). Each time a value of a dimension the cells vary over
# was simply unrepresented, so a mutation only that value could catch survived an
# exhaustive-looking matrix. So every dimension the cells vary over is declared *here*, with the
# values the cells must represent, and `dimension_problems()` asserts — over the assembled `CELLS`
# — that each declared value is represented by at least one cell, and that at least one cell among
# those is *negative* (a BLOCKED or ERROR verdict) for every value that has a verdict consequence.
# A value no cell represents fails by name and dimension, which is the failure round 11 and round
# 12 both should have produced.
#
# Buckets and raw states are *generated* from `DECLARED_VOCABULARY` above and `STATE_VOCABULARY`
# below, so a token added to the gate arrives with its own cells; the other dimensions are *grouped*
# here — the assertion reads the assembled `CELLS` back and names whatever a declared value is
# missing from.

# Sentinels, named so a failure message can print them. They stand for "the dimension takes its
# absent/undeclared value in this cell" as one value, so a cell that leaves the field out still
# counts as representing it.
JSON_ABSENT_SHAPE = "(empty stdout)"
TABLE_UNUSED_SHAPE = "(no table)"
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


def _table_shape(result):
    """The structural shape of one table fixture's stdout/stderr, header rule aside."""
    _returncode, stdout, stderr = result
    if stdout == "":
        return "stderr-only" if stderr else TABLE_UNUSED_SHAPE
    lines = [line for line in stdout.splitlines() if line.strip()]
    header = TABLE_HEADER.rstrip("\n")
    if all("\t" not in line for line in lines):
        return "garbage"
    if lines == [header]:
        return "header-only"
    if any("\t" not in line for line in lines):
        return "rows-with-truncated-line"
    if lines[0].rstrip("\n") == header:
        return "header-plus-rows"
    return "rows"


def _structured_rows(cell_):
    """The `--json` rows a cell's fixture yields, or `[]` when its stdout is not a JSON list."""
    _returncode, stdout, _stderr = cell_.json_result
    try:
        data = json.loads(stdout or "[]")
    except ValueError:
        return []
    return data if isinstance(data, list) else []


def _cell_source(cell_):
    """The surface the gate's read ends on for a cell: a structured list, or the table."""
    returncode, stdout, _stderr = cell_.json_result
    if returncode == 0:
        try:
            data = json.loads(stdout or "[]")
        except ValueError:
            data = None
        if isinstance(data, list):
            return {"structured"}
    return {"table"}


def _table_consumed(cell_):
    """True when the gate's checks read ends on the table surface — the fallback actually ran.

    The structured read is authoritative: when it yields rows the table is never consulted, so the
    cell's `table_result` fixture describes a read that did not happen and must not be counted as
    evidence that a table at that exit was executed (round-14 F2).
    """
    return _cell_source(cell_) == {"table"}


def _cell_buckets(cell_):
    """The bucket tokens a cell's structured rows carry, with an undeclared sentinel."""
    values = set()
    for row in _structured_rows(cell_):
        if isinstance(row, dict):
            token = str(row.get("bucket") or "").lower()
            values.add(token if "bucket/%s" % token in DECLARED_VOCABULARY else BUCKET_UNDECLARED)
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
    Dimension("source", ("structured", "table"), ("structured", "table"), _cell_source),
    # Both read surfaces carry the same exit domain, so both dimensions are driven from the single
    # `EXIT_CATEGORIES` declared above — a category cannot be represented on one surface only. Only
    # an *executed* table read counts: when the structured read succeeds the gate never consults the
    # table, so a cell's `TABLE_UNUSED` fixture (exit 0, empty stdout) must not be read as a table
    # that returned exit 0 — that supplied exit-0 coverage, negative included, from cells whose
    # table never ran (round-14 F2).
    Dimension("structured-exit", EXIT_CATEGORIES, EXIT_CATEGORIES,
              lambda cell_: {cell_.json_result[0]}),
    Dimension("table-exit", EXIT_CATEGORIES, EXIT_CATEGORIES,
              lambda cell_: {cell_.table_result[0]} if _table_consumed(cell_) else set()),
    Dimension("flags", ((False, False), (True, False), (False, True), (True, True)),
              ((False, False), (True, False), (False, True), (True, True)),
              lambda cell_: {(cell_.allow_no_checks, cell_.allow_table_only)}),
    Dimension("json-shape",
              (JSON_ABSENT_SHAPE, "unparseable", "list-of-objects", "list-with-non-object",
               "non-list"),
              (JSON_ABSENT_SHAPE, "unparseable", "list-of-objects", "list-with-non-object",
               "non-list"),
              lambda cell_: {_json_shape(cell_.json_result)}),
    Dimension("table-shape",
              (TABLE_UNUSED_SHAPE, "stderr-only", "garbage", "header-only",
               "rows-with-truncated-line", "header-plus-rows", "rows"),
              (TABLE_UNUSED_SHAPE, "stderr-only", "garbage", "header-only",
               "rows-with-truncated-line", "header-plus-rows", "rows"),
              lambda cell_: {_table_shape(cell_.table_result)}),
    # The declared bucket tokens, plus the undeclared sentinel. The ok tokens (pass/skipping/
    # neutral) never block, so only the blocking ones are required in a negative cell.
    Dimension("bucket", tuple(sorted(vocabulary("bucket"))) + (BUCKET_UNDECLARED,),
              ("fail", "cancel", "pending", BUCKET_UNDECLARED), _cell_buckets),
    # Every raw state gh prints, plus the absent/undeclared sentinel — each paired with a non-green
    # bucket somewhere, so each has a negative cell.
    Dimension("state", tuple(captured.STATE_VOCABULARY) + (STATE_ABSENT,),
              tuple(captured.STATE_VOCABULARY) + (STATE_ABSENT,), _cell_states),
    # The `--verified-head`/`--gates-rc` pair the cells are driven with. Every cell but the two
    # round-14 opt-in cells uses the matching head and a passing local gate; those two carry the
    # negative contexts (a head mismatch, a failing gate) that the blockers were otherwise never
    # tested against while the table opt-in was enabled.
    Dimension("verified-head/gates-rc",
              ((HEAD, 0), (MISMATCHED_HEAD, 0), (HEAD, 1)),
              ((MISMATCHED_HEAD, 0), (HEAD, 1)),
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


def cross_surface_exit_problems(cells):
    """Exit categories represented on only one of the two read surfaces.

    Both surfaces read the same `gh pr checks` exit domain (`EXIT_CATEGORIES`), so a category the
    cells exercise on one surface and never on the other is the round-13 gap: a mutation that
    special-cases that exit on the *unrepresented* surface has nothing to flip, and the
    per-dimension assertion above only sees the surface it is asked about. This check is across the
    two dimensions, naming the category and the surface that is missing it. Only an *executed*
    table read counts (round-14 F2): a cell whose structured read succeeded never consults the
    table, so its `TABLE_UNUSED` fixture cannot stand in for a table that ran at that exit.
    """
    problems = []
    seen = {"structured-exit": set(), "table-exit": set()}
    for cell_ in cells:
        seen["structured-exit"].add(cell_.json_result[0])
        if _table_consumed(cell_):
            seen["table-exit"].add(cell_.table_result[0])
    for code in EXIT_CATEGORIES:
        missing = sorted(surface for surface, values in seen.items() if code not in values)
        if not missing:
            continue
        if len(missing) == 2:
            problems.append((
                "cross-surface-exit",
                "the exit category %r is represented by no cell on either read surface" % (code,)))
        else:
            problems.append((
                "cross-surface-exit",
                "the exit category %r is represented on one read surface but missing from the %s "
                "surface" % (code, missing[0])))
    return problems


def guard_self_check():
    """The completeness guards must fire when an *executed* table exit disappears.

    Round-14 F2 was a gap in the guards, not the gate: they counted `table_result[0]` for every
    cell, including the ones whose structured read succeeded and whose table was never consulted,
    so `TABLE_UNUSED = (0, "", "")` kept supplying table-exit-0 coverage from cells whose table did
    not run. This drives the reviewer's reproduction — replace every *consumed* table fixture at
    exit 0 with a pending exit-8 table — and requires both guards to name the now-missing table
    exit 0. With the old counting the replacement still left exit 0 supplied by the unused fixtures
    and both guards stayed silent, which is exactly how a missing executed exit could hide.
    """
    replaced = [
        cell_._replace(table_result=(8, cell_.table_result[1], cell_.table_result[2]))
        if _table_consumed(cell_) and cell_.table_result[0] == 0 else cell_
        for cell_ in CELLS
    ]
    problems = []
    dimension = dimension_problems(replaced)
    cross_surface = cross_surface_exit_problems(replaced)
    if not any("the value 0 of the table-exit dimension" in message
               for _kind, message in dimension):
        problems.append((
            "guard-self-check",
            "replacing every consumed table exit 0 with exit 8 must make the table-exit dimension "
            "guard report the missing 0"))
    if not any(kind == "cross-surface-exit" and "table-exit" in message
               for kind, message in cross_surface):
        problems.append((
            "guard-self-check",
            "replacing every consumed table exit 0 with exit 8 must make the cross-surface guard "
            "report table exit 0 missing"))
    return problems


# --- the stderr line list: one comparison, and the guard that it is exact ----
# The comparison is test-side, so no gate mutation can pin its strictness (round-17 F2 property
# 8). `stderr_problems()` is the whole rule in one function, and `comparator_self_check()` runs
# the weakened forms of it against the cells' own pinned lists, so a careless edit to either the
# comparison or a fixture fails by name instead of silently dropping a catch.
STDERR_WITNESS_EXTRA = "pr-merge-check: <extra line produced by no run>"


def stderr_problems(expected, observed):
    """The exact-list stderr rule: the whole line list, in order, repeats included, no extras.

    Nothing weaker: set equality accepts a de-duplicated or a re-ordered report, containment
    (`set(expected) <= set(observed)`) accepts one that appends a line no cell expects, and each
    collapse drops the multiplicity and the order the round-16 and round-17 findings turned on. A
    cell names its list in `stderr_lines`; a cell that names none must print none.
    """
    if observed != expected:
        return "expected stderr lines %r, got %r" % (expected, observed)
    return None


def comparator_self_check():
    """Every pinned stderr list must discriminate, and the shipped comparison must reject each
    witness of it.

    For every cell that pins a stderr list, the shipped comparison must reject the de-duplicated,
    the re-ordered and the extra-line witness of that list:

    * the de-duplicated witness (`dict.fromkeys(lines)`) is rejected only when the list carries a
      repeat — without one that witness *is* the list, and a de-duplicating report would pass;
    * the re-ordered witness (`reversed(lines)`) is rejected only when the list is not a
      palindrome — `required-a, required-b, required-a` is its own reversal, which is how the
      `reversed(lines)` mutation survived every round-16 cell (round-17 C1);
    * the extra-line witness is rejected by exact equality alone: set equality accepts the first
      two witnesses, containment accepts all three, so each weakening of `stderr_problems()` fails
      here on the witness it lets through — the comparison cannot be weakened without a check
      failing.

    A fixture that stops discriminating and a comparison that stops being exact are the two ways
    this class reopened in rounds 16 and 17; each now names itself here.
    """
    problems = []
    for cell_ in CELLS:
        expected = list(cell_.stderr_lines or ())
        if not expected:
            continue
        witnesses = (
            ("de-duplicated", list(dict.fromkeys(expected)),
             "the list carries no repeat, so a de-duplicating report would pass"),
            ("re-ordered", list(reversed(expected)),
             "the list is a palindrome, so a reversing report would pass"),
            ("extra-line", expected + [STDERR_WITNESS_EXTRA],
             "an appended line is never part of the pinned list"),
        )
        for label, witness, degeneracy in witnesses:
            if witness == expected:
                problems.append((
                    "comparator-self-check",
                    "cell %s: the %s witness is the pinned list itself (%s)"
                    % (cell_.id, label, degeneracy)))
            elif stderr_problems(expected, witness) is None:
                problems.append((
                    "comparator-self-check",
                    "cell %s: the exact-list comparison accepts the %s witness, so it is weaker "
                    "than exact" % (cell_.id, label)))
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
#
# The cells also pin the whole check-command shape, not just its prefix: the argv of every
# `gh pr checks` call must be exactly the structured read or the fallback read of the *requested*
# PR, and every `git` call must carry the adjacent `["-C", <repo>]` pair — a `["git", repo, ...]`
# form keeps the path in argv while giving Git no valid repository selection. The fallback read is
# exercised here on purpose (`boundary-repo-gh-fallback-cwd`): the structured read succeeds in every
# other boundary cell, so the fallback call site — and its `cwd=repo` — was never reached, and
# dropping that one `cwd` survived the whole matrix.
BoundaryCell = namedtuple("BoundaryCell", "id surface reads require_fallback why")

BOUNDARY_CELLS = [
    # The structured read succeeds: every gh call must carry the repository directory.
    BoundaryCell("boundary-repo-gh-cwd", "gh", (JSON_GREEN, TABLE_UNUSED), False,
                 "gh takes the repository as the child's working directory, so the directory "
                 "--repo names must reach subprocess.run() unchanged"),
    # The structured read does not produce rows, so the *fallback* read runs: it too must carry the
    # repository directory, and it must actually have been issued.
    BoundaryCell("boundary-repo-gh-fallback-cwd", "gh", (JSON_ABSENT, (0, GREEN_TABLE, "")), True,
                 "the fallback read is a second gh call site: its cwd must reach the child and the "
                 "call must have happened, or dropping it there is invisible"),
    BoundaryCell("boundary-repo-git-flag", "git", (JSON_GREEN, TABLE_UNUSED), False,
                 "git takes the repository as `-C <path>` in argv, so the same directory must "
                 "reach the child that way, as the adjacent pair"),
]

# The two check-command shapes `gh pr checks` may be called with, for the requested PR. A call
# whose argv is neither is a shape this gate does not document.
STRUCTURED_CHECKS_ARGV = ("gh", "pr", "checks", REQUESTED_PR, "--json", "name,state,bucket")
FALLBACK_CHECKS_ARGV = ("gh", "pr", "checks", REQUESTED_PR)


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

def _threads_page(nodes, has_next, end_cursor):
    """One `reviewThreads` page, as the JSON `gh api graphql` prints."""
    return json.dumps({"data": {"repository": {"pullRequest": {"reviewThreads": {
        "pageInfo": {"hasNextPage": has_next, "endCursor": end_cursor},
        "nodes": nodes}}}}})


# The single terminal page every cell without a `thread_pages` fixture sees: no nodes to follow.
TERMINAL_THREADS = _threads_page([], False, None)


def _fake_run_for(cell_, records=None, repo_token=None):
    view = {"state": "OPEN", "isDraft": False, "headRefOid": HEAD, "headRefName": "feature"}

    def fake_run(cmd, cwd=None, capture_output=False, text=False, env=None):
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
            returncode, stdout, stderr = (cell_.json_result if "--json" in cmd
                                          else cell_.table_result)
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
    if cell_.allow_table_only:
        argv.append("--allow-table-only-checks")
    out, err = io.StringIO(), io.StringIO()
    with patch.object(module.subprocess, "run",
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
    # The stderr of a non-ERROR run, exactly: the whole line list a cell names, in order, and no
    # other line beside it, through the one comparison `stderr_problems()` states. A substring
    # count accepted a truncating report (one of two diagnostics still contains the fragment) and a
    # de-duplicating one (round-16 F1); a subset/set comparison accepted the reversed and extra-line
    # reports (round-17 F2 property 8, guarded by `comparator_self_check()`).
    return stderr_problems(list(cell_.stderr_lines or ()), err.splitlines())


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


def run_sh_cell(module, sh_cell):
    """sh() with subprocess.run() faked: returns the value sh() handed back."""

    def fake_run(cmd, cwd=None, capture_output=False, text=False):
        return subprocess.CompletedProcess(cmd, sh_cell.exit_code, sh_cell.stdout, sh_cell.stderr)

    with patch.object(module.subprocess, "run", side_effect=fake_run):
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
    driver = cell(boundary_cell.id, boundary_cell.reads[0], boundary_cell.reads[1], False, 0,
                  "MERGE-OK", None, (1, 1, 0, 0),
                  "the recording run only needs the read the cell names")
    argv = ["pr-merge-check.py", REQUESTED_PR, "--repo", repo, "--verified-head", HEAD,
            "--gates-rc", "0", "--allow-no-machine-review"]
    out, err = io.StringIO(), io.StringIO()
    with patch.object(module.subprocess, "run",
                      side_effect=_fake_run_for(driver, records, repo_token=repo)), \
            patch.object(sys, "argv", argv), redirect_stdout(out), redirect_stderr(err):
        module.main()


def check_boundary_cell(module, boundary_cell):
    """The repository the operator named must reach the child on its surface, unchanged.

    The run happens in a directory distinct from the runner's, so a dropped directory cannot pass
    by coincidence, and only the calls on the cell's own surface are judged. On the `gh` surface
    every call must carry that directory *and* every `gh pr checks` call must be exactly one of the
    two documented reads of the requested PR — a prefix check accepted `--json` alone, which let a
    dropped `str(pr)` reach real `gh` (and its current-branch PR). When the cell names the fallback
    read, that call must have been issued, or its forwarded directory is unobserved.
    """
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
            allowed = (STRUCTURED_CHECKS_ARGV, FALLBACK_CHECKS_ARGV)
            unexpected = sorted(shape for shape in shapes if shape not in allowed)
            if unexpected:
                return ("a gh pr checks call carries an argv this gate does not document: %r; the "
                        "documented shapes are %r and %r"
                        % (unexpected[0], STRUCTURED_CHECKS_ARGV, FALLBACK_CHECKS_ARGV))
            if STRUCTURED_CHECKS_ARGV not in shapes:
                return ("PR %s was not read with the documented structured argv %r; saw %r"
                        % (REQUESTED_PR, STRUCTURED_CHECKS_ARGV, sorted(shapes)))
            if boundary_cell.require_fallback and FALLBACK_CHECKS_ARGV not in shapes:
                return ("the fallback read %r was never issued, so its forwarded directory is "
                        "unobserved (saw %r)" % (FALLBACK_CHECKS_ARGV, sorted(shapes)))
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
    # The check-fetch fallback (human table) for the requested PR, in the named repository.
    (("gh", "pr", "checks", "7"), REPO_TOKEN, False),
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
    problems.extend(cross_surface_exit_problems(CELLS))
    problems.extend(guard_self_check())
    problems.extend(comparator_self_check())
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
