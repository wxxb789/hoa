# Session History Mining Methodology

## Why Naive Multi-Pass Linear Funnels Fail

1. **Closed-set Softmax OOD blindness.** In a standard mutually exclusive `choice`
   over `{noise, bucket_1, ..., bucket_k}`, an out-of-distribution (OOD) incident
   that matches none of the positive buckets shares zero features with `bucket_i`
   and gets pushed into the catch-all `noise` bucket with `P(noise) > 0.95`
   (epistemic uncertainty masquerading as high confidence). Entropy only peaks
   when an input straddles two *known* buckets (aleatoric ambiguity).
   **Fix:** Pair an unbiased, category-free `anomaly_probe` (`predicate`) with an
   explicit `unclassified_novel_*` escape-hatch choice. Rank OOD with
   `ood_residual = p_anom * (p_novel + 0.5 * max(0.0, 1.0 - p_routine - max_known))`,
   where `max_known` is the largest probability of a known non-routine bucket.
   For aleatoric ambiguity, inspect `confusion_pairs`: recurring high-overlap
   pairs of known positive buckets are merge candidates when both call for the
   same action.
2. **Repeated KV-cache prefill waste.** On `/v1/decisions`, encoding the state
   window dominates latency and cost (~95%+), whereas evaluating 3–4 independent
   orthogonal questions on the same encoded state is nearly free. Splitting
   orthogonal dimensions (evidence backing, failure mechanism, target owner,
   cross-repo durability) into serial passes wastes prefill and forces artificial
   competition between non-mutually-exclusive traits.
3. **Trajectory severance under blind chunking.** Agent sessions are Markov
   trajectories: a root cause at line 20 may surface at line 90 and be diagnosed
   at line 140. Fixed-line chunking severs cause from diagnosis.
   **Fix:** Build a whole-session **Session Skeleton** (`L0`) retaining 100% of
   human turns, tool/hook errors, and boundary claims while folding clean local
   read/edit streaks into single summary lines. Prune whole clean sessions at `L0`
   before zooming into overlapping causal turn-windows (`L1`).
4. **Prompt calibration drift across iterations.** Editing rubric wording shifts
   the Softmax temperature and baseline probabilities. Apparent "bimodal
   sharpening" without a locked validation set can simply reflect pushing gray-zone
   positives into `noise`.
   **Fix:** Gate every rubric revision on a locked 16-item Gold Anchor Set (8 true
   positives + 8 deceptive negatives). Accept a revision only when false negatives
   stay `0` and `worst_case_gap = min(score_pos) - max(score_neg)` is non-decreasing.

## Store Schemas Covered

### Claude Code (`~/.claude/projects/<project-slug>/`)

- Main sessions: `<session-uuid>.jsonl`
- Subagent workflows: `<session-uuid>/subagents/**/journal.jsonl` (filter rows
  with `"failed"`, `"error"`, or `"aborted"` and load matching `agent-<id>.jsonl`).
- Key records:
  - `type == "user"`: human string/text blocks (`isMeta != true`) and `tool_result`
    blocks (`is_error == true` or non-zero exit status).
  - `type == "assistant"`: `text` blocks and `tool_use` blocks (`id`, `name`, `input`).
  - `type == "system"`: `hookErrors[]`, `compact_boundary`, and `api_error` /
    `turn_aborted` warnings.
- Boilerplate stripping: delegated subagent tasks prepend `[Workflow harness — computed task] ... would be forged.`; replace that frame before classification so safety filters do not misfire.

### Oh My Pi / OMP (`~/.omp/agent/sessions/<encoded-cwd>/`)

- Main sessions: `<timestamp>_<session-uuid>.jsonl` (`type == "session"` line
  carries `cwd` and optional `parentSession` for branched continuations).
- Key records:
  - `type == "message"` with `message.role == "user"`: `message.content[].text`
    (strip injected `<system-reminder>` / `<system-notice>` wrappers when indexing
    human intent).
  - `type == "message"` with `message.role == "assistant"`: `message.content[]`
    contains `text` and `toolCall` (`id`, `name`, `arguments`).
  - `type == "message"` with `message.role == "toolResult"`: `toolCallId`,
    `toolName`, `isError`, and `content[].text`.

### Codex (`~/.codex/`)

- Prefer existing rollout JSONL. Completed items take precedence over duplicate
  raw response records; older rollouts can use `response_item` records directly.
  Without both databases, scan `rollout-*.jsonl`, including under `sessions/` and
  `archived_sessions/`.
- If a rollout is missing, look up its thread in `state_5.sqlite` and reconstruct
  its records from `thread_history_1.sqlite` in `rollout_ordinal` order. SQLite
  locators use those ordinals; JSONL locators use physical file lines.
- Open SQLite read-only. When WAL sidecars are missing or a lock blocks reads,
  use an immutable view to avoid creating or touching sidecars. The warning
  means recent WAL changes may be unavailable.
- Within the selected directory scope, retain user threads, clean `worker` or
  `default` subagents, and subagent threads with tool errors. Omit other clean
  internal roles unless `--include-codex-subagents` is passed.

## Stopping Criterion

Stop iterating `L1` rubrics as soon as:
1. Anchor `false_negatives == 0` and `worst_case_gap` improved or held steady;
2. `unclassified_novel_*` top-choice share drops below `1%` (or `< 3` spans);
3. Sampling the negative boundary (`max_neg_audit`) reveals zero missed cross-repo lessons.

Proceed immediately to `L3` baseline novelty reconciliation against live repository
files rather than over-tuning taxonomy labels.
