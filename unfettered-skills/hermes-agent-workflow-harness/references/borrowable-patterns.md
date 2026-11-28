# Borrowable patterns (mechanism → why → minimal port)

Distilled from a production coding-agent harness; each entry is independently portable.

### Receipts over hashes
Normalized content receipt (frontmatter + business body, status excluded) re-compared at every gate,
so a status advance cannot masquerade as a contract change. Port: one `receipt(path)` helper plus an
assertion at each transition; forbid ad-hoc whole-file hashing in the workflow text.

### Private execution state
`<repo>/.<harness>/workflow/<id>/apply-state.json` (gitignored): start `HEAD`, manifest of
pre-existing dirty paths, sealed review scope. Business artifacts stay clean; review excludes
untouched pre-existing dirt and blocks only on real overlap. Port: same layout under
`.hermes/workflow/<id>/`, written by the entry command, read by the review step.

### Dual-axis review with verdict invalidation
Standards axis (repo rules + Fowler smell baseline) and Spec axis (AC by AC) as isolated parallel
reviewers with separate verdicts; `MUST_FIX | DECISION_NEEDED | APPROVE`; any code change voids
APPROVE; three unimproved rounds on one violation stops for a human decision. Port: two `pi -p`
calls with disjoint prompts over one diff-scoped bundle; never merge the reports.

### Repair revisions instead of new work items
A defect appends a monotonic revision to the same spec: old task IDs, dependencies and completed
states preserved, new tasks pending; the rebind invalidates the old review seal but keeps the original
baseline. `repair_key = sha256(feature + canonical source)` stops the same defect being re-opened
without new reproduction facts. Port: append-only rows; never reset a completed task; never reuse an
old APPROVE.

### Authorized knowledge writes
Propose diffs → explicit user confirmation → seal the exact file whitelist into private state → only
then may the agent write; any drift during writing blocks and leaves the tree to a human; irreversible
moves go last, after all other artifact writes. Port: whitelist plus drift check.

### Index-driven context loading
One root `index.md` per tree, three columns `file | what it is | when to load`, `must-read` markers,
unindexed files are not in the read set, per-session mtime cache, and an explicit "what I loaded"
declaration (or "index missing"). Port: beats automatic memory extraction because it is reviewable and
bounded.

### Parallel scan DAG with write scopes
Cold-start a repo's knowledge base by fanning out scan agents (tech / db / api → service → boundary →
meta; frontend six-way). Each job declares `job_id, prompt_source, depends_on, write_scope,
forbidden_scope, expected_artifacts`; the parent serializes the shared index and validates every
artifact exists and is non-empty. Port: cheapest repo-onboarding mechanism available.

### Capability-matrix runtime abstraction
Manifest declares each capability `native | emulated | unsupported` with adapter references; a
tool-semantics table maps logical actions (`read_file`, `edit_file`, `run_command`, `ask_user`,
`invoke_skill`, `spawn_job`+`wait_job`, `stage_finish`) to native tools; shared core has no platform
branch; unknown runtime fails closed. Port: whenever two runtimes must share one contract.

### F2P / P2P as the objective eval standard
A case is a `base_commit → solution_commit` interval; gold checks are fail-to-pass (new behavior now
passes) and pass-to-pass (existing behavior still passes), calibrated by real execution, never by
"the file exists". Port: the repo's own test suite is the cheapest honest benchmark — no worker pool
and no judge model needed to answer "did this harness change help".

### Consent-gated, non-blocking telemetry
Opt-in per scope (project/user), reminder cycle, in-repo ledger committed with the PR, async
supplement reporting with `accepted`/`duplicate` acknowledgements, consumer-side quality gate
(valid/partial/invalid), and a hard rule that telemetry failure never blocks the business flow.
Port: keep the "never blocks" rule even if the ledger is a single JSONL file.
