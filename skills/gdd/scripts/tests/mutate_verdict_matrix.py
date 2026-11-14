#!/usr/bin/env python3
"""Mutation harness over the verdict matrix.

Every mutation below is a plausible wrong implementation of `pr-merge-check.py`. Each is applied in
memory to the module source (the checkout is never written) and the whole verdict matrix is re-run
against the mutant: at least one cell must flip, or the mutation survived an exhaustive matrix and
the harness fails loudly with the mutation id.

Run: python3 skills/gdd/scripts/tests/mutate_verdict_matrix.py

The catalogue is the twelve mutations from the previous sweep (sh_raw normalising the exit code or
the streams, a dropped non-object row, a non-list payload read as zero checks, the bucket/state
precedence, an unknown bucket or a missing bucket read as ok, pending or the opt-out not blocking, a
name-based header drop, an unrecognized verdict passing, a command error read as zero checks) plus
the five this round's findings named (the all-green non-zero fallback, the recognized-bucket/raw-state
disagreement, a reserved column name dropped as a header, and the missing-bucket default), plus
others the surface implies (a tab-less line parsed as a row, the header parsed as a check, the cancel
and skipping bucket mappings, and the zero-check opt-out granted unconditionally).
"""

from __future__ import annotations

import sys
import time
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import test_verdict_matrix as matrix  # noqa: E402

GATE_SOURCE_PATH = SCRIPTS / "pr-merge-check.py"
SOURCE = GATE_SOURCE_PATH.read_text(encoding="utf-8")


# --- the mutation catalogue -------------------------------------------------
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
            return [bucket_check(entry) for entry in data]""",
     "            return [bucket_check(entry) for entry in data if isinstance(entry, dict)]",
     "a non-object row is dropped instead of raising"),
    ("json-nonlist-becomes-empty",
     "        if isinstance(data, list):",
     """        if not isinstance(data, list):
            return []
        if isinstance(data, list):""",
     "a non-list payload is read as zero checks"),
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
    ("header-accepts-status-first-field",
     """        and {"NAME", "STATUS"} <= set(fields)
        and set(fields) <= TEXT_CHECK_COLUMNS
    )""",
     """        and {"NAME", "STATUS"} <= set(fields)
        and set(fields) <= TEXT_CHECK_COLUMNS
    ) or (bool(fields) and fields[0] == "STATUS")""",
     "a check named STATUS is dropped as a header"),
    ("header-prefix-match",
     """    return (
        len(fields) >= 2
        and {"NAME", "STATUS"} <= set(fields)
        and set(fields) <= TEXT_CHECK_COLUMNS
    )""",
     """    return line.upper().startswith("NAME") or (
        len(fields) >= 2
        and {"NAME", "STATUS"} <= set(fields)
        and set(fields) <= TEXT_CHECK_COLUMNS
    )""",
     "a NAME-prefixed row is dropped as a header"),
    ("tabless-line-becomes-a-row",
     '        if not line or "\\t" not in line or is_text_check_header(line):',
     "        if not line or is_text_check_header(line):",
     "a truncated line is parsed as a pending check"),
    ("header-parsed-as-a-check",
     '        if not line or "\\t" not in line or is_text_check_header(line):',
     '        if not line or "\\t" not in line:',
     "the header row is parsed as a check"),
    ("unknown-verdict-passes",
     '        conclusion = TEXT_CONCLUSIONS.get(verdict, "FAILURE")',
     '        conclusion = TEXT_CONCLUSIONS.get(verdict, "SUCCESS")',
     "an unrecognized table verdict is ok"),
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
    ("command-error-becomes-empty",
     """            if "no checks reported" in lowered or "no check runs found" in lowered:
                return []
            raise GateError(message.splitlines()[0] if message else f"exit {returncode}")""",
     """            if "no checks reported" in lowered or "no check runs found" in lowered:
                return []
            return []""",
     "an unparseable command error becomes zero checks"),
    ("all-green-nonzero-returns",
     """        if evaluate_checks(checks)["pass"]:
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
]


def load_mutated(source):
    module = types.ModuleType("pr_merge_check_mutant")
    module.__file__ = str(GATE_SOURCE_PATH)
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module


def main():
    start = time.monotonic()
    gate = matrix.load_gate()
    baseline = matrix.evaluate(gate)
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
        flipped = [cell_id for cell_id, problem in matrix.evaluate(mutant) if problem is not None]
        if not flipped:
            print("  SURVIVOR  %s (%s): no matrix cell flipped" % (mutation_id, note))
            survivors.append(mutation_id)
        else:
            print("  caught    %s (%s): %d cell(s), first %s"
                  % (mutation_id, note, len(flipped), flipped[0]))

    elapsed = time.monotonic() - start
    cells = len(matrix.CELLS) + len(matrix.STREAM_CELLS)
    print("mutation-harness: %d mutations over %d cells, %d survived, %.2fs"
          % (len(MUTATIONS), cells, len(survivors), elapsed))
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
