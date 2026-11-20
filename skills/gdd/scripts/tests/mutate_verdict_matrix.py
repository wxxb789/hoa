#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Require every in-memory gate mutation to fail the verdict matrix.

Anchored mutations exercise fail-open paths and subprocess forwarding.
Generated mutations reclassify each declared bucket into the other classes.

Run: uv run skills/gdd/scripts/tests/mutate_verdict_matrix.py
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
     """        for entry in data:
            if not isinstance(entry, dict):
                raise GateError(
                    "gh pr checks --json: expected an object per check, got "
                    + type(entry).__name__
                )
        return [bucket_check(entry) for entry in data]""",
     "        return [bucket_check(entry) for entry in data if isinstance(entry, dict)]",
     "malformed rows disappear instead of making the read fail"),
    ("json-nonlist-becomes-empty",
     '            raise GateError("gh pr checks --json: expected a list of checks")',
     "            return []",
     "a non-list payload is read as zero checks"),
    ("json-blank-becomes-empty",
     "        data = json.loads(stdout)",
     '        data = json.loads(stdout or "[]")',
     "blank stdout is read as zero checks"),
    ("bucket-raw-state-wins",
     """    bucket = str(entry.get("bucket") or "").lower()
    conclusion = CHECK_VOCABULARY.get(bucket)""",
     """    bucket = str(entry.get("bucket") or "").lower()
    conclusion = CHECK_VOCABULARY.get(bucket)
    if conclusion is not None and str(entry.get("state") or "").upper() in {
            "SUCCESS", "SKIPPED", "NEUTRAL", "FAILURE", "CANCELLED"}:
        conclusion = str(entry.get("state") or "").upper()""",
     "the raw state overrules a recognized bucket"),
    ("bucket-missing-defaults-to-pass",
     "    conclusion = CHECK_VOCABULARY.get(bucket)",
     '    conclusion = CHECK_VOCABULARY.get(bucket or "pass")',
     "a missing bucket becomes ok"),
    ("unknown-bucket-becomes-ok",
     "    conclusion = CHECK_VOCABULARY.get(bucket)",
     '    conclusion = CHECK_VOCABULARY.get(bucket, "SUCCESS")',
     "an unknown bucket becomes ok"),
    ("bucket-pending-counts-as-failure",
     "    waits = conclusion is None or conclusion in PENDING_CONCLUSIONS",
     "    waits = conclusion is None",
     "a declared pending bucket is reported as failing instead of pending"),
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
    ("cancelled-counts-as-ok",
     'GOOD_CONCLUSIONS = {"SUCCESS", "SKIPPED", "NEUTRAL"}',
     'GOOD_CONCLUSIONS = {"SUCCESS", "SKIPPED", "NEUTRAL", "CANCELLED"}',
     "a cancelled check passes"),
    ("cancel-bucket-becomes-neutral",
     '    "cancel": "CANCELLED",',
     '    "cancel": "NEUTRAL",',
     "the cancel bucket is ok"),
    ("skipping-bucket-becomes-failure",
     '    "pass": "SUCCESS",\n    "skipping": "SKIPPED",',
     '    "pass": "SUCCESS",\n    "skipping": "FAILURE",',
     "the skipping bucket is a failure"),
    ("bucket-vocabulary-swap-neutral-and-fail",
     '    "neutral": "NEUTRAL",\n    "fail": "FAILURE",',
     '    "neutral": "FAILURE",\n    "fail": "NEUTRAL",',
     "a failed check becomes green when two bucket classifications are swapped"),
    ("command-error-becomes-empty",
     "and re.fullmatch(r\"no checks reported on the '[^\\r\\n]+' branch\", stderr.strip())):",
     "and stderr.strip()):",
     "any command error at exit 1 can become an allowed zero-check result"),
    ("zero-check-error-ignores-stdout",
     "    if (returncode == 1 and not stdout.strip()",
     "    if (returncode == 1",
     "a failure with actual check data can be treated as zero checks"),
    ("zero-check-error-ignores-exit",
     "    if (returncode == 1 and not stdout.strip()",
     "    if (not stdout.strip()",
     "the zero-check diagnostic is trusted with an unrelated error exit"),
    ("json-rows-deduplicated-by-name",
     '        return [bucket_check(entry) for entry in data]',
     '        return list({entry.get("name"): bucket_check(entry) for entry in data}.values())',
     "structured rows with the same name collapse and a failure can vanish"),
    ("abbreviated-head-matches",
     'verified_head == head and bool(re.fullmatch(r"[0-9a-f]{40}", head))',
     'head.startswith(verified_head)',
     "an abbreviated verified head is accepted"),
    ("ci-clears-head-and-gate-blockers",
     "    facts[\"checks_source\"] = \"json\"",
     "    facts[\"checks_source\"] = \"json\"\n    reasons.clear()",
     "the manual CI decision waives earlier blockers"),
    ("ci-failure-forgiven-by-no-checks-opt-out",
     '    if not checks["pass"]:',
     '    if not checks["pass"] and not allow_no_checks:',
     "the zero-check opt-out waives a reported failure"),
    ("subprocess-cwd-dropped",
     "        proc = gdd_process.run(cmd, cwd=cwd, capture_output=True, text=True)",
     "        proc = gdd_process.run(cmd, cwd=None, capture_output=True, text=True)",
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
     "--allow-no-checks) is trusted as the read instead of reporting an "
     "operator error"),
    ("structured-read-accepts-check-exits-with-stdout",
     "    if returncode == 0:",
     "    if returncode == 0 or (returncode in (1, 8) and stdout):",
     "the structured read's non-zero exit is trusted whenever its stdout parses *and* the exit is "
     "one of the two `gh pr checks` uses for CI state (1 failing, 8 pending); every round-11 "
     "non-zero structured fixture used exit 4, so this narrower shape survived the matrix until "
     "round 12 added a structured exit 1 and 8 carrying a parseable payload"),
    ("structured-read-accepts-signal-exit",
     "    if returncode == 0:",
     "    if returncode <= 0:",
     "the structured read trusts any exit at or below zero, so a signal-terminated read (exit -15) "
     "whose stdout parses is taken as the read instead of reporting an error; the old "
     "structured-exit dimension named no negative exit, so nothing flipped"),
    ("structured-read-accepts-cancellation",
     "    if returncode == 0:",
     "    if returncode in (0, 2):",
     "the structured read trusts exit 2 (gh's cancellation), so a cancelled read whose stdout "
     "parses is taken as the read instead of reporting an error; the old structured-exit "
     "dimension named no exit 2, so nothing flipped"),

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
