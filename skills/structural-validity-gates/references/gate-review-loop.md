# Iterating a validity gate against an external reviewer

A byte-walking gate gets contradicted from both sides, and an automated reviewer is good at finding
the side you did not probe. This is the loop that converges without wasting agent rounds.

## Every round is a claim until you hold the bytes

Build the probe yourself for each reported case — a throwaway test file **inside** the repo (module
deps only resolve there), run under the repo's own runner with `--reporter=verbose` so `console.log`
reaches stdout:

```ts
// tests/.operator-probe.test.ts — deleted after the run
for (const cut of [0, floor(len * 0.1), floor(len * 0.5)]) {
  const part = bytes.subarray(0, len - cut);
  try { assertCompleteContainer(fmt, part); console.log(cut, 'ACCEPTED'); }
  catch (e) { console.log(cut, 'REJECTED:', (e as Error).message); }
}
```

Delete it before committing: a leftover probe shows up as an untracked file in the next tree check.
Node's `--experimental-strip-types` on a `.mjs` file is not a substitute — TS syntax such as `as const`
fails to parse, and the shell's `node` may be a different major than the project's.

**A probe is a program, and it can be the thing that is wrong.** Four rules, each learned by being
lied to:

- **Call the real exported signature.** A wrapper that takes `(bytes, format, limits)` fed a single
  options object returns the gate's *unparseable-input* verdict — `corrupt` — for a file you believe is
  valid. Re-read the signature in the source before trusting any rejection the probe produces.
- **Put a known-good positive control in the same run, and assert it passes.** Some case you already
  know succeeds (`100x16000` under a `16,383` bound, an intact fixture). If the control fails too, the
  probe is broken and every line in the table is noise. A table where every row says `REJECTED` is a
  symptom of the harness, not of the gate.
- **A probe that violates an unrelated invariant reports a defect that is not there.** A fixture whose
  referenced definition is fully transparent gets refused as "empty drawing"; a fixture whose
  type-selector rule also matches the children of the very container it references produces a genuine
  reference cycle. Both are the fixture's fault. Scope the fixture to what the case under test needs
  (a class only the consumers carry), and when the verdict names an invariant you were not testing,
  assume the fixture first.
- **Environment-dependent behaviour needs a child process.** A module-level cache (font discovery,
  path resolution, config load) is computed once per process, so setting the environment variable and
  calling the function again in the same run proves nothing. Assert those cases in a fresh process
  with the variable set in its environment, and compare against the same assertion without it.

**Reproduce a performance or complexity claim on the branch that actually runs it.** Read the guard
around the pass before concluding the claim is false: work that only executes when a document contains
a particular element (a `<use>`, an uploaded asset, a nested container) measures as instant when the
probe omits it. A sub-millisecond reading against a reported multi-second claim is far more often a
skipped branch than a bad reviewer. Then measure a **curve**, not a point — three sizes at least:
backtracking path counts depend on the relationship between depth and step count, so a size where the
number of combinations happens to be 1 reads flat while a nearby size explodes (single-digit
milliseconds one step up, tens of seconds a few levels down).

## The gate's own work is inside the budget

A gate that claims to bound a decoder's work must bound its own. Every pass you add to it — expansion
counting, per-consumer attribution, uniqueness checks, selector or schema matching — runs synchronously
in the same call, before any deadline, on input the attacker chooses. Two rules:

- **Any traversal that can revisit a state must memoise the state.** Matching a compound selector right
  to left and recursing over *every* ancestor is `C(depth, steps)` on a chain that is legal under the
  policy's own depth limit: measured inside one synchronous inspection call, 32 levels and 8 steps cost
  under a second, 40 levels and 10 steps cost about a minute, and each document was **accepted** while
  it ran. Memoise `(step, node)` → result, or compute the match set iteratively per step, so one rule
  costs `O(steps × elements)`; then state the complexity in the code comment, because the next person
  adding a selector form inherits it.
- **A work bound that is not a deadline is not a bound.** If a future construct could exceed the
  polynomial algorithm, add a work counter that converts exhaustion into a named refusal instead of a
  hang. Whatever you choose, a stall inside the gate is indistinguishable from a hung build.

Pin it with a regression that would fail loudly rather than flakily: a deep, non-matching case that
must finish well inside a generous ceiling, plus a matching case at the same depth asserting the count
is unchanged. Say the ceiling you picked and that a stall fails it, so nobody tunes the test to the
machine.

## Counting from parsed input

A bound you compute by dividing a token count breaks the moment the grammar lets several values share
one token. Three rules, all on the same axis:

- **Bound by the minimum tokens one instance can occupy, not by the nominal arity.** SVG arc flags are
  single characters, so `A10 10 0 0110 10` is `rx ry rot flag flag x y` written in fewer tokens than
  seven; dividing a group's numbers by the full arity counts three arcs where four render, and the
  under-count is exactly what lets an over-budget document through. Ask what the *fewest* tokens an
  instance can take (three for an arc: `rx ry rot`), then bound with `ceil(tokens / minimum)` and add
  one vertex per instance. Enumerate which letters/fields can pack — usually flags and one-character
  enums — and keep the exact division for the rest.
- **Unparseable input raises the estimate; it never falls back to one.** A lexer that cannot classify a
  character, a missing attribute, a rejected token: the fallback is the most pessimistic count the data
  could represent (every numeric token a vertex, every subpath a placement), because the only
  unacceptable direction is under-counting. Say so in the code comment, since the safe-looking
  `return 1` is the bug.
- **Assert the bound against the true count, not against a sibling spelling.** Two spellings of the same
  document carry different token counts and therefore different bounds, so "compact ≥ spaced" is a
  false invariant that fails on correct code — the honest comparison is `counted ≥ placements ×
  expansion` for the number of placements you can enumerate by hand. Pin the true count in the test
  and assert monotonic growth across three sizes; that catches both a regression and a bound that
  silently stopped tracking the input.

## Three verdict shapes that look like new findings

- **`has_any_findings: true` with no new inline comment.** The machine-review marker describes the
  full report, not the thread count. Read that exact report first: a headless reviewer may post no
  inline comments at all. Reproduce each finding, record its disposition, and request a new complete
  review after fixes or justified dismissals. Separately list threads with `isResolved` + `createdAt`;
  old threads need a reply with the fixing SHA and measured table, then resolution. Editing code to
  close a stale thread buys a round and leaves the same thread open.
- **A verbatim duplicate of an answered finding**, typically carrying a link to an older commit: the
  reviewer re-anchored an old thread onto the new head. Re-run your probe on the current head; if the
  case passes, answer with the table, name the fixing commit, resolve — do not dispatch.
- **A regression your own gate introduced**, reported as a new defect. That is a real finding even when
  it embarrasses the previous round: a stricter walker rejecting a legal construction is the failure
  mode of this class, not a nitpick. Fix the walker, not the fixture.

## Where the gate's module boundary has to be

A pure byte walker never needs the codec. Keep it in the module that identifies formats and import the
encoder/decoder lazily at the boundary that actually processes pixels (`import type` for erased types,
`await import()` inside the processing path). A module-scope native import re-breaks every path that
loads the module on a host whose binaries target another platform — including metadata-only discovery
and the cross-platform comparison test that exists to catch exactly this.

Prove it rather than assert it: a loader hook counting real module evaluations over a corpus with no
referenced media must report the codec as **not** loaded, with a positive control showing the hook
would have seen it.

## When the gate reads source code, the parser is the sweep

A gate that finds a property in a language's source — a platform-bound path literal, a banned import, a
magic constant — attracts one review finding per lexical escape for as long as a human writes the
lexer. The ladder, and what each rung costs:

1. **Regex over lines.** Fails on the other quote form first, then on anything spanning lines.
2. **Hand-written lexer with state.** Answers the quoted/raw-string round, then the escape-decoding
   round (`\\` collapsed before `\t` turns a Windows path into a control character), then the
   block-comment round, then a line starting with `*` read as a doc comment instead of `*p = …`, then a
   multi-line raw string that leaves comment syntax live, then a rune literal holding the delimiter.
   Each fix is five lines and each round is a CI cycle plus a review cycle.
3. **The language's own parser.** `go/parser` + `ast.Inspect` for `*ast.BasicLit` of kind
   `token.STRING`, `strconv.Unquote` for the value, positions from the `FileSet`; comments, runes,
   escapes and multi-line strings stop existing as a problem. Deleting the lexer is the fix, and the
   self-test cases that pinned each escape stay as regression pins for free.

**Escalate on the second same-class finding, not the fifth.** When round N's finding is another
spelling of the round N−1 finding, the next dispatch replaces the mechanism instead of patching the
case, and the reply says so. Hand the parser tool a file list on stdin and have it exit non-zero with
`file:line: value` so the surrounding harness stays a thin wrapper; the parser tool itself will need
the same exception marker as the fixtures (its own rule table is data, not a violation).

**A parser-based scan needs a positive and a negative fixture per lexical form**, not per bug report:
quoted, raw, multi-line raw, rune, comment prose, pointer assignment — each one asserted to be reported
or ignored as intended. That matrix is what makes deleting the lexer safe, and it is cheaper than five
rounds of fixing it.

## Past the fix-round cap

One further round is defensible when the new finding is the **same defect class** and cheap (one
function, one test): dispatch it as a single named round with a time cap and disclose the bound and the
reason to the operator in the same message. Anything wider is a decision, not an automatic round.

**Two further rounds of one class means the class is the deliverable, not the instances.** Producing a
third instance of "the gate is stricter than the format" turns the loop into whack-a-mole against a
reviewer that will keep finding legal-but-rare constructs. At that point stop patching the reported
case and sweep: walk the format's self-description and enumerate what the validator and the encoder
refuse to represent — every scan layout, every container the data may live in, every dimension/pixel
bound in the codec headers, every optional chunk and version byte — then fix all of them in one
dispatch with a matrix test over the enumeration (`references/format-constructs.md`). Report the sweep
as one round with its own table; do not let the reviewer's next pass define the scope a fourth time.

**When the model is a graph, the enumeration is the edge inventory plus the property rules.** A gate
that mirrors another implementation's semantics — a renderer, a resolver, a decoder, a CSS cascade —
leaks one edge kind per round: attributes first, then template references, then properties inherited
from an ancestor, then the same property arriving through a stylesheet. Before the next dispatch write
the table: every construct that can carry an edge, every property that can supply one, and for each
whether it is followed, inherited or refused, with the reason. Require that table in the fix prompt and
keep it beside the constant it documents. A reviewer finding an edge missing from the table is a defect
in the table, not a new case to patch.

**The inventory has two axes: edges and multipliers.** An edge that is followed is not yet counted —
the count is `expansion × placements`, and every mechanism that renders one reference more than once
is its own multiplier: one container per consumer, one inherited declaration per painted descendant,
one rule per matched element, one marker per interior vertex, one placement per subpath for the
start/end slots. Each multiplier needs a bound derived from the carrier's own data, not a constant:
per-vertex counts come from the geometry (`d`/`points` tokens, subpath count, a closepath adding the
initial point back as a vertex), and the bound must be at least the honest count for every legal
spelling — the minimum tokens one placement can occupy, not the nominal arity. When the carrier has
no data to read, the bound is the pessimistic one; `1` is the bug this class produces. Enumerate the
multiplier beside each edge in the table, so a reviewer's next find is "the table is short a row"
rather than "here is another bypass".

**A rule that decides override is a whitelist, not a validity parser.** Whether a declaration
*suppresses* an inherited reference cannot be answered by "the value parsed": a renderer ignores a
parseable-but-invalid paint and keeps the inherited one, so treating every non-deferring declaration as
an override silently drops multiplicity. Decide suppression positively — a short list of values that
provably paint no resource (the keywords for no paint, a hex or named colour the parser resolves, a
literal colour function with literal arguments) — and keep the ancestor reference for everything else:
`url()`, a bare resource name, an escaped keyword, a colour function wrapping `calc()`/`var()`, system
colours, unknown functions, unparseable values. Over-counting is the safe direction, and a whitelist
needs no paint grammar or colour database. Mirror case: a property that does not inherit can still be
given explicitly, so explicit `inherit`/`unset`/`revert` on a non-inherited reference property is its
own edge — refuse it as unsupported, naming the property, instead of making the property inherited.

**When the repeated findings are all inside one capability you added, plan to delete the capability.**
The signal is that each round's defect is in the same sub-feature (per-consumer attribution, a new
selector form, a new container type) while the rest of the gate stays quiet. Tell the operator the
fallback in the same message as the fix dispatch — "if the next round is also in this feature, the
feature goes: refuse that construct outright and keep the simpler contract" — so the third round is a
decision already made, not a surprise. Refusing a construct is cheaper and safer than owning an
attribution algorithm, and it keeps the accepted-subset narrowing visible in the docs.

## When a sibling increment merges mid-loop

Another goal landing on `main` while this PR is in review means a rebase before merge — and the rebase
moves the *fixture baseline*, not just the diff. A sibling that adds an emitted asset, a rasterized
image or a rendered element changes counts downstream, so a packaged smoke or gate script carrying
literals (`7 referenced`, `9 images`, `7 objects`) fails on a tree that is correct: the branch is stale,
not broken.

- Re-run the packaged smoke after the rebase and re-derive every literal from its output. Say in the PR
  that the assertion followed the fixture rather than being relaxed; the reviewer will otherwise read the
  changed constant as a weakened gate.
- A branch that adds a dependency conflicts in the lockfile. Resolve `package.json` as the union of both
  sides, then let the manager regenerate (`pnpm install --lockfile-only`), never a hand-merge of lock
  entries, and commit the regenerated lock so the frozen install in CI matches.
- Re-run the whole suite after the rebase and restate the baseline: the sibling's tests are new to this
  branch, so the old count is no longer the reference (`main` 98 files / 1,214 passed → branch 100 /
  1,248). A count that did not rise by the increment's own test count is the first thing to check.

## Posting, answering, closing

- **Write the poller as a file, not as `python3 -c` in a shell loop.** Nested quotes around an f-string
  inside a heredoc die as `SyntaxError: unexpected character after line continuation`, and the
  background job then sleeps through its entire budget printing nothing while the review sits finished.
  Keep `poll_round.py` in the task dir, append one timestamped line per poll with `status` and sha, and
  read that log once after launch: a log with one line and no growth is a broken poller, not "still
  waiting".
- **Run an explicitly model-pinned reviewer through the configured provider.** Use a headless adapter
  such as `pi -p --provider <selected-provider> --model <selected-model> @<prompt-file> @<diff-file>`.
  The project profile supplies those identifiers, not this protocol. GPT-family endpoints require
  the configured Responses API route, not Chat Completions. Do not change runtime settings, log in,
  start services, or substitute another model when that route fails. Capture the actual complete
  report and exit result; a failed run is a blocker, not review evidence.
- **Generate and post the evidence from a file.** GDD's `review-evidence.py` embeds the exact UTF-8
  report and SHA256 under `machine-review-state:v1`, with explicit full head, model, provider, and
  findings flags. Post via `gh pr comment <n> --body-file <comment-file>`, retain the returned id,
  and read back that exact comment body. `pr-merge-check.py` requires completed, clean evidence on
  the exact full 40-hex current head with a matching report digest; custom markers use the same
  schema, and malformed newest evidence cannot fall back to an older clean comment. Recheck the
  head before/after review, after readback, and before merge. See
  [`gdd/references/bot-review-loop.md`](../../gdd/references/bot-review-loop.md) for the complete
  reference commands and finding-disposition contract. The hash binds report bytes, not reviewer
  identity or the truth of the verdict; keep the invocation provenance too.
- **Reply, resolve, then read back the exact thread and paginated count.** A thread resolved with "done" is
  indistinguishable from one closed to satisfy the gate, so the reply carries the fixing sha and the
  measured table:

  ```bash
  gh api graphql -f query='mutation{addPullRequestReviewThreadReply(
    input:{pullRequestReviewThreadId:"<thread-id>", body:"Fixed in <full-sha>: <table>"}){comment{id body}}}'
  gh api graphql -f query='mutation{resolveReviewThread(input:{threadId:"<thread-id>"}){thread{isResolved}}}'
  gh api graphql -f query='query{node(id:"<thread-id>"){... on PullRequestReviewThread{
    id isResolved comments(last:1){nodes{id body}}}}}'
  ```

  The id is opaque, not the numeric comment id; a `null` back means a wrong id. Verify the expected
  reply and `isResolved: true`, then let the merge gate recount all pages of review threads.
- **A clean verdict is not a closed PR.** `has_any_findings: false` still ships with open threads, and
  the merge gate counts them — resolve every thread you answered before reading the verdict as final,
  because the next round otherwise re-reports work you already landed.

## Two reads that look authoritative and are not

- **A settled `gh pr checks` in the seconds after a push can be the previous run's verdicts.** The
  command lists the checks it knows about, and the newly queued run is not among them yet — so a
  watcher reports green (or fires the review request) about a head whose CI has not started. Bind the
  green decision to both facts in the same read: `gh pr view <n> --json headRefOid` equals the sha you
  pushed, and no line contains `pending|queued|in_progress`. Re-poll instead of trusting the first
  settled output.
- **Thread state is not report evidence.** A completed report with `has_any_findings: true` blocks
  even if every thread is resolved; a clean report does not close threads. Read the full report and
  enumerate `reviewThreads(first:100,after:$cursor)` with `pageInfo` until every page is read. Split
  "thread older than my review request" (re-probe, reply with the fixing SHA and measured table,
  then resolve) from "new report finding" (reproduce and disposition before re-review). An older
  linked commit can be pre-fix text re-anchored; never dispatch it without probing the current head.

## Reporting the table

Keep one table per round: case, bytes, `ACCEPTED`/`REJECTED`, reason. It is the reply text when a
finding turns out to be stale, and the regression baseline for the next round. Quote the measured
before/after in the commit message too — "the gate was stricter than the format" is only credible next
to the two byte counts.

**Quote only numbers your own run printed.** The fixer's answer carries its own gate table, and that is
a claim until the same command has run in your worktree. A commit message is the one place a wrong count
becomes permanent, because it is immutable once pushed: compose the message after the output is in hand
(or generate it from the log), never from the fixer's summary. If a wrong figure already shipped,
correct it in the PR comment with the verified value — do not amend or force-push a published commit to
repair a number, since that rewrites the review range the verdicts were earned against.

**The fixer can also be right about your brief.** When it answers with a measurement against the pinned
dependency that contradicts a number you put in the dispatch — the cap is inclusive, the renderer does
place a marker at a closing point, the nominal arity is not what the grammar allows — the measurement
outranks the brief: re-derive it yourself, accept it into the code, and correct the claim in the next
dispatch, saying what the wrong version would have caused (a false refusal of a legal document, or an
accepted over-budget one). A brief is a hypothesis with a deadline, not evidence.
