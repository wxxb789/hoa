---
name: evidence-backed-analytical-writing
description: >-
  Write an evidence-backed analytical report — Chinese policy briefs, capability assessments, or
  technical arguments that combine supplied claims with retrieved sources — by classifying every
  load-bearing number, building an evidence map, and drafting a uniform claim → evidence → mechanism
  → limitation spine. Use when the deliverable is prose whose every figure must survive an audit.
  Not for citation mechanics (that is grounded-citations), social posts, changelogs, or any piece
  where the claims are already verified and only the wording needs work.
metadata:
  version: "0.1.39"
  areas: "work-management"
  targets: "runtime-agnostic"
  summary: "evidence map plus a claim → evidence → mechanism → limitation spine for Chinese analytical reports; recency window, status ladder, negative findings"
  summary_zh: "中文分析报告：证据地图与「主张 → 证据 → 机制 → 局限」骨架；时效边界、状态阶梯、否定性结论"
  kind: "entry"
---

# Evidence-backed analytical writing

Use this skill for Chinese analytical reports, policy briefs, capability assessments,
and technical arguments that combine user-supplied claims with retrieved evidence.
It complements `grounded-citations`: this skill governs claim hygiene, structure,
and user-facing prose; `grounded-citations` governs the citation ledger and source
rendering.

## Procedure

1. **Normalize the brief.** Extract the requested language, approximate length,
   section count, section symmetry, audience, required claims, and requested
   source recency. Preserve the requested point order and visible form: when the
   input uses “一是/二是/三是” analytical paragraphs, keep that numbered
   structure unless the user asks for a different format. Do not preserve an
   unsupported number as fact. Locate any project style contract (`style/*.md`) before
   drafting and copy its bans into the QA checklist — contracts may forbid direct “我军”
   address (use 军队/相关力量) or require “要/应” imperatives in recommendation sections;
   contract wording overrides a prior draft's convention.

2. **Set the recency boundary before searching.** When the user asks for
   “最新/近期” data, establish a cutoff date, search current official releases
   first, and label older figures as trend baselines rather than current status.
   Prefer current summary-level statistics over a pile of newly published case
   stories; a newer anecdote is not automatically better evidence for a fleet-
   or system-level conclusion.
   A relevance-ranked search tool does **not** honour a recency window on its own: it
   will return pre-window material for a query that merely reads as “recent”. Put the
   window in the query text, forbid the fallback explicitly (“if nothing exists after
   <date>, say exactly that — do not fill the gap with older material”), then audit the
   returned source list and drop every item below the window floor before it reaches the
   evidence map. When a round leaks, keep it as a trace and re-run those routes — only
   the enforced round is admissible.
   A model-backed search tool may also answer from its own knowledge **without searching
   at all**; such an answer reads confident and well-structured. An answer with an empty
   source list is a lead, not evidence — never register or cite it.

3. **Classify every load-bearing claim before searching.** Mark each number as
   inventory, procurement, project target, type count, prototype/test result,
   or analytical estimate. Record scope, date, unit, and whether it describes a
   fielded capability or a plan. Use `references/claim-audit.md` for the wording
   decision.

4. **Build an evidence map before drafting.** For each important claim, record
   `claim → source → exact figure/date/scope → safe interpretation`. Prefer
   official government, audit, program, and primary technical sources. Use
   secondary reporting only for context or when the primary source is unavailable;
   label the limitation instead of laundering it into certainty.

5. **Resolve incompatible denominators.** Do not add or compare procurement
   quantities, fielded quantities, model counts, prototypes, and cumulative
   historical purchases unless the source defines a common denominator. When a
   supplied statistic cannot be independently supported, say so briefly and
   replace it with a sourced trend or metric.

6. **Draft each section with the same spine:** claim → measured evidence → mechanism or operational meaning → limitation → implication. Make the causal link explicit: unmanned-equipment application → change in personnel, process, visibility, or reach → resulting logistics characteristic. For a balanced multi-point brief, preserve the user's visible numbering and give each section comparable length and depth, normally within roughly 10–15%. Prefer a small set of fleet-, program-, or system-level summary metrics over many anecdotes; when the user asks for summary data and few examples, avoid platform-specific narratives unless the measured result is load-bearing, and do not let the final section become a case-study or data dump.

7. **Use precise status language.** Say “指标/计划/演示/试验/原型/已列装”
   exactly as supported. Separate deployed capability from a research demonstration
   and from a future aspiration. Convert absolutes such as “无死角” or “完全自主”
   into bounded claims about reach, exposure, endurance, or resilience. Rank every claim on the
   evidence-status ladder — 需求/概念 → 合同 → 试验/演示 → 交付/列装 → 有限使用 → 独立测量结果 —
   and never let one tier's evidence carry the next tier's conclusion (see
   `references/claim-audit.md`).

8. **Cite while drafting, not after.** Put inline citations immediately after the
   sentence carrying the figure or externally sourced claim. Register every source
   in the citation ledger before using its number, then render the Sources block
   mechanically — `grounded-citations/scripts/sources.py` owns both.

9. **Run a source-to-claim audit after edits.** After adding, removing, or
   reordering sources, inspect each citation number's title/topic against the
   sentence it supports. For an independent draft, reset the citation ledger
   before registering sources; for a continuation, preserve the existing ledger
   ids. Render the Sources block with `sources.py render --replace-in <draft>`
   before running `sources.py verify --strict`; stale registered sources can make
   strict verification fail even when the prose citations are correct. Ledger
   validation proves that an id exists; it does not prove that the page supports
   that claim.

10. **Deliver directly usable prose.** Default to concise Simplified Chinese,
   formal but readable report style, short paragraphs, balanced numbered sections,
   and a short methodology/coverage caveat when the input contains shaky figures.
   Put long source lists after the body; do not bury the requested deliverable
   under research narration.

## Negative findings and evidence backfill

When a question is answered by the *absence* of evidence, the negative finding is
itself a claim and must be auditable:

- Record it as a search-type conclusion (检索型结论): state the search window and the
  inclusion criteria — "在 <窗口> 公开材料中未见案例" — never as a capability
  statement in either direction.
- Attach an exclusion table: every item that superficially matches but fails the
  criteria, one row each with the disqualifying reason (enterprise/civilian source,
  theory article, modeling study, threat-role appearance, wrong service or echelon,
  foreign case). Without it, a later session rediscovers one of those items and
  cites it as evidence for the very claim the search refuted.
- Never substitute a foreign, theoretical, civilian, or adjacent-service example to
  fill a domestic gap; the gap is the finding.

Incremental re-verification (backfill) after an evidence packet or report is frozen:

- Do not mutate the frozen packet/report that already produced drafts; append an
  addendum and extend the verification log with a new dated batch, then state
  explicitly whether any existing claim was invalidated and whether the delivered
  report needs revision — "no change needed" is a valid recorded outcome.
- For each re-verified candidate, fetch the original full text and quote the exact
  phrase before logging it; fix provenance — an aggregator or reprint (a portal
  carrying another outlet's story) is not the original publisher.
- Some candidates exist only as a **bibliographic record** — title, authors, journal, volume,
  DOI — with the full text behind a paywall, a login wall, or a thesis catalogue. Log those as
  bibliography-level verification and say so in the batch, and forbid citing their findings: the
  record proves the paper exists, not what it concluded. Marking the tier keeps them usable as
  leads without letting a later draft borrow a conclusion nobody read.

## Final-report sourcing style (简单出处)

Final reports can use light sourcing by design: name the outlet inline in the prose
(《解放军报》、中国军网、国防部网 …) and close with a single `来源：` line naming the outlets and
the year window. No numbered reference list and no `[n]` markers in the final deliverable —
numbered citation machinery belongs to working drafts and process records only. When a numbered
draft is converted to this style, invert the QA checks: verify zero `[n]` residue, a present source
line, and a complete closing sentence, instead of keeping a marker-count gate.

## Multi-model draft iterations

Long-form reports can run as a multi-model draft line: a frozen packet (context + material +
skeleton × style variants) goes to several writer models; each draft's filename encodes what
produced it; the operator reviews with line-level comments and dictates each iteration.

- **Frozen stays frozen.** An approved final is not edited in place — it is `final v01` and stays
  byte-identical. Improvements run on a separate draft line (`drafts/`), and only the operator
  promotes a draft to a new final.
- **Name drafts by provenance dimensions:** `draft-vXX-<skeleton>-<style>-m-<model>` — iteration
  number, skeleton version, style version, model short name. Record the version map (which code =
  which skeleton/style, model short names) in the project's drafts README the first time; never leave
  the mapping only in chat.
- **The pattern's dimensions are the scope.** When the operator supplies such a pattern and asks for
  drafts, they mean every combination of the stated dimensions; an example model written inside the
  pattern is a format sample, not the target set. Generate the full matrix (skipping combinations
  that already exist), not one sample file.
- **The loop is comment-driven.** After a draft lands, the operator returns comments (quoted text +
  instruction); apply them as the next `vXX+1` for that combo, preserving the prior draft and
  receipts. Do not self-iterate or auto-promote to the final line.
- **Reuse the frozen packet; do not re-run completed discovery.** Draft waves build on research that
  already exists — redoing established discovery is waste the operator explicitly rejects.

## Always-on quality rules

- Never fabricate a current inventory, percentage, type count, performance figure,
  or effectiveness result to make the argument sound complete.
- Put units, time period, platform/status, and source scope beside every important
  number; a bare number is not evidence.
- Treat “can theoretically do X” as a capability implication, not proof that X
  has been operationally achieved.
- Preserve a clear boundary between fact, inference, and judgment; signal the
  boundary in the prose when it affects the conclusion.
- For “约N字,” aim for the requested length within roughly 10–15% unless the
  evidence needed to satisfy the brief makes that impossible; state the actual
  approximate length if materially over or under.
