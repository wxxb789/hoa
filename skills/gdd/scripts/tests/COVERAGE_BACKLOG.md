# Uncovered-path register — `pr-merge-check.py`

A work list, not a merge condition. Four consecutive review rounds each found an *unexercised path*
rather than a defect in the increment under review, so this file turns "the next uncovered path"
into an ordered queue an operator can work one entry at a time.

Scope: every reachable path in `skills/gdd/scripts/pr-merge-check.py` (and what it calls in this
repo) that the round-10 increment did not touch and that the artefacts — `test_verdict_matrix.py`
(the 397 cells + the 10-entry golden call log + the mutation catalogue), `test_review_evidence.py`
and `pr-merge-check.py --selftest` — still do not pin. Entries already pinned somewhere say so, so
the queue does not re-litigate covered ground; a gap that was found and closed is kept under
*Closed* below, so this file stays the single record of each class rather than only of what is
still open.

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

## Closed — round 15 F2: the table opt-in beside a blocker judged elsewhere

- **Path**: `evaluate()` — the `if not review["pass"]:` and `if unresolved:` clauses, which run
  *after* the checks read. `--allow-table-only-checks` decides only whether the table read is
  authoritative; it says nothing about the machine-review marker or the review threads.
- **The gap**: every cell that enabled the opt-in beside blocking evidence paired it with a blocking
  *checks* read, so a mutant that skipped those clauses when the opt-in was set survived the whole
  matrix. Two of them did: `if not review["pass"] and not allow_table_only_checks:` and
  `if unresolved and not allow_table_only_checks:` each reported MERGE-OK over a green exit-0
  fallback table where the shipped gate blocks with `review` / `threads`.
- **Now pinned**: `rule-table-opt-in-does-not-waive-review` and
  `rule-table-opt-in-does-not-waive-threads` — the opt-in plus a green exit-0 fallback table beside
  the blocking marker on comment page 2 and the unresolved thread on page 2 — with the mutations
  `opt-in-drops-blocking-review` and `opt-in-drops-unresolved-threads` registered in
  `mutate_verdict_matrix.py`.

---

## Closed — round 16 F1: the ignored-line report is pinned to the whole list

- **Path**: `report_ignored_table_lines()` — the `for line in lines:` loop, one stderr diagnostic
  per ignored tab-less line, and the two cells that drive a truncated table through `main()`.
- **The gap**: both cells used a one-line fixture and asserted the diagnostic as substrings
  ("carries … 'required'"), so narrowing the report to `lines[:1]` — or de-duplicating the list —
  survived the whole matrix, the golden call log, the evidence tests and the selftest. The
  reviewer's reproduction: fallback `(0, "build\tpass\nrequired-a\nrequired-b\n", "")` with
  `--allow-table-only-checks` prints two diagnostics under the shipped gate and one under the
  mutant, both MERGE-OK with tally `1/1/0/0`, so the second truncated row was swallowed silently.
- **Now pinned** (strengthened in round 17, below): `TRUNCATED_TABLE` carries four ignored tab-less
  lines — three distinct, one repeated, in a non-palindromic order — and both cells (the opt-in path
  and the default path) assert the **exact stderr line list**: every expected line, in order,
  repeats included, and no other line beside them (a non-ERROR cell that names none must print
  none). A report that stops at the first line fails on the missing lines and a de-duplicating one
  fails on the repeat. The mutation `ignored-line-diagnostic-truncated-to-the-first` is registered
  and is caught by these two cells, since each one's expected list holds all four lines.

---

## Closed — round 17 C1 + F2: the ignored-line diagnostic surface, systematically

- **Path**: `report_ignored_table_lines()` — the reporting loop, its per-line diagnostic and its
  opt-in clause — `ignored_table_lines()`, the collector that feeds it, and the exact-list stderr
  comparison in `test_verdict_matrix.py` that pins them.
- **C1 (the recorded finding)**: the round-16 fixture's ignored-line sequence, `required-a,
  required-b, required-a`, is a palindrome, so `for line in reversed(lines):` reproduced the
  expected list exactly and survived all 397 cells, the golden call log, the 94 evidence tests and
  the 68 selftest fixtures — a `main()` probe printed `a,b` vs `b,a` with the same MERGE-OK and
  tally `1/1/0/0`. **Fixed**: the fixture is now `required-a, required-b, required-a, required-c`
  — non-palindromic, the repeat kept — both cells assert the exact four-line list, and the reversal
  mutation is registered and caught.
- **F2 (the systematic pass)**: the whole surface is enumerated as eight properties, each proved by
  one in-memory mutation of the gate, run through the matrix; the comparison itself is test-side,
  so it is pinned by a guard instead. Every registered mutation is caught (the harness exits 0).

  | Property | Mutation / guard | Caught by |
  |---|---|---|
  | Completeness — truncating the report to the first line | `ignored-line-diagnostic-truncated-to-the-first` (`lines[:1]`, round 16) | both truncated cells (four-line lists) |
  | Ordering — reversed iteration | `ignored-line-diagnostic-reversed` (`reversed(lines)`) | both truncated cells (non-palindromic list) |
  | Duplicates — de-duplicating | `ignored-line-diagnostic-deduplicated` (`dict.fromkeys(lines)`) | both truncated cells (repeat present) |
  | Exactness — an extra line no cell expects | `ignored-line-diagnostic-extra-note` (a note printed per ignored line) | both truncated cells (the exact list has no note) |
  | No false positives — reporting a line that was not ignored | `ignored-lines-include-recognised-rows` (the collector drops the tab test, so valid rows and the exact header are reported) | 116 cells in all (first flip `json-nonlist-green-table`), the two truncated cells among them — the valid data row of the fixture is reported |
  | Both paths — the default read as well as the opt-in | `ignored-line-diagnostic-only-under-the-opt-in` (the report gated on the flag) | the default-path cell (its ignored lines go unnamed) |
  | Both paths — the opt-in's own wording | `ignored-line-opt-in-warning-dropped` (the "could conceal a check" clause removed) | the opt-in-path cell (its exact list pins the clause) |
  | Silence when clean — a clean read asserts empty stderr | `ignored-line-diagnostic-prints-when-clean` (a line printed when nothing was ignored) | 124 cells in all (first flip `json-nonlist-empty-table`), each expecting no stderr — the empty-list expectation is the load bearing assertion, and property 8 keeps it exact |
  | The comparator itself — exact equality, not subset/set | `comparator_self_check()` in `test_verdict_matrix.py`; the comparison is factored into `stderr_problems()` | the matrix's own `main()`: weakening `stderr_problems()` in memory to set equality leaves 4 guard problems (the de-duplicated and re-ordered witnesses accepted), to containment 6 (plus the extra-line witness); a fixture that loses its repeat or becomes a palindrome is named by the same guard (one problem each) |

  The guard is the reason a *fourth* variant is no longer silent: `reversed(lines)` and
  `dict.fromkeys(lines)` are ordinary rewrites of the loop, and the property they violate lives in
  the cell assertion, not the gate — the guard tests the assertion mechanism itself, on the
  witnesses, so the comparison cannot be weakened and the fixture cannot stop discriminating
  without a named failure.

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
4. A cell that pins a stderr line list must carry a repeat and must not be a palindrome
   (`comparator_self_check()` fails by name otherwise): a list that `dict.fromkeys()` or
   `reversed()` reproduces cannot pin de-duplication or order against a rewrite.
5. Refresh the counts in `CHANGELOG.md` from the matrix's own summary lines.
