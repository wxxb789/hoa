# Batch LLM Distillation Pipeline

Recipe for distilling a large corpus of reports/partial research into <notes-vault> garden
notes via a one-shot LLM (default `deepseek-v4.1-flash-fast` on `tencent-litellm`), in background batches.

## Model call (text-only one-shot)

```bash
hermes chat --query-file <prompt.md> -m deepseek-v4.1-flash-fast --provider tencent-litellm \
  -t clarify -Q --ignore-rules --max-turns 1
```

- `-t clarify` is the ONLY inert toolset: `-t ""` leaves ALL tools enabled (the model
  writes files itself and emits diff previews into stdout, corrupting parsing);
  `-t none` is rejected as an unknown toolset name.
- Use `--query-file`, never `-q`, for arbitrary text (no shell reinterpretation). A report body
  pasted inline through `-q` is the fragile version: shell quoting, metadata headers and the
  model's own opener all land in the same string, and a single stray backtick pair changes what the
  model sees. Write the composed prompt to a file under the scratch dir and pass that path.
- Post-process stdout: strip the trailing `session_id: ...` line; normalize absolute
  home paths to `~/`.

## Prompt contract (the output must satisfy this or the item fails)

- First line is `# <title>` (≤30 chars); fixed skeleton after it:
  `## 结论` → `## 关键机制与数字` → `## 反方 / 失效条件` →
  `## 判断` (bold **Fact / Inference / Judgment / Low confidence** each present) →
  `## 来源` (original path + date).
- ≤120 lines; tables ≤6 columns; no HTML; no invented numbers — absent numbers are
  forbidden, uncertain claims marked Low confidence; paths/commands/identifiers stay
  verbatim.
- Long sources: cap input at ~60K chars and tell the model it is truncated.

## Validation and failure isolation

- Tolerant H1: drop any chatty preamble lines before the first `# ` line, then require
  the first remaining line to be the H1 — models add "here is the note:" openers.
- Reject outputs >160 non-blank lines.
- Lint inside the vault before considering the item done
  (`markdownlint-cli2 -- <relative path>` from `<notes-vault>/`); on failure, retry ONCE
  feeding the lint errors back; still failing → move the file OUT of the vault to a
  `staging/failed/` dir and record `lint-failed`. Never leave a failing file in-tree
  (one bad file blocks the whole repo auto-sync, which is fail-closed).

## Ledger, batching, idempotency

- Append-only JSONL ledger keyed by source path; statuses:
  `ok` / `error` / `lint-failed` / `blocked-skip` / `military-queued` /
  `military-archived` / `no-material`. Re-runs skip statuses in the terminal set —
  the pipeline is resumable from any interruption.
- Batch by source size bands (e.g. ≥100KB / 40–99 / 20–39 / 10–19 / <10), ~3 workers
  of parallel one-shot calls; each batch is a separate invocable run.
- Stall guard: if a batch completes with zero new `ok` rows, abort the loop instead of
  spinning.

## Domain routing

- Keyword-classify topic + title + first ~4K chars into a garden domain
  (`ai dev security fin algorithms interview-prep`); default `dev` and flag for review.
- Military/defense guard first: matches queue to nana intake (see SKILL Rule 9), but
  EXPECT false positives (a SAR-imaging paper hits "雷达", a Tesla FSD post hits
  "监管") — review each queued item manually before overriding with a
  `--military-off` style re-run; verified-real ones go to nana raw intake.
- Target path: `garden/<domain>/research-notes/<source-date>-<topic-slug>.md`; add an
  auto-generated `_index.md` per domain and one parent link from the domain `_index.md`.

## Research-completion variant (sources with no final report)

- Concatenate the directory's md files (size-desc, capped) and ask the model to write
  the missing `REPORT.md` with a `完成度: high|medium|blocked` line near the top.
- `blocked` means the material is only failure logs / off-topic fragments — the honest
  output is "research not completed, blocked at X", NOT fabricated conclusions.
  Blocked reports are skipped by distillation (`blocked-skip`) but still count as
  terminal for cleanup purposes.

## Promoting an archived research tarball (existing reports, missing notes)

When the corpus already exists as `research/<date>/<slug>/{PLAN.md,REPORT.md,evidence/**}` inside a
backup tarball, the job is coverage triage plus distillation — not discovery. Working script:
`~/.hermes/scripts/research-promote-batch.py` (queue in, ledger out, per-item isolation).

1. **Decide coverage by filename stem, not by directory.** A note already exists if any
   `garden/*/research-notes/` stem equals or starts with `<date>-<slug>` — the note's domain is
   decided at distill time, so searching one domain dir produces false "missing" results.
2. **Write both lists before writing any note.** Queue = has a `REPORT.md` and the report contains a
   conclusion; archive = everything else, each with a reason (`no REPORT`, machine scratch dir such as
   `tmp/` or `x-post-analysis-<N>/`, daily hot-topic dump, non-kebab slug). The archive file is the
   decision record; a skipped item that exists nowhere reads as an oversight six months later — keep the
   accounting closed (`promoted + archived = uncovered`), because two unlisted items are what turn a
   finished pass into a silent gap.
   **Report size is not evidence of knowledge.** A 3 KB `REPORT.md` is just as likely to be a failure
   narrative — "all six fetch paths returned nothing", "only `PLAN.md` exists", "material never touched
   the question" — as a real finding. Size-banded triage therefore promotes incident logs into the
   knowledge garden, and unpicking them later costs a second full review. Triage on whether the report
   states a conclusion, and make the model refuse the rest (`SKIP: <reason>` in the output contract,
   handled as an archive row) instead of trusting your own size filter.
   - **Slug validity is a ledger row, not a silent skip.** `slug` must be kebab-case ASCII: a Chinese
     title or a YouTube id with uppercase letters cannot become `<date>-<slug>.md` without inventing a new
     name, so record it as archived with that reason rather than dropping it from both lists.
3. **Prompt rule beyond "no invented numbers": no gap-filling either.** If the report does not
   answer the question the slug implies, the note says so — a `REPORT.md` that never touched the
   topic yields a note whose 结论 is "this cannot be concluded from the material, status blocked"
   plus what it *does* support. That output is a success, not a failed distillation.
4. **Validate the frontmatter template, not just the title.** The 479 existing research notes carry
   `title / type: concept / status / created / updated / source_date / source_path / distilled_by /
   publish_candidate: false / tags: [research-note, <domain>, distilled] / category` — a missing
   field breaks the Base queries that read them. Reject before writing when: first line is not
   `---`, `category` is outside the domain enum, `## 结论` or the provenance string (`<date>/<slug>`)
   is absent, or the body is under ~300 chars. Every rejection is a ledger row with the reason, never
   a half-written note in the vault. **The model can pick one `category` and leave the template's example
   domain in `tags`** — rewrite `tags: [research-note, <category>, distilled]` from the parsed category
   after validation, or the note's tags disagree with the domain whose Base views are supposed to list it.
   Mismatches are invisible to lint and to sync, so nothing catches them later.
6. **Review the batch's titles before calling it done — and withdraw properly.** Titles are the cheapest
   quality signal there is: a page of "计划写了、正文没落盘" titles means the content filter failed, and
   deleting those notes is cheaper than a garden full of incident logs. Withdrawal is a three-part edit:
   delete the file, append a `withdrawn` ledger row carrying the reason, and add the source to the archive
   list. Deleting alone loses the decision, and the ledger's cumulative `written` count then overstates
   what the vault actually holds.
5. **Idempotency key is the target path glob** `garden/*/research-notes/<date>-<slug>.md` — the same
   reason as (1): the category is only known after the model answers, so a ledger keyed on the
   category would let a re-run write a second copy in another domain.

## Cleanup gates (destructive, last phase only)

1. Every source item has a terminal ledger status (`ok` / `blocked-skip` /
   `military-archived`); any gap aborts with the folder kept.
2. `tar czf ~/claw/backups/<source>-<date>.tar.gz` the whole source tree; verify the
   tar's file count equals the live file count.
3. Only then `rm -rf` the source tree; log before/after counts.
4. Final vault verification: `markdownlint-cli2 -- 'garden/**/research-notes/*.md'`
   0 issues, `vault.status` blocking_count=0, `.harness` unittest green.

Note: provenance `source_path` values in distilled notes become archival references
  to the backup tarball after cleanup — acceptable, the notes are self-contained.
