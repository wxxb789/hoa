---
name: interview-prep-artifacts
description: "Use when producing interview-prep artifacts into the vault."
version: 1.0.0
author: Zoe
license: MIT
metadata:
  hermes:
    tags: [interview, career, prep, <notes-vault>, promo-senior]
---

# Interview Prep Artifacts

Producing and filing interview-prep deliverables — question packs, system-design drills, STAR(R) stories,
mock-round critiques — into the vault, where this owner's prep system already lives.

## When to Use

- Owner asks for prep (「准备几个面试问题」「把这个项目整理成 STAR」「mock 一轮」), or a prep backlog row reaches done.
- A distilled link yields an interview lesson that implies a deliverable — route it to the owning project, not to chat.

**Not for** the vault mechanics (allowlist, gates, `goal_id` admission, closure, link checks): read
`obflow-vault-contribution` first, it governs every write below.

## Address Points (read, don't invent)

- `<notes-vault>/gtd/projects/interview-prep-workbench.md` — control plane: target lanes, P0/P1 backlog, the audited
  next-actions table (its "Input needed" / "Expected artifact" columns are the spec), session log.
- `garden/interview-prep/` — the artifacts; its `_index.md` lists them.
- `sources/research/career-interviews/` — distilled link material plus the evidence-strength notes that judge
  candidate-side tactics.

## Rules

1. **Match the row, then close the row.** Read the backlog row before writing; a note that satisfies no row is a
   detour. Landing one = checkbox `→ [[note]]`, the audit row's `→ done: [[note]]`, a dated session-log line,
   and the `_index.md` line.
2. **Structure for use in the room.** Question pack → a small fixed core set (4), each with 目的 / 好答案的样子 /
   追问 / 风险, plus a backup table by round; drill → a 15-minute outline carrying scale, auth boundary, failure
   modes, observability; story → STAR(R) with metric, tradeoff, reflection. A note the owner cannot deploy
   mid-interview is not a prep artifact.
3. **Write the English verbatim.** The lines he will actually say or ask go in English, ready to read aloud; the
   judgment columns stay ZH. A ZH note with no quotable English line gets improvised in the room.
4. **Ask for instances, not stances.** Precise questions request a concrete past case ("what's a change you'd
   call a clear win — how did you know?"); generic ones request an opinion, and team-structure / culture
   questions are already covered in the intro or answered with PR prose.
5. **Vibes-based sources enter as action lists with an evidence column.** A tactics thread, a LinkedIn post, a
   recruiter checklist is distilled into actions → external evidence → strength, with tensions and
   unfalsifiable claims named; never presented as validated practice.
6. **Frontmatter follows the policy, not the neighbours.** New `garden/` notes need `goal_id` (prep →
   `promo-senior`) even where the sibling drills in the folder predate the policy and carry none: copy their
   shape, keep the required keys, bump `updated:` on every edit.
7. **Gates before leaving the tree**: `markdownlint-cli2` + `.harness` `vault.status` (`blocking_count=0`) plus
   resolving the wikilinks just written — commands, the PyYAML interpreter trap and receipt reading live in
   `obflow-vault-contribution`.

## Pitfalls

- **A ticked checkbox without a link is a dead checkbox**, and an artifact living only in `garden/` is invisible:
  the next session reads the project note and re-derives work already paid for.
- **Do not restate the workbench** (lanes, priorities, open rows) inside the artifact — both copies go stale.
- **Prep artifacts are bound to a loop and expire with it**: date the company/loop-specific ones (title or
  frontmatter) so a later session does not treat stale phrasing as current prep.
