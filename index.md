# Index — artifacts by area & target

> **English** · [简体中文](./index.zh-CN.md)

The repo is organized **by type** (the folders). Every logical artifact also
gets **one row here**, labeled by `areas` and `targets` — because one artifact
often serves several areas or runtimes, and folders can't express that.

## Label vocabulary

```text
areas:    software-development | work-management | self-management
targets:  runtime-agnostic | repo-only |
          claude-code | codex | opencode | hermes | pi | kimi-code
```

- Both axes are **multi-valued** (comma-separated).
- **Type** is derived from the top-level folder — don't re-label it.
- `targets` = which `npx skills --agent` a skill installs to (`runtime-agnostic`
  = any; `repo-only` = never deployed, e.g. library/knowledge types).
- One row per **logical** artifact (not one per bilingual file).
- No `status` axis until experimental / deprecated states actually appear.

## Catalog

Hand-curated for now; Phase 3 may generate it from per-artifact metadata.

| Artifact | Type | Areas | Targets | Path | Notes |
|---|---|---|---|---|---|
| define-goal | skill | self-management, software-development, work-management | codex | `skills/define-goal/` | turn fuzzy intent into a measurable objective and create it with Codex goal tools |
| hoa-agent-retrieve | skill | self-management, software-development | runtime-agnostic | `skills/hoa-agent-retrieve/` | cross-agent history → coverage-manifested, deduped Retrieval Bundle |
| hoa-introspect | skill | self-management, work-management | runtime-agnostic | `skills/hoa-introspect/` | layered self-report: deterministic usage facets (L1) + evidence-cited blind-spot audit (L2) |
| hoa-introspect-distill | skill | self-management, software-development | runtime-agnostic | `skills/hoa-introspect-distill/` | distill approved repeatable work into a skill (or opt-in rule/config) via the runtime-native skill-creator or inline |

> Non-skill types (orchestration · agent · workflow · mcp · prompt · rule · eval · reflection) populate as real artifacts land.
