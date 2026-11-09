# Asset store vs runtime workspace

Use when the owner draws (or asks you to draw) a line like "long-term data assets live here, that folder is just a runtime workspace", or when a contract needs a rule about where durable output goes.

The contract sentence is the easy half. The half that goes wrong is writing persistence mechanics you never read: whether the store is its own repo, who commits it, which gates run, how large a batch is allowed.

## 1. Probe topology before writing the rule

```bash
# Is the working directory even versioned?  "fatal: not a git repository" is a finding, not an error.
git -C <workspace> rev-parse --show-toplevel

# Is the store its own repo, or a folder inside a bigger one?
git -C <repo>/<store> rev-parse --show-toplevel
git -C <repo> remote -v
git -C <repo> status -sb | head -3

# Nested repo / submodule check — a second .git means the store has its own history
git -C <repo> ls-files <store> | wc -l
find <repo> -maxdepth 3 -name .git -not -path '*/.git'
```

Interpretation rules:

- **Store inside a larger repo** → identity, commit hygiene, validation and secret scanning are that repo's, not a free-standing "git-as-sync" permission. The rule you write must name the repo and its pipeline.
- **Working directory is not a repo** → no history, no remote, no rollback. State that as a measured fact; it is the strongest argument for moving assets and it changes how urgently the owner reads the proposal.
- **Size the gap with numbers**: `du -sh */ | sort -hr` on the source, tracked-file count on the destination. "1.5G with zero version history" lands; "it would be better organized" does not.

## 2. Read the store's own contract, not just its folders

A real vault/asset store usually carries a kernel file + a structure doc (or equivalent) with an explicit
layer-ownership table — for example: evidence layer = raw material, synthesis layer = maintained
conclusions, chronology layer = dated records, commitments layer = goals, plus an isolated sensitive
work root. Map new content onto **its** layers; do not invent parallel folders, and do not restate its
taxonomy in the host contract — point at it.

## 3. Read the sync wrapper that actually persists it

Persistence in these setups is a scheduled wrapper, e.g. a job calling `scripts/<store>-sync.sh`, often
through a shared `lib/git-sync-common.sh`. Extract, verbatim:

- **New-file allowlist roots** — files outside them are never committed, so "move the assets in" silently loses anything placed elsewhere;
- **Per-run size cap** — a multi-hundred-MB source cannot be one migration batch;
- **Validation stack** — unit tests, store status/structure audit, markdownlint, secret scan; any failure means the whole batch is refused, not partially applied;
- **Refusal conditions** — pre-staged index, dirty tree, missing binary; these tell you not to hand-commit;
- **Commit message convention** — so your edits ride the pipeline instead of fighting it.

## 4. Verify every gate at the call site

Before writing "X blocks the pipeline", open the command implementation and the wrapper that invokes it. A check guarded by `if payload.get("check"):` that the pipeline calls with no payload is **not** a gate — it reports `skipped` and passes. Say "quality debt, not blocking" instead, and keep the two categories apart in the contract.

## 5. Write the rule as: judgment test + mapping table + invariants

Keep it short enough for an instruction file (example layer names abbreviated):

```markdown
<store> = 长期资产正本; <workspace> = 运行时工作空间。

判断式：6 个月后还会被引用 / 会改变判断 / 值得链接 → store；只是过程、可重建、过期即弃 → workspace。

| 内容 | 归宿 |
|---|---|
| 稳定结论 / 方法论 / 领域知识 | store `garden/<domain>/` |
...

- 写 store 前先读它的 kernel / STRUCTURE；分层以它为准。
- 同一事实只有一个正本；workspace 里的副本 = 待迁移或待删除。
- 只有提炼过、可长期引用的部分才提升，提升时保留 provenance，不在两边各写一份。
- store 的持久化机制（谁 commit、哪些门禁、单批上限）随该仓的 contract 走。
- 未完成迁移的目录是「待提升区」，默认不收新内容；仍有 fast-line 写入的目录显式记为唯一例外。
```

## 6. Migration plan: dry-run first, batch by the pipeline's limits

1. Read-only mapping pass: list every file, its destination path, and its structure-compliance gaps (frontmatter type, `_index`/hub link, kebab-case rename, size).
2. Batch by the sync size cap and by validation surface — small, verifiable batches beat one heroic move.
3. In the same batch as the move, update **every** reference to the old path: host contract, per-profile deltas, capture scripts, scheduled scripts, and the docs that quote them.
4. Keep the source directory until the batch that migrates it has landed; then retire it explicitly.

## Pitfalls

- **"git-as-sync, may commit+push" is not a rule.** It names no actor and no gate, and invites a hand-commit that skips the pipeline's validation and secret scan. Name the job, the roots, the cap, the gates.
- **A vault inside another repo inherits that repo's gates.** Do not create a second history or a nested repo to "keep the vault separate"; it breaks the allowlist, the size accounting, and the auto-sync's rebase step.
- **Sensitive subfolders widen exposure on migration.** When the store keeps an isolated private root, the migration must not copy private material into a published layer, and must not bypass the secret scan to make a batch pass.
- **Duplicate state stores are the real finding.** Two live GTD directories, two ledgers, two goal lists mean the owner is paying maintenance twice; report the duplication and the retirement order, not just the destination path.
- **Moving a named directory leaves dead paths everywhere.** Every contract mention, script path, and bot fast-line command that names the old location breaks silently; sweep them in the same batch or keep the directory as a documented exception.
