# Plan — the eval judge runs on a configuration, and the README explains the shape

Contract: [`docs/goals/2026-11-11-eval-judge-and-architecture.md`](../goals/2026-11-11-eval-judge-and-architecture.md)
Increment: `eval-judge-and-architecture` · branch `feat/eval-judge-and-architecture`

The repo's designated plan location is `docs/plans/` (the two archived increments use it). The
contract moves to `docs/goals/archive/` unchanged on close.

## 1. Public / API shape

### 1.1 `evals/judge_trigger_evals.py`

The script keeps its job — build the catalog from `scripts/generate_index.py`, ask a fresh-context
judge one routing question per case, report per-case pass/fail — and replaces its private client.
No `ghc_search` import, no `JUDGE_MODEL` literal, no default endpoint.

```bash
python evals/judge_trigger_evals.py [--limit N] [--json] [--record] [--force]
                                    [--base-url URL] [--model NAME] [--effort LEVEL]
```

Resolution through `scripts/skill_config.py`, in the documented order
(`flag → env → $XDG_CONFIG_HOME/evals/config.yaml`, fallback `~/.config/evals/config.yaml →
default`):

| Config key | CLI flag | Environment variable | Default |
|---|---|---|---|
| `base_url` | `--base-url` | `EVALS_BASE_URL` | none — required |
| `model` | `--model` | `EVALS_MODEL` | none — required |
| `effort` | `--effort` | `EVALS_EFFORT` | `low` |
| `api_key` | — | `EVALS_API_KEY` | none — request is unauthenticated |

- The config namespace is the literal `evals`; the environment names follow the resolver's
  `<SKILL_BIG_SNAKE>_<KEY_BIG_SNAKE>` rule and are documented in the module docstring.
- The credential key is generic (`api_key`), not a vendor name; the script never names a gateway's
  key. The secret is read from the resolver so env beats the config file; there is no `--api-key`
  flag (a command line leaks into `ps`).
- `base_url` is the OpenAI-compatible base. `/chat/completions` is appended unless the value already
  ends with it. Only `http`/`https` URLs are accepted.
- The request body is `{model, messages:[{role:user, content}], max_tokens:2048,
  reasoning_effort: effort}`. `reasoning_effort` is the chat-completions spelling of the resolved
  effort; the baseline records the same string.
- The reply is read from `choices[0].message.content`; the pick is the stripped string verbatim.
  Grading is unchanged: pass iff `pick in case["must_pick"]`. A reply that names no catalog entry
  is a failed case whose `pick` stays verbatim; the batch continues.
- One case's exception (HTTP error, connection error, unusable payload) becomes
  `pick = "error: ..."`, `passed = false`; other cases still run.

Exit codes: `0` all cases passed, `1` at least one failed (including per-case errors), `2`
configuration/usage error (missing `base_url`/`model`, malformed config, record conflict,
`--record` with `--limit`, `--force` without `--record`).

Unconfigured output (exit 2) names all three keys and the config path:

```text
judge_trigger_evals: judge endpoint and model are not configured.
  base_url  --base-url / EVALS_BASE_URL        (missing)
  model     --model / EVALS_MODEL              (missing)
  effort    --effort / EVALS_EFFORT             default: low
config file: <XDG_CONFIG_HOME-or-HOME>/.config/evals/config.yaml
```

A `ConfigError` from the resolver is printed as `judge_trigger_evals: <path>:<line>: ...` with
exit 2, which is the resolver's existing malformed-config behaviour.

#### Baseline record

`--record` writes `evals/baseline.json` atomically with exactly:

```json
{
  "case_count": 25,
  "model": "<resolved model>",
  "effort": "<resolved effort>",
  "passed": 25,
  "total": 25,
  "judge_endpoint_host": "<host[:port]>",
  "generated_at": "<UTC ISO-8601 seconds>Z",
  "per_case": [{"id": "...", "pick": "...", "passed": true}]
}
```

- Only `--record` writes it. A judged run without `--record` never touches the tree.
- `--record` refuses a partial run (`--limit`) with exit 2: the CI check compares `case_count` with
  the full suite, so a partial record would be born inconsistent.
- An existing record is never overwritten silently: without `--force` the script exits 2 before any
  network call; `--force` replaces it and says so on stderr.
- The write is a temp file in the same directory plus `os.replace`, so a crash cannot leave a
  half-written baseline.
- `judge_endpoint_host` is `urlsplit(base_url).netloc`, i.e. host plus port when present. No path,
  query, credentials or API key enters the record.

### 1.2 `evals/run_trigger_evals.py`

Stays offline and deterministic. It keeps every existing structural/catalog check and adds a
baseline check:

- absent record → allowed (a fresh checkout before the first `--record`), reported as
  `no baseline recorded yet`, exit 0;
- present record → every `per_case.id` must exist in `trigger-cases.json` and be unique;
  each entry needs `id:string`, `pick:string`, `passed:bool`;
  `passed == sum(per_case.passed)`, `case_count == len(cases)`, `total == case_count`,
  `len(per_case) == case_count`, `0 <= passed <= total`;
  `model`, `effort`, `judge_endpoint_host`, `generated_at` must be non-empty strings;
  wrong types, unknown keys are not rejected, malformed JSON is an error.
- Any violation prints `run_trigger_evals: baseline.json: ...` and exits 1. No network.

The extra `total`/`len(per_case)` equalities are what make "internally consistent" mean the file
actually describes the run it claims; the contract's three checks are all included.

### 1.3 `evals/test_judge_trigger_evals.py`

Stdlib only, no network beyond `127.0.0.1`:

- subprocess CLI tests: unconfigured exit 2 with the three key names and config path; malformed
  config exit 2 naming `path:line`; flag > env > config > default for `base_url`/`model`/`effort`
  (three stub servers, asserting which one received the request and which model/effort arrived);
  env > config for `api_key` via the `Authorization` header;
- a `http.server` stub implementing `POST /v1/chat/completions` (writes JSON, reads
  `choices[0].message.content`), correct picks read from `trigger-cases.json` so no answer is
  hard-coded;
- `--limit 3 --json` → exit 0, `{passed,total,results[]}` shape, three results;
- non-catalog reply → that case fails with `pick` verbatim, others pass, exit 1;
- one HTTP 500 → that case fails with `error: ...`, others pass, exit 1;
- `--record` with `--limit` → exit 2; `--record` full stub run writes the exact schema; a second
  record without `--force` exits 2 and leaves the bytes unchanged; `--force` replaces it;
- `run_trigger_evals` baseline validator: absent, valid, unknown id, duplicate id, wrong sum,
  wrong `case_count`, wrong `total`/length, non-bool `passed`, malformed JSON; and `main()` exits 0
  with a valid record and 1 with a broken one (patched baseline path; the real tree is untouched).

Tests write fixtures only under `.tmp-artifacts/eval-judge-tests/`, construct the child environment
from scratch (`HOME`, `XDG_CONFIG_HOME`, no `EVALS_*`), and never read the operator's config.

### 1.4 `README.md` — "How this repository is shaped"

A new section between "Structure" and "Unified skill versions" (the Chinese mirror gets the same
section in `README.zh-CN.md`, per the repo's bilingual policy). It contains only claims checked
against the tree:

1. **Four composition layers** — the `metadata.kind` values `entry`, `controller`, `stage`,
   `mechanism`, with what each is for and the current counts/example of non-entry ones.
2. **Surfaces** — `skills/` (deployable, 40 at this tree) versus the library folders
   (`agents/`, `mcps/`, `orchestration/`, `prompts/`, `rules/`, `workflows/`, each with its actual
   artifact count), plus `evals/`, `reflections/`, `ref/`, `scripts/`; generated `index.md` /
   `index.zh-CN.md`; deployment split with chezmoi.
3. **Contract graph R1..R9** — every rule number with one line of what it rejects, each read from
   `scripts/check_contract_graph.py`, not recited.
4. **The CI gate set** — every step command in `.github/workflows/ci.yml` (including the new judge
   test step and the PR-only and release conditions) with what it protects.
5. **Eval grading and its honest limit** — catalog construction, prompt, exact-match grading,
   `--record` baseline, offline baseline arithmetic, and the single-model/single-prompt limits:
   the pass rate says that one model on that date routed the curated cases as intended, not that
   users will; a changed model, effort, prompt or case set breaks comparability.

Existing README statements that the new judge configuration falsifies are updated; other sections
are not rewritten.

## 2. Edge-case semantics

- Empty flag/env values are "not supplied" (the resolver's rule); the next step wins.
- A flag/environment value suppresses the corresponding config read, but `api_key` has no flag, so
  a malformed config file still fails a fully flagged run unless `EVALS_API_KEY` wins first. This
  is the resolver's normal precedence, not a special case.
- `--limit` bigger than the case count judges the whole suite; `--limit 0` means all cases.
- Empty cases still exit 1 (`no cases to judge`), as before.
- `effort` is not validated against a fixed list: the endpoint may accept levels this repo does not
  know. The default is `low`.
- The baseline never includes `must_pick`, error text beyond the pick, or the API key.
- A stale baseline (case set changed) fails CI rather than being silently ignored; re-record with
  `--record --force`.

## 3. Evidence plan

1. `python -m unittest evals.test_judge_trigger_evals -v` — all wiring and failure-control tests.
2. Real CLI unconfigured run with a clean environment: exit 2, key names, config path.
3. Real CLI malformed-config run: exit 2, `path:line`.
4. Real CLI stub run with the full `trigger-cases.json`: `--json` output, exit 0; a full
   `--record` run into a temp baseline path, then the baseline checker accepts it and rejects a
   deliberately broken copy (real command output).
5. `grep -nE 'gpt-|ghc' evals/judge_trigger_evals.py` — no output.
6. `python evals/run_trigger_evals.py` — exit 0; absent-baseline and present-baseline paths.
7. `python -m unittest` for the touched/adjacent suites, `python scripts/check_contract_graph.py`,
   `generate_index.py --check`, `check_frontmatter.py`, `vendor_shared.py --check`,
   `check_changelog.py --base origin/main`, `version.py check`, `version.py check-bump`,
   `version.py check-merge`, plus the CI-equivalent suite set, each with its exit code.
8. README claims verified by `grep`/`--list` in the tree and captured in the evidence record.

The real judged baseline is the operator's run against their configured endpoint; the authoring
agent proves the wiring and the record logic against the local stub. `evals/baseline.json` is not
committed by this increment; `run_trigger_evals.py` reports `no baseline recorded yet` until the
operator records one.

Sequencing: the full test suite is never run beside a measurement/benchmark job. The stub is a
unit-test server, not a benchmark; the suites run one after another.

## 4. Design trade-offs / ambiguities

- **"Four layers" vs the seven folders listed in the contract.** The sentence names four layers and
  then lists seven surfaces. Read as two axes: the four `kind` layers (entry/controller/stage/
  mechanism) and the surfaces that actually exist. The README states both explicitly, with counts,
  so neither reading is lost.
- **§6 "no change to any skill's frontmatter" vs the repo's unified version gate.** `VERSION` must
  be bumped for a PR, and `python scripts/version.py check` requires all 40 `metadata.version`
  values to mirror it; `version.py bump` also rewrites the generated indexes. Not bumping fails CI.
  Resolution: bump the patch and let `version.py bump` mirror it; no `kind`, `consumes`,
  `produces`, summary, area or target changes. The archived-contract text stays unchanged, and the
  evidence record names the mechanical version mirror. Recommendation if this is unacceptable:
  amend the repo's version rule in a separate increment, not here.
- **Absent baseline in CI.** The contract says the gate proves the record internally consistent; it
  also says the record is committed only by `--record` and the operator performs the real run. A
  hard requirement would make the PR red before the operator's run. Resolution: absence is legal
  and reported; a present record is always checked. This keeps CI offline and does not invent a
  baseline from the stub.
- **`--record` refuses `--limit`.** The contract's `case_count == len(cases)` check is otherwise
  unsatisfiable for a partial run. Refusing at record time is the smallest way to make the invariant
  true by construction.
- **Credential key.** `api_key` is a generic resolver key (env `EVALS_API_KEY`), not a vendor key
  name; the script contains no gateway or model identifier. Hiding the key entirely would make the
  script unusable against an authenticated endpoint; a `--api-key` flag would leak through process
  listings.
- **Effort transport.** Chat-completions has no `reasoning` object; `reasoning_effort` is the
  compatible field. Endpoints that ignore unknown fields keep working; an endpoint that rejects it
  is a documented compatibility limit, not silently swallowed.
- **Baseline strictness beyond the three named checks.** `total`/`len(per_case)` are also pinned.
  They are part of the record schema, and without them a record can claim 25 cases while carrying
  three rows.
- **Chinese README.** The contract names `README.md`, but the repo's bilingual policy requires the
  mirror in the same change. The Chinese section carries the same checked claims; no other Chinese
  section is rewritten.

## 5. Out of scope

- Judging `evals/skill-method-cases.json`; it keeps its own validator.
- Changing any case's `must_pick` / `distractors`, or adding/removing cases.
- Multi-judge consensus, temperature sweeps, retries, cost accounting.
- Running the real judge in CI or committing an operator's baseline from the authoring machine.
- Rewriting README sections other than the new architecture section and statements the judge
  configuration falsifies.
- Changing skill frontmatter beyond the mechanical `metadata.version` mirror required by
  `VERSION`, and changing contract-graph rules or the registry.
- Adding dependencies: the judge and its tests are stdlib only; PyYAML remains confined to the
  existing repo tooling.

## 6. Close

Bump `VERSION` 0.1.31 → 0.1.32 with `python scripts/version.py bump`, add the `CHANGELOG.md`
entry, write `docs/evidence/2026-11-11-eval-judge-and-architecture.md` with real output and exit
codes, move the contract unchanged to `docs/goals/archive/`, update `docs/goals/README.md`, add the
new CI test step, and leave the tree uncommitted for verification.
