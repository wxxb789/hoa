# Evidence — a mechanism, or no claim

Contract: [`docs/goals/archive/2026-11-11-mechanism-or-no-claim.md`](../goals/archive/2026-11-11-mechanism-or-no-claim.md)
Date: 2026-11-11 · Version: 0.1.31

All commands ran from the repository root on this host. Exit codes are the process exit codes. The
self-test and the unit suites were run sequentially, never beside a measurement job.

## 1. The shared resolver

`python -m unittest scripts.test_skill_config -v` → `Ran 14 tests ... OK`, exit 0. The tests cover:

- flag beats env beats config beats default, one assertion per step;
- empty flag/env values fall through, matching `gdd.py`'s previous `if value:` behaviour;
- `$XDG_CONFIG_HOME` beats `$HOME/.config`, and `root=` overrides both;
- a missing file and a missing key both fall back to the default;
- a directory at the config path, invalid UTF-8, and every unsupported construct raise
  `ConfigError` naming the path (and the line where a line exists);
- flat scalars, quoted strings, comments, blank lines, CRLF and BOM;
- the CLI provenance line and the `goal-driven-delivery`/`GDD_STATE_FILE` path, env and flag cases.

Real CLI output for a temp `XDG_CONFIG_HOME`:

```text
$ XDG_CONFIG_HOME=$PWD/.tmp-artifacts/mechanism-or-no-claim/provenance \
    python scripts/skill_config.py --skill goal-driven-delivery --key GDD_STATE_FILE
GDD_STATE_FILE=/tmp/config-ledger.tsv (from config /home/azureuser/repos/hoa/.tmp-artifacts/mechanism-or-no-claim/provenance/goal-driven-delivery/config.yaml)
exit=0

$ XDG_CONFIG_HOME=$PWD/.tmp-artifacts/mechanism-or-no-claim/provenance \
    GDD_STATE_FILE=/tmp/env-ledger.tsv \
    python scripts/skill_config.py --skill goal-driven-delivery --key GDD_STATE_FILE
GDD_STATE_FILE=/tmp/env-ledger.tsv (from env GDD_STATE_FILE)
exit=0

$ XDG_CONFIG_HOME=$PWD/.tmp-artifacts/mechanism-or-no-claim/empty \
    python scripts/skill_config.py --skill goal-driven-delivery --key GDD_STATE_FILE \
    --default /tmp/default-ledger.tsv
GDD_STATE_FILE=/tmp/default-ledger.tsv (from default)
exit=0

$ python scripts/skill_config.py --skill goal-driven-delivery --key GDD_STATE_FILE \
    --root $PWD/.tmp-artifacts/mechanism-or-no-claim/bad
skill_config: /home/azureuser/repos/hoa/.tmp-artifacts/mechanism-or-no-claim/bad/goal-driven-delivery/config.yaml:1: missing value for 'nested'; nested mappings and empty values are not supported
exit=1
```

The resolver returns an environment value verbatim; `gdd.py` keeps its pre-existing
`os.path.expanduser` when it builds child-process paths. No new default and no normalisation were
added.

## 2. goal-driven-delivery resolves all six keys

`bash skills/goal-driven-delivery/scripts/tests/run-gdd-selftest.sh` → `selftest: 57/57 ok`, exit 0.
Checks 1–52 are the pre-existing suite and pass unchanged, including the environment-only defaults
(42–44), archive contract resolution (27), and the launcher/env pass-through checks (23–24). Five
checks were added:

```text
ok 53 - config-file GDD_STATE_FILE is honoured (rc=0)
ok 54 - gdd status reads the config-file ledger
ok 55 - environment beats the config file
ok 56 - explicit --launcher beats the config file (rc=0)
ok 57 - malformed config exits 2 naming path and line (rc=2)
```

The six keys are resolved through the vendored copy of `scripts/skill_config.py`:
`GDD_STATE_FILE`, `GDD_TASK_ROOT`, `GDD_RUN_ROOT`, `GDD_LAUNCHER`, `GDD_TEMPLATES`, and
`GDD_GOAL_GLOB`. The last was documented but unused before this increment; its default keeps the
active-tree-then-archive search the self-test pins, and a custom glob is used verbatim. `gdd status`
now passes the resolved state/task/run paths to `delivery-state.py`, so the config file takes effect
on the delegated read path as well.

## 3. Contract graph R9

Before the rule existed, the analyzer at HEAD `25b7706` printed:

```text
dangling: acceptance-verdict produced by delegated-work-acceptance
dangling: scope-seal produced by delegated-work-acceptance
dangling: chain-plan produced by goal-driven-delivery
dangling: implementation produced by subagent-driven-development
total 40 skills, 10 artifacts
```

After the rule and the registry's `terminal:` block:

```text
$ python scripts/check_contract_graph.py
contract graph: 40 skills, 10 artifacts, ok
exit=0
```

`python -m unittest scripts.test_check_contract_graph -v` → `Ran 18 tests ... OK`, exit 0. The five
new tests pin R9 in both directions: an unconsumed production fires with the artifact and producing
skill, a consumed artifact passes, a terminal entry needs a non-empty one-line reason, a non-mapping
`terminal:` is rejected, and `external:` artifacts are exempt both as productions and consumptions.

The registry now carries:

```yaml
terminal:
  acceptance-verdict: the operator's ruling is the destination; no phase reads this artifact
  chain-plan: the controller's routing plan is consumed by the operator, not a skill
  implementation: the merged code is the destination; no skill consumes the delivery
  scope-seal: worktree-scope.py verify checks the tree; no skill consumes the artifact
```

`acceptance-verdict` and `scope-seal` are **terminal**, not consumed by `goal-driven-delivery`. Phase
5 of that skill runs `worktree-scope.py diff/seal/verify`, phase 6 runs `pr-merge-check.py`; neither
reads the artifact produced by `delegated-work-acceptance`, and GDD does not declare `consumes`.
Declaring a consumer would have invented a handoff the phases do not contain.

## 4. One convention, several pointers

`skill-porting-and-publishing` § Configuration names `scripts/skill_config.py` once and describes
the API, the CLI, the env-name rule and the vendoring rule. Nine skills replace their restated chain
with a pointer to that section:

```text
$ grep -rl "Resolution order and the config-file path are defined once" skills --include='*.md' | wc -l
9
```

Those files are `ai-coding-agent-delegation`, `contract-bound-deliverables`,
`evidence-boundary-discipline`, `git-auto-sync-pipelines`, `goal-driven-delivery`,
`spec-convergence`, `subagent-driven-development`, `systematic-debugging` and `writing-plans`.
`AGENTS.md` now states the two-sided graph rule. No skill's table or documented default changed.

## 5. Gates

| Command | Output | Exit |
|---|---|---|
| `python -m unittest scripts.test_skill_config -v` | `Ran 14 tests ... OK` | 0 |
| `python -m unittest scripts.test_check_contract_graph -v` | `Ran 18 tests ... OK` | 0 |
| `python -m unittest scripts.test_skill_config scripts.test_check_contract_graph scripts.test_generate_index` | `Ran 61 tests ... OK` | 0 |
| `bash skills/goal-driven-delivery/scripts/tests/run-gdd-selftest.sh` | `selftest: 57/57 ok` | 0 |
| `python scripts/check_contract_graph.py` | `contract graph: 40 skills, 10 artifacts, ok` | 0 |
| `python scripts/generate_index.py --check` | no output | 0 |
| `python scripts/check_changelog.py --base origin/main` | `check_changelog: VERSION and CHANGELOG.md both changed` | 0 |
| `python scripts/version.py check-merge` | `0.1.31` | 0 |
| `python scripts/vendor_shared.py --check` | no output | 0 |
| `python scripts/check_frontmatter.py` | `check_frontmatter: 40 skills OK` | 0 |
| `python scripts/version.py check` | no output | 0 |
| `python -m unittest scripts.test_install_host_skills scripts.test_check_changelog scripts.test_version` | `Ran 69 tests ... OK` | 0 |
| `python -m unittest scripts.test_check_frontmatter` | `Ran 6 tests ... OK` | 0 |
| `python -m unittest scripts.test_release` | `Ran 13 tests ... OK` | 0 |

## 6. Residual risks and limits

- `delivery-state.py` invoked directly still reads only its environment variables. The config file
  takes effect through `gdd.py`, which passes resolved `--state-file`/`--task-root`/`--run-root`
  values; rewriting the direct entry point was out of scope.
- The config parser is deliberately a subset. Valid YAML that uses nesting, anchors, flow
  collections, block scalars, tags or document markers is rejected with `path:line`, not read.
- A key that is already an environment-variable name is used verbatim. This is what keeps
  `GDD_STATE_FILE` byte-identical; ordinary keys use `<SKILL_BIG_SNAKE>_<KEY_BIG_SNAKE>`.
- `GDD_GOAL_GLOB` is new behaviour at the top level: it was documented but unread before. A custom
  glob is used verbatim and does not get the bundled default's archive fallback.
- R9's terminal reasons are checked for presence and one-line shape, not for semantic truth. The
  four current reasons are reviewable prose in the registry, not executable assertions.
- The nine skills' scripts still resolve values as they did; this increment changes only their
  documentation pointer. Their env names and defaults are unchanged.
- The live host's config and installed skills were not touched.

## 7. Operator re-run on the final tree (2026-11-11)

Run by the operator, not the authoring agent, on the working tree of `feat/mechanism-or-no-claim`
(59 files). Probe fixtures live outside the repo: `~/.hermes/cache/scratch/hoa-goal-b-verify/`.

**R9 negative probe** — a throwaway skill declaring `produces: orphan-thing`, no consumer, no
`terminal:` entry:

```
skills/x/SKILL.md: R9: artifact 'orphan-thing' produced by 'x' is neither consumed by a skill
nor registered under terminal:
```

**Resolver provenance** — `scripts/skill_config.py --skill gdd --key GDD_STATE_FILE`:

| Setup | Output |
|---|---|
| `XDG_CONFIG_HOME=<tmp>/gddcfg` holding `gdd/config.yaml: GDD_STATE_FILE: /tmp/from-config.tsv` | `GDD_STATE_FILE=/tmp/from-config.tsv (from config <tmp>/gddcfg/gdd/config.yaml)` |
| `XDG_CONFIG_HOME=<empty dir>` | `GDD_STATE_FILE=(unset) (from default)` |
| config present + explicit `flag=` argument | `/from/flag.tsv` |

**Gates re-run on the final tree**

| Command | Result | Exit |
|---|---|---|
| `python -m unittest scripts.test_skill_config scripts.test_check_contract_graph scripts.test_generate_index` | `Ran 61 tests ... OK` | 0 |
| `python -m unittest scripts.test_install_host_skills scripts.test_check_changelog scripts.test_version scripts.test_check_frontmatter scripts.test_release` | `Ran 88 tests ... OK` | 0 |
| `bash skills/goal-driven-delivery/scripts/tests/run-gdd-selftest.sh` | `selftest: 57/57 ok` | 0 |
| `python scripts/check_contract_graph.py` | `contract graph: 40 skills, 10 artifacts, ok` | 0 |
| `python scripts/generate_index.py --check` | no output | 0 |
| `python scripts/check_frontmatter.py` | `check_frontmatter: 40 skills OK` | 0 |
| `python scripts/check_changelog.py --base origin/main` | `VERSION and CHANGELOG.md both changed` | 0 |
| `python scripts/vendor_shared.py --check` | no output | 0 |
| `python scripts/version.py check` | no output | 0 |
