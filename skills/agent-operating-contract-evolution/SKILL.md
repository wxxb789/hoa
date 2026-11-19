---
name: agent-operating-contract-evolution
description: >-
  Evolve an agent's operating contract: its identity file, operating protocol, layered memory /
  skills / config, and any repo whose product IS an agent contract or control plane. Use when asked
  to optimize, review, or refactor those files, or when the owner corrects how the agent approached
  identity, routing, delegation, or persistence. Not for ordinary repo coding rules, and not for
  one-off task notes.
metadata:
  revision: "3"
  areas: "software-development,work-management,self-management"
  targets: "runtime-agnostic"
  summary: "evolve an agent's identity file and operating protocol by layer, with coverage markers, behavioral evals, and load-scope probes"
  summary_zh: "按分层演进 agent 身份文件与操作协议：覆盖标记、行为评测、加载范围探测"
  kind: "entry"
---

# Agent Operating Contract Evolution Skill

## Gates (hold on every path)

- Back up Yellow edits before writing; if the owner asked for a draft, do not edit.
- Compression changes no rules. Declare one marker per rule before editing and verify coverage.
- An authorization-boundary change is a cross-file invariant: grep all layers, change every hit
  in one pass, and restate unchanged limits (no force-push, no history rewrite, no secrets in Git).
- Protected instruction files require approval; timeout is not consent. Do not retry or bypass
  with another tool. Leave the file unchanged, discard its redundant backup and report blocked
  or contradictory lines and the exact pending edit.
- Run gate evals with read-only tools or safe mode; never run irreversible cases with default
  tools. Check external state. If a tool wrote externally, report the exact effect and ask
  keep vs revert; never silently revert. Record the owner's decision and fix.
- Do not edit runtime source to fix contract behavior. Probe what actually loads before moving
  a rule; explicitly pass needed rules to subagents that skip context files.
- Profile deltas carry differences only; regenerate profiles from root + delta and repair section pointers.
- Verify store ownership and an alleged gate's implementation and call site before asserting it.
  Sweep old references in the same migration batch; inventory the full depth before retirement.
- Measure behavior before and after contract edits; keep cases outside the workspace and fail
  contaminated runs. Never describe same-family reviews as independent.

## When to Use

Evolve or audit identity files, operating protocols, team-agent definitions, or user-owned
agent contracts/control planes (research, orchestration, evidence pipelines). Trigger on owner
corrections to identity, workflow, formatting, delegation or persistence. Not for one-off notes
or ordinary repo coding rules unless the task is explicitly about agent behavior or operating
contracts. For a kernel flip or a control-plane refactor, read the
[refactor playbook](references/agent-repo-refactor-playbook.md). For repo-owned skill placement,
read the [port procedure](references/repo-owned-skills-port.md).

Triggers: "evolve your soul", "audit every identity file", "work async", "keep files organized"; unifying or retiring scattered scripts or making them portable across harnesses goes to the refactor playbook.

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
- Prove no rule was lost: `uv run scripts/contract-coverage-check.py OLD NEW markers.txt` (declare one distinctive substring per rule before editing, check after). Only if a script command fails (for example `uv` is not found), read [references/troubleshooting.md](references/troubleshooting.md).

Compress rules, not exemplars. Keep voice anchors like "the assistant you'd actually want at 2am": deleting every anchor flattens the voice; no added rule restores it.

Apply density to **instruction files only**. Your own replies to the owner stay human-facing; compressed chat is telegraphic and unreadable. The contract should require full sentences, one idea per line, and explicit causal links.

## Measure the real per-turn prompt before optimizing

Instruction files are only part of the per-turn cost. Pull the runtime's own assembled prompt from its
persisted prompt record, measure section sizes by marker, and cut the largest reducible block — usually
the skills list, pruneable through the runtime's disabled-skill list on the root config and every profile.
Procedure, measured numbers, verification (one-shot + compare same prompt hash family), the append-log
staleness trap, and the drift-guard script pattern: `references/context-budget-measurement.md`.

## Route by task

- **Behavior:** use [behavioral evals](references/behavioral-evals.md) before and after contract
  edits; keep 10–15 one-shot cases with expect/forbid patterns and compare raw outputs.
- **Loading:** read [context-file-loading probes](references/context-file-loading-probes.md)
  before choosing a rule's layer; verify the loader, cwd scope, and slot precedence.
  Rules that must hold regardless of cwd belong in the identity file; an overlay preempts, it does not add.
- **Persistence:** read [storage and routing probes](references/asset-store-vs-workspace-routing.md)
  before writing ownership or sync rules; read [vault migration](references/knowledge-vault-migration-execution.md)
  before executing a migration.
- **Review:** read the [system review method](references/agent-contract-system-review.md) and its
  operating-contract checklist before reviewing or optimizing a control plane.

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
   - Preserve what works, merge duplicates, and gate overbroad routes. Write trigger → action → proof.
   - For compression, use the marker check above; rule changes need their own approval.

6. **Back up before durable edits**
   - Timestamp the backup for Yellow edits (identity, protocol, config, skills, team docs).
   - Apply and verify; report final and backup paths and the meaningful diff.

7. **Regenerate the derived identity layer whenever the canonical identity file changes**
   - Reconcile generated profiles from root plus deltas; check wrapper flags, then verify drift,
     phrase presence and section counts. Fix stale section pointers in the same edit.
   - Follow the reconcile and renumber procedure in [pitfalls](references/pitfalls.md).


8. **Run a self-evolution pass after meaningful sessions**
   - What friction happened?
   - Which layer should absorb the lesson?
   - Should a skill be patched/created?
   - Are there duplicate or stale rules to tighten?

## Verification

A successful operating-contract evolution should produce:

- clear layer placement for every new lesson
- backup path for each durable edited file
- final path(s)
- diff or meaningful change summary
- at least one proof of verification (read-back, diff, status, or command output)

## References

- [Contract evolution case study](references/contract-evolution-case-study.md): voice and layered architecture.
- [Context budget measurement](references/context-budget-measurement.md): assembled prompt and drift checks.
- [Context file loading probes](references/context-file-loading-probes.md): discovery, precedence and verification.
- [System review](references/agent-contract-system-review.md): evidence, overhead, review checklist and fixes.
- [Repo refactor playbook](references/agent-repo-refactor-playbook.md): kernel flips, parity and pre-commit gates.
- [Repo-owned skill port](references/repo-owned-skills-port.md): placement, sanitization and read-back.
- [Asset store routing](references/asset-store-vs-workspace-routing.md): topology, gate proof and batching.
- [Knowledge vault migration](references/knowledge-vault-migration-execution.md): inventory, links and retirement.
- [Behavioral evals](references/behavioral-evals.md): cases, before/after comparison and contamination risks.
- [Pitfalls](references/pitfalls.md): edits, renumbering, review and migration.
- `scripts/contract-coverage-check.py` and `scripts/contract-eval-run.py`: coverage and behavior.
