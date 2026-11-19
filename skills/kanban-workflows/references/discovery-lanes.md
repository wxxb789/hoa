# Parallel discovery lanes

When the work is "gather evidence from many directions" rather than "make changes", the productive
shape is: **N independent lanes → one verifier → main-thread synthesis**.

- One card per lane, each writing **exactly one distinct output file**, all in a shared
  `--workspace dir:<repo>`. Distinct files are what let many workers share one directory without
  write conflicts — do not rely on locking.
- Put the shared evidence discipline in **one** in-repo guide file (search tool + its path, source
  priority list, output format, "record failures, never invent") and have every card point at it.
  Repeat per card only that lane's own queries and scope.
- Add the verifier as a **child of every lane** (`--parent <id>` per lane) so it only becomes ready
  when all lanes finish. Its job is dedupe by origin family, contradictions, and a ranked candidate
  list — not prose.
- **Workers gather, the main thread judges.** Synthesis, causal ranking and the final verdict stay
  with the main agent; a worker's completion summary is a claim, not evidence.
- For search lanes, put the time window *inside* the query string when the search tool ranks by
  relevance rather than recency, and require every finding to carry publisher + date + URL.

Mechanics worth knowing before you debug — the subcommands are not named the way you expect:

- `board kanban --board <slug> dispatch` runs a pass now; with gateway dispatch enabled ready cards
  also start on an interval, so a card can be claimed before you have finished planning the batch.
- **Write the shared guide file to disk and verify it exists BEFORE creating the cards that point at
  it.** A worker that cannot read a file its card names blocks with `needs_input` instead of
  improvising — correct behaviour, but you get several simultaneous blocks on the same missing file.
- **A card needs an assignee profile or dispatch skips it** (`skipped_unassigned` in the JSON).
  `board kanban --board <slug> assign <id> <profile>`; run it before the first dispatch pass.
  For auto-decomposed cards at scale, set `kanban.default_assignee` (and
  `kanban.orchestrator_profile`) in config so decomposition output gets an owner without
  per-card assignment.
- **Do not also start the standalone `daemon` when `kanban.dispatch_in_gateway: true`** — it refuses
  to run because the two race for claims (pass `--force` only when there is genuinely no gateway).
  The gateway ticks on `kanban.dispatch_interval_seconds`; tune that instead of adding a second
  dispatcher.
- **`dispatch --max N` returning `spawned: []` is a per-profile concurrency cap, not a failure.** The
  remaining assigned cards are picked up on the next tick — wait a tick and re-list before debugging.
- `unblock <id>` returns a `needs_input`-blocked card to ready once you have supplied what it asked
  for; no need to recreate the card.
- `link` / `unlink` take **parent then child**.
- `kanban list` / `show` / `log` (not `task list`), `kanban boards` (not `board`), and
  `block <id> "<reason>"` takes the reason **positionally** — there is no `--reason` flag. `edit`
  changes a live card's title/body, which is the cheap way to fix a mis-scoped card instead of
  recreating it.
- **`complete` refuses an evidence-free close**: pass `--result "..."` (or `--summary`) describing
  what was done and where the artifact is. An empty completion is rejected by design.
- **A card blocked in `review` is usually a done card with a broken transition, not missing work.**
  Read `show <id>`: a `review_requested` event carrying artifact paths plus later
  `worker_lost`/`crashed` runs with `exit_code 1` and output like `execution unknown; retained by
  owner` means the review worker died on the state transition. Verify the artifact yourself against
  the card's acceptance criteria, `comment` the verification, then `complete --result`. Re-running
  the work burns a worker cycle and can overwrite a good draft.
- **`create --body-file <path>` for any real card body.** Inline `--body` mangles quoting, and bodies
  with tables, blank lines, or lines starting with `-` are the normal case. Write the body file into
  the task directory first so the same file remains the durable brief after the card closes.
- **`--workspace dir:<abs path>` when the worker must edit a real checkout.** Default is scratch (a
  copy nobody publishes) and `worktree` forks a tree; both are wrong when the target repo has its own
  publisher (an auto-sync cron, a landing gate), because the edits then never reach the branch the
  publisher watches. Use `dir:` and let the repo's own publication path commit them.
- **Pass `--board <slug>` on every command, including `create`.** `boards` prints the *current* board
  with a `●`, and a bare `create` lands there — which is usually the previous project's board.
- **`create --json | tail` hides the id** in the trailing object fields; capture it with
  `grep '"id"'` or follow with `list` before `assign`/`dispatch`.
- Ready cards for one assignee profile dispatch in a single pass and run in parallel **when they
  touch different repos**; same-repo cards need explicit `link` ordering or a bounded
  `--max-runtime`, not hope.

## Pitfalls across board operations

1. Orchestrator doing the implementation and leaving the board stale.
2. Cards that lack acceptance criteria or verification commands.
3. Workers reporting success without artifacts or command output.
4. Tenant/profile confusion: doing work in the wrong agent profile, repo, org, or account.
5. Notification spam that hides the one important blocker.
6. Reassigning stuck work without preserving partial diffs/logs.
7. **A card title can collide with a repo's retired vocabulary.** A worker that reads the repo
   contract may (correctly) refuse a card whose naming implies a retired process; parking it as
   blocked is right behaviour, not a bug. Name cards in neutral language, and when the repo has
   retired a lifecycle, say so on the card ("this is not the retired X process; it is new work under
   <authority>").
8. **The auto-decomposer re-promotes whatever you block.** A blocked card that gets split can be
   promoted again in a loop. Once you have decided the main thread will do that work instead,
   **archive** the card; do not keep re-arguing with it.
9. **A blocked parent silently parks its children.** A verifier waiting on a blocked lane sits in
   `todo` indefinitely: `unlink <parent> <child>` frees it, or finish the lane yourself and archive
   the stale card.
10. **Calibrate a card's acceptance threshold against a real sample before dispatching.** Generate
    one sample artifact and measure it with the exact command the card names; a gate written in the
    wrong unit (e.g. a CJK-character count enforced against a checker that counts total file
    characters — the two differ ~2×) false-blocks workers that actually succeeded, and every false
    block costs a manual release cycle. When a mis-written criterion blocks an otherwise-done card,
    correct the criterion and release the card against it (`edit` a live card; comment + complete a
    blocked-but-done one) — do not re-run the work.
