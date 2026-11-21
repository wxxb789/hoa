"""Captured `gh pr checks` output, so the verdict matrix reads the tool's vocabulary, not memory.

The structured captures below come from gh 2.103.3 on 2026-11-15, from an
in-flight, a failing, and a finished PR. GitHub CLI returns exit 0 for each
JSON result; the exported buckets carry the verdicts.

`STATE_VOCABULARY` and `STATE_BUCKETS` are the bucket derivation from gh 2.103.3
`pkg/cmd/pr/checks/aggregate.go` (````switch state { ... }````, default branch: everything not named
there is pending). They are the reference for the raw `state` values gh prints beside the bucket, and
the matrix generates its bucket x state dimension from them. The gate itself never reads the raw
state: the bucket is the verdict.
"""

PENDING = {
    "json": '[{"bucket":"pending","name":"build","state":"IN_PROGRESS"}]',
    "json_rc": 0,
}

FAILING = {
    "json": ('[{"bucket":"fail","name":"verify","state":"FAILURE"},'
             '{"bucket":"pass","name":"foreign-notes","state":"SUCCESS"},'
             '{"bucket":"pass","name":"shallow-clone-refusal","state":"SUCCESS"}]'),
    "json_rc": 0,
}

FINISHED = {
    "json": ('[{"bucket":"pass","name":"build","state":"SUCCESS"},'
             '{"bucket":"pass","name":"Windows Bun 1.4 compatibility","state":"SUCCESS"},'
             '{"bucket":"pass","name":"lint","state":"SUCCESS"},'
             '{"bucket":"pass","name":"typecheck","state":"SUCCESS"},'
             '{"bucket":"pass","name":"test","state":"SUCCESS"},'
             '{"bucket":"pass","name":"Node Current compatibility","state":"SUCCESS"},'
             '{"bucket":"pass","name":"Docker image","state":"SUCCESS"}]'),
    "json_rc": 0,
}

# Named so a failure says which live capture drifted.
CAPTURES = {"pending": PENDING, "failing": FAILING, "finished": FINISHED}

# Every raw `state` gh can print on a check run (gh 2.103.3 pkg/cmd/pr/checks/aggregate.go).
STATE_VOCABULARY = (
    "SUCCESS",
    "SKIPPED",
    "NEUTRAL",
    "ERROR",
    "FAILURE",
    "TIMED_OUT",
    "ACTION_REQUIRED",
    "CANCELLED",
    "EXPECTED",
    "REQUESTED",
    "WAITING",
    "QUEUED",
    "PENDING",
    "IN_PROGRESS",
    "STALE",
)

# The same switch, read as state -> bucket: what these states are grouped into.
STATE_BUCKETS = {
    "SUCCESS": "pass",
    "SKIPPED": "skipping",
    "NEUTRAL": "skipping",
    "ERROR": "fail",
    "FAILURE": "fail",
    "TIMED_OUT": "fail",
    "ACTION_REQUIRED": "fail",
    "CANCELLED": "cancel",
    "EXPECTED": "pending",
    "REQUESTED": "pending",
    "WAITING": "pending",
    "QUEUED": "pending",
    "PENDING": "pending",
    "IN_PROGRESS": "pending",
    "STALE": "pending",
}
