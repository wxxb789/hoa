---
name: agent-operating-contract-evolution
description: >-
  Evolve an agent's operating contract: its identity file, operating protocol, layered memory /
  skills / config, and any repo whose product IS an agent contract or control plane. Use when asked
  to optimize, review, or refactor those files, or when the owner corrects how the agent approached
  identity, routing, delegation, or persistence. Not for ordinary repo coding rules, and not for
  one-off task notes.
metadata:
  version: "0.1.30"
  areas: "software-development,work-management,self-management"
  targets: "runtime-agnostic"
  summary: "evolve an agent's identity file and operating protocol by layer, with coverage markers, behavioral evals, and load-scope probes"
  summary_zh: "按分层演进 agent 身份文件与操作协议：覆盖标记、行为评测、加载范围探测"
  kind: "entry"
---

# Agent Operating Contract Evolution Skill

Use this when the owner asks to optimize, review, evolve, or refactor an agent's identity file, operating
protocol, team-agent definitions, a runtime operating contract, or a user-owned repo whose product IS an
agent contract / control-plane system (research control planes, orchestration harnesses, evidence
pipelines). This skill is for class-level agent behavior design, not one-off task notes.

## When to Use

Trigger on requests like:
- "evolve your soul"
- "review all identity files" / "review the profile identities" / "audit every identity file"
- "review the operating protocol"
- "optimize your agent definition"
- "make the team agents work better"
- "reduce blocking / work async"
- "keep files organized"
- "review / optimize / improve this system" where the target is a user-owned repo whose product is an agent contract or control plane (research systems, orchestration harnesses, evidence pipelines)
- "unify the scattered per-project scripts" / "retire the old scripts" / "make this portable across harnesses" on such a repo — load the refactor playbook reference before executing
- "deprecate the legacy agent file, use the new kernel" — kernel flips on any repo an agent reads
- "make this repo self-contained" / "move those skills into the repo, not the host skills folder" / "port the profile skill into the repo" — skill-placement work on such a repo; load `references/repo-owned-skills-port.md` before executing
- user corrects how the agent approached identity, workflow, formatting, delegation, or persistence

Do **not** use for ordinary repo-specific coding rules unless the task is explicitly about agent behavior or operating contracts.

## Core Principle

Treat the agent system as layered architecture:

- identity file (e.g. `SOUL.md`) → identity, stance, voice, hard limits
- operating protocol (e.g. `AGENTS.md`) → operating rules, routing, safety, artifacts, execution behavior
- memory → stable facts, preferences, environment quirks
- skills → reusable procedures, workflows, pitfalls
- config → runtime behavior, models, providers, tools
- artifacts → long outputs under a designated artifact workspace

Never solve an operating-contract problem by dumping every lesson into one file. Put each rule in its canonical layer.

## Instruction files are read by a model, not by a person

The identity file and operating protocol are injected context consumed by an LLM. Human legibility is not a requirement and mostly costs tokens. Optimize for: the shortest text that still forces the same behavior, one meaning per rule, no rule contradicting another.

- Density forms that hold up: `condition → action`, `禁：X`, symbol operators (`→`／`≤`／必给`), key-prefix mapping (`本体=/关系=/姿态=`).
- Cut on sight: connective prose ("我的本体是…我的关系是…"), self-explanation that does not generalize to unseen cases, decorative metaphor, human-oriented section titles ("我到底是谁？"), and any rule stated twice in different words.
- Keep: hard limits word-for-word, the minimum examples needed to stop a rule from drifting, and 1–2 voice anchors.
- Report measured `bytes` and non-heading rule-line counts before/after — never estimated ones.
- Prove no rule was lost: `scripts/contract-coverage-check.py OLD NEW markers.txt` (declare one distinctive substring per rule before editing, check after).

Voice anchors are the deliberate exception. A single line like "the assistant you'd actually want at 2am" is cheap and calibrates tone in a way rule text cannot. Compress rules, not exemplars: deleting every anchor flattens the voice, and no added rule restores it.

This density applies to **instruction files only**. Replies to the owner are human-facing: full sentences, one idea per line, explicit causal links. Applying the compression rule to chat produces telegraphic output the owner cannot parse — the two surfaces need different budgets, and the contract should say so.

## Measure the real per-turn prompt before optimizing

Instruction files are only part of the per-turn cost. Pull the runtime's own assembled prompt from its
persisted prompt record, measure section sizes by marker, and cut the largest reducible block — usually
the skills list, pruneable through the runtime's disabled-skill list on the root config and every profile.
Procedure, measured numbers, verification (one-shot + compare same prompt hash family), the append-log
staleness trap, and the drift-guard script pattern: `references/context-budget-measurement.md`.

## Behavioral regression, not just coverage

Coverage proves no rule was lost. It does not prove the file still produces the right behavior — a rewrite can keep every sentence and still shift hedging, gate behavior, or tone.

- Keep 10–15 one-shot cases (`<runtime> -z "<prompt>"`), each asserting a behavior the contract explicitly governs: decisive take, red gate, destructive confirm, ADHD support shape, fact verification, channel style, ask-before-side-effect, retry stop.
- Per case declare `expect` (regex alternatives, at least one must hit) and `forbid` (failure signatures, none may hit). Forbidden patterns are what catch the regressions the rules exist to prevent.
- Run before and after every contract edit; compare pass counts and diff raw outputs (`runs/<ts>/raw/*.txt`). Report a measured baseline instead of asserting the new version "feels better".
- **Contamination pitfall**: if the case file lives where the agent can scan (inside the project workspace it is asked to investigate), it finds the assertions and answers the test — observed as a case's `forbid` regex quoted back verbatim in the reply. Keep cases and runner outside the agent's workspace (e.g. a runtime-level `evals/` directory).
- Reference implementation: `scripts/contract-eval-run.py` (cases JSON beside it, or `--cases`).

## Layering is necessary but NOT sufficient — check what actually loads

Putting a rule in the "right" layer does not guarantee the runtime injects it. Instruction files have
**different, cwd-dependent discovery scopes**, and many runtimes load only ONE project-context file per
session (first match wins). A correctly-layered rule in a file the current cwd never loads is silently dead.

Hard facts to establish per runtime (and the reason not to reason by analogy):

- The **identity file** is usually the only globally loaded, cwd-independent slot (one fixed path, every
  turn). If a rule must hold *regardless of cwd*, it MUST live there. You cannot make a rule global by
  relocating a project-context file into the runtime home — that is not its mechanism.
- The **operating protocol file** typically loads only when session cwd === the exact directory holding it
  (top-level only, no parent walk, no recursion, and often **no git requirement**). Starting in a
  subdirectory does not pull in the top-level file at startup.
- An **overlay file** (a dot-prefixed variant) may walk cwd→git-root and have **higher priority than** the
  operating protocol — adding one *preempts* the existing file (which then stops loading). It does not
  "also load".
- **Delegated subagents** commonly run with `skip_context_files` → they see neither the identity file nor
  the project file; pass needed contract rules via the delegation `context=`.

So when the owner wants "my contract to work no matter where I start a session",
the answer is **promote to the identity file**, not "keep it in the protocol file" and not "add an overlay".
Confirm the owner's real cwd habits before choosing the protocol file as the home for must-always-hold
rules.

Verify, don't reason: `references/context-file-loading-probes.md` has the probe commands. Run them rather
than inferring discovery behavior.

## Ownership and routing rules are storage facts — verify before you write

When the owner says "long-term assets live in X, Y is just a runtime workspace", the contract edit is the easy half; the half that goes wrong is asserting mechanics you never read.

- Probe topology first: `git -C <dir> rev-parse --show-toplevel`, `git remote -v`, a nested-`.git` scan, `git ls-files <store> | wc -l`. A knowledge vault that reads like a standalone store is often a folder inside a larger repo — then persistence belongs to that repo's pipeline, not to a generic "git-as-sync" claim.
- A source directory that is **not** a repo (no history, no remote, no rollback) is the strongest argument for the move; report it as measured fact, not opinion.
- Read the sync wrapper that actually persists the store (a scheduled job calling a repo-specific script, often through a shared library): new-file allowlist roots, per-run size cap, validation stack, refusal conditions, commit convention. Those become the rule; "may commit + push" is not one.
- Never write "X blocks the pipeline" without opening the command implementation **and** its call site. A check guarded by an optional payload key that the pipeline never passes is quality debt, not a gate.
- Report duplication as the finding (two GTD stores, two ledgers, two goal lists); moving files without retiring the copy recreates it in a week.

Full probe set, rule template, migration batching and pitfalls: `references/asset-store-vs-workspace-routing.md`.

The execution half — complete inventory, target-side frontmatter/link conventions, bulk path rewriting, validation, retirement order, and distilling a research backlog into the store — is in `references/knowledge-vault-migration-execution.md`.

## Procedure

0. **Handle the owner shortcut**
   - If the owner says “GEPA this”, interpret it as: capture the trace, find the right durability layer, apply low-risk fixes immediately, then show proof.
   - Do not ask for confirmation unless the fix is Red-risk or the layer choice is genuinely ambiguous.

1. **Load current context deliberately**
   - Read the target file(s): identity file, operating protocol, team docs, or config as relevant.
   - Use session history when the owner asks you to learn from prior behavior.
   - Avoid ritual reads; load context by trigger.

2. **Identify the correction class**
   - Style/voice issue → likely the identity file or a response-shape rule in the operating protocol.
   - Workflow/routing issue → the operating protocol.
   - Stable owner preference → memory, and often a governing skill if task-class behavior changed.
   - Reusable task procedure → skill.
   - Runtime/model/tool behavior → config.

3. **Ask using low-friction choice prompts when design is subjective**
   - Prefer 2-4 choices.
   - If the owner selects multiple options, synthesize them instead of forcing a single answer.
   - For multi-section identity work, ask one section at a time.
   - When the owner asks for a draft first, do not edit files yet.

4. **Design from richer source material, not just existing files**
   - If the task starts from an article, research note, or external design, extract reusable architecture from that source.
   - Do not merely reformat the current file and call it evolution.
   - Clearly map what came from source material vs existing local conventions.

5. **Prefer surgical contract patches over sprawling rewrites**
   - Preserve what works.
   - Merge duplicate sections.
   - Add routing gates where rules could overfire.
   - Keep language operational: trigger → action → proof.
   - A compression pass is behavior-preserving by contract: same rules, shorter form. Never add a rule while compressing — the diff stops being reviewable and the owner only approved the rewrite.
   - Before editing, enumerate every rule you must preserve as a distinctive marker substring; after writing, run `scripts/contract-coverage-check.py`. A marker per rule beats a prose read-through for proving nothing was dropped.

6. **Back up before durable edits**
   - For Yellow edits (identity file, operating protocol, config, skills, team docs), create a timestamped backup.
   - Apply the edit.
   - Read back or otherwise verify.
   - Return final path, backup path, and the meaningful diff summary.

7. **Regenerate the derived identity layer whenever the canonical identity file changes**
   - The root identity file is canonical; every per-profile identity file is GENERATED from root + that profile's delta file. Editing root alone leaves every served profile stale — the profile copies are what sessions actually load.
   - Repair: run the layer-reconcile wrapper. Wrappers often repair by default and accept **only** `--dry-run`; `--apply` / `--check` may belong to the underlying sync script, so passing them to the wrapper just errors. Check the wrapper's accepted flags before invoking it, and treat silence on a dry run as "no drift".
   - Verify: re-run `--dry-run` (silence = no drift), `grep -rl "<new phrase>" <root identity> <profiles>/*/identity*` (root + all profiles share it), and `grep -c "^## "` per profile (root section count + 1 overlay section).
   - Renumbering or deleting a section is a **cross-file invariant**: profile deltas hardcode section-range pointers ("above sections 0-14 apply"). Grep the deltas for the old range and fix it in the same edit, then reconcile.

8. **Run a self-evolution pass after meaningful sessions**
   - What friction happened?
   - Which layer should absorb the lesson?
   - Should a skill be patched/created?
   - Are there duplicate or stale rules to tighten?

## Operating Contract Review Checklist

When reviewing the operating protocol like a code reviewer, check:

- **Scope separation**: Is identity leaking into the protocol? Is ops leaking into the identity file?
- **Trigger clarity**: Does each rule say when it applies?
- **Conflict risk**: Do async, context-loading, safety gates, and delegation rules fight each other?
- **Blast radius**: Are Green / Yellow / Red gates defined by reversibility and impact?
- **Team leverage**: Are specialist agents used when they improve quality or wall-clock time, not for ceremony?
- **Model leverage**: Is there a heuristic for fast/default/strong model routing without hardcoding stale model names?
- **Filesystem hygiene**: Are artifacts named, scoped, and cleaned after work?
- **Persistence routing**: Are durable lessons going into the right layer?
- **Live-inventory accuracy**: a section that enumerates live objects (profiles, scheduled jobs, delivery
  channels, model ids) is a fact table, not a rule. Re-derive it from the runtime's profile list / the
  scheduler's job list / config after any infrastructure change, and keep a drift checker asserting
  each live name appears in the file — rosters grow silently while the prose stays confidently wrong.
- **Proof trail**: Are edits requiring backup, diff/path/proof, and minimal verification?
- **Control-plane overhead ratio**: For contract/control-plane systems, measure control bytes/files against product bytes (a completed object's records vs its deliverables). A ratio approaching or exceeding 1:1 is over-engineering regardless of correctness — report it as the headline finding.
- **Mechanical ceremony done by the LLM**: Any contract step where the LLM computes, transcribes, or verifies values a script or git could own (hashes, IDs, counters, hand-made snapshot copies) is both token waste and the dominant error source. The contract should let the LLM declare intent and let a script stamp and verify.
- **Fail-closed composition**: A fail-closed contract running under an orchestrator that treats `blocked` as terminal and unretryable guarantees whole-run death on a single mechanical slip. Check what the surrounding runtime does with each contract state before adding more gates; tier ceremony by risk and provide a lite path plus an automatic doctor for weaker models.
- **Validator signal value**: Run the system's own validator and count standing errors. A permanently-red validator has zero signal — new failures drown in old noise; require fix-or-legacy-freeze.
- **Proposal shape when the owner asks "review and give me N improvements"**: deliver ranked options (highest value first), each with the specific lines/measurement it rests on, the concrete edit, expected effect, and cost. Close with an explicit "deliberately not doing" list — the owner reads judgment boundaries, not a menu. Every option must be **independently executable by name** ("execute option 1") without re-deriving the plan, and cite the real gap (grep first — do not re-propose something already in the file or the ops contract).

## Pitfalls

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
- **Cleaning host bytes out of a repo and then putting them back**: when a repo's contract forbids host paths / host-only tool names in its bytes, the sanitization log is the easiest place to reintroduce them — a "before" column quoting the original host path writes it straight back in. Describe each removed item generically ("a host checkout path inside the harness example"). Full port procedure: `references/repo-owned-skills-port.md`.
- **Layer-placed but never loaded**: Putting a rule in the "correct" layer is not enough if the runtime won't load that file for the owner's cwd. The protocol file loads only at its exact directory; an overlay file preempts it; only the identity file is global. Confirm load conditions before declaring a refactor done.
- **Crossing the loader wires**: The project-context file types use separate loader functions with different scopes. An overlay file's "walk to git root" is NOT the protocol file's behavior (which does no parent walk and ignores git). Never reason by analogy from one file's discovery to another — check the actual loader. (This skill's author made exactly this error mid-session.)
- **Hash-freezing the contract itself**: A contract that binds per-file content hashes of its own text into every launched object guarantees that each later contract edit invalidates all in-flight objects' bindings — drift errors accumulate by design, and repair commits become routine. Freeze state with a single git commit reference (change detection = `git diff <commit> -- <path>`), and never make the LLM the hash transcriber.
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
- **Stale section numbers after a renumber**: merging or deleting a numbered section silently breaks every hardcoded reference — profile deltas, team docs, and other files that cite "section 14" or a range. Grep the whole identity/ops layer for the retired number in the same edit; a doc that self-describes its structure must have no dangling numbers.
- **Profile delta restating a fact owned by another layer**: a per-profile delta must carry only differences. Restating a fact from the fact store (level, work hours) or a gate from the operating protocol creates a second copy that drifts silently — the fact changes once, one copy goes stale, and nothing errors. Point at the canonical file instead ("身份、作息见 <fact store>").
- **Whole-file rewrite blocked after a partial read**: a whole-file write may be refused when the file's current content was not fully read in this session, and an earlier full read stops counting once a targeted edit has changed the file. Re-read the whole file immediately before a full rewrite, or use targeted edits; otherwise the write bounces and burns a round trip.
- **Eval harness with live tools performs the red action it tests**: a case whose prompt says “just merge it, don't ask” was executed by a full-toolset one-shot session — it merged a real PR during a baseline run. Restrict gate cases to a read-only toolset (no shell/git) or a safe mode, never run destructive/irreversible cases on default toolsets, and check external state after every eval run.
- **Cases are discoverable anywhere on the filesystem**: moving them out of the workspace is not enough — a searching agent found the runtime-level `evals/cases.json` and quoted its own assertions back. Substitute a per-run nonce into prompt text and flag replies matching `cases.json|评测集|eval set` as contaminated instead of scoring them.
- **Background runs have no tty and silently poison terminal cases**: a suite launched as a background job failed its first terminal-dependent case and still reported a score. Run eval suites in the foreground so terminal-dependent cases stay valid.
- **Contract polish as displacement**: repeated rounds of identity/prompt refinement are high-feedback, low-risk, and unfailable — exactly the profile of an avoidance task. Before accepting another round, check whether a decaying deliverable exists (evidence log mtime, unpushed work, empty inbox, stalled plan) and say it once with the measured fact, then proceed with what was asked. Name the tradeoff; do not moralize and do not refuse the work.
- **Tooling that writes externally leaves an open red state**: a harness, script, or eval can perform an irreversible external action while testing for it. Do not unilaterally revert or “fix history” — surface the exact effect, offer keep vs revert, and after the owner decides, record decision + applied fixes in a durable incident note so it is never re-litigated. Reverting a legitimate change to undo your own process error punishes the repo for the wrong thing.
- **Narrow assertions produce false failures**: expect-regexes written from the rule text miss equivalent phrasing (“不值。别推倒。” failed a `不值得` pattern). Widen with the alternatives the rule actually permits before concluding the contract regressed; two of twelve baseline failures were assertion bugs, not behavior bugs.
- **Blocking questions answered mid-audit**: ask the pruning/risk question *before* the heavy edits, with 2-4 concrete levels (light/moderate/aggressive) expressed in measured savings — the owner picks a level, you execute the whole plan without re-asking.
- **Eval cases that encode a false premise**: a pushback case asserting "you said X earlier" sends the agent into session history, where it finds `cases.json` and quotes the assertions back. Write cases self-contained (put the claim in the prompt) and let `contaminated` count as FAIL, not neutral.

- **Migration without a reference sweep leaves dead paths**: moving a directory the contract names (an evidence path, a capture script, a bot fast-line command) turns every mention into a dangling path a later session follows into nothing. Grep contract, bot deltas, scheduled scripts and docs for the old path and update them in the same batch as the move — or keep the directory as the single documented exception until its batch runs.
- **Depth-limited inventory undercounts the move**: `find <dir> -maxdepth 2` showed five files in a ledger directory; the third level held the decision memo, two execution sheets, two review notes and a valuation script — all durable. Enumerate with `find <dir> -type f | sort` (no maxdepth), and treat `tar tzf` of the backup archive as the authoritative pre-deletion manifest, so "it only had five files" can never justify deleting real content.

## Verification

A successful operating-contract evolution should produce:

- clear layer placement for every new lesson
- backup path for each durable edited file
- final path(s)
- diff or meaningful change summary
- at least one proof of verification (read-back, diff, status, or command output)

## References

- `references/contract-evolution-case-study.md` — session-derived lessons from evolving an identity file and an operating protocol with a layered-architecture source.
- `references/context-file-loading-probes.md` — probe-based mechanics for identity/protocol/overlay/legacy agent files: exact discovery scope per file, the single-slot mutual-exclusion order, prompt-assembly tiers, the subagent blind spot, the globality decision, and the commands that verify it. Read this before deciding which file a rule belongs in.
- `references/agent-contract-system-review.md` — deep-review method for user-owned agent contract / control-plane repos: evidence to gather first (contract-surface count, overhead census, validator run, state history), over-engineering heuristics, ranked fix patterns (script-stamping, git content-addressing, risk-tiered lanes, state-machine collapse, doctor script, telemetry), and what not to break. Load before reviewing or optimizing such a system.
- `references/agent-repo-refactor-playbook.md` — execution counterpart to the review method: kernel flip (legacy file → real file + compat symlink), parity-first unification of scattered scripts into one CLI, validator exemption wiring, archive rotation with verbatim entry preservation, and pre-commit verification gates. Load before executing a refactor of such a repo.
- `references/repo-owned-skills-port.md` — moving host/profile skill copies into a self-contained repo: deciding repo-owned vs general per skill, the port + sanitize procedure, CRLF/LF fidelity when editing an existing repo, hash-binding safety checks, and the verification set that actually counts (validator before/after diffed, pinned dev env, remote SHA read-back).
- `references/asset-store-vs-workspace-routing.md` — splitting durable asset store from runtime workspace and encoding it in a contract: git-topology probes, reading the store's own layer table, extracting the real sync contract (allowlist roots, size cap, validation, refusal), verifying each claimed gate at the call site, the rule template, and migration batching.
- `scripts/contract-coverage-check.py` — run after any compression/rewrite of an instruction file: takes OLD, NEW and a markers file (one distinctive substring per rule), reports measured byte/rule-line deltas, flags markers that vanished or now appear twice, exits non-zero on loss.
