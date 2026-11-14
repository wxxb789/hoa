# Uncovered-path register — `pr-merge-check.py`

A work list, not a merge condition. Four consecutive review rounds each found an *unexercised path*
rather than a defect in the increment under review, so this file turns "the next uncovered path"
into an ordered queue an operator can work one entry at a time.

Scope: every reachable path in `skills/gdd/scripts/pr-merge-check.py` (and what it calls in this
repo) that the round-10 increment did not touch and that the artefacts — `test_verdict_matrix.py`
(the 379 cells + the 10-entry golden call log + the mutation catalogue), `test_review_evidence.py`
and `pr-merge-check.py --selftest` — still do not pin. Entries already pinned somewhere say so, so
the queue does not re-litigate covered ground.

Ordering is by consequence: what an untested regression there would do to a *verdict* first, then to
an operator's diagnosis, then to usage. Each entry names the smallest fixture that would pin it; a
`Verdict`/`ShCell`-style cell driven through `main()` is preferred, because the golden call log only
sees what the gate *invokes*, never what it does with the answer.

---

## 1. A GraphQL error payload is treated as an empty thread list

- **Path**: `fetch_review_threads()` — the `if payload.get("errors"): raise GateError(f"graphql: …")`
  branch, and the `or {}` tolerance that reads a payload missing `data.repository.pullRequest` as
  zero threads.
- **Regression consequence (fail-open, worst case)**: a mutant that ignores `errors` reads a failed
  thread read as "no threads" and turns `verdict: BLOCKED: threads` into `MERGE-OK` on a PR with an
  open review thread — the exact fail-open the pagination cells were added to close, one layer down.
- **Smallest fixture**: one verdict cell whose thread fixture serves
  `{"errors": [{"message": "rate limited"}]}` as page 1; expect exit 2 and a one-line
  `pr-merge-check: graphql: …` on stderr (`ERROR` cell with `error_contains`), plus a second cell
  serving `{}` (no data key) to pin the "absent block reads as zero threads, not a crash" rule.
- **Pinned today**: nothing. No test supplies an `errors` payload or a payload without `data`.

## 2. A non-array comment page is treated as no comments

- **Path**: `fetch_issue_comments()` — `if not isinstance(batch, list): raise GateError("gh api
  comments: expected a JSON array")`, and the `json.loads(raw or "[]")` empty-stdout tolerance.
- **Regression consequence (fail-open)**: reading a `gh` object payload (for example
  `{"message": "Bad credentials"}` on stdout with exit 0) as an empty page hides every comment, so
  `evaluate_review()` finds no marker and, under `--allow-no-machine-review`, `BLOCKED: review`
  becomes `MERGE-OK` — the machine-review decision is dropped without a diagnostic.
- **Smallest fixture**: two verdict cells with `comment_pages=[<object>]` and `comment_pages=[[]]`
  plus an empty-string page; expect exit 2 naming the array for the object, and the ordinary
  "marker unknown" block for the empty one.
- **Pinned today**: nothing. The paginated cells added in round 10 use well-formed arrays only.

## 3. `main()`'s `--json` output contract

- **Path**: `main()` — `if args.json: print(json.dumps(facts, indent=2, ensure_ascii=False))`,
  including the `verdict` / `reasons` keys it injects.
- **Regression consequence (diagnosis)**: the only machine-readable output of the gate is one
  `json.dumps` call no test reads; a renamed or dropped key silently breaks every downstream
  consumer (a CI job reading `.verdict`) while the human path stays green.
- **Smallest fixture**: one cell driven with `--json` that asserts the parsed object's `verdict`,
  `reasons`, and the presence of `pr_state`, `head`, `checks`, `review`, `threads`, `gates` — the
  keys the human path prints.
- **Pinned today**: nothing. Every cell parses the human lines; the `--json` flag is only named in
  the gate's own usage docstring and `references/phases/06-merge.md`.

## 4. A page that claims more threads but returns no cursor

- **Path**: `fetch_review_threads()` — the `if not page.get("hasNextPage") or not cursor: return
  nodes` guard, specifically the `not cursor` half.
- **Regression consequence (hang, then operator error)**: a truncated page with
  `hasNextPage: true, endCursor: null` is the one response with no advancing cursor. Dropping the
  `not cursor` half re-requests the same page forever — the gate never returns, so a CI job blocks
  until its own timeout instead of printing a verdict.
- **Smallest fixture**: a thread fixture whose page 1 is `([], True, None)` and a call-counting
  fake that raises after a bounded number of graphql calls; expect the gate to return the page-1
  rows (exit 1 with `BLOCKED: threads` when page 1 carries an unresolved thread).
- **Pinned today**: nothing. Every fixture either ends the thread list or advances the cursor.

## 5. `main()`'s usage exits

- **Path**: `main()` — `if not args.pr: return 2` ("PR number is required") and the
  `if not str(args.pr).isdigit(): return 2` branch.
- **Regression consequence (operator contract)**: the documented exit-2 contract for a usage error
  is unobserved; a mutant that returns 1, or prints a verdict for an absent PR, is invisible — and
  a CI wrapper that distinguishes 2 from 1 would read a usage error as a blocked merge.
- **Smallest fixture**: two subprocess-free cells patch `sys.argv` to `["pr-merge-check.py"]` and
  `["pr-merge-check.py", "abc"]`, asserting exit 2, empty stdout and the one-line stderr message.
- **Pinned today**: nothing calls `main()` without a numeric PR.

## 6. The human lines other than `checks:` and `verdict:`

- **Path**: `print_human()` — the `head:`, `review:`, `threads:`, `gates:` and `state:` lines and
  the `note=` suffix from `--gates-note`.
- **Regression consequence (diagnosis)**: `check_cell()` compares only the `verdict: ` and
  `checks: ` lines, so a mutant that drops the `review:` line, mislabels `head_match`, or omits the
  operator's `--gates-note` still passes every cell while the report an operator reads at merge time
  loses the provenance the gate exists to print.
- **Smallest fixture**: extend one existing cell's comparison to the full stdout for a cell with a
  found marker and a `--gates-note`, asserting the `review:` and `gates: … note=…` lines verbatim.
- **Pinned today**: `pr_state_line()` and `head_line()` are pinned by `--selftest` as pure builders;
  the composed `print_human()` output is not.

## 7. A malformed `gh pr view` payload

- **Path**: `evaluate()` — `json.loads(sh(["gh", "pr", "view", …]))` raising `ValueError` on
  non-JSON (caught in `main()` as exit 2), and `view.get("headRefOid") or ""` for a payload that
  parses but omits the head.
- **Regression consequence (verdict)**: an empty head makes `resolve_head()` report
  `head not verified` and block, which is correct; the untested part is that a truncated read
  reaches the exit-2 operator error rather than a traceback, and that a `state` key that is present
  but null reads as `pr not open` rather than open.
- **Smallest fixture**: two cells whose PR-view fixture is `"<html>"` and `{"state": null,
  "isDraft": false, "headRefOid": HEAD, "headRefName": "feature"}`.
- **Pinned today**: `evaluate_pr_state()`'s MERGED/CLOSED/draft values are pinned by `--selftest`;
  the transport-level malformed payloads are not.

## 8. `--gates-note` and `--gates-rc` clauses through the flag surface

- **Path**: `build_parser()` → `evaluate(gates_rc=…, gates_note=…)` and `evaluate_gates()`'s
  `facts["note"]`.
- **Regression consequence (verdict, bounded)**: `evaluate_gates()` is pinned as a pure function by
  `--selftest`, but the flag plumbing from `main()` is not: dropping `args.gates_rc` (so `--gates-rc
  0` no longer counts) would block every merge with `gates missing`; dropping `--gates-note` loses
  the operator's context. The cells all pass `--gates-rc 0 --verified-head HEAD` and the two flags
  are shelled once each.
- **Smallest fixture**: two cells: one with `--gates-rc 0` and no `--verified-head` (expect
  `BLOCKED: verified head missing`), one with `--gates-note "unit suite"` asserting the note on the
  `gates:` line.
- **Pinned today**: the pure `evaluate_gates()` cases only.

## 9. `repo` name without a `/`

- **Path**: `evaluate()` — `owner, _, name = name_with_owner.partition("/")` when `gh repo view`
  returns a bare name.
- **Regression consequence (diagnosis)**: the comment URL becomes `repos/<owner>//issues/<pr>/…`,
  which `gh` rejects; the gate would exit 2 with an opaque gh message instead of naming the malformed
  repository identity.
- **Smallest fixture**: one cell whose `gh repo view` fixture returns `"fixture-repo"` (no slash).
- **Pinned today**: nothing; every fixture returns `fixture-owner/fixture-repo`.

## 10. `evaluate(offline=True)`

- **Path**: `evaluate()`'s `if offline: … return facts, reasons` early exit.
- **Regression consequence (none reachable)**: `main()` never passes `offline`, so the branch is
  unreachable from the CLI and no artefact exercises it. Either it is dead code to delete, or the
  flag it was meant to back must be added before it can be tested.
- **Smallest fixture**: none through `main()` — a decision first (delete the parameter, or add the
  flag), then a cell for it.
- **Pinned today**: nothing, by construction.

---

## How to work an entry

1. Add the fixture to `test_verdict_matrix.py` (a `Cell` with `comment_pages` / `thread_pages`, or a
   new `ShCell`-style probe), driven through `main()` where the entry says so.
2. If the fix changes what the gate *invokes*, update `GOLDEN_CALLS` by hand after reading the gate
   diff — never by pasting the observed set back.
3. Register the corresponding mutation in `mutate_verdict_matrix.py` with an anchor that matches the
   gate source exactly once, and re-run
   `python3 skills/gdd/scripts/tests/test_verdict_matrix.py` and
   `python3 skills/gdd/scripts/tests/mutate_verdict_matrix.py`.
4. Refresh the counts in `CHANGELOG.md` from the matrix's own summary lines.
