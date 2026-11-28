---
name: llm-corpus-structuring
description: Use when structuring an OCR corpus into verified data.
version: "0.1.0"
license: MIT
metadata:
  version: "0.1.0"
  areas: "research,data"
  targets: "runtime-agnostic"
  summary: "scanned/OCR corpora → structured items: structure pass first, one call per unit, verbatim evidence, mechanical validation"
  summary_zh: "扫描/OCR 语料结构化：先做结构识别、按单元调用、evidence 逐字校验、机械验证"
  kind: "controller"
  produces: "structured-dataset"
  hermes:
    tags: [ocr, corpus, extraction, validation, dataset]
    related_skills: [evidence-backed-analytical-writing, owner-decision-requests]
---

# LLM corpus structuring

Turn a scanned or OCR'd corpus (exam book, manual, forms dump) into structured records a program can
consume, with provenance strong enough that a wrong record is caught before it ships. The model is the
extractor; the operator owns structure, validation and the accept/reject line.

## When to use

- "Clean up this PDF corpus and give me structured data", "strip the noise so our program can use it".
- Any batch where the source is images or OCR text and the output is JSON records.

Not for: a handful of pages (read them), or text that already parses with a real grammar.

## Procedure

### 0. Settle the data boundary before the first model call

If the source is marked internal-only, unlicensed or private, externalising it creates a third-party
copy and that risk belongs to the owner — ask, and record the answer next to the artifacts: who
consented, which provider and endpoint, which file range, what it will not be used for, and how the
batch can be revoked. Keep every derived artifact outside the public repo; the private boundary is the
local database, not a directory name.

### 1. Inventory the corpus, then rule-clean it idempotently

Count pages, bytes, lines; split native-text pages from OCR pages; classify lines (body, blank, page
number, running head, item entry). Then a rule pass with **no network**: drop page numbers, collapse
repeated blank lines, normalise CJK-only spacing.

- Classify a running head by **position at the page edge PLUS a structural-label whitelist**, never by
  "this short line repeats across pages" — the second rule eats `Part A`, `Text 1`, `Questions 13-18`
  and any repeated section banner, and you will not notice until the structure is wrong.
- Make the pass idempotent and prove it: run twice, require byte-identical manifest and per-page
  sha256. A cleaner that drifts between runs cannot be re-run after a fix.

### 2. Recover the STRUCTURE before extracting anything

This is the step page-level extraction always skips and always regrets.

Build a compact overview — one line per page: page number, item count found, answer count, the item
numbers present, and the first two or three text lines. One model call over that overview returns the
units: `{name, kind, item_pages, answer_pages, item_count, index_range}`.

Why it is mandatory: books reuse numbering across units (six mock papers all numbered 26-55), and a
single item's stem, options and answer live on different pages. A page-local pass therefore cannot pair
an item with its answer, and it silently splits stems from option lists. An index-regression or
"section label" heuristic is not a substitute — per-page labels flap between adjacent pages of the same
unit.

Sanity-check the returned structure against the corpus: unit count × items per unit should match the
answer-side block count, and every page range must lie inside the corpus.

### 3. One call per unit, never per page

Give the call the unit's item pages **and** its answer pages in one prompt, separated by explicit
`=== PAGE NNN (role) ===` markers, and state the expected item count and number range in the prompt.
Pairing then happens inside the call where both halves are visible; nothing has to be guessed
across calls.

### 4. Pin the prompt contract

Numbered, non-negotiable rules, in the prompt:

1. Output exactly N items covering the stated range — a missing item is a defect, so list the answer
   page's numbering first and reconcile.
2. Copy stems and options character-for-character: no translation, no summarising, no completing a
   word the OCR dropped.
3. Fill an answer only from text that states it; otherwise `null`. Never infer.
4. `evidence` must be a sentence that exists verbatim on the item's own page.
5. Stems cut across a page break are rejoined without ellipsis.
6. Option count follows the item type — a matching item may legitimately offer 7 labels and a banked
   cloze 15. Do not normalise to four.

Prompt skeletons: [`references/prompt-recipes.md`](references/prompt-recipes.md).

### 5. Pilot one unit, grade it, then batch

Run a single unit and grade it before spending the corpus: items vs expected, answers present,
evidence verbatim hits, option-count histogram. If evidence hits are near zero the prompt is wrong
(models paraphrase silently) — fix the prompt, not the data.

### 6. Repair the quote field in its own pass, then anchor it to the page's own bytes

`evidence` is the field models paraphrase most, even under an explicit "copy verbatim" rule: a fill-in
blank `(19)___` comes back as `(0)...B...`, lines get joined, spaces normalised. The rest of the record
is fine, so do not re-extract it — re-pairing whole items to fix one field costs the corpus and can
change answers that were already right.

- **Repair pass:** one call per unit with the same unit text plus the `index → answer` list, asking only
  for the copied sentence per index (`{"index", "sentence"}`, `null` where none exists). Same input,
  short output, so it costs a fraction of the extraction and recovers most of the field in one go.
- **Anchor, do not trust:** never ship the model's rendering as the quote. Search the sentence's words in
  the page text with a sliding window — longest first (whole token list, then 12, 9, 7, 5 words) with
  `\W+` between tokens — and store the span **as the page wrote it**. Right wording with wrong spacing
  becomes a valid substring; wrong wording fails to match and the item stays unreviewed, which is the
  honest outcome.
- **One sentence for every item means the range is wrong.** If a unit's repair pass returns the same
  sentence for all its items, the passage spans pages and the unit's page range truncated it — the
  sentence usually belongs to a neighbouring unit. Fix the structure, not the prompt.
- Grade before and after, per unit. A field repair that moves a unit from a third to 28/30 is normal; one
  that stays flat means the range is wrong, not that the model is weak.

### 7. Validate mechanically, never by eyeballing output

- **Coverage against the structure pass**, not "how many did we get": expected vs extracted per unit,
  plus the explicit list of missing numbers.
- **Evidence containment**: enforce a minimum length so a three-character match cannot pass, then
  compare in the right order: **exact span against the raw body first, whitespace-normalised against a
  whitespace-normalised body second**. Flattening only one side is the classic false-negative — a
  verbatim quote that happens to span a line break is "not a substring" of the flattened page, so a
  whole batch of correct quotes grades as paraphrased and you go rewrite a prompt that was already
  working. Validate against **the exact bytes you will ship as the page body**, not against the raw OCR —
  when the judging corpus and the rendered corpus differ, correct evidence fails containment for no
  reason and the hit rate understates the batch.
- **Answer hit rate** and the label actually existing among the item's options.
- **Type histogram** to confirm the corpus really has the item shapes the prompt allows.
- Emit a per-item machine-readable report plus a human table; a single number is not a report.

### 8. Separate confidence tiers explicitly

Score each item on: answer present, evidence verbatim, stem non-empty, at least two options with the
answer label among them. Only that intersection may be marked reviewed automatically; everything else
stays unreviewed for a human, and the report states the counts. Never let "the model returned a record"
mean "the record is usable" — a wrong answer that enters a practice pool is worse than a missing one.

### 9. Emit an import shape plus a ledger

Per-item JSON files plus a page manifest, so the consuming program imports each record individually and
a single bad record is isolated. Keep an append-only ledger keyed on the input sha256 so a re-run skips
finished units, and let one unit's failure retry without aborting the batch.

### 10. Close the loop against the consuming program's real contract

Read the importer's parser before designing the output, and import into a throwaway store before calling
the batch done. Docs describe the shape; the parser decides which fields are mandatory. Then **exercise
the consumer's primary operation once** — start a run, generate a report, render the record — because
"223 records accepted" only proves the schema matched; it does not prove a user can do the thing the
corpus exists for. A single end-to-end call whose output you read (counts, the rendered fields, the
known-missing text) is the difference between a shipped batch and a pile of validated JSON.

- **Every field the program requires must exist in the source, or the decision is the owner's.** A schema
  that demands per-option reasoning for a book whose answer key explains only the correct option leaves
  two paths — generate the missing explanations (marked as generated, human-reviewed before use) or
  relax the program — and both change what a learner is told. Put it to the owner with costs; do not let
  the batch quietly fabricate, and do not relax a practice gate on your own.
- **While that decision is pending, keep the placeholder out of the stored record.** Stuffing
  `"not explained by the source"` into the missing slots makes the importer accept the batch today, but
  the string is indistinguishable from real content to every downstream consumer, and the decision then
  costs a full re-import. Ship the subset that genuinely has the field, leave the rest out, and say how
  many are waiting on the decision. The likely answer is that absence becomes a first-class state in the
  schema (a missing-key list such as `option_reasoning_missing: ["B","C"]` plus one presentation-layer
  string) rather than a value invented to satisfy a validator.
- **A schema change does not clean the rows already stored.** Once absence becomes a first-class state,
  every record imported under the old rule still carries the invented placeholder — the code is fixed and
  the data is not. Re-import the whole batch into a fresh store (an incremental import skips the keys that
  already exist and hides them), then read the consumer's own output as the acceptance proof: the human
  line for a missing field and the structured missing-key list, side by side. "The validator accepts it
  now" is a claim about the code, not about what the corpus contains.
- **Enumerate the schema's hard limits before extracting, not after importing.** A validator often caps
  something the source does not (this corpus: "has 15 options, want 2..8"), and the cap silently excludes
  an entire item type — 60 of 285 records — while every other field is perfect. Grep the importer for its
  bounds (option count, field length, label set) in step 0 and fold them into the structure pass, so the
  shortfall is a known number from the start instead of a surprise at import time, and the owner hears
  "one item type is out of schema" rather than "the import failed".
- **The manifest is a strict contract.** Field count, and any byte or character counts, must match the
  files exactly; unit numbering must be contiguous or the importer fills every gap with placeholder
  records. Re-import into a fresh temporary database and read the reported page and record counts back —
  "the directory exists" proves nothing.
- **Pick the unit boundary to match the program's holdout semantics.** If a passage spans pages and its
  items live on those same pages, ship one record per passage-set rather than per page; otherwise a
  learner sees an item without the text it tests, and sibling items get scored as independent units.
- **A listing command can spend exposure.** In a consumer that tracks exposure, commands that render
  records (`questions`, `show`, `list`) may record a presentation per record and silently consume the
  holdout pool before it is ever used — the pool then reports zero qualifying records and looks like a
  data defect. Read pool state **before** any listing, and run inventory listings against a throwaway
  copy of the store.
- **Reconcile per unit inside the store, not by the loader's totals.** "added 222, failed 62" hides a unit
  that arrived at 19/30 because one field was rejected record by record. Query the store grouped by unit
  and compare against the structure pass; a shortfall is a field-level rejection, and the field named in
  the rejection message is the worklist.

## Pitfalls

- **Item count is not quality.** A page-level pass can return plausible-looking records at 40% coverage
  with almost no answers paired; check coverage and pairing before believing any of it.
- **A page-level pass is salvageable as text, not as records.** If you extracted per page before
  recovering the structure, keep its page text (a model-cleaned page body is usually cleaner than the
  rule pass and worth rendering) and discard its items outright: re-pairing page-level items onto
  set-level answers never converges, because a page-local index carries no unit identity. Grade that
  pass by answer-pairing rate — near-zero pairing means the granularity is wrong, not that the prompt
  needs another tweak.
- **Do not lower the evidence threshold to raise the hit rate.** The fix for paraphrase is a stricter
  prompt plus a pilot; if the field still comes back rendered, repair that one field and anchor it to the
  page's own characters (step 6), never a shorter minimum.
- **A per-page section label is not a structural boundary.** The same unit gets three different labels
  on three adjacent pages.
- **Do not run the whole corpus on an ungraded prompt.** The cost of a wrong pass is the corpus, not one
  call.
- **HTTP 504 on a single unit is normal on free/slow pools** — retry with backoff and a per-unit failure
  row; do not restart the batch or conclude the provider is down.
- **Grades are per unit, not per corpus.** A 99% corpus average can hide one unit at 50%; report the
  weak unit by name and re-run it.
- **Re-grade the weak units, not the whole corpus.** Use the per-unit report as the worklist: clear the
  failing units' ledger rows and outputs, re-run only those, re-grade. Accepting a 90% hit rate while
  four named units sit at 50-70% is a decision to ship known-weak data.
- **An unimportable batch is worth nothing.** Reserve time for a real import against a temp store; a
  perfect 285-record extraction that the program rejects has the same value as an empty one.
