---
name: hoa-skill-set-audit
description: >-
  Use when asked to audit, prune or consolidate the whole set of skills a session is offered,
  across plugin, hub, project and repo sources. Finds overlapping or contradictory skills,
  shadowing, same-name drift, visibility mistakes, broken ../ closure and listing-budget
  truncation, ranks fixes and gives necessity verdicts. Also offers weekly recommendations from
  recent work. Not for reviewing one skill (hoa-skill-review), provenance or upstream freshness
  (hoa-skill-curate), or editing skills.
disable-model-invocation: true
metadata:
  revision: "2"
  areas: "software-development,self-management"
  targets: "runtime-agnostic"
  summary: "audit the whole offered skill set: per-skill quality, overlap, shadowing, contradictions, same-name drift, visibility, ../ closure, listing budget; report-only"
  summary_zh: "审计会话实际提供的整套技能：单项质量、重叠、遮蔽、指令冲突、同名漂移、可见性、../ 闭包、清单预算；只出报告"
  kind: "entry"
---

# Skill Set Audit

Audits the set the model is actually offered in this session — every source at once — not one
skill. The unit of harm is the set: two good skills with one trigger, a stale copy that wins the
bare name, a hidden child a parent can no longer reach.

## Gates

- **Report-only.** Do not edit, hide, disable, move, install or delete anything. A change needs an
  owner confirmation that names each skill and action; carry it out through
  hoa-skill-curate's execution procedure. Hidden is a selection decision, not authorization.
- **The listing is truth for "offered"; disk is truth for content.** Never reconstruct the offered
  set from disk or memory, and never judge a skill's content from its listing line.
- **Every finding cites evidence**: a listing line, an `inventory.json` field, or `file:line`.
  Zero usage is evidence, not proof of low value; an unclear owner scenario is `needs confirmation`.
- Re-read this file after compaction before continuing the passes.

## Configuration

| Input | Resolves | Default |
|---|---|---|
| `--host NAME` | add a host's documented roots (`claude`, `codex`, `pi`, `omp`, `opencode`, `dsh`) | none |
| `--root DIR` | any other root: custom dirs, a repo's `skills/`, roots the host config names | none |
| `SKILL_SET_AUDIT_ROOTS` | roots (`os.pathsep`-separated) when neither flag is given | unset |
| `--project DIR` | base for project-level host roots | cwd |
| `CLAUDE_CONFIG_DIR`, `CODEX_HOME` | host homes used by the presets | `~/.claude`, `~/.codex` |

`~` resolves per OS (`%USERPROFILE%` on Windows). Per-host roots, precedence, hide controls and
budgets: [references/hosts.md](references/hosts.md).

## Procedure

For a request to recommend skills from recent work, skip the audit and follow sections 1–3 of
[usage-based recommendations](references/usage-based-recommendations.md). Use a seven-day window,
return at most three Simplified Chinese bullets or `[SILENT]`, and never change state or schedule
a job in this mode.

1. **Capture the offered set.** Copy the host's skill listing from this session's context
   verbatim into a scratch file outside the repo, one `- name: description` line per entry.
   Keep entries that show no description — they are truncation evidence. If the host shows no
   listing, say so, audit disk only, and mark every offered-set claim unverified.
2. **Enumerate disk.** Pass every host in
   play in one run, so `duplicates.by_name` compares copies across hosts:
   `uv run scripts/inventory.py --host <host> [--host <host> ...] [--root DIR ...] --offered <listing> > <scratch>/inventory.json`.
   Exit 1 means findings exist — the normal case; 2 means no usable root or listing.
   `offered.not_on_disk` holds namespaced plugin entries (`plugin:name`, expected: plugin skills
   come from the listing) and built-ins; for any other entry, add the missing root.
   `offered-twice` marks one bare name offered more than once (e.g. a plugin skill plus a disk copy).
3. **Per-skill pass** (inventory `findings` plus reading). Trigger clarity: the first sentence
   says when to use, the description names an anti-trigger and no workflow steps. Length vs the
   caps of the hosts in play (`description-over-cap` applies the DSH cap only with `--host dsh` or
   an unlabeled `--root`; `listing-entry-over-cap`). Frontmatter validity and hidden-key form.
   Broken references (`broken-link`). Oversized bodies (`body-over-limit`). Bundled files the body
   never names (`unreferenced-file`) — a missing "Additional resources" list means the model does
   not know they exist.
4. **Set pass.** Work through the checks below on visible skills first, then hidden ones.
5. **Pruning and consolidation.** Assess each skill named in a set finding (or every skill when
   the owner asked for a full prune) on five axes: usage (recent, historical, unobserved — from
   the host's usage data, never from the name), overlap (unique, complementary, replacement
   candidate), core value (owner's main workflows, on demand, non-core), quality (clear, bulky or
   ambiguous, stale, risky, malformed), and necessity (non-inferable behavior or knowledge vs advice
   a capable model already follows unaided). Protocol duplicated across a skill family: read
   [skill family integrity](../hoa-skill-create/references/skill-family-integrity.md) and follow it.
6. **Verify adversarially.** Give an independent reviewer the claims, their evidence anchors and
   scope, not the finder's reasoning. Re-read the evidence or rerun the probe, try to refute each
   claim, and record what was checked and a `confirmed`, `weakened` or `refuted` verdict. Drop
   refutations and narrow weakened claims. Personally re-check the evidence for high-impact fixes
   and proposed deletions. If fresh context is unavailable, perform a separate verification pass
   and label it `single-context`; do not present missing evidence as verified.
7. **Report** and stop.

## Necessity verdicts

Give each assessed skill exactly one: `keep`, `keep explicit-only`, `merge into <name>`,
`cut`, `needs A/B`, or `needs owner`. State the evidence that earns it. Do not equate no
observed usage with no value. `keep explicit-only` is for valuable manual workflows; verify that
required sibling Read links still resolve. A single skill needing deeper judgment goes to
`hoa-skill-review`; provenance and upstream freshness stay with `hoa-skill-curate`.

For a locally authored skill with no upstream, the owner's rule is **180 days unloaded, or
never loaded** makes it a cut candidate, unless current projects suggest a plausible near-term
use. Use usage records with known coverage and directory history, not `SKILL.md` mtimes. Missing
usage data is `unobserved`, not evidence for a cut. Every cut stays a proposal pending explicit
owner confirmation.

Nominate at most five uncertain skills for A/B, and run probes only if the owner authorizes
the cost. Write two or three representative prompts and a rubric first. Run with and without the
skill in isolated environments, check the no-skill trace never loaded it, and grade responses
blind against the rubric. A skill that adds no verified value is a cut or merge candidate.

## Set-level checks

| Check | Evidence | Typical fix |
|---|---|---|
| Overlapping activation | `overlap` pairs (lexical candidates only), then read both descriptions against 2–3 realistic requests: would the model pick reliably? | merge, or narrow one description with a mutual anti-trigger |
| Contradictory instructions | the same situation governed by two bodies (commit rules, output format, authority) with different answers | one owner; the other points to it |
| Shadowing | `totals.visible_names`, plus a generic skill whose trigger swallows a specialist's | hide or retire distractors; keep the visible set small (hosts.md § Shadowing) |
| Near-duplicate names/descriptions | `overlap`, `duplicates.by_hash` | merge or retire the weaker |
| Same name, different content | `duplicates.by_name` with `same_content: false`; `offered-twice`; hosts.md says which copy wins per host | remove or re-sync the losing copy; pin the source |
| Visibility mistakes | `offered.hidden_but_offered`; `codex-policy-missing`; `hidden-codex-only`; a chained child absent from every root, or removed by a host deny/exclude setting | fix the frontmatter/openai.yaml pair; install the child; never deny a chained child |
| Broken `../` closure | `closure-*` findings: lexical and physical sibling must both exist and match | install the parent's whole `../` closure into the same root |
| Wrong discovery depth | `beyond-host-depth` | move the skill to the host's discovered level |
| Budget and truncation | `offered.without_description`, `totals.visible_description_chars` vs the host budget | shorten descriptions, hide rarely chosen skills |
| Horizontal knowledge in a skill | a skill every task needs, or one never selected while its content is always relevant | move it to an always-on index (AGENTS.md / rules) |

## Report

Lead with counts (offered, on disk, visible, hidden, per root) and the highest-confidence take.
Then findings ranked by harm — wrong skill selected or unreachable first, drift and budget next,
hygiene last — each with evidence and one concrete fix: `merge`, `narrow description`, `hide`,
`retire`, `move to always-on index`, `retain`, or `needs confirmation`. A deletion or merge
proposal states the replacement or the scope reason. Include the necessity verdicts with evidence
and the verification mode. For more than ~20 rows, write the full table
as CSV/JSON in the scratch directory and link it; never let a large inventory hide the decision.
End with what was not verified and an explicit statement that nothing was changed.

## Pitfalls

- **Do not use an old inventory as runtime truth.** Platform gates, disabled settings and
  malformed metadata make listing and disk counts differ; reconcile both before declaring totals.
- **`node_modules` phantom skills.** A vendored package can ship its own `SKILL.md`; loaders skip
  `node_modules`, so it costs no prompt. The inventory skips it — do not report or disable it.
- **Lexical similarity is a candidate list, not a verdict.** Low scores can still compete for
  one request; high scores can be complementary stages of one chain.
- **Do not patch a user-owned, bundled, hub-installed, external or pinned skill.** Report the
  boundary and recommend adoption or owner action.
- **Do not make a raw Markdown table the only deliverable on a channel that renders tables
  poorly.** Attach the CSV/JSON and give readable rows.

## Additional resources

- [scripts/inventory.py](scripts/inventory.py) — read-only root scanner; `--help` lists flags,
  JSON fields and exit codes.
- [scripts/test_inventory.py](scripts/test_inventory.py) — its tests on synthetic skill trees.
- Only if a script command fails (for example `uv` is not found), read [references/troubleshooting.md](references/troubleshooting.md).
- [references/hosts.md](references/hosts.md) — per-host roots, precedence, hiding, listing budgets,
  shadowing evidence.
- Sibling: `../hoa-skill-create/references/skill-family-integrity.md` — auditing a protocol duplicated
  across one skill family; install `hoa-skill-create` into the same host root.
