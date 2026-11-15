---
name: plan-to-issues
description: >-
  Break PRDs or plans into issue-level tasks. Produces a list of issues (title + body + labels) and
  can optionally open them via `github-issues` skill.
metadata:
  version: "0.1.62"
  areas: "work-management"
  targets: "runtime-agnostic"
  summary: "break a PRD or plan into issue-level tasks with titles, bodies and labels"
  summary_zh: "把 PRD 或计划拆成 issue 级任务：标题、正文、标签"
  kind: "entry"
---

# plan-to-issues

Input: PRD markdown or plan document. Output: CSV of issues + optional `gh` commands.
