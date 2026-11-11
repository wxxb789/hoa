# Goal — the eval judge runs on a configuration, and the README explains the shape

Increment id: `eval-judge-and-architecture`
Repo: `wxxb789/hoa` · one run · one PR · mergeable alone

## Why this exists (the failure it answers)

1. **The judge is not runnable by anyone but this machine.** `evals/judge_trigger_evals.py` hard-codes
   `JUDGE_MODEL = "gpt-5.6-luna"` and calls `ghc_search.post(ghc_search.default_endpoint(), …)` — a
   specific gateway reached through another skill's private script. `run_trigger_evals.py` grades
   only structure and catalog cross-references, so CI is green while the actual routing quality of the
   library has never been measured anywhere reproducible. The repo's own rule (`skill-porting-and-publishing`)
   says configuration is a gate, not advice; this file violates it in the one place where a wrong model
   quietly turns into a wrong pass rate.
2. **No baseline.** Even when the judge runs, nothing records what the pass rate was, on which model,
   on which case set. A number nobody can compare against is not evidence.
3. **README describes the catalog, not the machine.** A reader learns that skills exist; they do not
   learn the layering (entry / controller / reference artifacts), the contract graph and its R-rules,
   how a stage is gated, or what the evals are for. The first thing a new contributor or an agent
   needs is the shape of the thing, and it is not written down.

## 1. Observable pass condition

- `evals/judge_trigger_evals.py` resolves **judge endpoint, judge model and judge effort** through
  `scripts/skill_config.py` in the documented order (CLI flag → environment variable → config file →
  documented default). No model id, gateway URL or key name is a literal in the script.
  - With nothing configured, the script exits 2 and prints the exact keys it needs and where the
    config file lives. It must not silently fall back to a model nobody chose.
  - A configured run works against a plain OpenAI-compatible chat-completions endpoint (no
    dependency on `ghc-search`'s private client); a `--base-url`, `--model`, `--effort` flag wins over
    env, which wins over the config file.
- A judged run writes a **baseline record** `evals/baseline.json`: `{case_count, model, effort,
  passed, total, judge_endpoint_host, generated_at, per_case: [{id, pick, passed}]}` — machine-readable,
  committed only by explicit `--record`, never overwritten silently.
- `evals/run_trigger_evals.py` (the CI gate, still offline) additionally proves the baseline record is
  internally consistent: every case id exists, `passed == sum(per_case.passed)`, `case_count == len(cases)`.
  It stays offline and deterministic — no network in CI.
- `README.md` gains a section "How this repository is shaped" that states, at minimum:
  - the four layers and what each is for (skills / agents / mcps / orchestration / prompts / rules /
    workflows as they actually exist), with the frontmatter `kind` values used by the contract graph;
  - the contract graph and every rule it enforces by number (R1..R9), each with one line of what it
    rejects;
  - the gate set CI runs and what each gate protects;
  - how an eval case is graded, and the honest limit of a single-model judge.
  Every claim in that section must be true of the tree: each rule number, each gate command and each
  `kind` value is verified against the code, not recited from memory.

## 2. Judging artifact

- `python evals/judge_trigger_evals.py --limit 3 --json` against a configured endpoint prints a JSON
  object with `passed`, `total`, `results[]` and exit code 0/1 — the operator runs this themselves
  during verify and pastes the real output into the evidence record.
- `python evals/run_trigger_evals.py` exits 0 with the baseline-consistency checks included.
- `grep -nE 'gpt-|ghc' evals/judge_trigger_evals.py` returns nothing.

## 3. Failure control

- Without configuration: exit 2, message names the three keys and the config path — proven by a test
  that runs the script with an empty environment and an empty `XDG_CONFIG_HOME`.
- A malformed config file: exit 2 naming `path:line` (the resolver's existing behaviour, reused).
- A judge reply that does not name a catalog entry: counted as a failed case with `pick` preserved
  verbatim; the batch still completes.
- Network failure on one case: per-case failure, never aborts the other cases (existing behaviour,
  keep it and keep the test).

## 4. Out of scope

- Judging the `skill-method-cases.json` suite (it keeps its own validator).
- Changing any case's `must_pick` / `distractors`.
- Multi-judge consensus, temperature sweeps, or cost accounting.
- Rewriting README sections other than the new architecture section and any statement the new judge
  configuration falsifies.

## 5. Evidence plan

- Test file(s) for the resolver wiring (no network): flag > env > config > default, and the
  unconfigured exit-2 path.
- **Who runs the real judge:** the authoring agent proves the wiring against a local, stdlib-only
  stub of an OpenAI-compatible chat-completions endpoint on `127.0.0.1` (no network, no
  credentials, no key in any test). The operator then performs the real judged run with
  `--record` against a configured endpoint and pastes that output into the evidence record. The
  increment is not mergeable on the stub alone, but the stub is what CI can hold.
- A README diff read against the code: every rule number and gate command checked in the tree.

## 6. Mergeable alone

Touches `evals/`, `scripts/skill_config.py` consumers, `README.md`, `VERSION`, `CHANGELOG.md` and the
evidence record. No change to any skill's frontmatter, no change to the contract graph rules
themselves. Reverting the commit restores the previous judge exactly.
