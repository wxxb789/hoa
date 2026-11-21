---
name: session-history-mining
description: >-
  Mine local Claude Code, OMP, and Codex session history for reusable operational
  lessons using two-level pruning, multi-head `/v1/decisions` probes, residual
  active learning, and gold-anchor calibration. Explicit invocation only;
  not for single-repo or periodic self-retros.
disable-model-invocation: true
metadata:
  revision: "1"
  areas: "self-management,software-development"
  targets: "runtime-agnostic"
  summary: "mine Claude Code, OMP, and Codex history with two-level pruning, decision probes, residual active learning, and gold anchors"
  summary_zh: "挖掘 Claude Code、OMP 与 Codex 会话历史，使用两级剪枝、决策探针、残差主动学习和黄金锚点"
  kind: "entry"
---

# session-history-mining

Extract reusable operational guardrails, hidden failure modes, and workflow rules
from local Claude Code, OMP, and Codex session history without linear
full-text rereads, closed-set Softmax blind spots, or prompt calibration drift.

## Gates

- **Domain and secret isolation before model calls.** Classify project directories
  before reading transcripts. Physically skip out-of-scope or corporate checkouts
  and mixed scratch directories. Strip credentials, bearer tokens, and private
  endpoints locally before sending any state to a decision endpoint, and strip
  agent-workflow prompt-injection boilerplate frames so safety classifiers do not
  false-refuse.
  Use the optional `--allow-regex` / `--deny-regex` filters to separate personal
  and work checkouts in mixed stores; omit them only when all checkouts under
  the supplied roots are in scope. Codex filters match the working directory
  (without its Windows extended-length prefix) or the derived project slug;
  deny matches take precedence.
- **Read-only stores and gitignored scratch.** Never mutate session stores, WAL
  files, or repositories during mining. Write intermediate JSONL skeletons, spans,
  and score ledgers only to an outside-worktree state directory or a directory
  confirmed ignored by `git check-ignore`.
- **Advisory probabilities, primary-agent proof.** Decision-model probabilities
  rank and route; they never prove a root cause or authorize an edit. Every
  surviving candidate must be verified against raw session line numbers and
  reconciled against live repository files before proposing changes.
- **Gold-anchor monotonicity.** Never adopt a revised rubric (`v2+`) unless it
  preserves zero false negatives and maintains or widens the worst-case positive-vs-negative
  margin on a locked anchor set (`>= 8` positives + `>= 8` negatives).

## Workflow

Run `scripts/mine_sessions.py` via `uv run`. Only if a script command fails (for
example `uv` is not found), read [references/troubleshooting.md](references/troubleshooting.md).
See [references/methodology.md](references/methodology.md) for the underlying
information-theoretic contracts and residual formulas.

### 1. Extract redacted L0 skeletons and L1 causal spans

```bash
S=skills/productivity/session-history-mining/scripts/mine_sessions.py
OUT=/tmp/session-mining-run   # or a gitignored scratch directory

uv run "$S" extract \
  --claude-root ~/.claude/projects \
  --omp-root ~/.omp/agent/sessions \
  --codex-root ~/.codex \
  --allow-regex '(?i)(repos-|chezmoi|dotfiles)' \
  --deny-regex '(?i)(src-|work|corp|msw)' \
  --out-dir "$OUT"
```

Supply only the roots you intend to mine. Codex prefers existing JSONL rollouts
and reconstructs pruned rollouts from `state_5.sqlite` and
`thread_history_1.sqlite`. With no database pair, it scans rollout files under
the supplied root, including `sessions/` and `archived_sessions/`. SQLite reads
are read-only; if the extractor warns that it opened an immutable view, recent
WAL changes may not be visible. Clean internal subagent threads are omitted by
default unless their role is `worker` or `default`; use
`--include-codex-subagents` to retain all roles within the selected scope.

`extract` emits:
- `skeletons.jsonl` — one compact trajectory skeleton per session (`~300-600` tokens:
  all user turns, tool/hook non-zero errors, and assistant boundary claims, with
  clean read/edit runs folded). Also includes failed subagent runs from workflow
  journals.
- `spans.jsonl` — overlapping causal turn-windows (`--max-span-chars`, 2-step
  overlap so root-cause and resolution are not severed), tagged with `has_pivot`
  and exact `file:Lstart-Lend` locators.
- `extract-manifest.json` — coverage by root, including Codex included/skipped
  threads and counts backed by JSONL or SQLite. For SQLite evidence,
  `thread_history_1.sqlite#thread=<id>` locators use `rollout_ordinal` values,
  not file lines.

### 2. Level 0 tree-root pruning (`skeletons.jsonl`)

```bash
uv run "$S" judge \
  --stage l0 \
  --input "$OUT/skeletons.jsonl" \
  --output "$OUT/l0-scored.jsonl"
```

Retain sessions with `anomaly_probe >= 0.20`, `user_correction_probe >= 0.20`,
`durability >= 0.45`, or non-zero `hook_errors`. Audit the top 5–8 pruned
sessions near the boundary to confirm zero false negatives before zooming into L1.

### 3. Level 1 orthogonal multi-head scan + residual reflection

Filter `spans.jsonl` to pivot spans belonging to L0-surviving sessions, then run
Round 1 with bundled orthogonal heads (`anomaly_probe`, `mechanism` with explicit
`unclassified_novel_lesson` escape hatch, and `reusable_guardrail` score):

```bash
uv run "$S" filter-spans \
  --l0 "$OUT/l0-scored.jsonl" \
  --spans "$OUT/spans.jsonl" \
  --output "$OUT/l1-candidates.jsonl"

uv run "$S" anchor-check \
  --rubrics "$OUT/custom-rubrics.json"   # optional; defaults to bundled v1/v2 rubrics

uv run "$S" judge \
  --stage l1-v1 \
  --input "$OUT/l1-candidates.jsonl" \
  --output "$OUT/l1-r1-scored.jsonl"

uv run "$S" residuals \
  --scored "$OUT/l1-r1-scored.jsonl" \
  --spans "$OUT/l1-candidates.jsonl" \
  --output "$OUT/r1-residuals.json"
```

Inspect **only** the three residual pools in `r1-residuals.json` (pulling adjacent
spans when truncated):
1. **Epistemic OOD pool** (`ood_residual = P(anomaly) * P(novel)`): genuine
   unknown unknowns that escaped known buckets -> add a specific positive bucket.
2. **High-anomaly gray-zone pool** (`P(anomaly) >= 0.85` with middling guardrail
   score or high Shannon entropy): single-app noise or slash-command plumbing ->
   add explicit negative exclusions.
3. **Refusal pool**: inspect stripped framing if any safety refusal occurred.

Validate your refined rubric on the locked anchor set (`anchor-check`), confirm
worst-case gap does not shrink, and run Round 2 (`--stage l1-v2` or `--rubrics-file`)
until the OOD escape-hatch rate drops near `0%` and scores turn bimodal.

### 4. Baseline novelty reconciliation and line-verified report

Run `--stage l3-novelty` with `--baseline-file <current-rules-summary.md>` over
Round 2 survivors to separate:
- `cockpit_or_target_gap` (uncovered actionable gap),
- `route_to_sibling_repo` (valid lesson owned by another repo),
- `already_covered` (prevented by existing docs, hooks, or tests).

Re-open the raw JSONL lines or the read-only SQLite items at the cited ordinals
for every surviving gap. Verify current repository files before presenting
`evidence locator -> concrete harm -> live coverage -> minimal fix -> canonical owner`.

## Configuration

Resolved through `scripts/skill_config.py` (see [references/configuration.md](references/configuration.md)),
with fallback to `GHC_DECISIONS_*` and `EVALS_*` environment variables so an
existing `ghc-decisions` setup works with zero duplicate configuration:

| Key | Flag | Environment variable | Default |
|---|---|---|---|
| `base_url` | `--base-url` | `SESSION_HISTORY_MINING_BASE_URL` (falls back to `GHC_DECISIONS_BASE_URL`) | none (required for `judge` / `anchor-check`) |
| `model` | `--model` | `SESSION_HISTORY_MINING_MODEL` (falls back to `GHC_DECISIONS_MODEL`) | none (required for `judge` / `anchor-check`) |
| `api` | `--api` | `SESSION_HISTORY_MINING_API` | `decisions` (`decisions` or `chat-completions`) |
| `workers` | `--workers` | `SESSION_HISTORY_MINING_WORKERS` | `16` |
| `api_key` | — | `SESSION_HISTORY_MINING_API_KEY` | `dummy` |

## Additional resources

- `scripts/mine_sessions.py` — stdlib-only extractor, multi-head `/v1/decisions` batch runner, anchor verifier, and residual analyzer.
- `scripts/mining_rubrics.json` — bundled `l0`, `l1-v1`, `l1-v2`, `l3-novelty` rubrics and the 16-item locked gold anchor set.
- `scripts/skill_config.py` — vendored configuration resolver.
- `scripts/tests/test_mine_sessions.py` — offline extraction, redaction, OOD residual, and anchor-gating tests.
- [references/methodology.md](references/methodology.md) — algorithmic design: why Softmax hides OOD, hierarchical skeleton complexity, orthogonal multi-head projection, and residual active learning.
- [references/configuration.md](references/configuration.md) — configuration lookup order and file path.
- [references/troubleshooting.md](references/troubleshooting.md) — read only when a `uv run` command fails.
