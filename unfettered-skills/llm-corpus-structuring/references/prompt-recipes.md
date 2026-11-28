# Prompt skeletons

Two calls do the work. Keep them separate: the overview call decides *boundaries*, the unit call
extracts *records*.

## 1. Structure identification (one call over the whole corpus)

Input: one line per page — `pNNN items=<n> answers=<n> item_numbers=<csv> answer_numbers=<csv> | <first 2-3 lines>`.

```
You are recovering the structure of a scanned book.
Known facts: items cluster on pages A-B, answers on pages C-D; item numbering REPEATS across units.
Return only JSON:
{"units":[{"name":"mock-1","kind":"mock","item_pages":[24,29],"answer_pages":[64,70],
           "item_count":30,"index_range":[26,55],"evidence":"<one clause>"}]}
Rules: judge from the data only; ranges must stay inside the corpus; when answer-block and item-block
counts disagree, say so in `evidence` instead of hiding it.
```

Grade the response before trusting it: `units x item_count` should match the answer-side block sizes,
and page ranges must not overlap.

## 2. Per-unit extraction

Input: the unit's item pages then its answer pages, joined with role markers, plus the expected count.

```
=== PAGE 024 (items) ===
...
=== PAGE 064 (answers) ===
...

Return only JSON:
{"unit":"<name>","items":[{"index":26,"stem":"...",
  "options":[{"label":"A","text":"..."}],"answer":"B",
  "evidence":"<verbatim sentence from the item page>","explanation":"<answer page note, may truncate>"}],
 "glossary":[{"term":"...","meaning":"..."}]}

Hard rules
1. Exactly <N> items covering <range>; reconcile against the answer page numbering first.
2. Stems and options copied character-for-character: no translation, no summary, no invented words.
3. `answer` only when a page states it; otherwise null. Never infer.
4. `evidence` verbatim from the item page; null if absent.
5. A stem split across a page break is rejoined, no ellipsis.
6. Option count follows the item type (4 / 7 / 15 are all valid).
7. Valid JSON, no raw newlines inside strings.
```

## 3. Validator checklist (code, not prose)

For each unit, with `page_text` = normalised concatenation of the unit's item pages:

```
normalise(t)    -> collapse all whitespace runs to one space, strip
coverage        : len(items) vs expected_count, missing = range - {index}
answer_ok       : answer != null and answer.upper() in [label.upper() for label in options]
evidence_ok     : len(normalise(ev)) >= min_len and normalise(ev) in normalise(page_text)
stem_ok         : len(stem.strip()) > 0
option_type     : 4 -> single, >4 -> bank-N, else partial-N   (report per unit)
high_confidence : answer_ok and evidence_ok and stem_ok and len(options) >= 2
```

Report per unit, then totals: expected, extracted, answered, evidence-hit, high-confidence, the weak
unit named explicitly, and the option-type histogram. Fail the batch on a unit whose coverage is below
the contract's floor rather than averaging it away.
