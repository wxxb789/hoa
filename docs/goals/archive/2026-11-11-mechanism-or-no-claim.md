# Goal — a mechanism, or no claim

Increment id: `mechanism-or-no-claim`
Repo: `wxxb789/hoa` · one run · one PR · mergeable alone

## Why this exists (the failure it answers)

Two promises in this library have no mechanism behind them.

1. **The config chain.** Nine skills document the same resolution order — CLI flag → environment
   variable → `$XDG_CONFIG_HOME/<skill>/config.yaml` (falling back to `~/.config/<skill>/config.yaml`)
   → documented default. `grep -rl XDG_CONFIG_HOME --include=*.py .` finds one file, and it is not a
   loader. `gdd.py` reads `GDD_STATE_FILE` and friends from the environment only. So `SPEC_DIR`,
   `SPEC_ROUND_CAP`, `PLAN_DIR`, `GDD_STATE_FILE` are documented keys that no code resolves: a user
   who writes the config file gets the default and never learns why.
2. **The contract graph is one-sided.** R3 rejects a `consumes` with no producer. Nothing rejects a
   `produces` nobody consumes, so `chain-plan`, `implementation`, `acceptance-verdict` and
   `scope-seal` sit in the graph as artifacts with no stated destination. The graph can tell you who
   makes a thing, never who verifies it.

## 1. Observable pass condition

- `scripts/skill_config.py` exists, stdlib only, and exposes `resolve(skill, key, *, flag=None,
  env=None, default=None, root=None)`:
  - precedence is flag → env var → config file → default, and each step is covered by a test;
  - the env var name is the documented one (`<SKILL_BIG_SNAKE>_<KEY_BIG_SNAKE>`);
  - the config file is `$XDG_CONFIG_HOME/<skill>/config.yaml`, falling back to
    `~/.config/<skill>/config.yaml`; `--root`/`root=` overrides the config base for tests and
    non-default homes;
  - a missing key is not an error (the default wins); an unreadable or malformed file is an error
    naming the path and the line, never a silent default;
  - a flat `key: value` YAML subset is supported (scalars, quoted strings, comments, blank lines);
    nested mappings, anchors and multi-document files are rejected with a clear message rather than
    half-parsed.
- `skills/goal-driven-delivery/scripts/gdd.py` resolves all six variables in its configuration table
  through that resolver: environment behaviour is byte-identical to today (every existing test
  passes unchanged), and a config file now actually takes effect. One test proves the file path is
  honoured for `GDD_STATE_FILE` and that an explicit CLI value still wins.
- `python scripts/skill_config.py --skill <name> --key <KEY>` prints the resolved value and whether
  it came from flag/env/config/default, so a user can see why a key has the value it has.
- Contract graph **R9**: every artifact a skill produces is either consumed by some skill or listed
  under `terminal:` in `scripts/contract_graph_registry.yaml` with a one-line reason. R9 fires with
  the artifact name and the producing skill.
- The four currently dangling artifacts are resolved honestly:
  - `implementation` → `terminal` (the merged code is the destination);
  - `chain-plan` → `terminal` (the controller's routing plan is consumed by the operator, not a skill);
  - `acceptance-verdict`, `scope-seal` → declared consumed by `goal-driven-delivery`, whose phase 5
    verifies the seal and phase 6 requires the verdict. If that is untrue of the phases as written,
    declare them `terminal` instead and say so — do not invent a consumer.
- All nine skills that document the chain name the shared resolver once, in
  `skill-porting-and-publishing` (the skill that owns the convention), and the others point at it
  instead of restating a rule they do not implement.

## 2. Judging artifact

`scripts/skill_config.py` + `scripts/test_skill_config.py`, the `gdd.py` diff, the R9 rule in
`check_contract_graph.py` + its tests, and the registry's `terminal:` block.

## 3. Failure control

- Environment behaviour must not regress: if `GDD_STATE_FILE` is set, the resolved path is exactly
  that string; no normalisation, no expansion, no new default.
- No new dependency; no PyYAML. An unsupported YAML construct is an error, not a best guess.
- Do not change any skill's documented default — only who resolves it.
- R9 must not fire on `external:` artifacts (`request`, `work-report`, `git-commit`, `ci-result`).

## 4. Out of scope

- Editing `~/.hermes` runtime config, any bot's `allowed_skills`, or any installed skill.
- The judge for trigger cases, README architecture documentation, and the launcher's unbounded
  `events.ndjson` (each its own increment).
- Rewriting skills other than the one-line pointer in `skill-porting-and-publishing` and the config
  table in `goal-driven-delivery`.

## 5. Evidence plan

```bash
python -m unittest scripts.test_skill_config -v          # precedence, XDG vs ~/.config, errors
python -m unittest scripts.test_check_contract_graph -v  # R9 both ways + external exemption
bash skills/goal-driven-delivery/scripts/tests/run-gdd-selftest.sh   # env unchanged + config file honoured
python scripts/check_contract_graph.py
python scripts/generate_index.py --check
python scripts/check_changelog.py --base origin/main
python scripts/version.py check-merge
python scripts/skill_config.py --skill goal-driven-delivery --key GDD_STATE_FILE   # provenance line
```

The PR body carries the resolver's provenance output for a temp `XDG_CONFIG_HOME`, and the graph
output before (4 dangling) and after (0).

## 6. Mergeable alone

Nothing here depends on the next increment. After the merge a documented key either resolves or the
skill stops promising it, and the graph can no longer hide an artifact with no destination.
