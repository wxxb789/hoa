# Contract evolution pitfalls

## Edit and protect the contract

- **An authorization-boundary change is a cross-file invariant.** When the owner grants or revokes a
  standing permission ("no approval needed for X"), the old sentence usually lives in three layers — the
  repo's own contract, the host operating protocol's action gates, and memory — and changing one leaves
  the next session following whichever stale copy it loads, or asking for approval that no longer exists.
  Grep the old wording across the identity file, the operating protocol, repo contracts and the fact store
  first, edit every hit in one pass, and restate the invariants that did NOT change (no force-push, no
  history rewrite, no secrets in Git) so the new permission is not read as a blanket waiver.
- **Single-section misunderstanding**: If the owner says sections should be question-like or richer, do not simply add one new bullet. Re-derive the whole structure if needed.
- **Over-asyncing**: Async-first means reducing owner blocking, not hiding quick or decision-critical work in the background.
- **Ceremonial delegation**: Maximize team-agent leverage, not team-agent usage. Simple low-risk tasks should stay fast path.
- **Ritual context loading**: Read relevant files before grounded work, but do not perform file reads for simple conversational/preferences responses.
- **Prompt bloat**: More rules are not automatically better. Prefer fewer rules with sharper triggers.
- **Source-code escape hatch**: Do not edit the runtime's source to fix behavior that belongs in the identity file, operating protocol, memory, skills, or config.
- **Protected instruction files are approval-gated**: writes to the identity file / operating protocol (and other protected agent-instruction files) may be refused unless the owner approves an interactive prompt — and a prompt that times out is NOT consent. Do not retry the write, and do not reach the same file through a shell, script, or editor path; report the blocked state, leave the file byte-identical, and offer to re-issue the prompt on the owner's word. Delete any backup you made for that blocked edit — an unchanged source turns the backup into misleading clutter. A block that lands **mid-batch** leaves the contract internally inconsistent (new section says X, old section still says not-X): say in the report exactly which lines are now stale and what the pending edit is, so the next session patches it instead of trusting the contradiction.
- **Layer-placed but never loaded**: Putting a rule in the "correct" layer is not enough if the runtime won't load that file for the owner's cwd. The protocol file loads only at its exact directory; an overlay file preempts it; only the identity file is global. Confirm load conditions before declaring a refactor done.
- **Crossing the loader wires**: The project-context file types use separate loader functions with different scopes. An overlay file's "walk to git root" is NOT the protocol file's behavior (which does no parent walk and ignores git). Never reason by analogy from one file's discovery to another — check the actual loader. (This skill's author made exactly this error mid-session.)
- **Hash-freezing the contract itself**: A contract that binds per-file content hashes of its own text into every launched object guarantees that each later contract edit invalidates all in-flight objects' bindings — drift errors accumulate by design, and repair commits become routine. Freeze state with a single git commit reference (change detection = `git diff <commit> -- <path>`), and never make the LLM the hash transcriber.
- **Profile delta restating a fact owned by another layer**: a per-profile delta must carry only differences. Restating a fact from the fact store (level, work hours) or a gate from the operating protocol creates a second copy that drifts silently — the fact changes once, one copy goes stale, and nothing errors. Point at the canonical file instead ("身份、作息见 <fact store>").
- **Whole-file rewrite blocked after a partial read**: a whole-file write may be refused when the file's current content was not fully read in this session, and an earlier full read stops counting once a targeted edit has changed the file. Re-read the whole file immediately before a full rewrite, or use targeted edits; otherwise the write bounces and burns a round trip.
- **Tooling that writes externally leaves an open red state**: a harness, script, or eval can perform an irreversible external action while testing for it. Do not unilaterally revert or “fix history” — surface the exact effect, offer keep vs revert, and after the owner decides, record decision + applied fixes in a durable incident note so it is never re-litigated. Reverting a legitimate change to undo your own process error punishes the repo for the wrong thing.

## Reconcile and renumber generated layers

### Regenerate the derived identity layer whenever the canonical identity file changes

- The root identity file is canonical; every per-profile identity file is GENERATED from root + that profile's delta file. Editing root alone leaves every served profile stale — the profile copies are what sessions actually load.
- Repair: run the layer-reconcile wrapper. Wrappers often repair by default and accept **only** `--dry-run`; `--apply` / `--check` may belong to the underlying sync script, so passing them to the wrapper just errors. Check the wrapper's accepted flags before invoking it, and treat silence on a dry run as "no drift".
- Verify: re-run `--dry-run` (silence = no drift), `grep -rl "<new phrase>" <root identity> <profiles>/*/identity*` (root + all profiles share it), and `grep -c "^## "` per profile (root section count + 1 overlay section).
- Renumbering or deleting a section is a **cross-file invariant**: profile deltas hardcode section-range pointers ("above sections 0-14 apply"). Grep the deltas for the old range and fix it in the same edit, then reconcile.

- **Stale section numbers after a renumber**: merging or deleting a numbered section silently breaks every hardcoded reference — profile deltas, team docs, and other files that cite "section 14" or a range. Grep the whole identity/ops layer for the retired number in the same edit; a doc that self-describes its structure must have no dangling numbers.

## Review proposals

- **Same-family reviewers labeled independent**: Subagent reviewers from the same model family are self-consistency checks, not independent review. Label them as such in review records, or route genuinely independence-requiring reviews across model families — a contract that demands independence while accepting same-family self-review is violating itself.
- **When the contract still produces mediocre output, review the contract, not the output**: send the
  file plus one failing artifact to an other-family model with three questions — which three rules most
  let it still fail (each must answer “what makes it fail anyway”), where our criteria are weaker than the
  reference method, and where we should concede outright — and require directly pasteable replacement
  text. Let that model write the revised file (feed current text + review, ask for the whole file), then
  verify mechanically: line caps, headings whose numbers must change with the body (a “two types”
  heading after adding a third), lint and build. Hand-merging the model's sentences flattens exactly the
  judgement you paid for.
- **Unmeasured savings claims in a contract proposal**: `wc -l -c` a copy of the file before promising how many lines/bytes a merge or prune removes. Estimating from the visible block over-states it (a section merge read as "-20 lines / -800 chars" measured -13 / -135), and an owner who checks data notices. Measure first, or phrase the benefit as direction and report real numbers after applying.
- **Contract polish as displacement**: repeated rounds of identity/prompt refinement are high-feedback, low-risk, and unfailable — exactly the profile of an avoidance task. Before accepting another round, check whether a decaying deliverable exists (evidence log mtime, unpushed work, empty inbox, stalled plan) and say it once with the measured fact, then proceed with what was asked. Name the tradeoff; do not moralize and do not refuse the work.
- **Resolve risk before editing**: offer a few pruning scopes with measured savings. A scope choice is not durable-write approval unless the owner explicitly authorizes the edits it entails.

## Migrate and retire paths

- **Cleaning host bytes out of a repo and then putting them back**: when a repo's contract forbids host paths / host-only tool names in its bytes, the sanitization log is the easiest place to reintroduce them — a "before" column quoting the original host path writes it straight back in. Describe each removed item generically ("a host checkout path inside the harness example"). See the [full port procedure](repo-owned-skills-port.md).
- **Migration without a reference sweep leaves dead paths**: moving a directory the contract names (an evidence path, a capture script, a bot fast-line command) turns every mention into a dangling path a later session follows into nothing. Grep contract, bot deltas, scheduled scripts and docs for the old path and update them in the same batch as the move — or keep the directory as the single documented exception until its batch runs.
- **Depth-limited inventory undercounts the move**: `find <dir> -maxdepth 2` showed five files in a ledger directory; the third level held the decision memo, two execution sheets, two review notes and a valuation script — all durable. Enumerate with `find <dir> -type f | sort` (no maxdepth), and treat `tar tzf` of the backup archive as the authoritative pre-deletion manifest, so "it only had five files" can never justify deleting real content.
