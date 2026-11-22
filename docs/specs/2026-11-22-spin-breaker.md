# Spin Breaker Specification

## Problem

Operators and coding agents get trapped in unproductive loops either before execution (starting edits or delegation while the target surface, observable acceptance signal, or forbidden boundary is still implicit) or mid-session (accumulating unfalsified guesses, absorbing emergent meta-ideas into the active task's acceptance envelope, and repeatedly nudging `continue` without eliminating any hypothesis). The operator needs an explicit, portable, manual-invocation skill in `hoa` (`spin-breaker`) that locks a lightweight pre-flight execution contract or halts mid-session spinning, parks side quests and restart breadcrumbs safely, and optionally renders a self-contained static HTML causal/hypothesis map when plain-text chat collapses topological structure.

## Scope

- Ship a curated portable skill package at `skills/productivity/spin-breaker/` in `hoa`, named `spin-breaker` (`q5b`), belonging to `hoa` alone (`q1a`).
- Make `spin-breaker` hidden / explicit-invocation-only (`q3a`): set `disable-model-invocation: true` in `SKILL.md` frontmatter and ship `agents/openai.yaml` with `policy.allow_implicit_invocation: false`.
- Provide two explicit sub-modes inside `spin-breaker` (`q2b`):
  1. **Pre-flight lock** (`lock` / pre-execution): before code edits or worker delegation, verify and lock three concrete items — target client/host/tenant surface, observable input-to-output check, and forbidden boundary — using host-native compact selection/confirmation UI where available (with plain-text numbered fallback when host UI is unavailable or disconnects).
  2. **Mid-spin rescue** (default / mid-session): halt further edits, branches, and background dispatches; separate mixed-in side quests from the original user-visible outcome; present a compact 5-line state reckoning (original outcome, last verified fact with locator, falsified vs. unfalsified hypotheses, single discriminating read-only probe, and a 3-way choice: run the probe, freeze and park with a 4-line restart breadcrumb, or retire the branch).
- Include an optional `map` mode (`q1a`) backed by a zero-dependency Python 3.13 stdlib CLI script (`scripts/spin_breaker.py`, PEP 723 inline metadata, run via `uv run`) that renders a self-contained static HTML causal/hypothesis elimination map into `./.tmp-artifacts/<bundle-name>/` at the target repository root, with all backing data/assets inside that single bundle subfolder.
- Support configurable persistence for parked side quests and 4-line restart breadcrumbs (`q4a`) via vendored `scripts/skill_config.py` (`CLI flag -> environment variable -> ~/.config/spin-breaker/config.yaml -> documented default`):
  - Default local store: `./.tmp-artifacts/spin-breaker/parked-items.md` (git-ignored, zero external tool requirement).
  - Optional external memory adapter: configurable command template or adapter setting (for example writing to an external memory CLI) executed only after explicit operator confirmation in the current turn.
- Register `spin-breaker` in `scripts/vendor_shared.py` (`skill_config.py`, `configuration.md`, `troubleshooting.md`) and regenerate `index.md` and `index.zh-CN.md`.
- Record this converged specification at `docs/specs/2026-11-22-spin-breaker.md` in the `hoa` mission branch (`q7b`).

## Out of scope

- Standalone always-on web applications, local HTTP servers, background daemons, or databases (`accept and confirmed.`).
- Cross-repository edits to `dotfiles` host hooks or statuslines for passive spin-detection reminders (`q1a`, `accept and confirmed.`).
- Model-visible implicit routing activation, `evals/trigger-cases.json` `must_pick` entries, and fresh-context two-arm agent behavioral evaluations (`q3a`, `q6b`, `accept and confirmed.`).
- Unconfirmed mutations to tracked source code, unconfirmed discarding of Git worktree changes, or unconfirmed writes to external memory stores (`accept and confirmed.`).

## Acceptance

- **AC-01**: `skills/productivity/spin-breaker/SKILL.md` and `skills/productivity/spin-breaker/agents/openai.yaml` exist, declare `name: spin-breaker`, `disable-model-invocation: true`, `policy.allow_implicit_invocation: false`, `metadata.kind: "entry"`, `metadata.revision: "1"`, and contain zero hardcoded home paths, personal/assistant names, repository IDs, model IDs, or private endpoints.
- **AC-02**: `skills/productivity/spin-breaker/SKILL.md` defines both operator sub-modes (`pre-flight` 3-element execution lock and `mid-spin` 5-line reckoning + side-quest separation + 3-way choice) with explicit non-mutation gates until the operator confirms an option, plus plain-text fallback when host form UI is unavailable.
- **AC-03**: Running `uv run skills/productivity/spin-breaker/scripts/spin_breaker.py map ...` against structured JSON input writes a self-contained HTML bundle under `<repo-root>/.tmp-artifacts/<bundle-name>/` (HTML file + backing JSON inside the bundle folder, zero loose files in `.tmp-artifacts/` root, UTF-8 encoding, zero third-party dependencies).
- **AC-04**: Running `uv run skills/productivity/spin-breaker/scripts/spin_breaker.py park ...` writes parked side quests or 4-line restart breadcrumbs to the default `<repo-root>/.tmp-artifacts/spin-breaker/parked-items.md`, resolves configuration in order `CLI flag -> SPIN_BREAKER_* env var -> ~/.config/spin-breaker/config.yaml -> default`, and invokes an optional configured external adapter command only when `--confirm-external` is explicitly passed.
- **AC-05**: Offline tests in `skills/productivity/spin-breaker/scripts/tests/test_spin_breaker.py` pass under `pytest`, covering `map` bundle layout/escaping, `park` markdown formatting (side quest + 4-line restart breadcrumb), config resolution precedence, and external adapter gating (no external execution without `--confirm-external`, clean failure reporting on non-zero adapter exit).
- **AC-06**: All `hoa` repository static and packaging gates pass cleanly: `check_frontmatter.py`, `check_contract_graph.py`, `check_skill_links.py`, `generate_index.py --check`, `vendor_shared.py --check`, `version.py check-revisions`, `ruff check`, and `evals/run_trigger_evals.py`.

## Testing seam

Public CLI boundary of `skills/productivity/spin-breaker/scripts/spin_breaker.py` exercised by `pytest` (`skills/productivity/spin-breaker/scripts/tests/test_spin_breaker.py`), combined with the `hoa` repository static packaging and contract gates (`scripts/check_frontmatter.py`, `scripts/check_contract_graph.py`, `scripts/check_skill_links.py`, `scripts/generate_index.py --check`, `scripts/vendor_shared.py --check`, `scripts/version.py check-revisions`, `uvx ruff@0.17.5 check --config ruff.toml --force-exclude scripts evals skills`, and `evals/run_trigger_evals.py`) (`q6b`).

## Open questions

None.
