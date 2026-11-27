# Dispatch boundary and scope seal

Read when establishing what the sender was authorized to change, resolving scope
overlap, or recording and verifying an increment for landing. This is context
for acceptance, not independent authority to dispatch or expand scope.

## Check the bounded dispatch (the other half of the loop)

Acceptance presupposes a bounded dispatch. Send the work as a request FILE, not a chat prompt, so the
sender works from a fixed scope and the acceptance criteria exist before the work starts:

- Request file in the owning task dir (`<task>/<batch>-request.md`): Context (exact files to read) →
  Scope (explicit write surface, named exclusions, "no scheduled-job / config / profile / repo write"
  clauses, rollback expectations) → Deliver (numbered, each item with its gate and the real baseline
  numbers) → output artifact requirements (`result.md`, backups, diffs, ledger). Add the stop rule:
  when an approved value (an ID, a threshold, a target) is missing, the sender stops and reports it
  instead of choosing one, and it makes no live or production calls.
- Dispatch it headless and in the background — it runs for minutes; use the transport your harness
  provides (see `gdd-route-omp` for the OMP path) and keep the log plus the produced
  artifacts in the task dir.
- Pass absolute target paths for isolated worktrees and nested subagents: a relative write path
  resolves against the child's harness cwd and can land files in a scratch worktree. Verify the
  intended repository's `git status` directly (including checking for forbidden `docs/plans/*` or
  prematurely archived records) rather than trusting the subagent's report.
- A line like `open terminal failed: not a terminal` is the CLI failing to open an interactive terminal
  under a headless flag — not a run failure. Judge by exit code and produced artifacts.
- A clean process exit is itself only a claim: acceptance still re-runs the gates itself, as set out in [delivery checks](delivery-checks.md).

## Seal the working increment by path, not report hash

Review dispatches at a commit range, so uncommitted work is invisible to it. Bind the tree to a
recorded scope with `scripts/worktree-scope.py`:

1. `snapshot` when you take the tree: HEAD plus every dirty path (mode and content digest). Those
   paths are the baseline, not part of the increment.
2. `diff` after the work: `changed_paths` are the increment, `excluded_preexisting_paths` were
   already dirty and are untouched, `overlapping_paths` had two writers — stop and ask the operator
   which one owns each path before going further.
3. Seal once the review passes; `--accept-overlap` is an explicit operator decision and is
   recorded, so the fact survives into the record. Then take one of two pairs: `seal` + `verify`
   reads disk bytes, so it judges the working tree; `seal --index` + `verify --commit <rev>` binds
   to the shipped commit. A flagged seal writes only `commit_seal` (no legacy `seal`), per path the
   Git mode and full blob OID (null for a deletion); the legacy `diff`/`seal` receipts stay
   untouched, so pick the pair that matches what you are accepting.
4. `verify` after committing and before landing: exit 1 names every `added`, `modified` or `removed`
   path, so a post-review edit cannot ship unexamined. `verify --commit <rev>` resolves one commit
   and checks that commit's path set and per-path mode/OID against `commit_seal`, then walks
   `baseline.head..<rev>` for paths touched outside the seal; it reads no file, status or index, so a
   dirty worktree cannot weaken or fake the verdict. It never falls back to a legacy seal, and it
   refuses a shallow repository, an active graft file or a candidate that is not a descendant of the
   sealed base. History audits path membership, not intermediate blob contents at sealed paths.

The oracle is the path set, not a content hash of the report: a document can be rewritten without
changing the increment, and a one-line edit can change everything. Put the same path set and
`scope_sha` in the acceptance verdict and the PR body. State resolution: `--state-file`, then
`$HOA_SCOPE_STATE`, then `$XDG_STATE_HOME/hoa/scope`, then `~/.local/state/hoa/scope`; one JSON file
per repo+label.

Never bind a receipt to a tree digest that includes the receipt directory itself (for example
`docs/**`): writing the receipt invalidates its own digest, and rebasing drifts embedded counts.
Bind only the source subject (excluding the evidence directory explicitly) or record the final
summary in the PR body, label every count with the revision it describes, and re-collect fresh
evidence whenever the collection tool itself changes.

## Rule on the boundary

- Authorize the bounded, meaning-preserving subset and name the exclusion in the same breath. A wikilink
  conversion between pages that already mention each other is mechanical and reversible in one revert;
  a new sentence, a frontmatter `confidence`/`supersedes` edit, a merge, or a code change is not — those
  stay with the operator. "Do the mechanical part; these four stay put" gets work moving without
  spending the operator's ruling on it.
- Ruling on the sender's own house convention is yours when it is reversible in minutes and touches no
  knowledge. Decide it, say why, and say what you are not deciding (a physical reordering of a
  provenance file, for example, buys nothing when the parser is order-independent and rewrites an
  append-only record).
- Two teammates' surfaces can collide in one tree: end every round with the exact list of uncommitted
  paths and whose they are. Commit and push stay with the operator.
- **A worker blocking on scope is doing its job — compare its list with the approved plan's manifest
  before treating it as a stop.** The card you wrote can be narrower than the plan it executes (a
  garden-only card against a vault-wide link rewrite), in which case the paths the *manifest* lists are
  already in scope and authorizing them is not an expansion; anything the manifest does not name is a
  new ruling. When you authorize, name the path classes exactly, require a fresh pre-execute backup (an
  older archive predates later drift and is not a rollback unit), and restate the reserved lanes that
  stay closed.
