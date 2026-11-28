---
name: hermes-obflow-vault-contribution
version: 1.1.0
description: "Use when contributing content to the <notes-vault> vault."
author: Zoe
license: MIT
metadata:
  hermes:
    tags: [<notes-vault>, <notes-repo>, vault, obsidian, distill, migration, provenance]
---

# <notes-vault> Vault Contribution

Covers writing, migrating, and batch-distilling long-term knowledge into the <notes-vault>
Obsidian vault, and routing material between `~/claw`, <notes-vault>, and <research-repo>.

## When to Use

| You hear / see | Do |
|---|---|
| 把某块内容放进 <notes-vault> / 提升（promote）进 vault / 长期资产归位 | Rules below |
| 批量蒸馏 / distill 一堆报告或研究进 garden | Rules + `references/distill-pipeline.md` |
| 军事 / 国防 / PLA 相关材料要入库 | Rule 9 (nana intake, never auto-write nana wiki) |
`Rules 2–4 + 15 (allowlist roots, blocking-vs-advisory gates, red-sync triage)`

**Not for**: what belongs where at the policy level — that is `~/claw/AGENTS.md` Data Assets section
(owner-level routing, loads in ~/claw). This skill is HOW to land content in the vault correctly.

## Rules

1. **<notes-vault> is a subdirectory of the <notes-repo> repo** (`~/repos/<notes-repo>`, single `.git`,
   remote `<owner>/<notes-repo>`) — never treat it as its own repo. Write the working tree only;
   commit + push belongs to the `[ops] repo auto-sync` cron (`~/.hermes/scripts/thoughtscape-sync.sh`,
   every 2h at :15). Never hand-commit and never pre-stage the index — the sync script refuses a
   pre-staged index and fails closed. When content must land now, invoke the script yourself
   (`bash ~/.hermes/scripts/thoughtscape-sync.sh`): it runs the same scope/size/validate/secret
   gates and pushes, so it is not a bypass. Verify with the run's appended `OK pushed <sha>` line in
   `~/.hermes/logs/thoughtscape-sync.log` plus `git status -sb` showing no divergence from
   `origin/main` — exit code alone is not proof.
2. **New files sync only under the allowlist roots**: `garden/ gtd/ journals/ sources/ templates/ <work-tag-a>/
   prompts/ bases/ assets/ .agents/ .harness/ .docs/ .obsidian/` (paths relative to `<notes-vault>/`).
   A file landed anywhere else is silently never committed.
3. **Gates run in a fixed order, and only two classes may block**: `.harness/tests` unittest →
   `.harness/fin/tests` unittest → `vault.status` (structure audit) → markdownlint on all md; then gitleaks +
   ≤20MB new bytes per run. **Blocking = code/repo integrity**: the control-plane suite (synthetic fixtures,
   not the live artifact), the structure audit, scope/size, the staged secret scan. **Advisory = a verdict
   that moves when the owner's real data or a freshly-imported file moves** — the fin suite loads the live
   portfolio snapshot, lint judges whatever mirror was just imported — so `sync_warn` logs it, prints
   `thoughtscape-sync WARNING: <stage>: <first lines>`, and lets the run continue. Both helpers live in
   `~/.hermes/scripts/lib/git-sync-common.sh`; the warning keeps its **own**
   `~/.hermes/cache/sync-state/<name>.warn` and delivers once per distinct finding (signature = first 12 hex
   of the md5 of the message, so a new defect re-alerts while `suppressed duplicate warning` marks a repeat);
   a missing linter binary warns too, it no longer fails the run. **Owner ruling: a verdict that can move
   because HIS data moved must never abort the vault sync** — fail-closed there means the vault refuses to
   persist reality whenever reality is inconvenient, and every unrelated pending edit freezes behind it. A
   still-blocking gate is about the repo, never about the content he just wrote — say which side it is on
   before he has to ask. Advisory drops the abort, not the defect: lint every new or edited file before
   leaving the working tree: `cd ~/repos/<notes-repo>/<notes-vault> && markdownlint-cli2 -- '<relative path>'`.
   Quarantine failures outside the vault (e.g. a `staging/failed/` dir), never leave them in-tree.
   Backups of vault files count as strays too: write them to `~/claw/tasks/<date>/<task>/backups/`, never
   as `<file>.bak-<ts>` beside the original. Git already holds the pre-edit content, and one untracked
   non-allowlist file is the known class that blocks a whole fail-closed sync batch — including
   unrelated content.
4. **Read `<notes-vault>/AGENTS.md` + `STRUCTURE.md` before the first write of a session.** The vault's own
   contract wins inside the vault: `sources/` → `garden/` promotion chain, `<work-tag-a>/` never enters
   public projection, no folder inbox, templates need registry entries.
5. **Placement map** (durable synthesis → raw evidence → executable control):
   - `garden/<domain>/` — distilled conclusions, concepts, playbooks (domains: `ai dev security fin
     algorithms interview-prep learning lifestyle research-methods …`).
   - `garden/<domain>/research-notes/` — batch-distilled research notes, one auto-generated
     `_index.md` per domain, linked once from the domain `_index.md`.
   - `gtd/<area>/` — commitments and projects. A project that owns more than one file (a topic pool, per-item material, a plan) becomes a DIRECTORY `gtd/projects/<slug>/` whose `_index.md` carries the project frontmatter (`type: project`, `status: active`) so the active-projects Base still lists it, plus a placement table saying which subdirectory holds what and who writes it. Dated machine-written files live in subdirectories (`topics/`, `facts/`), never loose at the project root.
  - `sources/<topic>/` — raw originals + a provenance README (origin path, ingest date, limits).
   - `.harness/` — executable control scripts (finance capture, ledger generators), not garden.
6. **Naming pitfalls**: the interview domain is `interview-prep`, not `interview` (a classifier that
   emits `interview` creates a ghost top-level domain); kebab-case ASCII or Chinese filenames both
   valid; no catch-all status dirs (`draft/`, `todo/`); `garden/` rejects active `type: project`
   notes (projects belong in `gtd/`). **A newly promoted `garden/` note must declare `goal_id`** —
   `structure-policy.json` → `garden_admission_policy` admits only the active goal ids
   (`content-brand`, `financial-independence`, `promo-senior`, `system-reliability`; the goal notes
   themselves live in `gtd/goals/`). With no fitting goal, stop at `sources/` (or `journals/til/`) with
   `status: archived` instead of promoting; admission fails even when every other field is right.
   Notes written before the policy need no backfill, and editing one does not require adding `goal_id`.
   Editing an existing note in place bumps its `updated:` date (add the key after `created:` if the note
   lacks it) — a garden note changed without a bumped `updated:` reads as untouched in later audits.
   **`captured` / `distilled` / `archived`, `maintenance_kind` and `compiled_into` are the `sources/`
   (`process-clips`) lane's vocabulary and do NOT belong on a `garden/` note** — a garden note's
   lifecycle is its `status` (`seedling` → `growing` → `evergreen`, or `archived`). A writer that copies
   the clips fields onto a garden note is inventing a key (see rule 11). In the clips lane, exactly one
   of `captured` / `distilled` / `archived` applies, `maintenance_kind` matches the destination
   (`research` → `sources/research/<category>/`, `reference` → `sources/references/<category>/`) and
   `compiled_into` lists only the notes the insight actually landed in — one note, one destination,
   never both `references/` and `research/`.
7. **Wiki hygiene**: link every new `garden/`/`gtd/` note from an `_index.md` or existing hub using
   vault-root-qualified wikilinks (`[[garden/ai/agents/<note>|label]]`). Sync does NOT gate on
   orphans (`link_health` is skipped in the sync path), but wiki health audits them later.
   **A note written as a deliverable for an existing project must also be closed back into that project's own
   tracking surface** — the next session opens the project note, not your chat. Mark the backlog row it
   satisfies (`- [x] … → [[<note>]]`), add the link where the project keeps its artifact list, and append one
   dated session-log line. Locate that owner by the siblings it already links (`grep -rl '<sibling note stem>' gtd/`),
   not by a directory named after the topic: an artifact that exists only in `garden/` is invisible, and a
   checkbox ticked without a link sends the next session re-deriving work already paid for.
8. **Distilled notes carry provenance frontmatter**: `source_path`, `source_date`, `distilled_by`,
   `publish_candidate: false`. Distill conclusions and reusable judgments — never copy the source
   wholesale; one canonical copy (vault), no parallel evolution in `~/claw`.
   **A source whose own conclusion is "not completed" is not knowledge.** Fetch-blocked threads,
   plan-only directories and material-missing reports are incident logs: they belong in the archive list
   (with a reason) and never in `garden/`, whatever their byte size says. Volume is not the goal — a batch
   that yields four real notes out of twenty-one candidates is the correct outcome, not a failed one.
   `tags:` must also name the same domain as `category:`; a model that picks `research-methods` while
   leaving `dev` in the tags splits the note from the Base view that is supposed to list it.
9. **Military / defense / PLA material → <research-repo> `raw/pending-intake/<original-path>/`** with
   a `PROVENANCE.md` (origin, ingest date, unverified-citations limit). NEVER auto-write nana
   `wiki/` — its contract requires every material claim traceable to inspected evidence; bulk LLM
   distillation produces unauditable syntheses. Real nana ingest is nana's own profile workflow.
   Financial content keeps NO_TRADE semantics: policy/evidence/execution separation is mandatory.
10. **Destructive cleanup of source dirs only on terminal state**: every source item must be
    `ok` / `blocked-skip` / `military-archived` in the run ledger; then tar the whole source tree to
    `~/claw/backups/`, verify the tar's file count equals the live count, and only then `rm -rf`.
    Any non-terminal item aborts cleanup with the folder kept.
11. **Verify a batch, then report the next sync tick**: `markdownlint-cli2` 0 issues **over a nonzero file
    count**, `vault.status` with `blocking_count=0`, unittest green. Read the linter's own `in N files`
    tally: a config or ignore mismatch can answer `0 issues in 0 files` and pass without opening a single
    one of your files, so a bare "0 issues" is not evidence that a lint ran — quote the count, never the
    verdict alone, and do not report a vacuous pass as the file's cleanliness. Run the gates the way the sync script
    does — `pytest` is NOT installed in the harness venv, so:
    `cd ~/repos/<notes-repo>/<notes-vault> && env -u PYTHONPATH -u PYTHONHOME uv run --project .harness
    python -m unittest discover -s .harness/tests -p 'test_*.py'`
    and `uv run --project .harness python .harness/harness.py run vault.status`.
    The `.harness/fin` suite is a **separate** gate and its own `uv` project — neither command above covers
    it, so take its exact invocation from the sync wrapper's own fin stage instead of reconstructing it, and
    keep the wrapper's gate order (rule 15).
    **Strip the ambient interpreter env before believing a red run.** The agent shell exports its own
    `PYTHONPATH`/`PYTHONHOME`, `uv run` imports that tree, and the suite then reports failures that
    vanish under `env -u PYTHONPATH -u PYTHONHOME` (measured: 4 errors → `OK (skipped=1)`, same
    command, same tree). Until the sanitized run is green, the failure is the shell — never report it
    to the owner as a vault regression or a data fault.
    The sync cron picks the working tree up at the next `15 */6 * * *` tick — report that timing
    instead of committing manually.
    **Read the harness receipt's own `status`, not the stdout tail or the shell exit code.** A missing
    module or a probe fault lands as `result.status: FAILED` with `result.data.error_type`
    (`No module named 'yaml'` is the classic one when the interpreter lacks PyYAML), while the JSON around
    it prints normally, so reading only the end of stdout still looks like a successful collection — use the
    `uv run` form above, or an interpreter that has the dependency, and assert `status`.
    **Resolve every wikilink you just wrote before leaving the working tree.** Sync does not gate on link
    health (`link_health` is skipped), so a typo'd `[[garden/…]]` ships silently and only surfaces in a
    later wiki audit: this skill's own copy (`scripts/vault-links-check.py` **ships with this skill, not with
    the vault** — `<notes-vault>/scripts/` does not exist, so a bare `scripts/vault-links-check.py` runs from the
    vault root as File-not-found) resolves each target path-qualified or by file stem, prints
    `unresolved: N` and exits non-zero on any unresolved one.
    **Run it from the vault root with vault-relative paths** (`cd ~/repos/<notes-repo>/<notes-vault>`), naming the
    checker inside this skill's directory, and prefer `/usr/bin/python3` (the mise-shim `python3` may lack
    its deps):
    `/usr/bin/python3 ~/.hermes/skills/devops/obflow-vault-contribution/scripts/vault-links-check.py '<relative path>'`
    The checker resolves against the vault, so passing `<notes-vault>/<path>` from the repo root returns a FALSE
    `MISSING FILE`. A `![[bases/*.base#…]]` embed on an `_index.md` is a Base embed, not a note link,
    and the checker counts it unresolved — before reporting any such hit as a regression, confirm the
    previous commit already carries it (`git show <prev-sha>:<path> | grep '<link>'`).
    **A green lint is not a rendered read-back either**: a literal backtick inside single-backtick inline code
    closes the span early, and neither markdownlint nor the link checker reports it — when a sentence must
    list shell metacharacters, spell them out (反斜杠 / 反引号 / 美元符) instead of quoting the backtick.
    **No new frontmatter key without precedent in the target layer.** When accepting a delegated or
    batch-written note, grep the lane for every key the writer added (`grep -rl '<key>' garden/`): a
    count of exactly 1 — the new note itself — means the vocabulary came from another lane's contract;
    delete the key and say so. Read the structure audit off the receipt, not the stdout tail:
    `vault.status` prints a `NO_OP` envelope, so take `result.data.structure.blocking_count` from
    `.harness/receipts/<latest>.json` and keep its `warning_count` (pre-existing debt) separate from it.
    **You own the bytes you accept.** If acceptance turns up an imprecise claim in a note still
    uncommitted in your tree, patch it in place — a completed evidence chain beats an
    attributed-but-unverifiable number — and name every edit you made in the report; a silent
    correction is an unaccounted write.

12. **Migrating a `~/claw/` directory into the vault**: inventory before moving — a `research/` with
    hundreds of files may be a third-party git checkout (→ `~/repos/`, not vault content; check
    `git remote`/`git status`, not the directory name). For every path a live script reads or writes,
    grep the WHOLE live surface, not just `~/.hermes/scripts`: `~/.hermes/profiles/*/cron/jobs.json`,
    `~/.hermes/profiles/*/SOUL.md`, `~/.hermes/LOCAL_OVERRIDES.md`, `~/.hermes/skills`, the materialized
    `profiles/*/skills/*` copies (mode 0444 — fix the source skill, then
    `profile-skill-materialize.py --apply --profile <p> --force`), and
    `~/claw/{AGENTS.md,bots,references,gtd}`. Files a script parses as key-value (e.g. `gtd/goals/*.md`
    read by `morning-decisions.py`) must NOT gain YAML frontmatter fences — that parser stops at the
    first non-matching line, so a `---` header silently drops the item. The same holds for ANY line that
    parser cannot match: a heading, a prose block or a `---` rule placed ahead of or inside the key-value
    block hides every key after it, so new prose goes BELOW the block. The vault's own gates do not read
    that parser — unittest, `vault.status` and markdownlint stay green while the item has vanished from
    the consumer — so a green batch is not the read-back for a goal file: check the consuming script's
    expectation against the edited file before leaving the tree. Keep regenerated intermediates
    (e.g. `weekly-prefill-latest.md`) in `~/claw`, move only evidence into `<work-tag-a>/`, leave a
    `~/claw/<dir>/README.md` pointer, and archive one-off snapshots outside both trees.
    Include every **panel / digest generator** in the consumer sweep, not just the runners you remember:
    they read the vault too, and a literal path left pointing at `~/claw` degrades them to generic
    placeholder output with exit 0 instead of failing, so a miss in this list is invisible for days
    (fix shape and proof live in the `hermes-cron` skill: rule 28, plus its own `cases.md` → "Generated panel").
13. **When a scheduled producer starts writing into the vault, move every address point at once and
    constrain its output.** Such a producer has three: the job prompt
    (`~/.hermes/profiles/<p>/cron/jobs.json`), the seed/collector script it runs, and any prompt text
    naming the output path. Update all three (back up `jobs.json` first, re-read the job after writing to
    confirm), keep an env override for the new target, and put the vault's constraints into the prompt
    verbatim: exactly one file per run, kebab-case name, headings + lists only, no frontmatter, no index
    page, no orphan wikilinks.    A producer left writing loose files, or with a catch-all name, blocks the
    ENTIRE next sync batch — including unrelated finance/ops content.
    When that producer is also under a capacity policy (a pool that must not grow past N), the verdict
    arrives as a token computed by its own collector script, and the human-owned index — the table whose
    rows are counted — stays outside its write scope: candidates land in the dated file and promotion into
    the counted table is the owner's act (`mechanical-gate-design` §9). A producer told to police its own
    quota drifts, and one allowed to edit the counted record moves the goalpost.
    **When that producer's output is a managed section inside a file other writers also edit, the contract is
    replace-in-place, not append.** Mark the section with exclusive begin/end markers and rewrite only the
    bytes between them, then prove it with the three-digest probe (`verification-probes` §5) after two
    consecutive runs — the section must update while every byte outside it stays identical, including after the
    file's own generator (the daily-note exhaust writer) runs in between. **And the producer must exclude its
    own output from what it ingests**: a collector that re-reads the channel it posts receipts into records
    those receipts as content, so filter by author id and never by prompt text — a new receipt wording reopens
    it silently. Keep the ingest target env-overridable (`<X>_VAULT=<scratch>`) so the whole chain can be
    driven against a fixture vault, and delete that fixture's test rows and scratch artifacts afterwards: a
    stash left in the real daily note is the one failure the gates cannot see.
14. **Material lives in the vault; only the finished artifact goes to its publication repo.** 选题、计划、
    策略、材料、素材 belong in `gtd/` (project note + subdirectories) or `sources/`; the publication repo
    (blog / publisher checkout) holds finished posts and its own writing contracts, never the topic pool,
    the per-piece fact list or the strategy notes. The reverse also holds: the vault does not keep the
    draft body — a version that gets rewritten repeatedly has exactly one home, and that home is the
    publication side. After such a move, downgrade the old `~/claw/<dir>/` to a pointer README that names
    the new authoritative paths (rule 12), or the next session keeps writing at the old location.

15. **A red sync reports only the FIRST failing stage — enumerate every gate yourself.** The gates run in a
    fixed order (`.harness/tests` → `.harness/fin/tests` → `vault.status` → markdownlint) and the run stops at
    the first red one, so a red `fin` hides a red markdownlint. A stage line that *changes* between ticks
    means the earlier gate healed or a new commit entered the tree — never that the same failure mutated.
    Read `~/.hermes/logs/thoughtscape-sync.log` first: `FAIL(<sig12>)` is a hash of the failure message, so a
    changed signature is a **different** failure (and therefore a separate alert), while the matching
    `suppressed duplicate alert` line means that tick equalled the already-notified failure, not that the tick
    was healthy. `~/.hermes/logs/ops-alerts.log` gives the alert timeline. Then run every gate by hand before
    claiming a fix. **Gate-red is not data loss**: nothing was committed or pushed, every edit is still in the
    working tree — fix the gate, do not re-do or relocate the work.
    Failure shapes an automated heal cannot clear — plus the finding that is not a defect at all:
    - **markdownlint MD051 (link fragments) has no autofix**, so `obflow_pre_sync.py`'s `markdownlint --fix`
      reports success while the gate stays red. The recurring shape is an imported/mirrored document whose
      inline `[N](#citation-bottom-N)` citations point at a bottom section that was never materialized (the
      real footnotes sit under `## Footnotes` with a different anchor, or none). Make the anchor exist — the
      vault forbids restructuring a source-fidelity mirror for style.
    - **A gate test that asserts over the LIVE snapshot encodes the regime it was written in.** The fin suite
      loads the newest portfolio snapshot, so a legitimate swing turns it red with no code change: a loss puts
      total assets below the principal base and inverts a "buffer in pp of principal > decline as a share of
      assets" assertion. Two layers, in order: this verdict is `sync_warn`, never `sync_fail` (rule 3), because
      his real loss must never wedge the batch — and the assertion is still the gate's fault, never the data's,
      so fixture it (frozen input) before trusting it as a guard; **never edit the vault's portfolio data to
      make a gate pass**. Because the pre-gate align
      is report-only, a gate can also go red at the tick right after a fetch brought a new upstream commit's
      data into the tree; date the regression from the branch's `git reflog`.
    - **The secret scan's own false positive — the import marker.** `gitleaks git --staged` reports
      `generic-api-key` on the import pipeline's inline media metadata
      (`<!-- MEDIA: {"entityKey": "<36-char id>", "mediaItems": […] } -->`): a high-entropy content id, not a
      credential, emitted once per imported file, so one import can produce ~10 hits in a single path. Triage
      it without ever loading the value into context — re-run with `--report-format json --report-path <tmp>`,
      print only `RuleID / File / StartLine`, then re-print the line with every `[A-Za-z0-9_-]{12,}` run masked
      and report the key name plus the value's length, character classes and entropy. Then hand the owner the
      decision: a scanner exception is a security-surface change, so never whitelist silently and never rewrite
      the imported file (the next import reintroduces the marker). The shape to propose is a narrow allowlist
      for that one pattern in a repo-side `.gitleaks.toml` — a new repo-root file, so its name must also enter
      both root-file allowlists (preflight + `obflow_pre_sync.py`) or the hook quarantines it, or point
      `GITLEAKS_CONFIG` at a host-side file instead. Until he rules, the gate stays red and nothing is pushed:
      a possible leak is not in the same class as a data-dependent verdict, and owner impatience about his data
      is not a licence to route around it.
    - **A backup of a vault file must live outside the repo.** Every root the preflight allows is inside the
      checkout, so `<file>.bak-<ts>` written beside it is a brand-new *tracked* file at the next tick: the
      backup enters history and the next reader diffs it as content. Copy to the agent workspace or `/tmp`
      instead. Host scripts under `~/.hermes/scripts/` are not a repository, so a `.bak` beside those stays
      local and is correct. A backup already committed this way comes out by deleting it in the worktree —
      the next tick commits the removal; never `git rm` plus a hand-commit (the tick refuses a pre-staged
      index).
    - **Owner ruling (2026-11-25): a gate never judges the data it is persisting.** The decisions this
      incident produced, for reuse: the fin suite's data-regime assertion was **deleted** (it tested whether
      the owner's real portfolio was profitable — not a property of any artifact), while the control-plane
      suite, `vault.status`, scope/size and the secret scan stay blocking; both data-dependent gates stay
      `sync_warn`. A live-data assertion that must survive belongs on a frozen fixture, and asserting the
      owner's numbers is never the fix — the *facts* are the input, not the verdict.

## References

- `references/distill-pipeline.md` — batch LLM distillation recipe: model call form (prompt file, not
  `-q`), prompt contract, tolerant parsing, lint-fail isolation, ledger idempotency, size-band batching,
  research-completion variant (`完成度: blocked`), promoting an archived research tarball (content-based
  coverage triage — failure logs are not knowledge, `SKIP` handling, frontmatter/`tags` validation,
  archive-vs-queue decision record, batch review and how to withdraw a promoted note), cleanup gates.
