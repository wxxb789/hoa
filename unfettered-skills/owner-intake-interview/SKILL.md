---
name: owner-intake-interview
description: "Use when filling a template from owner knowledge via Q&A."
version: 1.0.0
author: Zoe
license: MIT
metadata:
  hermes:
    tags: [intake, interview, template, owner-facts, career]
    category: productivity
---

# Owner intake interview

Fill a structured document (baseline sheet, intake form, decision-memo inputs) from knowledge only
the owner holds — numbers about their job, systems, accounts, before/after changes. The deliverable
is a file where every entry traces to an owner answer, not to a plausible guess.

## When to Use

- A template has blanks that need private owner facts: tenant counts, volumes, timings, staffing,
  what changed and by how much.
- Not for facts that are lookup-able (calendars, ledgers, repos, monitors) — retrieve those instead
  and mark them as sourced.

## Procedure

1. Read the template first and list its exact fields, labels verbatim. Those labels are the
   downstream contract; do not rename or restructure them mid-fill.
2. Ask **one question per message**. When the owner says "依次逐个 / 一个一个来", they mean it:
   a batch of questions gets partial answers and the missing ones cost a second round.
3. Offer ranges as choices (2–4, recommended first) and let the free-text row carry the exact
   number; don't enumerate options inside the question prose.
4. Patch the file **immediately after each answer** (field label + answer). Never collect and write
   at the end — an interrupted session must not lose answers already given.
5. Keep the owner's own unit and qualifier. Derived equivalences go in parentheses, labelled as
   derived: `每季度 5–10 张（3 个月 renew 周期）≈ 每月 2–4 张`.
6. Unknown → write the template's own TODO convention (`TODO(问人)`), never invent a number to
   make the sheet look finished.
7. On clarify timeout: stop. Do not re-ping or re-ask the same question. Save state, then report
   "N of M fields done, remaining: <field>", plus the single open question so it can resume later.
   If the owner answers out-of-band afterwards (a plain message carrying the missing fact), treat that
   as the answer: re-read the file, patch that field, and continue from the next empty one — never
   restart the round or re-ask fields already recorded.

## Pitfalls

- **Compound questions stall.** A field needing a comparison (before → after, two metrics in one
  line) often gets zero answers. Ask the concrete observational question first ("人工介入一次大概
  多久"), then the comparison, then derive the sentence yourself.
- **Don't manufacture precision.** `5–10 per quarter` is not "8 per month"; record the range and
  label any arithmetic as derived. Promotion/career sheets get quoted verbatim later.
- **A "一句话" field is built, not asked.** Interview the concrete observations first (before-state,
  per-unit time, incident history, cause of the one incident), then write the draft sentence into the
  file together with a short supporting-facts block (each number traced to an owner answer, derived
  arithmetic labelled) and a one-line claim boundary stating what the numbers do and do not support
  ("人工减半 + 根因定位成立；零事故不成立"). Then ask the owner a single approval question
  (定稿 / 再收一版 / 自己改). If the delta is still unavailable, write TODO naming exactly what is
  missing (before-state, baseline, error rate) — never a plausible sentence that sounds measurable.
- **Record the claim boundary in the file, not just in the chat.** These sheets get quoted verbatim
  later; a number without its boundary turns into an overclaim the owner cannot retract.
- **The file is the state.** Re-read it before resuming; do not trust conversation memory about
  which fields are still empty.
- Do not ask for facts you can retrieve yourself (tenant inventory in a repo, amounts in a ledger).
  Burning an owner question on a lookup is the main cost of this format.

## Reporting

Close each round with a compact filled summary (one bullet per field), what remains, and the one
next step. Short, answerable, no essays.
