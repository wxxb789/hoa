# Plan — a mechanism, or no claim

Contract: [`docs/goals/archive/2026-11-11-mechanism-or-no-claim.md`](../goals/archive/2026-11-11-mechanism-or-no-claim.md)
Increment: `mechanism-or-no-claim` · branch `feat/mechanism-or-no-claim`

The repo has no designated plan directory and no profile that forbids one, so the plan lives in
`docs/plans/`. The contract is archived on close, unchanged.

## 1. Public / API shape

### 1.1 `scripts/skill_config.py` (new, stdlib only)

```python
resolve(skill, key, *, flag=None, env=None, default=None, root=None) -> str | None
explain(skill, key, *, flag=None, env=None, default=None, root=None) -> Resolved
```

- `skill` is the skill directory name, used only for the config path `<base>/<skill>/config.yaml`
  and for the default environment-variable prefix. It is rejected when it contains a path separator
  or is `.`/`..`, so a malformed call cannot escape the config base.
- `key` is the operator-config key. The environment name is the documented one:
  - a key already shaped like an environment variable (`[A-Z][A-Z0-9_]*`) is used verbatim, which is
    what keeps `GDD_STATE_FILE` byte-identical for goal-driven-delivery;
  - any other key becomes `<SKILL_BIG_SNAKE>_<KEY_BIG_SNAKE>` (non-alphanumerics become `_`).
- Precedence is flag → env var → config file → default. `None` and `""` mean "not supplied" at the
  flag/env steps; that matches `gdd.py`'s existing `if value:` handling and preserves the current
  environment behaviour. The config file is not opened when a flag or env var already won.
- `env` is the environment mapping (default `os.environ`). It supplies the key's variable and the
  `XDG_CONFIG_HOME`/`HOME` used for the config base, so tests never read the operator's real config.
- `root` overrides the config base entirely: `<root>/<skill>/config.yaml`. Without `root`, the base
  is `$XDG_CONFIG_HOME`, falling back to `$HOME/.config`.
- A missing file or a missing key is not an error; the default wins. An unreadable file, a malformed
  line, an unsupported construct or a duplicate key raises `ConfigError(ValueError)` whose message
  starts with `<path>:<line>:` (path only for unreadable files). It never degrades to a default.
- `Resolved` carries `value`, `source` (`flag`/`env`/`config`/`default`) and `detail` (variable name
  or config path) so the CLI and tests can report provenance without re-resolving.

CLI:

```bash
python scripts/skill_config.py --skill <name> --key <KEY> [--flag VALUE] [--default VALUE] [--root DIR]
```

prints one line: `<KEY>=<value> (from flag|env <VAR>|config <PATH>|default)`. An unresolved key
prints `(unset)`; a config error goes to stderr and exits 1.

#### Supported config subset

One flat document, one `key: value` per line. Blank lines and comments (`#`, including indented
comment-only lines) are ignored. Values are strings; single-quoted (`''` escape) and double-quoted
(`\"`, `\\`, `\n`, `\t`, `\r`) scalars and plain scalars are supported. An unquoted trailing
` # comment` is stripped; a `#` inside a quoted scalar is data.

Rejected with `<path>:<line>: ...`, never half-parsed:

- indentation on a content line (the nested-mapping shape) and a bare `key:` with no value;
- leading `{`/`[` (flow collections), `&`/`*` (anchors/aliases), `|`/`>` (block scalars), `!`/`%`/
  `` ` `` (tags/directives/reserved indicators);
- `---`/`...` document markers (multi-document files);
- missing `:`, invalid key characters, duplicate keys, unterminated quotes, unknown escapes, trailing
  garbage after a closing quote.

No PyYAML, no dependency: the parser is the mechanism, not a wrapper around a YAML library whose
errors might silently accept a construct this subset promises to reject.

### 1.2 `skills/goal-driven-delivery/scripts/gdd.py`

- Adds a vendored `scripts/skill_config.py` beside it (copied by `scripts/vendor_shared.py`) so an
  installed skill package remains self-contained; `vendor_shared.py --check` becomes the drift gate.
- Resolves the six documented keys through the resolver:
  `GDD_STATE_FILE`, `GDD_TASK_ROOT`, `GDD_RUN_ROOT`, `GDD_LAUNCHER`, `GDD_TEMPLATES`,
  `GDD_GOAL_GLOB`.
- Environment behaviour is unchanged: the defaults and `expanduser` calls stay where they are, and
  a set environment variable returns exactly its string from `resolve` (the pre-existing path
  expansion in gdd is applied afterwards, as today).
- `--launcher`/`--templates` become `None` argparse defaults and are resolved with
  `flag=args.launcher`/`flag=args.templates`, so a CLI value beats env/config. `cmd_status` passes
  the resolved state/task/run roots to `delivery-state.py`, so a config file takes effect there too.
- `GDD_GOAL_GLOB` is now actually used. The default `docs/goals/*<goal>*.md` still searches the
  active tree first and then `docs/goals/archive/*<goal>*.md`, preserving the archive resolution the
  self-test already pins. A custom glob is used verbatim.
- `ConfigError` is caught in `main()` and reported as `gdd: <path>:<line>: ...` with exit 2, matching
  the existing `fail()` convention.

### 1.3 Contract graph R9

`scripts/contract_graph_registry.yaml` gains a `terminal:` mapping from artifact to a one-line
reason. `_registry()` returns `(external, shared, terminal)`, validating every terminal value as a
non-empty single-line string.

`analyze()` adds one rule after the existing graph is built:

```
R9  every artifact produced by a skill is consumed by some skill
    or listed under terminal: with a reason
```

The violation names the artifact, its producing skill and the accepted alternatives; `external:`
artifacts are exempt. The four current dangling artifacts are resolved as follows:

| Artifact | Producer | Resolution |
|---|---|---|
| `implementation` | `subagent-driven-development` | `terminal` — the merged code is the destination |
| `chain-plan` | `goal-driven-delivery` | `terminal` — the operator consumes the routing plan |
| `acceptance-verdict` | `delegated-work-acceptance` | `terminal` — no phase reads this artifact |
| `scope-seal` | `delegated-work-acceptance` | `terminal` — `worktree-scope.py verify` checks the tree, not the artifact |

The contract offered a choice for the last two: declare them consumed by `goal-driven-delivery` if
phase 5 verifies the seal and phase 6 requires the verdict. Reading those phases as written, phase 5
runs `worktree-scope.py diff/seal/verify` and phase 6 runs `pr-merge-check.py`; neither reads an
artifact produced by `delegated-work-acceptance`, and GDD does not declare `consumes`. Claiming a
handoff would invent a consumer, so both are `terminal` and the evidence record says why.

### 1.4 Documentation

- `skills/skill-porting-and-publishing/SKILL.md` owns the convention and names the shared resolver
  once: API, config path, CLI, the vendoring rule for installed packages, and the env-name rule
  (already-env-shaped keys verbatim).
- The other skills that restate the chain (`ai-coding-agent-delegation`,
  `contract-bound-deliverables`, `evidence-boundary-discipline`, `git-auto-sync-pipelines`,
  `goal-driven-delivery`, `spec-convergence`, `subagent-driven-development`,
  `systematic-debugging`, `writing-plans`) replace that sentence with a pointer to the owning
  section. Their tables and documented defaults do not change.
- `skills/skill-porting-and-publishing/references/de-coupling-checklist.md` points at the mechanism
  instead of presenting the order as prose only.
- `AGENTS.md` composition contracts gains the two-sided graph rule.
- `gdd.py`'s module docstring/`--help` and GDD's Configuration section document the config file and
  key names; the six defaults are unchanged.

## 2. Evidence plan

1. `python -m unittest scripts.test_skill_config -v` — precedence, XDG vs `~/.config`, root override,
   flat subset, every rejection class, CLI provenance, GDD key path/flag.
2. `python -m unittest scripts.test_check_contract_graph -v` — R9 both directions, terminal reason
   validation, external exemption, plus every pre-existing R1–R8 pin.
3. `bash skills/goal-driven-delivery/scripts/tests/run-gdd-selftest.sh` — existing env behaviour
   unchanged, config file honoured for `GDD_STATE_FILE`, env beats file, CLI beats file, malformed
   file fails loudly.
4. `python scripts/check_contract_graph.py` — before: the four dangling names (captured before the
   rule existed); after: `0` dangling, exit 0.
5. `python scripts/vendor_shared.py --check` — vendored resolver matches the canonical file.
6. `python scripts/skill_config.py --skill goal-driven-delivery --key GDD_STATE_FILE` against a temp
   `XDG_CONFIG_HOME`, plus the env and default forms, for the PR body's provenance line.
7. The contract's full gate list, with exit codes, recorded in `docs/evidence/`.

The self-test becomes hermetic against an operator config: it exports a temp `XDG_CONFIG_HOME` and
unsets `GDD_GOAL_GLOB` at the top, so a real `~/.config/goal-driven-delivery/config.yaml` cannot
change the result.

## 3. Design trade-offs

- **Env name derivation.** The contract's `<SKILL_BIG_SNAKE>_<KEY_BIG_SNAKE>` cannot be applied
  mechanically to GDD (`GDD_STATE_FILE` would become
  `GOAL_DRIVEN_DELIVERY_GDD_STATE_FILE`) without breaking the "byte-identical environment" clause.
  The resolver therefore treats an already-env-shaped key verbatim and prefixes only ordinary keys.
  This is the smallest rule that satisfies both clauses; it is documented and tested both ways.
- **Vendored copy vs repo-relative import.** An installed skill is a self-contained package, so a
  repo-relative import would make the config file work only in this checkout. A vendored copy plus
  the existing drift gate keeps one source of truth and a working installed package.
- **Lazy config read.** A malformed file does not break a flag/env override, because precedence means
  the file is not consulted. This is the normal meaning of precedence; the error contract still
  applies whenever the file is the deciding source.
- **Empty values.** Empty flag/env values are treated as absent to preserve `gdd.py`'s current
  `if value:` semantics. A config line with an empty value is an error rather than an ambiguous
  empty string.
- **Terminal reasons are mandatory.** An empty or multi-line reason fails the registry parse, so the
  exemption cannot become a bare allowlist.

## 4. Out of scope

- No change to `~/.hermes`, any bot's `allowed_skills`, or an installed skill.
- No trigger-judge, README architecture rewrite, or launcher `events.ndjson` work (each its own
  increment).
- No migration of the other skills' scripts or environment names; only their prose pointer. Their
  tables keep the documented defaults and variable names.
- No `delivery-state.py` rewrite: `gdd.py` passes resolved values to it, which is the documented
  path. Direct invocation keeps its current environment-only behaviour.
- No new dependency and no PyYAML.

## 5. Close

Bump `VERSION` (patch), mirror it through `python scripts/version.py bump`, add a `CHANGELOG.md`
entry, write `docs/evidence/2026-11-11-mechanism-or-no-claim.md` with real output and exit codes,
move the contract unchanged to `docs/goals/archive/`, and update `docs/goals/README.md`. Leave the
tree uncommitted for verification.
