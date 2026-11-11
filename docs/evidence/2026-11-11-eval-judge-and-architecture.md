# Evidence — the eval judge runs on a configuration

Contract: [`docs/goals/archive/2026-11-11-eval-judge-and-architecture.md`](../goals/archive/2026-11-11-eval-judge-and-architecture.md)
Plan: [`docs/plans/2026-11-11-eval-judge-and-architecture-plan.md`](../plans/2026-11-11-eval-judge-and-architecture-plan.md)
Date: 2026-11-11 · Version: 0.1.32

All commands ran from the repository root on this host, sequentially; no measurement or benchmark
ran beside the test suites. Exit codes are the process exit codes. The contract was archived
unchanged: `diff -u` between `HEAD:docs/goals/2026-11-11-eval-judge-and-architecture.md` and
`docs/goals/archive/2026-11-11-eval-judge-and-architecture.md` exited 0.

## 1. The judge resolves its configuration

`evals/judge_trigger_evals.py` contains no model id, gateway URL or vendor credential name:

```text
$ grep -nE 'gpt-|ghc' evals/judge_trigger_evals.py
grep_exit=1
```

No output, exit 1 — grep's "no match" status. The only client is
`urllib.request` posting to `<base_url>/chat/completions`.

`python -m unittest evals.test_judge_trigger_evals -v` → `Ran 25 tests ... OK`, exit 0. The
precedence test starts three independent stubs and asserts which one received the request and
which model/effort arrived:

- flag beats env beats config: the flag server gets the only request, with
  `model=flag-model`, `reasoning_effort=flag-effort`; the env and config servers get none;
- env beats config: the env server gets it with `model=env-model`;
- config is used when neither flag nor env supplies a value: `model=config-model`,
  `reasoning_effort=high`;
- with `effort` absent, the request carries the documented default `low`;
- `EVALS_API_KEY` beats `api_key` in the config file, and the winning value is sent as
  `Authorization: Bearer ...`.

Real CLI, clean `HOME`/`XDG_CONFIG_HOME` and no `EVALS_*` variables:

```text
$ evals/judge_trigger_evals.py
exit=2
judge_trigger_evals: judge endpoint and model are not configured.
  base_url  --base-url / EVALS_BASE_URL  (missing)
  model     --model / EVALS_MODEL  (missing)
  effort    --effort / EVALS_EFFORT  default: low
config file: /home/azureuser/repos/hoa/.tmp-artifacts/eval-judge-and-architecture/smoke/xdg/evals/config.yaml
Set them in that file, in the environment, or with the flags.
```

Malformed config (`base_url:` with no value), same environment:

```text
$ evals/judge_trigger_evals.py
exit=2
judge_trigger_evals: /home/azureuser/repos/hoa/.tmp-artifacts/eval-judge-and-architecture/smoke/xdg/evals/config.yaml:1: missing value for 'base_url'; nested mappings and empty values are not supported
```

Three cases against a stdlib-only chat-completions stub on `127.0.0.1` (no external network, no
credential):

```text
$ evals/judge_trigger_evals.py --limit 3 --json \
    --base-url http://127.0.0.1:43825/v1 --model stub-model
exit=0
{
  "passed": 3,
  "total": 3,
  "results": [
    {"id": "route-to-teams-send", "pick": "teams-cdp",
     "must_pick": ["teams-cdp"], "passed": true},
    {"id": "route-to-copilot-chat-code", "pick": "m365-copilot-cdp",
     "must_pick": ["m365-copilot-cdp"], "passed": true},
    {"id": "route-explicit-teams-cdp", "pick": "teams-cdp",
     "must_pick": ["teams-cdp"], "passed": true}
  ]
}
```

Failure control is pinned by tests, not only by inspection:

- `test_network_failure_is_per_case`: one case's endpoint returns HTTP 500; that case's pick is
  `error: HTTP 500: ...`, the other two pass, exit 1.
- `test_non_catalog_reply_fails_one_case_with_verbatim_pick`: one reply is `no-such-artifact`; that
  case fails with the pick preserved verbatim, the batch completes, exit 1.
- `test_unconfigured_exits_two_with_keys_and_config_path` and
  `test_malformed_config_exits_two_naming_path_and_line` assert the two exit-2 paths above.
- `test_record_with_limit_is_a_usage_error` and `test_force_without_record_is_a_usage_error`
  assert exit 2 before any request.

The authoring agent did **not** run a real judge model. The local `127.0.0.1:4141` gateway is
Responses-only (`HTTP 400: model "..." is not accessible via the /chat/completions endpoint`), so
the operator's configured chat-completions endpoint is the first real judge run (§6).

## 2. Baseline record and the offline gate

A full stub run with `--record` (25 cases, no `--limit`) wrote the record and exited 0:

```text
$ evals/judge_trigger_evals.py --record \
    --base-url http://127.0.0.1:43825/v1 --model stub-model --effort low
exit=0
...
25/25 passed
judge_trigger_evals: wrote /home/azureuser/repos/hoa/evals/baseline.json
```

The record it wrote (per_case truncated for this page; generated from the stub and deleted before
delivery):

```json
{
  "case_count": 25,
  "model": "stub-model",
  "effort": "low",
  "passed": 25,
  "total": 25,
  "judge_endpoint_host": "127.0.0.1:43825",
  "generated_at": "2026-11-11T01:52:03Z",
  "per_case": [
    {"id": "route-to-teams-send", "pick": "teams-cdp", "passed": true},
    {"id": "route-to-copilot-chat-code", "pick": "m365-copilot-cdp", "passed": true}
  ]
}
```

The CI gate with that record present:

```text
$ python evals/run_trigger_evals.py
exit=0
PASS: 25 trigger cases valid; every must_pick/distractor resolves to a cataloged artifact (49 artifacts); baseline consistent (25/25 passed, model stub-model, 2026-11-11T01:52:03Z)
```

The same gate with `passed` changed to 0 (the only edit):

```text
$ python evals/run_trigger_evals.py
exit=1
run_trigger_evals: baseline.json: passed 0 != sum(per_case.passed) 25
```

And with no baseline recorded:

```text
$ python evals/run_trigger_evals.py
exit=0
PASS: 25 trigger cases valid; every must_pick/distractor resolves to a cataloged artifact (49 artifacts); no baseline recorded yet (judge_trigger_evals.py --record)
```

`BaselineGateTests` in `evals/test_judge_trigger_evals.py` additionally pins: unknown id, duplicate
id, `passed` != sum, `case_count` != the current suite, `total` != `case_count`, row count !=
`case_count`, non-boolean `passed`, missing field, malformed JSON, non-object JSON, and `main()`
exiting 0/1 for a consistent/broken record with a patched path. `RecordTests` pins the exact key
set, `case_count`/`total`/`passed`/`per_case` shape, the `model`/`effort`/host values, the
`generated_at` shape, refusal without `--force` (bytes unchanged, no new request), and replacement
with `--force`.

The tree contains no `evals/baseline.json`: `test -e evals/baseline.json` is false after the smoke
sequence. The stub record was deliberately removed; a measured baseline must come from the
operator's configured endpoint, not from a stub.

## 3. README claims verified against the tree

The new section "How this repository is shaped" was checked with a script that reads the code, not
the prose:

```text
PASS 40 skills
PASS 49 artifacts
PASS 25 cases
PASS 37 entry
PASS controller/stage/mechanism
PASS R1..R9
PASS reasoning_effort documented
PASS config names documented
PASS every CI command in README (missing=[])
PASS zh has 49/25 claims
10/10 checks pass
```

Details:

- `scripts/check_contract_graph.py --list` yields 40 skills: 37 `entry`, 1 `controller`
  (`goal-driven-delivery`, produces `chain-plan`), 1 `stage` (`subagent-driven-development`,
  `plan` → `implementation`), 1 `mechanism` (`delegated-work-acceptance`). The four counts and the
  three examples in the table are those values.
- `scripts/generate_index.py collect()` yields 49 catalog entries: 40 skills, 4 prompts, 1 agent,
  1 MCP, 1 orchestration, 1 rule, 1 workflow. Every surface row matches that output.
- `evals/trigger-cases.json` has 25 cases.
- R1–R9 are the literal rule labels emitted in `scripts/check_contract_graph.py`; the README line
  for each was written from the condition beside its `violations.append`.
- Every `run:` command in both CI jobs appears verbatim in the README table, checked by parsing
  `.github/workflows/ci.yml` with PyYAML (`missing=[]`). The three-directory Bun loop is summarized
  as the loop it is.
- `README.zh-CN.md` carries the same section and the same counts; the repo's bilingual policy
  requires the mirror in the same change.

No pre-existing README statement was falsified: the old README described the catalog and deploy
split but did not name the judge model, endpoint, or grading path, so this change adds the section
and rewrites nothing else.

## 4. Gates

Run sequentially in this order; exit codes are real.

| Command | Output | Exit |
|---|---|---|
| `python -m unittest evals.test_judge_trigger_evals -v` | `Ran 25 tests ... OK` | 0 |
| `python evals/run_trigger_evals.py` | `PASS: 25 trigger cases ... 49 artifacts; no baseline recorded yet` | 0 |
| `python -m unittest scripts.test_skill_config` | `Ran 14 tests ... OK` | 0 |
| `python scripts/test_check_contract_graph.py` | `Ran 18 tests ... OK` | 0 |
| `python scripts/check_contract_graph.py` | `contract graph: 40 skills, 10 artifacts, ok` | 0 |
| `python scripts/generate_index.py --check` | no output | 0 |
| `python scripts/test_generate_index.py` | `Ran 29 tests ... OK` | 0 |
| `python scripts/check_frontmatter.py` | `check_frontmatter: 40 skills OK` | 0 |
| `python -m unittest scripts.test_check_frontmatter` | `Ran 6 tests ... OK` | 0 |
| `python scripts/version.py check` | no output | 0 |
| `python scripts/version.py check-bump` | `0.1.32` | 0 |
| `python scripts/check_changelog.py --base origin/main` | `check_changelog: VERSION and CHANGELOG.md both changed` | 0 |
| `python scripts/version.py check-merge` | `0.1.32` | 0 |
| `python scripts/test_version.py` | `Ran 42 tests ... OK` | 0 |
| `python scripts/test_release.py` | `Ran 13 tests ... OK` | 0 |
| `python scripts/vendor_shared.py --check` | no output | 0 |
| `python -m unittest scripts.test_install_host_skills` | `Ran 21 tests ... OK` | 0 |
| `python -m unittest scripts.test_check_changelog` | `Ran 6 tests ... OK` | 0 |
| `python skills/ghc-search/scripts/test_ghc_search.py` | `Ran 14 tests ... OK` | 0 |
| `python skills/hoa-introspect/evals/run.py` | `PASS: zero blind spots; ...` | 0 |
| `python skills/hoa-introspect-distill/evals/run_evals.py` | `{"pii_gate": "PASS", ...}` | 0 |
| `python skills/define-goal/evals/validate_fixtures.py` | `PASS: define-goal fixtures are structurally valid ...` | 0 |
| `python evals/validate_skill_method_cases.py` | `PASS: skill-method cases have valid rubrics ...` | 0 |
| `python -m unittest evals.test_validate_skill_method_cases` | `Ran 3 tests ... OK` | 0 |
| `bun install --frozen-lockfile && bun run check && bun test` in `scripts/shared` | `15 tests`, `0 fail` | 0 |
| same in `skills/teams-cdp/scripts` | `29 tests`, `0 fail` | 0 |
| same in `skills/m365-copilot-cdp/scripts` | `41 tests`, `0 fail` | 0 |

`VERSION` is 0.1.32; `python scripts/version.py bump` changed exactly the 40
`metadata.version` scalars in `skills/*/SKILL.md` (40 additions, 40 deletions, checked with
`git diff --unified=0 skills`). That mechanical mirror is required by `version.py check` and the
PR patch-bump gate; no `kind`, `consumes`, `produces`, summary, area or target changed. The contract
says "no change to any skill's frontmatter"; the plan records this as the ambiguity it is and
recommends the version rule be changed separately if the literal reading is preferred.

## 5. Residual risks and limits

- **No real judged baseline yet.** `evals/baseline.json` is absent by design until the operator
  runs `--record` against a configured endpoint. The stub proves the record logic and the gate
  arithmetic, not routing quality. The increment is not mergeable on the stub alone, per the
  contract's evidence plan.
- **Endpoint compatibility.** The request uses `max_tokens` and `reasoning_effort`, the classic
  chat-completions fields. An endpoint that rejects either needs a compatible gateway; the script
  does not retry or downgrade the body, so the failure surfaces per case rather than silently
  changing the measurement.
- **Single-model judge.** The pass rate is one model's reading of one prompt on one curated case
  set. It is not user routing quality, inter-rater agreement, or a guarantee for another model.
  Changing model, effort, prompt or cases breaks comparability; the baseline pins them, and the
  gate rejects a stale case count.
- **Secret handling.** `api_key` lives in the resolver's config file or `EVALS_API_KEY`; the config
  file is operator-managed and should be mode 0600. No key is written to the baseline or printed.
- **Host identity only.** `judge_endpoint_host` is `host[:port]`; it intentionally omits the path,
  query and credential, so two endpoints on one host are indistinguishable in the record.
- **Absent baseline is allowed.** A fresh checkout before the first `--record` must not fail CI;
  the gate says `no baseline recorded yet` and still validates every structural/catalog invariant.
- **Mechanical version mirror.** 40 skill frontmatter files changed a version scalar only; the
  archived contract text is unchanged and the evidence above separates that from a contract change.
- **The Chinese README gained a section.** Required by the repo's bilingual policy, not by the
  contract's literal filename list; it carries the same verified claims.

## 6. Operator verification (executed 2026-11-11)

The judge was pointed at a plain OpenAI-compatible chat endpoint through the `EVALS_*` variables only
(`EVALS_MODEL=deepseek-v4.1-flash`, `EVALS_EFFORT=low`); nothing about the endpoint is compiled into the
script, and no credential appears in this record.

| Run | Command | Result |
|---|---|---|
| 1 | `judge_trigger_evals.py --limit 3 --json` | 3/3 pass (`route-to-teams-send`, `route-to-copilot-chat-code`, `route-explicit-teams-cdp`) |
| 2 | `judge_trigger_evals.py --json` (full set) | exit 0 — every case passed |
| 3 | `judge_trigger_evals.py --record --json` | 24/25; wrote `evals/baseline.json` |

**The one failing case in run 3, and why it is not hidden.** `route-boundaryless-goal-to-spec-first`
demands `spec-convergence`; run 3's judge answered `define-goal`. Run 2, same endpoint and model,
answered `spec-convergence` for that same case (exit 0 proves the whole set passed). So the case is
ambiguous between two sibling skills, and the recorded 24/25 is a single sample rather than a stable
rate. The contract puts changing a case's `must_pick` out of scope, so this stays in the record as a
finding for a separate case-disambiguation increment — the baseline was not re-run until it went green.

**Gates re-run by the operator on this tree**

| Command | Result |
|---|---|
| `python -m unittest evals.test_judge_trigger_evals` | `Ran 25 tests ... OK` |
| `python evals/run_trigger_evals.py` | `PASS: 25 trigger cases valid; every must_pick/distractor resolves to a cataloged artifact (49 artifacts); baseline consistent (24/25 passed, model deepseek-v4.1-flash, 2026-11-11T01:59:02Z)` |
| `python -m unittest scripts.test_skill_config` | `Ran 14 tests ... OK` |
| `python scripts/test_check_contract_graph.py` | `OK` |
| `python scripts/check_contract_graph.py` | `contract graph: 40 skills, 10 artifacts, ok` |
| `python scripts/generate_index.py --check` / `test_generate_index.py` | clean / `OK` |
| `python scripts/check_frontmatter.py` | `check_frontmatter: 40 skills OK` |
| `python scripts/version.py check` / `check-bump` | clean / `0.1.32` |
| `python scripts/check_changelog.py --base origin/main` | `VERSION and CHANGELOG.md both changed` |
| `python scripts/vendor_shared.py --check` | clean |
| `python -m unittest scripts.test_install_host_skills scripts.test_release scripts.test_version scripts.test_check_frontmatter scripts.test_check_changelog` | `Ran 88 tests ... OK` |
