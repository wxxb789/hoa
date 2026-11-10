# Goal — host install parity and catalog truth

Increment id: `host-install-and-catalog-truth`
Repo: `wxxb789/hoa` · one run · one PR · mergeable alone

## Why this exists (the failure it answers)

An audit on 2026-11-10 found that 8 of 40 skills exist in this repo and are absent from every
runtime: `define-goal`, `spec-convergence`, `teams-cdp`, `m365-copilot-cdp`, `hoa-introspect`,
`hoa-introspect-distill`, `hoa-skill-review`, `hoa-skill-work`. Two of them point at each other in
prose (`writing-plans` → `spec-convergence` → `define-goal`), so an installed skill hands off to a
skill that does not exist. Nothing noticed, because nothing compares the repo to the host.

At the same time the generated index carries a **second source of truth**: ~30 English/Chinese
summaries hard-coded in `scripts/generate_index.py`, and the `spec-convergence` one still advertises
"one numbered round per level" — the protocol that was replaced the same day. `--check` stays green
because both sides are static.

## 1. Observable pass condition

- `python scripts/install_host_skills.py --root <host-skills-dir> --check` exits 0 on a host where
  every `skills/*/` in this repo is installed, and exits 1 naming each absent, drifted or wrongly
  linked skill otherwise. It never writes in `--check` mode.
- `python scripts/install_host_skills.py --root <dir> --link` is idempotent: a second run makes no
  change and reports nothing to do; it refuses to replace a real directory with a symlink and says so.
- `python scripts/generate_index.py --check` is green with **no per-skill summary map in the
  generator**: each skill's English and Chinese summary come from its own frontmatter
  (`metadata.summary` / `metadata.summary_zh`), falling back to the first sentence of `description`
  when a summary is absent. The `spec-convergence` row in both indexes describes the current protocol.
- `python scripts/check_changelog.py --base origin/main` exits 1 when `VERSION` changed in the
  increment but `CHANGELOG.md` did not, and 0 otherwise. It runs in the PR job.
- After the change, running `--link` against this machine's host installs the 8 absent skills; the
  resulting `--check` exits 0. (The operator runs this; the agent must prove it against a temp root.)

## 2. Judging artifact

The four scripts above plus their unit tests, and the real `--check` output before and after linking
into a temp root that mirrors this machine's host layout.

## 3. Failure control

- Never delete, move or rewrite anything inside the host skills dir; `--link` only creates symlinks
  and reports what it refuses to touch. A real directory where a symlink is expected is reported as
  drift, not replaced.
- The summary migration must be byte-faithful: every summary currently in the generator's map moves
  into the matching skill's frontmatter unchanged, and the generated `index.md` /
  `index.zh-CN.md` differ only in the rows that were stale.
- No new runtime dependency; stdlib + git only.
- If a skill has no `summary_zh`, its Chinese cell falls back to its English summary rather than to a
  wrong translation.

## 4. Out of scope

- Editing any bot's `allowed_skills`, `config.yaml` or `skills.disabled` (runtime policy, operator
  step, separate action).
- A config-file loader for `$XDG_CONFIG_HOME/<skill>/config.yaml` (next increment).
- Producer-side contract-graph rules, README architecture documentation, or a model judge for the
  trigger cases (later increments).

## 5. Evidence plan

```bash
python -m unittest scripts.test_install_host_skills -v      # temp roots: absent / linked / drift / idempotent
python -m unittest scripts.test_generate_index -v           # frontmatter summaries + fallback
python -m unittest scripts.test_check_changelog -v          # version-changed rule both ways
python scripts/generate_index.py --check
python scripts/check_contract_graph.py
python scripts/check_frontmatter.py
python evals/run_trigger_evals.py
python scripts/version.py check-merge
python -m unittest scripts.test_version
```

The PR body carries the real output of `--check` before and after `--link` on a temp root, and the
diff of `index.md` restricted to the rows that changed.

## 6. Mergeable alone

Nothing in this increment requires the next one: after the merge, the repo can install itself into a
host and its catalog describes the current skills. The follow-up increments (allowlist wiring,
config loader, graph consumer side, README, judge) each stand on their own.
