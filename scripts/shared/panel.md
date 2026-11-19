# Audit panel protocol

Finders, then adversarial verifiers, then a completeness critic, then a parent spot-check.
The audit is read-only on its subject. Each SKILL.md supplies the dimensions, inputs and verdicts.

## Run directory (outside the subject; never committed)

`--state-dir` flag → `AUDIT_STATE_DIR` → `state_dir` in `${XDG_CONFIG_HOME:-~/.config}/audits/config.yaml`
→ `${XDG_STATE_HOME:-~/.local/state}/audits`. A run is `<root>/<subject-slug>/<YYYY-MM-DD>/` (slug: the repo
name or `practice`; pick a distinct slug if a name is shared, and use the session date). The prior run is the
newest sibling directory. The same config file may set `lens_file` (replaces the lens below).

`AUDIT_STATE_DIR` and `~/.config/audits/config.yaml` (or its XDG equivalent) deliberately share a
namespace between `hoa-practice-retro` and `hoa-repo-reckoning` so they can read each other's ledgers.
This is an exception to the per-skill config convention.

For `hoa-practice-retro`, `HOA_PRACTICE_RETRO_ROOTS` (JSON array of workspace paths) overrides
`roots`, and `HOA_PRACTICE_RETRO_REPORT_LANGUAGE` overrides `report_language` in
`${XDG_CONFIG_HOME:-~/.config}/hoa-practice-retro/config.yaml`. The usual order applies:
CLI flag (if available), environment variable, config file, then the skill's documented default.

| File | Writer |
|---|---|
| `scope.md` | parent: subject, pinned ref/window, depth, dimensions and why, capabilities used or missing, prior run, cost estimate |
| `find-<dim>.json` | finder: `{"dim": "...", "findings": [Finding, ...]}`; `[]` is a valid result |
| `verify-<dim>.json` | verifier: `{"dim": "...", "verdicts": [Verdict, ...]}` |
| `find-critic.json`, `verify-critic.json` | critic and its verifier |
| `spot.json` | parent: `["finding-id", ...]` it re-checked itself (✔ in the report) |
| `report.md`, `ledger.jsonl` | `scripts/findings.py report` |
| `decisions.jsonl` | `scripts/findings.py decide` only, after the owner answers |

```text
Finding: {"id": "kebab-id-stable-across-runs", "kind": "dumb|unknown", "title", "claim",
          "evidence": ["path:line", "cmd -> observed output", "bundle:<origin>#<file>?line=N"],
          "impact", "action", "owner": "here|<other repo or skill>", "effort": "S|M|L",
          "severity": "high|medium|low", "sources": ["https://..."]   # required for kind unknown}
Verdict: {"id", "verdict": "confirmed|weakened|refuted", "claim": "(required when weakened)",
          "severity": "(optional downgrade)", "rationale", "checked": ["what the verifier ran itself"]}
```

## Steps

1. **Scope.** Write `scope.md` first. Depth: `quick` = 3–4 dimensions, no external lane; `standard`
   (default) = 6–9 dimensions plus the external lane; `deep` = standard plus per-slice sub-briefs. State
   the cost before fanning out (reference standard run: 20 workers, about 1.3M tokens; quick is about a
   tenth). Escalate depth only on request. Scheduled runs default to `quick`.
2. **Evidence basis.** Every dimension brief names its risk class: data loss or spend, trust boundary
   (work/personal bleed, identity, secrets), irreversible state, or recurring cost. Size, counts and
   "many files" are informational until tied to one. `(unavailable)` is missing data, never a finding.
3. **Find.** One brief per dimension, at most about 15 files or 2k lines per slice (cut bigger scopes
   into named sub-slices). A brief carries the subject path, the dimension, the lens, the prior ledger
   ids for that dimension, and the output path. Pass paths, never pasted content. The **external
   lane** (one or two finders) only hunts unknown unknowns: platform features, ecosystem tools and
   practices that would replace or obsolete what the subject does. Each needs a `sources` URL **and**
   local evidence that it applies here.
4. **Verify adversarially.** One verifier per dimension, in a context that did not produce the
   findings. It gets the find file and the subject, never the finder's reasoning. It re-runs or
   re-reads the evidence itself (`checked` is never empty), tries to refute each finding, else narrows
   it (weaken the claim, downgrade severity). It also applies the cost bar: the cause is still on the
   current tree, and the fix costs less than the cost it removes.
5. **Critique.** One critic reads `scope.md`, every verified finding and the dimension roster, asks
   what a competent outsider would have checked that nothing covered, and writes `find-critic.json`.
   A verifier pass on it follows.
6. **Spot-check.** The parent re-runs the decisive evidence of every high-severity finding and every
   finding whose action deletes something, then lists those ids in `spot.json`. Worker reports are
   evidence, not acceptance.
7. **Report.** Run `uv run scripts/findings.py check RUN`, then
   `uv run scripts/findings.py report RUN --prev PRIOR` (omit `--prev` on a first run).
   Above the generated tables, write a ≤5-line **meta-diagnosis** (the one pattern behind most
   findings) and a **suggested order** (day 0: pure deletion or config; week 1; later).
8. **Gate.** Nothing in the subject changes. Each item the owner rules on is recorded with
   `uv run scripts/findings.py decide RUN ID accepted|rejected|done "reason"`; a rejected id stays suppressed until
   its evidence changes. Unattended runs (no user) stop after step 7 and record no decisions; a missing
   answer is not a rejection.

## Fan-out: a capability, with a sequential fallback

Needed: start N independent workers, each with a fresh context, a written brief, read-only access to
the subject, and a way to return a JSON file. Optional: web search; a model from another family for the
external or critic lane. Runtimes differ (subagents or task agents, a headless CLI per brief such as
`codex exec --output-schema` or `claude -p`, an orchestrator that can host any of them). Detect what
this runtime exposes and record it in `scope.md`; do not assume. Dispatch all finders in one batch,
then all verifiers in one batch; verifiers never see finder transcripts.

**No worker primitive:** run each dimension yourself, one at a time, and write its find file before
starting the next. Verify only after every find file exists, reading only the files and the subject.
Put `verification: single-context` in `scope.md` (the report header copies it). **No web search:**
put `external lane: not run` in `scope.md`; table B then says so instead of looking empty.

## Default lens (the subject's own AGENTS.md / CLAUDE.md wins on conflict)

- **Default to deletion.** For each gate, check, abstraction or doc: what irreversible harm would its
  removal risk (work/personal bleed, wrong identity, secret or config leak, data loss), and has the same
  pain recurred three times? If neither, it is a deletion candidate.
- **Every check binds to a decision.** Which owner action does a red result trigger? None means ceremony.
- **Stdlib and platform first.** Hand-rolled code a platform or tool already provides (server-side
  rulesets, schema-validated CLI JSON, pytest) is a finding.
- **No single-caller wrappers, custom verification envelopes, or lockfile ceremony on zero-dependency code.**
- **Measure before build.** Features shipped while the measurement that would justify them is unrun.
- **Diagnostics name the exact offending key, path or value.**
