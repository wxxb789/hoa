---
name: hermes-nana-research
description: Use when working on <research-repo> (NRS) outside its repo.
version: 1.0.0
author: Zoe
license: MIT
metadata:
  hermes:
    tags: [<research-repo>, nrs, router, discovery, pointer]
    category: research
---

# <research-repo> (NRS) — host discovery pointer

Thin pointer only. The research system is repository-owned; this skill carries **no** NRS
methodology. Read the repo files themselves instead of copying their content in here.

## When to Use

- A task touches the <research-repo> repo but the session is not running inside that checkout.
- You need the NRS contract, a repo-owned capability skill, or a `.harness` tool and are not sure
  which file owns it.
- You are about to record a Nana lesson and need to send it to the right repository layer.

## Locate

- Checkout: `~/repos/<research-repo>` — the single checkout. If it is missing, ask the owner; do not
  clone or recreate it.

## Ownership boundary (do not conflate repos)

- `<research-repo>` = 配偶 Nana 的研究仓库，研究方法、控制记录与产出归它。
- `<notes-repo>` = owner 个人 Notes 仓库（personal notes + `<notes-vault>/`，其中 `<notes-vault>/<work-tag-a>/` 是工作笔记）。它有自己的 vault 契约和 `thoughtscape-sync` 自动提交。
- Nana 研究产出去 <research-repo>；个人/工作笔记去 <notes-repo>。两者不互相写入，也不共用 skill 放置规则。

## Route (load only what the task needs)

1. Kernel and authority order: `<checkout>/AGENTS.md`.
2. Repo-owned capability skills: `<checkout>/skills/` — start at `skills/<research-repo>/SKILL.md`
   (router: orientation, contract routing, harness tool index), then the capability that points to.
3. Deterministic tool interfaces: `<checkout>/.harness/README.md`.
4. NRS study lifecycle and control records: `<checkout>/docs/agent-contract/research-system/README.md`.
5. Bot roles and their runtime materializer: `<checkout>/bots/README.md` — the roster, write surfaces,
   `bots/bindings/hermes/materialize.py --check|--apply`, and the single-writer lease. Profiles are
   generated, never edited directly.

## Rules

- **Skill ownership & placement**: any <research-repo> skill work — create, refine, or evolve —
  happens in the repo, never in the host skills folder. Two repo layers: portable, versioned
  methodology → `<checkout>/skills/<name>/` (committed); skills highly tied to Nana work
  (machine/env/ops) → `<checkout>/.agents/skills/<name>/` — machine-local and gitignored, activated
  per machine with `hermes skills trust` run from the checkout, loaded only for sessions inside the
  repo, and overriding same-named profile skills. Edits go to the existing file. The host side holds
  this discovery pointer only — never a method copy under `~/.hermes/skills/**`.
- **Bot/runtime 定义归 repo**：Nana 专属 bot（一律 `-nrs` 结尾）的 job、SOUL delta、routine、模型与审批边界以 repo 为正本，`~/.hermes/profiles/*` 只是生成物；改 bot 先改 repo 再物化，host 不得成为第二真相。
- General cross-project skills stay external — incidental Nana use does not move them into the repo.
  A Nana-specific lesson learned while using one is written to the repo's owning layer, not appended
  to that skill.
- `raw/` is immutable provenance. Commit only when the task explicitly authorizes it; never push
  without separate authorization. The repo `AGENTS.md` wins over host habit.
- Never put secrets, host paths, or private-session data into repo bytes.
