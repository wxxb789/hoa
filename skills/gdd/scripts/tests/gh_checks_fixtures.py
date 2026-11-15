"""Captured `gh pr checks` output, so the verdict matrix reads the tool's vocabulary, not memory.

Two surfaces report a check verdict and the merge gate reads both:

* `gh pr checks --json name,state,bucket`, where `bucket` is the per-check verdict gh still reports
  (`conclusion` was removed in gh 2.103), and
* the non-TTY table, whose STATUS column prints that same bucket word — except that gh prints a
  `cancel` bucket as `fail` (`pkg/cmd/pr/checks/output.go`, `addRow`).

The captures below were taken with gh 2.103.3 on 2026-11-15 from three live open PRs: one whose only
check was still running (the table exits 8 while a check is pending), one with a failing check
(exit 1), and one whose run had finished (exit 0). Check names are as gh printed them; URL hosts and
paths are normalized (`https://example/...`). Every other byte — above all every verdict word — is
the captured output, which is what `tests/test_verdict_matrix.py` classifies.

`STATE_VOCABULARY` and `STATE_BUCKETS` are the bucket derivation from gh 2.103.3
`pkg/cmd/pr/checks/aggregate.go` (````switch state { ... }````, default branch: everything not named
there is pending). They are the reference for the raw `state` values gh prints beside the bucket, and
the matrix generates its bucket x state dimension from them. The gate itself never reads the raw
state: the bucket is the verdict.
"""

PENDING = {
    # A run in flight: the table exits 8, and gh's `--json` still prints the row as data.
    "table": "build\tpending\t0\thttps://example/1/job/1\t\n",
    "table_rc": 8,
    "json": '[{"bucket":"pending","name":"build","state":"IN_PROGRESS"}]',
    "json_rc": 0,
}

FAILING = {
    "table": ("verify\tfail\t4m9s\thttps://example/2/job/2\t\n"
              "foreign-notes\tpass\t20s\thttps://example/2/job/3\t\n"
              "shallow-clone-refusal\tpass\t8s\thttps://example/2/job/4\t\n"),
    "table_rc": 1,
    "json": ('[{"bucket":"fail","name":"verify","state":"FAILURE"},'
             '{"bucket":"pass","name":"foreign-notes","state":"SUCCESS"},'
             '{"bucket":"pass","name":"shallow-clone-refusal","state":"SUCCESS"}]'),
    "json_rc": 0,
}

FINISHED = {
    "table": ("Docker image\tpass\t20s\thttps://example/3/job/5\t\n"
              "Node Current compatibility\tpass\t23s\thttps://example/3/job/6\t\n"
              "Windows Bun 1.4 compatibility\tpass\t3m11s\thttps://example/3/job/7\t\n"
              "build\tpass\t24s\thttps://example/3/job/8\t\n"
              "lint\tpass\t29s\thttps://example/3/job/9\t\n"
              "test\tpass\t31s\thttps://example/3/job/10\t\n"
              "typecheck\tpass\t25s\thttps://example/3/job/11\t\n"),
    "table_rc": 0,
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
