---
name: content-pipeline
description: "Use when shipping a blog post: topic, facts, draft, gate."
version: "0.1.0"
author: Zoe
license: MIT
metadata:
  hermes:
    tags: [writing, content, blog, gtd, handoff]
    related_skills: [writing, owner-decision-requests, obflow-vault-contribution]
  version: "0.1.0"
  areas: "productivity,writing"
  targets: "host-bound (trial run; promote to hoa once stable)"
  summary: "orchestrate one blog post end to end: topic -> facts -> Studio draft -> owner title -> publish gate"
  summary_zh: "编排一篇长文：选题 → 事实清单 → Studio 出稿 → owner 定标题 → 发布门禁"
  kind: "entry"
  produces: "published-post"
---

# Content pipeline

One long-form post, end to end. This skill owns the **orchestration and the handoffs**, not the writing rules:
the prose contract stays in the blog repo, the topic-pool contract stays in the vault, the drafting protocol
stays with the drafting agent. Read those; do not restate them here.

## When to Use

- the owner asks to write, ship or continue a long-form post;
- a topic moves out of the pool into drafting;
- a handed-off draft arrives back for the title choice or the publish gate;
- the weekly topic job's output needs an owner decision (promote a candidate, or it reports `POOL_FULL`).

## Who does what

| Step | Who | Output | Where |
|---|---|---|---|
| Topic pool (weekly candidates, quarterly picks) | weekly topic cron produces candidates; owner promotes a candidate into the pool table | pool of at most `POOL_LIMIT` topics | vault `gtd/projects/content-brand/` (`_index.md` table + `topics/`) |
| Fact list | drafting agent, before any prose; the directory's own `README.md` is the format authority (read it before the first write of a session) | one file per post, every number carries its source **and its caliber** | vault `…/content-brand/facts/<slug>.md`, named by the post's slug |
| Series check | drafting agent | the post's one claim, its series, whether material suffices | blog `BRIEF.md` (three questions + series table) |
| Draft | **`studio` profile**, single model, three passes, launched detached (skill `omp-headless-orchestration`) | `posts/<YYYY-MM-DD>-<slug>.md` | blog repo, **branch in a dedicated worktree** (`git worktree add … -b post/<slug>`); the main worktree stays on `main`, clean |
| Title | owner picks 1 of 3 candidates (each with promise + where the body delivers it) | chosen title | — |
| Publish gate | front-door agent verifies, then asks the owner | `git push` → site deploy | blog repo |

## Hard rules

- **Prose is always the low reasoning effort** — first draft, line-by-line revision, tightening, every model,
every pass. High/max is allowed for audit (fact check, review, choosing among variants) but an audit must never
write or rewrite prose.
- **Drafting is one model, three passes.** A multi-model pipeline is for review and error-finding only.
- **A number is not a fact until its command is re-run in the current tree.** Counts quoted by a topic
  card or any planning note (test totals, page counts, 「N 绿」) record what was believed when they were
  written; the fact list owns the measured value. Re-run the producing command, record the command and the
  caliber, and when the card and the re-run disagree **write both** and mark the item `待统一` — never
  reconcile by silently picking the nicer number, and keep the unreconciled one out of the prose.
  The same holds for the citation behind a claim: a planning note that cites a `~/claw/tasks/<date>/<task>/`
  log is citing a path that cleanup deletes once the task's conclusion is promoted. Open the cited artifact —
  when it is gone, re-derive the fact from the home that survives (the commit itself: `git show --stat <sha>`
  for the shape of a fix, `git show <sha>^:<path>` for the pre-fix form) and write down which source you
  actually read, instead of quoting a citation whose bytes no longer exist.
- **The fact list is raw material, not a draft.** Sources after every number, `推断：` prefix on every
  inference, conflicts written as conflicts, no body sentences; dated machine-written files go in the
  project's subdirectory (`facts/`), never loose at the project root.
- **The drafting lane never pushes.** Drafting ends at a branch in a dedicated worktree plus its report
  (draft path, 3 titles with the promise each makes and where the body delivers it, re-sourced number
  table, lint + preview-build evidence); the push is the deploy step and stays behind the owner's gate.
- **The vault never holds prose.** Topic, plan, strategy, material, fact lists live in the vault; only the finished
post goes to the blog repo.
- **The pool has a ceiling.** When the pool gate reports `POOL_FULL`, the weekly job only tops up existing topics'
material; candidates live in the `topics/` weekly file until the owner promotes one. Never edit the pool table to
add a candidate.
- **A post needs a series.** No matching series in `BRIEF.md` → the series table is extended first, then the post
starts. `NO-SERIES` topics do not enter the pool.
- **Publishing always needs the owner.** Pushing the blog repo is a deploy; a draft is not a publication.

## Points of authority (read, don't copy)

- prose contract: blog `AGENTS.md` (pipeline), `WRITING.md` (single post), `BRIEF.md` (series and topics)
- pipeline authority: vault `gtd/projects/content-brand/_index.md`
- drafting protocol: `~/claw/bots/studio/AGENTS.md`
- local values all overridable: `BLOG_REPO`, `OBFLOW_CONTENT_DIR`, `STUDIO_SEED_CONTENT_DIR`, `STUDIO_SEED_INBOX`
  (each has a default derived from `$HOME`; never hard-code a host path into a promoted copy)

## Publish gate: the front-door checklist

A draft that came back for the gate is still a draft. Run these **in the post's worktree, in this order**, and
quote each output in the report — every step is a claim the owner cannot check for himself.

1. **Re-base before you verify anything.** `git fetch origin`, then
   `git merge-base --is-ancestor origin/main HEAD`. A branch that sat for days is behind, and the base moved for
   a reason that can change the render (a generator pin bump) — gates run against a stale base prove nothing
   about the thing that would actually merge.
2. **Lint:** `corepack pnpm dlx markdownlint-cli2 "**/*.md"` under the repo's own config. Read the
   `Linting: N files` line; `Summary: 0 issues in 0 files` counts only files that contributed findings, so it
   reads as zero on a clean pass too.
3. **Refresh the publish set:** `anc review --content .` rewrites `.publish-set.json`. `git diff` must show
   exactly the one new slug, and it must be **committed on the branch** — a release build refuses a set that is
   missing, dirty, or short a slug, so an uncommitted review file is a deploy that fails *after* the merge.
4. **Preview build**, with the generator version the deploy workflow pins (read the pin out of
   `.github/workflows/publish.yml`; a preview built from another version does not prove what will deploy):
   `node <pinned-anc>/bin/anc.mjs build --content . --out dist`.
   - **Read the counts from stdout** — `content: N discovered, M published, K dropped`, `residue scan ok: N
     files, 0 findings`. `content-report.json` nests its counts under `counts`, so a top-level
     `report['discovered']` returns `None` and a green build looks empty.
   - The report lives in the **worktree's git dir**, not the checkout:
     `git rev-parse --git-path publish-report/content-report.json` (a worktree's `.git` is a file, so it lands
     under `<main-repo>/.git/worktrees/<wt>/publish-report/`). `dropped` must hold only `publish: false` files,
     the prose contracts and the config.
5. **Then ask — with the draft attached.** One question, the evidence above, and the post itself, so the owner
   reads before the push rather than after it.
6. **Push path: branch → PR → squash-merge into `main`.** `main` stays linear and the deploy workflow fires on
   the merge. A repo whose own history shows direct pushes is not showing consent for today's — and a standing
   grant inside the repo's contract is a repo-local rule, which does not outrank the operating contract and never
   unlocks the public-publish gate.

## Acceptance

- the post exists once in the blog repo, with frontmatter the site expects (`title`, `slug`, `language`, `description`, `tags`)
- the publish-gate checklist above ran green in the post's worktree, with its outputs quoted in the report
  (lint counts, publish-set diff, preview-build counts and residue scan)
- the deploy run for the merged commit is green, and the live page matches the title and body
- the fact list stays in the vault after publication: it is the material audit for the next post

## Pitfalls

- Writing prose in the main session because it is convenient: the drafting agent owns the draft, the front door
owns the handoff — a draft produced on the wrong side skips the fact list and the series check.
- Editing the pool table to "just add" a candidate: candidates belong in the weekly file until the owner promotes them.
- Treating a finished draft as published, or pushing the repo to "see how it looks": a push is a deploy.
- Raising the reasoning effort for a revision: the prose gets stiffer, not better; audits use the higher effort and
  never write prose.
- Transcribing a number from the topic card as if it were measured: a card's count is a claim about the
  moment it was written, and only the reconciling re-run makes it a fact — an unreconciled count in the
  body is exactly the error the fact list exists to prevent.
- Letting the drafting lane write into the publication checkout's main worktree, or push "to see how it
  looks": both turn a draft into a deploy.
- Restating the blog's writing rules inside a routing note: two copies drift, and the copy that gets read is the
  one that is wrong. **The copies hide in prompt literals, not only in prose.** When the blog contract changes, grep
  the distinctive token of each changed rule (a length cap, a link minimum, a label such as `推断：`, a named pass)
  across the pipeline's own bytes: a generation script keeps them inside its `STYLE_NOTE` shell string and its judge
  prompt, and the drafting bot's protocol file repeats the pass names. Replace every hit with a **pointer to the
  canonical section** — `见 blog 的 WRITING.md 第 N 节`, and when the rule's home is another file (`BRIEF.md` for
  series and the misjudgement paragraph, `AGENTS.md` for the passes) name *that* file, never a bare section number —
  then re-run the repo's own linter on the reference post, which is the only thing that proves the copy is gone.
- Asking for the push without re-basing first, or quoting a preview build from a generator version other than the
  workflow's pin: the answer is still yes/no, but what deploys is not what you verified.
- Naming the vendored generator's path inside its checkout in the build command pulls that project's own
  `AGENTS.md` into context (Hermes' subdirectory-hint loader keys on the paths a command touches, not only on `cd`) —
  thousands of tokens for a one-line build. Call it through a shim or symlink in your own tree.

## Related

- `writing` — the per-channel prose contract (load it for the channel's specifics; this skill only routes).
- `owner-decision-requests` — the title choice and the publish approval are owner rounds; deliver them as forms.
- `obflow-vault-contribution` — how content lands in the vault without tripping its gates.

## Trial status

Host-bound while it runs: this skill is being exercised on one machine before it is generalized. When it has run
stable for a while, promote it to `hoa` by demoting every literal (host paths, model ids, channel ids) to config
with a default, and keep only the orchestration here.
