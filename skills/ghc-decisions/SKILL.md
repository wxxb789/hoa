---
name: ghc-decisions
description: >-
  Run opt-in structured rubric checks through an OpenAI-compatible `/v1/decisions`
  decision model or `/v1/chat/completions` fallback. Use when a parent workflow
  or operator explicitly opts in to fast predicate, choice, or score triage across
  bundled presets (claim-audit, ci-triage, tool-risk, skill-review, memory-curation,
  pr-feedback-triage, citation-entailment, model-escalation, spec-readiness). Not
  a substitute for deterministic gates, artifact inspection, or primary agent sign-off.
disable-model-invocation: true
metadata:
  revision: "1"
  areas: "software-development,work-management"
  targets: "runtime-agnostic"
  summary: "opt-in `/v1/decisions` and `/v1/chat/completions` rubric classifier with 9 bundled presets"
  summary_zh: "按需启用（opt-in）的 `/v1/decisions` 与 `/v1/chat/completions` 结构化 Rubric 分类器，内置 9 大日常预设"
  kind: "mechanism"
---

# ghc-decisions

Opt-in structured rubric classifier for fast `predicate`, `choice`, and `score`
checks (`0 output tokens` on native `/v1/decisions` models such as
`gpt-6-luna-decisions`, with `/v1/chat/completions` fallback).

## Gates

- **Opt-in only.** If neither `--base-url`/`--model`, `GHC_DECISIONS_BASE_URL`/`GHC_DECISIONS_MODEL`,
  nor `$XDG_CONFIG_HOME/ghc-decisions/config.yaml` (`~/.config/ghc-decisions/config.yaml`)
  is configured, `scripts/ghc_decisions.py` prints `{"skipped": true, "reason": "not configured"}`
  and exits `0` when `--if-configured` is passed (or exits `2` on direct required calls).
  Parent workflows must continue their deterministic verification without failing when
  this skill is unconfigured or unreachable.
- **Advisory triage, never sole acceptance.** A decision model does not run commands,
  inspect the filesystem, or prove a claim. Always re-derive numbers and run
  deterministic repository gates independently.
- **Atomic criteria.** Keep custom questions single-step (`predicate`, mutually
  exclusive `choice`, or `score` with 2–10 levels) and branch in code rather than
  asking for multi-hop reasoning.

## Usage

Run `scripts/ghc_decisions.py` via `uv run`. Only if a script command fails (for
example `uv` is not found), read [references/troubleshooting.md](references/troubleshooting.md).

```bash
S=skills/ghc-decisions/scripts/ghc_decisions.py   # or ~/.agents/skills/ghc-decisions/scripts/ghc_decisions.py

# List bundled presets
uv run "$S" --list-presets

# Run a preset only when the operator has configured ghc-decisions (exits 0 with {"skipped": true} otherwise)
uv run "$S" --if-configured --preset claim-audit --state-file state.json

# Explicit one-shot call against a local ghc-proxy /v1/decisions endpoint
uv run "$S" --preset pr-feedback-triage \
  --base-url http://127.0.0.1:4141/v1 \
  --model gpt-6-luna-decisions \
  --api decisions \
  --state '{"finding":"...", "evidence":"...", "candidate":"..."}'
```

## Bundled Presets

| Preset | Questions (`type`) | Primary parent / use case |
|---|---|---|
| `claim-audit` | `verdict` (`choice`), `action_required` (`predicate`), `risk_score` (`score`) | `delegated-work-acceptance`, `report-claim-audit`, `hermes-ops-claim-verification` |
| `ci-triage` | `symptom` (`choice`), `root_cause_proven` (`predicate`), `triage_priority` (`score`) | CI / test / scheduled-job failure log triage |
| `tool-risk` | `tier` (`choice`), `out_of_scope` (`predicate`), `blast_radius` (`score`) | PreToolUse / permission hook shadow-mode risk classification |
| `skill-review` | `bucket` (`choice`: `change`/`verify`/`consider`), `has_direct_contradiction` (`predicate`) | `hoa-skill-review` intake and candidate grading |
| `memory-curation` | `durability` (`choice`), `relationship` (`choice`) | `distill-memory` / `nmem` pre-write deduplication and noise filtering |
| `pr-feedback-triage` | `resolution` (`choice`: `resolved_root_cause`/`symptom_patch`/`unaddressed`/`regression_introduced`) | `review-revision-candidates`, `ce-resolve-pr-feedback` |
| `citation-entailment` | `entailment` (`choice`: `strictly_entailed`/`temporal_or_scope_drift`/`unsupported_extrapolation`/`insufficient_evidence`) | `evidence-boundary-discipline`, `official-document-verification` |
| `model-escalation` | `route` (`choice`: `stay_fast_worker`/`escalate_single_reviewer`/`escalate_dual_audit`) | `gdd`, `ai-coding-agent-delegation` review tier routing |
| `spec-readiness` | `readiness` (`choice`: `ready_to_dispatch`/`missing_acceptance_seam`/`unbounded_scope`) | `spec-convergence`, `define-goal` pre-dispatch gate |

## Configuration

Resolved through `scripts/skill_config.py` (see [references/configuration.md](references/configuration.md)):

| Key | Flag | Environment variable | Default |
|---|---|---|---|
| `base_url` | `--base-url` | `GHC_DECISIONS_BASE_URL` | none (opt-in; skips under `--if-configured`) |
| `model` | `--model` | `GHC_DECISIONS_MODEL` | none (opt-in; skips under `--if-configured`) |
| `api` | `--api` | `GHC_DECISIONS_API` | `decisions` (`decisions` or `chat-completions`) |
| `effort` | `--effort` | `GHC_DECISIONS_EFFORT` | `low` (used by `chat-completions`) |
| `api_key` | — | `GHC_DECISIONS_API_KEY` | `dummy` |

## Additional resources

- `scripts/ghc_decisions.py` — stdlib-only CLI and library for `/v1/decisions` and `/v1/chat/completions`.
- `scripts/rubrics.json` — the 9 bundled rubric presets.
- `scripts/skill_config.py` — vendored configuration resolver.
- `scripts/tests/test_ghc_decisions.py` — offline unit and HTTP-stub tests.
- [references/configuration.md](references/configuration.md) — configuration lookup order and file path.
- [references/troubleshooting.md](references/troubleshooting.md) — read only when a `uv run` command fails.
