# Knowledge vault migration — execution

Use with `asset-store-vs-workspace-routing.md`. That file decides **whether and why** a store is the canonical home; this one is **how to move content in without losing or duplicating it**.

Applies to any Obsidian/Markdown knowledge store kept in Git and persisted by a scheduled sync job: layer map in its own kernel/structure doc, validation gates, allowlist roots, no hand-commits.

## 1. Inventory the source completely before promising a scope

```bash
find <src> -type f | sort          # NO -maxdepth: dated subfolders hide their payload one level deeper
du -sh <src>/*/ | sort -hr
wc -c <src>/**/*.md                # size per file, to spot real documents vs stubs
```

Classify every file into exactly one bucket — this decides destination, not the folder name:

| Bucket | Test | Destination |
| --- | --- | --- |
| Dated record | carries a decision, review, execution sheet, ledger snapshot | store's dated-record layer, content preserved |
| Distilled conclusion | says what is true, what we decided, why | synthesis layer (`garden/<domain>/`), rewritten short |
| Raw evidence | datasets, JSON dumps, scraped originals, imported reports | evidence layer (`sources/<domain>/`) with a provenance README |
| Procedure | how to run/repeat something | skill or store's procedure layer |
| Process | multi-round notes, intermediate drafts | stays in the workspace, expires |

A "cleanup" that skips classification deletes the decisions and keeps the drafts.

## 2. Map onto the store's own layers, not a parallel taxonomy

Read its kernel + structure doc first and copy its vocabulary: which layer owns policy, which owns dated operations, which owns evidence, which owns chronology, which is private. Then place each bucket. Rules that repeatedly decide placement:

- Dated decision memos and reviews often belong with operating records or the domain's dated-analysis folder — follow existing siblings, not your instinct.
- An empty registry/list in the workspace is usually already implemented as a Base/query view; do not migrate the empty table, migrate the rules it referenced.
- Procedure text that duplicates a policy page gets folded in as a pointer, not copied.

## 3. Write with the target's frontmatter and link conventions

Copy the shape from a neighbouring note in the same folder (`sed -n '1,15p' <sibling>.md`). Typical required fields: `title`, `type`, `status`, `created`, `updated`, `data_as_of`, `publish_candidate: false`, `tags`, `category`.

- `type` comes from the vocabulary already present in that tree (`grep -rh '^type:' | sort | uniq -c`) — inventing `procedure` where the store uses `playbook` breaks structure audits.
- `data_as_of` is mandatory on anything numeric; a record without it cannot be cited later.
- **Every new note in a maintained layer needs an inbound link from an `_index.md`/hub**, vault-root-qualified (`[[garden/x/y/note|label]]`). Unlinked notes become orphans and the health check is not run by the sync job, so the debt lands silently.
- Respect structure policy: maintained-synthesis layers generally refuse active `type: project` notes and catch-all status folders (`draft/`, `todo/`).

## 4. Bulk transfer: prepend frontmatter + rewrite old paths in one pass

For N>2 files, script it instead of hand-copying:

1. Read each source file, prepend its frontmatter block, write to the destination path.
2. Apply an ordered regex rewrite table for old → new references (old absolute path, old relative path, quoted forms, template placeholders). Emit a per-file hit count.
3. After writing, grep the destinations for the old path prefix — a non-zero hit is a broken reference you just shipped.
4. Leave one intentional provenance line ("content source: <old dir>, migrated <date>") so future readers can trace it; everything else must point at the new location.

Keep a script and a manifest in the workspace task folder; the next batch reuses both.

## 5. Validate with the pipeline's own gates before claiming done

```bash
markdownlint-cli2 -- '<touched files>'
<store>/../.harness/... run vault.status        # structure audit + prompts/templates
uv run --project <harness> python -m unittest discover -s tests -p 'test_*.py'
git status --short
```

All three must be green: the scheduled sync refuses the whole batch on the first failure, and a half-written migration then sits in the working tree looking finished.

## 6. Persistence belongs to the sync job, not to you

The sync runs on a timer, so it may commit and push **while you are still verifying**. Before reporting "uncommitted":

```bash
git -C <repo> log --oneline -3
git -C <repo> log --oneline origin/main -1
tail -5 <sync-log>
<runtime> cron list | grep -A5 '<sync job name>'
```

Report the real state (committed SHA + pushed, or the next tick time). Do not hand-commit to "finish" a migration — a pre-staged index is a refusal condition, and a hand-commit skips the secret scan.

## 7. Retire the source explicitly

1. `tar czf <backups>/<name>-<date>.tar.gz -C <src> <dir>` and **verify with `tar tzf`** — this listing is the deletion manifest.
2. Replace the directory with a short pointer README: where each kind of content now lives, backup path, and the unchanged hard rules.
3. Delete the moved content only after the pointer exists and the destination validated.
4. In the same batch, update every downstream reference: host contract, per-profile deltas, capture scripts, scheduled scripts, and the fact store entry that named the old path. A retired path that still appears in a profile delta resurrects a second source of truth.

## 8. Distilling a research backlog (not a copy job)

When the owner says "distill the research into the store", the workspace backlog is usually hundreds of sub-topic folders, each with a primary report plus process notes.

1. Inventory at sub-topic depth, not date depth: one row per `<date>/<sub-topic>` with markdown count, size, and whether a primary report exists. Write the rows to JSON in the workspace; aggregate in code, never by eye.
2. Pick exactly one input per sub-topic (the named report; else the largest note).
3. Emit a note of ≤120 lines: conclusion → mechanism/numbers → counter-case → judgment labelled `Fact` / `Inference` / `Judgment` / `Low confidence` → provenance line with source path and date.
4. Version-sensitive material (capability surveys, model lists, tool flags) carries `data_as_of` + version and an explicit "recheck after upgrade"; it is a snapshot, not evergreen truth.
5. Raw material goes to the evidence layer with a provenance README; process-only folders stay in the workspace and expire.
6. Link each distilled note from the domain `_index.md`, then lint + status.
7. Batch the rest by value density and get the owner's ordering; a 400-report backlog is several batches, and saying so early beats a heroic single pass.

### Running the distillation through a model at scale

8. Use a scripted one-shot model call, not a tool-using agent:

   ```bash
   <runtime> --query-file <prompt.md> --model <model> --no-tools --answer-only --max-turns 1
   ```

   `--query-file` (not `-q`) keeps arbitrary text out of shell/argparse parsing; strip the toolset so the model can only emit the note; answer-only output keeps the reply machine-readable; one turn prevents a wandering session. Flag names differ per runtime — keep the four properties, not the spelling. Strip the trailing session-id line the CLI appends. Normalize absolute host paths in the output back to `~/` — the model echoes them into the provenance line.
9. Gate every note before it stays in the store: write it, `markdownlint-cli2` that one file; on failure retry once with the lint errors appended to the prompt, then park the note in `staging/failed/` and delete it from the store. The scheduled sync is fail-closed over the whole tree — one lint-broken note blocks every future sync, including content unrelated to the migration.
10. Make the run idempotent with a JSONL ledger (source path → status). Crash and re-run skip `ok` rows; `error` rows and rerouted rows reprocess. Run as a background job (2–3 workers, batches by size bands, a per-batch log), and finish with fixed verification: ledger counts, lint over all new files, status `blocking=0`, and a sample quality read.
11. Tolerate chatty preambles: a compliant model still opens with “已读取原文，笔记如下：” before the H1. Drop everything above the first `# ` line; reject only when no H1 exists at all. Validate structure on the truncated output, not the raw one.

## Pitfalls

- **Depth-limited `find` undercounts.** Dated folders hide decisions/executions/valuation one level lower than the folder listing suggests; a five-file directory was twelve, including the only decision memo. Always `find -type f`, and let the tar manifest confirm.
- **Copying instead of folding duplicates policy.** If the migration creates a second description of the same rules, delete the source version in the same batch and leave a pointer; two live copies drift within a week.
- **Orphan notes pass local lint.** Markdownlint does not check graph connectivity, and the sync job's status call may skip link health entirely — adding the `_index` link is your job, not the linter's.
- **Reports and dated records are not "process".** Deleting a migration source after moving only the summaries loses exactly the artefacts an audit needs.
- **Paths inside migrated documents point at the old home.** Frontmatter moves cleanly; body text (source lists, `§` references, reproduction commands) keeps the old absolute path unless rewritten and grepped.
- **Domain synonyms create ghost top-level folders.** Classify against the store's actual domain directories (`ls <store>/garden/`), not natural synonyms — an `interview` label silently created a nonexistent `garden/interview/` beside the real `garden/interview-prep/`, and only a post-run directory check caught it. Validate every domain name against the directory list before the first write; move + frontmatter-fix after the fact works but wastes a verification cycle.
- **Cross-repo routing by keyword overcounts and needs a review queue.** Regexing bodies for a sensitive topic flagged a radar paper (“雷达”), a car-autonomy post and a philosophy thread. Queue keyword matches for explicit review and route only genuine hits; an evidence-strict repo takes a source-ingest + provenance note (source tier, low confidence, unverified-claims boundary) plus a synthesis citing that source — never an auto-generated synthesis passing as researched evidence.
- **A migration is a Yellow-risk batch, not a Red one** — backup + diff + validation is enough; but publication, trading, or anything the store marks as external delivery stays gated.
