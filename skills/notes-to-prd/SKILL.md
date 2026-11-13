---
name: notes-to-prd
description: >-
  Convert notes/ideas into structured PRD markdown. Produces a PRD draft under `docs/prd/` and
  optional issue breakdown.
metadata:
  version: "0.1.56"
  areas: "work-management"
  targets: "runtime-agnostic"
  summary: "turn notes or an idea into a structured PRD draft"
  summary_zh: "把笔记或想法转成结构化 PRD 草稿"
  kind: "entry"
---

# notes-to-prd

Use this skill to turn bullet notes or chat into a PRD skeleton. Outputs a markdown file and an optional issues CSV or GH issue payloads.

# Usage
- Input: freeform notes or a link to a plan document
- Output: `.md` file under `docs/prd/<slug>.md`
