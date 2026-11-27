---
name: hoa-practice-mine
description: >-
  Mine local Claude Code, OMP, and Codex session history and project memory stores
  for reusable operational guardrails and unknown unknowns using two-level pruning,
  multi-head `/v1/decisions` probes, residual active learning, and raw-line verification.
  Explicit invocation only. Use hoa-practice-retro for periodic cross-repo retros
  and rubric-tune for iterative rubric refinement.
disable-model-invocation: true
metadata:
  revision: "2"
  areas: "self-management,software-development"
  targets: "runtime-agnostic"
  summary: "mine local session history and memory stores for reusable guardrails and unknown unknowns using a decision model"
  summary_zh: "用 Decision Model 低成本挖掘本地会话与记忆中的可复用护栏和未知盲区"
  kind: "entry"
---

# hoa-practice-mine

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

Use the Bash `hoa` function below to run the packaged CLI via `uvx`. In a local
checkout use `uv run hoa ...` instead, or omit the function if `hoa` is installed.
Only if a command fails, read [references/troubleshooting.md](references/troubleshooting.md).
See [references/methodology.md](references/methodology.md) for the underlying
information-theoretic contracts and residual formulas.

### 1. Extract redacted L0 skeletons and L1 causal spans

```bash
# Bash example (adjust variable syntax for PowerShell or other shells)
hoa() { uvx --from git+https://github.com/wxxb789/hoa hoa "$@"; }
OUT="<scratch-dir>"   # e.g. a gitignored scratch directory

hoa history extract \
  --claude-root ~/.claude/projects \
  --omp-root ~/.omp/agent/sessions \
  --codex-root ~/.codex \
  --include-memories \
  --cursor-file "$OUT/extract-cursor.txt" \
  --min-lines 12 \
  --out-dir "$OUT"
```

Add `--allow-regex '<pattern>'` / `--deny-regex '<pattern>'` when filtering
personal vs. work project directories.

Supply only the roots you intend to mine. For a follow-up run over a backlog
already mined, add `--since <ISO date>` to keep only sessions active since then
(file modification time for JSONL; `threads.updated_at` for Codex SQLite); the
manifest records the cutoff. Alternatively pass `--cursor-file <path>` to read
and update an incremental watermark automatically when `--since` is omitted, and
`--min-lines 12` to skip one-turn probe sessions up front. `extract` streams
`skeletons.jsonl` and `spans.jsonl` incrementally to disk as sessions are parsed.
Codex prefers existing JSONL rollouts
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
  and exact `file:Lstart-Lend` locators. Identical spans across branched sessions
  are deduplicated by content hash by default (`--no-dedup-spans` disables this).
- `memories.jsonl` — when `--include-memories` is passed, redacted Claude project
  `memory/*.md` files and scope-matched Codex `memories_1.sqlite` summaries ready
  to score directly at `l3-novelty` against live rules.
- `extract-manifest.json` — coverage by root, including Codex included/skipped
  threads and counts backed by JSONL or SQLite. For SQLite evidence,
  `thread_history_1.sqlite#thread=<id>` locators use `rollout_ordinal` values,
  not file lines.

### 2. Level 0 tree-root pruning (`skeletons.jsonl`)

```bash
hoa mine judge \
  --stage l0 \
  --input "$OUT/skeletons.jsonl" \
  --output "$OUT/l0-scored.jsonl"
```

Retain sessions with `anomaly_probe >= 0.20`, `user_correction_probe >= 0.20`,
raw `durability >= 0.45` (`>= 0.225` normalized for the bundled L0 scale),
`p_clean < 0.80` (`routine_clean` and `one_off_code_bug` probability mass),
or non-zero `hook_errors`. On large backlogs where the loose OR retains too many
sessions, pass `--strict` (requiring `(anomaly AND durability) OR correction OR
hook_errors`) and tune `--min-anomaly` / `--min-durability` / `--min-correction`.
`filter-spans` fails open for model refusals and
request failures: it keeps those sessions eligible for pivot selection and
counts only model refusals in `l0_refusal_sessions`. If `judge` writes a ledger
but exits `1` for failed requests, investigate the failures and use the ledger
for fail-open filtering; do not treat failed rows as clean. Audit the top 5–8
pruned sessions near the boundary before zooming into L1.

### 3. Level 1 orthogonal multi-head scan + residual reflection

Filter `spans.jsonl` to pivot spans belonging to L0-surviving sessions. For routine
mining runs using the bundled rubrics (once `anchor-check` has passed for your
endpoint), score directly with `--stage l1-v2` to halve model calls; run `l1-v1`
first only when iterating on a custom taxonomy (hand off deeper rubric refinement
to `rubric-tune`).

```bash
hoa mine filter-spans \
  --strict \
  --l0 "$OUT/l0-scored.jsonl" \
  --spans "$OUT/spans.jsonl" \
  --output "$OUT/l1-candidates.jsonl"

hoa mine judge \
  --stage l1-v2 \
  --input "$OUT/l1-candidates.jsonl" \
  --output "$OUT/l1-r2-scored.jsonl"

hoa mine residuals \
  --stage l1-v2 \
  --scored "$OUT/l1-r2-scored.jsonl" \
  --spans "$OUT/l1-candidates.jsonl" \
  --output "$OUT/r2-residuals.json"
```

Inspect the following residual pools in `r1-residuals.json` (pull adjacent
spans when truncated):
1. **Epistemic OOD pool** (`ood_residual = p_anom * (p_novel + 0.5 * max(0.0, 1.0 - p_routine - max_known))`,
   where `max_known` is the largest probability among known, non-routine buckets):
   add a positive bucket only for genuine unknown mechanisms.
2. **High-anomaly gray-zone pool** (`P(anomaly) >= 0.80` with a normalized
   guardrail score in `[0.25, 0.70]` or Shannon entropy `>= 1.50`): inspect
   routine noise and add explicit negative exclusions if needed.
3. **Refusal pool**: `refusal_count` sums model refusals (`reason: model_refusal`)
   and failed requests (any other `reason`, such as HTTP errors or timeouts).
   Fix the endpoint for the latter; for the former, inspect the framing and strip
   any new fixed injection shell with `--redact-regex`.

Use `confusion_pairs` to find recurring overlap between two known positive
buckets. Inspect examples before merging labels that call for the same action.

After inspecting Round 1, check the candidate against the locked anchors,
then run and inspect Round 2. The commands below use the bundled `l1-v2`.
For a custom revision, prepare a rubric file that preserves the anchors and
`l1-v1` baseline and carries the revised `l1-v2`; pass `--rubrics <file>` to
`anchor-check`, the Round 2 commands, and `select-survivors`.

```bash
hoa mine anchor-check --baseline-stage l1-v1 --candidate-stage l1-v2
```

Continue only if the anchor check passes.

```bash
hoa mine judge --stage l1-v2 \
  --input "$OUT/l1-candidates.jsonl" --output "$OUT/l1-r2-scored.jsonl"
hoa mine residuals --stage l1-v2 \
  --scored "$OUT/l1-r2-scored.jsonl" --spans "$OUT/l1-candidates.jsonl" \
  --output "$OUT/r2-residuals.json"
```

Apply the [stopping criterion](references/methodology.md#stopping-criterion)
before advancing; do not refine a rubric at the expense of the anchors.

### 4. Baseline novelty reconciliation and line-verified report

Join strong non-routine Round 2 judgments back to their source spans to
restore the `text` stripped by `judge`. Assemble `current-rules-summary.md`
from the target repositories (or curate one manually), then score the restored spans:

```bash
hoa mine baseline --repo /path/to/repo-a --repo /path/to/repo-b \
  --output "$OUT/current-rules-summary.md"
hoa mine select-survivors --stage l1-v2 \
  --scored "$OUT/l1-r2-scored.jsonl" --spans "$OUT/l1-candidates.jsonl" \
  --output "$OUT/l3-candidates.jsonl"
hoa mine judge --stage l3-novelty --baseline-file "$OUT/current-rules-summary.md" \
  --input "$OUT/l3-candidates.jsonl" --output "$OUT/l3-scored.jsonl"
```

Separate the resulting novelty judgments:
- `target_gap` (uncovered actionable gap),
- `route_to_sibling_repo` (valid lesson owned by another repo),
- `already_covered` (prevented by existing docs, hooks, or tests).

Re-open the raw JSONL lines or the read-only SQLite items at the cited ordinals
for every surviving gap:

```bash
hoa history show --spans "$OUT/spans.jsonl" --format readable --context 3 <span-id> [<span-id> ...]
```

`show` prints unredacted evidence for the primary agent (use `--format raw` for
verbatim JSONL lines); never forward it to a decision endpoint. If `--include-memories`
was used, also run `l3-novelty` on `$OUT/memories.jsonl` to surface high-signal
single-machine memories ready to graduate into canonical repos. Verify current
repository files before presenting
`evidence locator -> concrete harm -> live coverage -> minimal fix -> canonical owner`.

## Configuration

See [references/configuration.md](references/configuration.md). After the skill-specific
lookup, unset keys fall back to `SESSION_HISTORY_MINING_*` (legacy alias),
`RUBRIC_JUDGE_*`, `GHC_DECISIONS_*`, then `EVALS_*` environment variables.
The config file is `$XDG_CONFIG_HOME/hoa-practice-mine/config.yaml` (fallback
`~/.config/hoa-practice-mine/config.yaml`); the fallback reads environment
variables only, never another skill's config file.

| Key | Flag | Environment variable | Default |
|---|---|---|---|
| `base_url` | `--base-url` | `HOA_PRACTICE_MINE_BASE_URL` (falls back to `RUBRIC_JUDGE_BASE_URL`) | none (required for `judge` / `anchor-check`) |
| `model` | `--model` | `HOA_PRACTICE_MINE_MODEL` (falls back to `RUBRIC_JUDGE_MODEL`) | none (required for `judge` / `anchor-check`) |
| `api` | `--api` | `HOA_PRACTICE_MINE_API` | `decisions` (`decisions` or `chat-completions`) |
| `workers` | `--workers` | `HOA_PRACTICE_MINE_WORKERS` | `16` |
| `api_key` | — | `HOA_PRACTICE_MINE_API_KEY` | `dummy` |

## Additional resources

- [agents/openai.yaml](agents/openai.yaml) — explicit-only invocation policy for Codex.
- [references/methodology.md](references/methodology.md) — algorithmic design: why Softmax hides OOD, hierarchical skeleton complexity, orthogonal multi-head projection, and residual active learning.
- [references/configuration.md](references/configuration.md) — configuration lookup order and file path.
- [references/troubleshooting.md](references/troubleshooting.md) — read only when a CLI command fails.
