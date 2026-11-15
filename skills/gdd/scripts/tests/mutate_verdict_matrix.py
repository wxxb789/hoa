#!/usr/bin/env python3
"""Mutation harness over the verdict matrix.

Every mutation below is a plausible wrong implementation of `pr-merge-check.py`. Each is applied in
memory to the module source (the checkout is never written) and the whole verdict matrix — every
cell plus the golden call-log comparison — is re-run against the mutant: at least one cell must
flip, or the recorded call set must change, or the mutation survived an exhaustive matrix and the
harness fails loudly with the mutation id.

Two catalogues make up the run:

* the anchored mutations: the twelve from the previous sweep (sh_raw normalising the exit code or
  the streams, a dropped non-object row, a non-list payload read as zero checks, the bucket/state
  precedence, an unknown bucket or a missing bucket read as ok, pending or the opt-out not blocking,
  a name-based header drop, an unrecognized verdict passing, a command error read as zero checks),
  the five this round's earlier findings named, the three round-5 findings named (a normalising
  header comparison, a table-only read that authorises by default, and a two-token vocabulary
  swap), the two round-6 findings named (a flag conflation that lets the table-only opt-in grant the
  zero-check opt-out, and a whole line normalised before the header comparison), the two the round-8
  finding named (the working directory dropped inside `sh_raw`, so `gh` inspects the caller's
  repository instead of the one `--repo` names, and a `git` call that drops its repository), the six
  the round-9 findings named (the structured read's dropped PR number, the fallback read's dropped
  PR number and its dropped working directory, the two `git` calls' `-C <repo>` pair kept as a bare
  path, and a trimmed `gh pr view --json` field list — the last reached by no cell, so only the
  golden call log catches it), the one the round-11 finding named (the structured read's non-zero
  exit accepted whenever its stdout is non-empty, so a parseable payload beside an operator error is
  trusted as the read), the one the round-12 finding named (the same acceptance narrowed to the two
  check-result exits 1 and 8 — the shape the round-11 fixtures, all at exit 4, left invisible), the
  one the round-14 finding named (the table opt-in clearing the verified-head and local-gate
  reasons already accumulated, so a blocker decided before the checks read merged over a green
  table), and the ones the surface implies (a tab-less line parsed as a row,
  the header parsed as a check, the cancel and skipping bucket mappings, the zero-check opt-out
  granted unconditionally, an unordered header, a pending bucket read as failing);
* one generated mutation per declared `CHECK_VOCABULARY` entry, reclassifying that token into every
  other classification ("a failing verdict read as ok", "an ok verdict read as pending"). They are
  generated from the vocabulary, so a token added to the gate arrives with its own mutations and
  cannot be added without being pinned. A single-token reclassification is caught both by the
  declaration check and by a cell, and the explicit `vocabulary-swap-*` mutation exchanges two
  tokens' meanings at once — the shape that was invisible while the cells read the gate for what
  was correct (round-5 finding F2).

Run: python3 skills/gdd/scripts/tests/mutate_verdict_matrix.py
"""

from __future__ import annotations

import sys
import time
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
for _path in (str(SCRIPTS), str(HERE)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import test_verdict_matrix as matrix  # noqa: E402

GATE_SOURCE_PATH = SCRIPTS / "pr-merge-check.py"
SOURCE = GATE_SOURCE_PATH.read_text(encoding="utf-8")


# --- the anchored catalogue -------------------------------------------------
# (id, anchor present exactly once in the source, replacement, note)

MUTATIONS = [
    ("sh-raw-normalizes-exit",
     '    return proc.returncode, proc.stdout or "", proc.stderr or ""',
     '    return 0, proc.stdout or "", proc.stderr or ""',
     "a non-zero exit is dropped inside sh_raw"),
    ("sh-raw-strips-streams",
     '    return proc.returncode, proc.stdout or "", proc.stderr or ""',
     '    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()',
     "the forwarded streams are normalized"),
    ("json-nonobject-row-dropped",
     """            for entry in data:
                if not isinstance(entry, dict):
                    raise GateError(
                        "gh pr checks --json: expected an object per check, got "
                        + type(entry).__name__
                    )
            return [bucket_check(entry) for entry in data], "json\"""",
     """            return [bucket_check(entry) for entry in data
                    if isinstance(entry, dict)], "json\"""",
     "a non-object row is dropped instead of raising"),
    ("json-nonlist-becomes-empty",
     "        if isinstance(data, list):",
     """        if not isinstance(data, list):
            return [], "json"
        if isinstance(data, list):""",
     "a non-list payload is read as a structured zero-check success"),
    ("bucket-raw-state-wins",
     """    bucket = str(entry.get("bucket") or "").lower()
    conclusion = BUCKET_CONCLUSIONS.get(bucket)""",
     """    bucket = str(entry.get("bucket") or "").lower()
    conclusion = BUCKET_CONCLUSIONS.get(bucket)
    if conclusion is not None and str(entry.get("state") or "").upper() in {
            "SUCCESS", "SKIPPED", "NEUTRAL", "FAILURE", "CANCELLED"}:
        conclusion = str(entry.get("state") or "").upper()""",
     "the raw state overrules a recognized bucket"),
    ("bucket-missing-defaults-to-pass",
     "    conclusion = BUCKET_CONCLUSIONS.get(bucket)",
     '    conclusion = BUCKET_CONCLUSIONS.get(bucket or "pass")',
     "a missing bucket becomes ok"),
    ("unknown-bucket-becomes-ok",
     "    conclusion = BUCKET_CONCLUSIONS.get(bucket)",
     '    conclusion = BUCKET_CONCLUSIONS.get(bucket, "SUCCESS")',
     "an unknown bucket becomes ok"),
    ("bucket-pending-counts-as-failure",
     "    waits = conclusion is None or conclusion in PENDING_CONCLUSIONS",
     "    waits = conclusion is None",
     "a declared pending bucket is reported as failing instead of pending"),
    ("vocabulary-keys-keep-the-surface",
     "        key[len(prefix):]: value",
     "        key: value",
     "the vocabulary keys keep their surface, so no token maps to a conclusion"),
    ("pending-does-not-block",
     """        "pass": pending == 0 and failing == 0,
        "reason": "ok" if pending == 0 and failing == 0 else "checks not green",""",
     """        "pass": failing == 0,
        "reason": "ok" if failing == 0 else "checks not green",""",
     "pending no longer blocks"),
    ("opt-out-forgives-pending",
     '        "pass": pending == 0 and failing == 0,',
     '        "pass": failing == 0 and (pending == 0 or allow_no_checks),',
     "--allow-no-checks forgives a reported pending check"),
    ("zero-checks-needs-no-flag",
     '            "pass": bool(allow_no_checks),',
     "            \"pass\": True,",
     "a zero-check read passes without the opt-out"),
    ("header-accepts-unordered-fields",
     "    return fields == list(TEXT_CHECK_COLUMNS)",
     """    return (len(fields) >= 2 and {"NAME", "STATUS"} <= set(fields)
            and set(fields) <= set(TEXT_CHECK_COLUMNS))""",
     "the header is matched as an unordered set of column names"),
    ("header-accepts-a-leading-run",
     "    return fields == list(TEXT_CHECK_COLUMNS)",
     "    return len(fields) >= 2 and fields == list(TEXT_CHECK_COLUMNS[: len(fields)])",
     "a leading run of the column names is accepted as the header"),
    ("header-prefix-match",
     "    return fields == list(TEXT_CHECK_COLUMNS)",
     """    return line.upper().startswith("NAME") or fields == list(TEXT_CHECK_COLUMNS)""",
     "a NAME-prefixed row is dropped as a header"),
    ("tabless-line-becomes-a-row",
     '        if not line.strip() or "\\t" not in line or is_text_check_header(line):',
     '        if not line.strip() or is_text_check_header(line):',
     "a truncated line is parsed as a pending check"),
    ("header-parsed-as-a-check",
     '        if not line.strip() or "\\t" not in line or is_text_check_header(line):',
     '        if not line.strip() or "\\t" not in line:',
     "the header row is parsed as a check"),
    ("line-stripped-before-the-header-comparison",
     """        if not line.strip() or "\\t" not in line or is_text_check_header(line):
            continue
        cells = line.split("\\t")""",
     """        line = line.strip()
        if not line or "\\t" not in line or is_text_check_header(line):
            continue
        cells = line.split("\\t")""",
     "the whole line is normalised before the header comparison, so a row with an empty field "
     "collapses onto the header and vanishes"),
    ("unknown-verdict-passes",
     '        conclusion = TEXT_CONCLUSIONS.get(verdict, "FAILURE")',
     '        conclusion = TEXT_CONCLUSIONS.get(verdict, "SUCCESS")',
     "an unrecognized table verdict is ok"),
    ("cancelled-counts-as-ok",
     'GOOD_CONCLUSIONS = {"SUCCESS", "SKIPPED", "NEUTRAL"}',
     'GOOD_CONCLUSIONS = {"SUCCESS", "SKIPPED", "NEUTRAL", "CANCELLED"}',
     "a cancelled check passes"),
    ("cancel-bucket-becomes-neutral",
     '    "bucket/cancel": "CANCELLED",',
     '    "bucket/cancel": "NEUTRAL",',
     "the cancel bucket is ok"),
    ("skipping-bucket-becomes-failure",
     '    "bucket/pass": "SUCCESS",\n    "bucket/skipping": "SKIPPED",',
     '    "bucket/pass": "SUCCESS",\n    "bucket/skipping": "FAILURE",',
     "the skipping bucket is a failure"),
    ("command-error-becomes-empty",
     """            lowered = message.lower()
            if "no checks reported" not in lowered and "no check runs found" not in lowered:
                raise GateError(message.splitlines()[0] if message else f"exit {returncode}")""",
     """            lowered = message.lower()
            if "no checks reported" not in lowered and "no check runs found" not in lowered:
                return [], "json\"""",
     "an unparseable command error becomes a structured zero-check success"),
    ("all-green-nonzero-returns",
     """        elif evaluate_checks(checks)["pass"]:
            # A non-zero exit means the read was not complete (gh exits 8 while any check is
            # pending and 1 when one failed), so an all-green parsed table is a partial read —
            # a truncated row or an ignored command error. That is never permission.
            detail = message.splitlines()[0] if message else f"exit {returncode}"
            raise GateError(
                "gh pr checks: non-zero exit with an all-green table "
                f"({detail}); the read was incomplete"
            )""",
     "        pass",
     "an all-green table under a non-zero exit becomes permission"),
    ("header-comparison-normalises",
     """    fields = line.split("\\t")
    return fields == list(TEXT_CHECK_COLUMNS)""",
     """    fields = [cell.strip().upper() for cell in line.split("\\t")]
    fields = [cell for cell in fields if cell]
    return fields == list(TEXT_CHECK_COLUMNS)""",
     "the header comparison strips empty fields and case, so a data row vanishes"),
    ("table-only-all-green-authorises",
     '    if table_only and (checks["total"] == 0 or checks["pass"]):',
     "    if False:",
     "a table-only read authorises a merge by default instead of blocking"),
    ("table-opt-in-grants-the-zero-check-opt-out",
     "    checks = evaluate_checks(checks_rows, allow_no_checks=allow_no_checks)",
     "    checks = evaluate_checks(checks_rows, allow_no_checks=allow_no_checks"
     "\n                                 or allow_table_only_checks)",
     "--allow-table-only-checks is conflated with --allow-no-checks, so an empty table-only read "
     "merges on one flag instead of requiring both"),
    ("table-opt-in-clears-the-other-reasons",
     '    table_only = checks_source == "table" and not allow_table_only_checks',
     '    table_only = checks_source == "table" and not allow_table_only_checks'
     '\n    if allow_table_only_checks:\n        reasons = []',
     "the table opt-in clears the verified-head and local-gate reasons already accumulated, so a "
     "mismatched head or a failing --gates-rc merges over a green table"),
    ("vocabulary-swap-neutral-and-timed-out",
     """    "table/neutral": "NEUTRAL",
    "table/failing": "FAILURE",
    "table/fail": "FAILURE",
    "table/cancelled": "CANCELLED",
    "table/canceled": "CANCELLED",
    "table/timed_out": "TIMED_OUT",""",
     """    "table/neutral": "TIMED_OUT",
    "table/failing": "FAILURE",
    "table/fail": "FAILURE",
    "table/cancelled": "CANCELLED",
    "table/canceled": "CANCELLED",
    "table/timed_out": "NEUTRAL",""",
     "two token meanings are exchanged in memory: neutral now blocks and timed_out is ok"),
    ("fallback-accepts-any-nonzero-exit",
     "        if returncode not in (1, 8):",
     "        if False:",
     "every non-zero fallback exit is accepted as CI data, so an operator error (gh's 2 "
     "cancellation, 4 authentication, a signal's negative code) reads as `checks pending`"),
    ("both-opt-ins-suppress-a-non-green-verdict",
     '    elif not checks["pass"]:',
     '    elif not checks["pass"] and not (allow_no_checks and allow_table_only_checks):',
     "the two opt-ins together suppress a non-green checks verdict, though each covers only its "
     "own read and neither forgives a reported pending or failing check"),
    ("json-rows-deduplicated-by-name",
     '            return [bucket_check(entry) for entry in data], "json"',
     '            return list({entry.get("name"): bucket_check(entry) for entry in data}.values()),'
     ' "json"',
     "structured rows are indexed by name, so a repeated check name collapses two rows into one "
     "and a failing row vanishes"),
    ("subprocess-cwd-dropped",
     "        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)",
     "        proc = subprocess.run(cmd, cwd=None, capture_output=True, text=True)",
     "the working directory the call forwarded is dropped at subprocess.run(), so gh inspects the "
     "caller's repository instead of the one --repo named"),
    ("git-repository-flag-dropped",
     'sh(["git", "-C", repo, "rev-parse", "HEAD"])',
     'sh(["git", "rev-parse", "HEAD"])',
     "a git call drops its repository, so the local head is read from the caller's repository"),
    ("structured-checks-pr-dropped",
     '["gh", "pr", "checks", str(pr), "--json", "name,state,bucket"], cwd=repo',
     '["gh", "pr", "checks", "--json", "name,state,bucket"], cwd=repo',
     "the structured read drops the PR number, so real gh reads the current branch's PR instead"),
    ("fallback-checks-pr-dropped",
     'sh_raw(["gh", "pr", "checks", str(pr)], cwd=repo)',
     'sh_raw(["gh", "pr", "checks"], cwd=repo)',
     "the fallback read drops the PR number, so real gh reads the current branch's PR instead"),
    ("fallback-checks-cwd-dropped",
     'sh_raw(["gh", "pr", "checks", str(pr)], cwd=repo)',
     'sh_raw(["gh", "pr", "checks", str(pr)])',
     "the fallback read drops its working directory at the call site, so gh inspects the caller's "
     "repository instead of the one --repo named"),
    ("git-repository-path-kept-but-flag-dropped",
     'sh(["git", "-C", repo, "rev-parse", "HEAD"])',
     'sh(["git", repo, "rev-parse", "HEAD"])',
     "a git call keeps the repository in argv but drops the adjacent -C pair, so Git no longer has "
     "a valid repository selection while a membership check still sees the path"),
    ("git-abbrev-ref-flag-dropped",
     'sh(["git", "-C", repo, "rev-parse", "--abbrev-ref", "HEAD"])',
     'sh(["git", repo, "rev-parse", "--abbrev-ref", "HEAD"])',
     "the second git call loses its -C pair too, so the branch is read from the caller's repository"),
    ("pr-view-field-list-trimmed",
     '"headRefOid,headRefName,state,isDraft",',
     '"headRefOid,headRefName,state",',
     "the structured PR read asks for fewer fields than the gate needs — no cell names this argv, "
     "so only the golden call log catches it"),
    ("comment-pagination-inclusive-boundary",
     "        if len(batch) < 100:",
     "        if len(batch) <= 100:",
     "the comment-page continuation stops at a full page, so it never reads page 2 and the "
     "machine-review marker there cannot block"),
    ("thread-pagination-cursor-dropped",
     '        cursor = page.get("endCursor")',
     "        cursor = None",
     "the thread-page cursor is dropped, so the loop stops after page 1 and an unresolved thread "
     "on page 2 never blocks"),
    ("sh-does-not-trim",
     "    return stdout.strip()",
     "    return stdout",
     "sh() returns the child's stream untrimmed, so a newline-terminated branch name fails the "
     "local-branch comparison and a verified head reads as unverified"),
    ("structured-read-accepts-any-nonzero-with-stdout",
     "    if returncode == 0:",
     "    if returncode == 0 or stdout:",
     "the structured read's non-zero exit is ignored whenever its stdout is non-empty, so a "
     "non-zero structured read whose stdout parses (a passing array, or an empty one under "
     "--allow-no-checks) is trusted as the read instead of falling back to the table and its "
     "operator error"),
    ("structured-read-accepts-check-exits-with-stdout",
     "    if returncode == 0:",
     "    if returncode == 0 or (returncode in (1, 8) and stdout):",
     "the structured read's non-zero exit is trusted whenever its stdout parses *and* the exit is "
     "one of the two `gh pr checks` uses for CI state (1 failing, 8 pending); every round-11 "
     "non-zero structured fixture used exit 4, so this narrower shape survived the matrix until "
     "round 12 added a structured exit 1 and 8 carrying a parseable payload over a non-green "
     "fallback"),
    ("structured-read-accepts-signal-exit",
     "    if returncode == 0:",
     "    if returncode <= 0:",
     "the structured read trusts any exit at or below zero, so a signal-terminated read (exit -15) "
     "whose stdout parses is taken as the read instead of falling back to the table; the old "
     "structured-exit dimension named no negative exit, so nothing flipped"),
    ("structured-read-accepts-cancellation",
     "    if returncode == 0:",
     "    if returncode in (0, 2):",
     "the structured read trusts exit 2 (gh's cancellation), so a cancelled read whose stdout "
     "parses is taken as the read instead of falling back to the table; the old structured-exit "
     "dimension named no exit 2, so nothing flipped"),

    # --- round-15 findings --------------------------------------------------
    ("ignored-line-diagnostic-dropped",
     """    report_ignored_table_lines(ignored, allow_table_only)
    return checks, "table\"""",
     '    return checks, "table"',
     "the tab-less lines the table parser ignores are never named on stderr, so the only trace of a "
     "truncated row disappears while the verdict stays green"),
    ("opt-in-drops-blocking-review",
     '    if not review["pass"]:',
     '    if not review["pass"] and not allow_table_only_checks:',
     "the table opt-in drops a blocking machine-review verdict, though it decides only whether the "
     "table read is authoritative"),
    ("opt-in-drops-unresolved-threads",
     "    if unresolved:",
     "    if unresolved and not allow_table_only_checks:",
     "the table opt-in drops the unresolved-thread blocker, though it decides only whether the "
     "table read is authoritative"),
]


# --- the generated catalogue: one mutation per declared vocabulary entry ----
# Each entry is reclassified into every other classification — "a failing verdict read as ok", "an
# ok verdict read as pending" — anchored on the entry's own source line, so the vocabulary cannot
# grow without its mutations arriving with it.
_TARGETS = (("ok", "SUCCESS"), ("pending", "PENDING"), ("failing", "FAILURE"))


def vocabulary_mutations():
    mutations = []
    for key in sorted(matrix.VOCABULARY):
        conclusion = matrix.VOCABULARY[key]
        current = matrix.classification(conclusion)
        anchor = '    "%s": "%s",' % (key, conclusion)
        for target, replacement in _TARGETS:
            if target == current:
                continue
            mutations.append((
                "vocab-%s-to-%s" % (key.replace("/", "-"), target),
                anchor,
                '    "%s": "%s",' % (key, replacement),
                "the declared token %s is read as %s instead of %s" % (key, target, current),
            ))
    return mutations


MUTATIONS.extend(vocabulary_mutations())


def load_mutated(source):
    module = types.ModuleType("pr_merge_check_mutant")
    module.__file__ = str(GATE_SOURCE_PATH)
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module


def main():
    start = time.monotonic()
    gate = matrix.load_gate()
    baseline = matrix.evaluate_with_calls(gate)
    if baseline:
        for cell_id, problem in baseline:
            print("  BASELINE FAIL  %s: %s" % (cell_id, problem))
        print("mutation-harness: the unmutated module already violates the matrix; stopping")
        return 1

    survivors = []
    for mutation_id, old, new, note in MUTATIONS:
        count = SOURCE.count(old)
        if count != 1:
            print("  ANCHOR FAIL  %s: anchor matches %d times (need exactly 1)" % (mutation_id, count))
            survivors.append(mutation_id)
            continue
        try:
            mutant = load_mutated(SOURCE.replace(old, new))
        except Exception as exc:
            print("  SURVIVOR  %s: the mutant could not even load (%s: %s)"
                  % (mutation_id, type(exc).__name__, exc))
            survivors.append(mutation_id)
            continue
        flipped = [cell_id for cell_id, problem in matrix.evaluate_with_calls(mutant) if problem is not None]
        if not flipped:
            print("  SURVIVOR  %s (%s): no cell or golden call-log entry flipped" % (mutation_id, note))
            survivors.append(mutation_id)
        else:
            print("  caught    %s (%s): %d problem(s), first %s"
                  % (mutation_id, note, len(flipped), flipped[0]))

    elapsed = time.monotonic() - start
    cells = (len(matrix.CELLS) + len(matrix.STREAM_CELLS) + len(matrix.SH_TRIM_CELLS)
             + len(matrix.BOUNDARY_CELLS))
    print("mutation-harness: %d mutations over %d cells, %d survived, %.2fs"
          % (len(MUTATIONS), cells, len(survivors), elapsed))
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
