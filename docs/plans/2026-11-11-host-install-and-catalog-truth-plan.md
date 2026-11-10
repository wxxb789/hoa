# Plan — host install parity and catalog truth

Contract: [`docs/goals/2026-11-10-host-install-and-catalog-truth.md`](../goals/2026-11-10-host-install-and-catalog-truth.md)
Increment: `host-install-and-catalog-truth` · branch `feat/host-install-and-catalog-truth`

The repo has no designated plan directory and no profile that forbids one, so the plan lives in
`docs/plans/`. The contract is archived on close, not rewritten.

## 1. Public / API shape

### 1.1 `scripts/install_host_skills.py` (new)

```text
python scripts/install_host_skills.py --root <host-skills-dir> --check
python scripts/install_host_skills.py --root <host-skills-dir> --link
```

- `--root` is required; `--check` and `--link` are mutually exclusive and one is required.
- The repo side is every non-hidden directory in `skills/` that contains `SKILL.md` (the same set the
  catalog and version tooling already treat as custom skills).
- A host entry `<root>/<name>` is **installed** when it is either
  - a symlink whose resolved target is the repo's `skills/<name>`, or
  - a real directory whose file set, file bytes and internal symlink targets equal `skills/<name>`.
- Host entries that do not correspond to a repo skill are ignored; the installer never deletes or
  rewrites them.
- `--check` writes nothing (including no `__pycache__`: `sys.dont_write_bytecode = True`) and exits
  0 when every repo skill is installed. Otherwise it exits 1 and prints one line per finding:
  `absent:`, `drifted:` (real directory differs; the first differing paths are named) or
  `wrongly linked:` (symlink resolves elsewhere, including a broken link).
- `--link` creates only symlinks, using the absolute resolved repo path as target. It is idempotent:
  a second run changes nothing and prints `nothing to do`. For a symlink pointing elsewhere it
  replaces the link and reports `relinked:`. A real directory that differs is **refused**, named,
  left untouched; other skills are still linked in the same run, and the process exits 1. A regular
  file at a skill's path is refused the same way.
- Usage errors (missing root, root is a file, neither/both modes) exit 2.
- Symlink creation is `os.symlink` to a temporary name plus `os.replace`, so a concurrent reader
  never sees a half-created link and an existing link is never followed.

### 1.2 `scripts/check_changelog.py` (new)

```text
python scripts/check_changelog.py --base origin/main
```

- `--base` defaults to `origin/main`.
- Compares the merge base of `--base` and `HEAD` with the **working tree** (`git diff --name-only
  <merge-base> -- VERSION CHANGELOG.md`), so it works both in CI and before committing locally.
- Exit 0 when `VERSION` is unchanged, or when it changed together with `CHANGELOG.md`.
- Exit 1 only when `VERSION` changed and `CHANGELOG.md` did not, with the reason on stderr.
- Exit 2 when git fails (unknown base, not a repository), never silently green.
- CI runs it in the pull-request job with `--base origin/main`.

### 1.3 Summary source (catalog truth)

- A skill's summaries live in its own YAML frontmatter: `metadata.summary` (English) and
  `metadata.summary_zh` (Chinese), string scalars.
- A library artifact's summaries live in its existing `<!-- index: ... -->` metadata comment:
  `summary="..."` and `summary_zh="..."`. Library artifacts have no YAML frontmatter and the repo
  rule is that their catalog metadata stays in that comment; this keeps one carrier per artifact.
- The comment parser becomes quote-aware (`;` and `"` inside a double-quoted value are part of the
  value). Existing unquoted and quoted comments parse to the same values as before.
- Resolution order, English: `summary` → first sentence of the frontmatter `description` → first
  readable body line. Chinese: `summary_zh` → the resolved English summary. An artifact with no
  usable English note is an error, as today.
- `NOTES` in `scripts/generate_index.py` is deleted; there is no per-skill summary table.
- All 49 current entries (40 skills + 9 library artifacts) move byte-for-byte into their artifacts;
  only the stale `spec-convergence` entry is rewritten, in both languages, to the current
  one-root-per-round protocol. `index.md` and `index.zh-CN.md` therefore change on exactly those two
  rows.

### 1.4 `scripts/check_frontmatter.py` (new gate script)

The gate list and the contract's evidence plan name this command, but the file does not exist yet;
CI currently uses an inline shell loop. The script checks every `skills/*/SKILL.md`:

- YAML frontmatter delimited by `---` on the first line and a closing `---`;
- non-empty string `name` equal to the skill directory name;
- non-empty string `description`;
- `metadata.version`, `metadata.areas`, `metadata.targets` through the shared catalog parser, and
  string type for `summary` / `summary_zh` when present.

Exit 1 with one line per failure, 0 otherwise. CI's inline shell step is replaced by this command so
there is one implementation of the rule.

## 2. Edge-case semantics

| Case | `--check` | `--link` |
|---|---|---|
| entry missing | exit 1, `absent: name` | create link, report `linked: name` |
| link → correct repo dir | ok | no change |
| link → other path (incl. broken) | exit 1, `wrongly linked: name -> target` | replace link, report `relinked: name` |
| real dir byte-identical | ok | no change |
| real dir differs | exit 1, `drifted: name (...)` | refuse, report `refused: name`, exit 1 |
| regular file at entry | exit 1, `wrongly linked` (not a dir/link) | refuse, exit 1 |
| root missing / not a dir | exit 2 | exit 2 (never invents a host layout) |
| extra host skill | ignored | ignored |

Changelog rule:

| VERSION vs merge base | CHANGELOG.md vs merge base | exit |
|---|---|---|
| unchanged | unchanged or changed | 0 |
| changed | changed | 0 |
| changed | unchanged | 1 |

## 3. Trade-offs and rejected alternatives

- **Library summaries in the index comment, not YAML frontmatter.** The contract says "its own
  frontmatter" but nine `NOTES` entries belong to library artifacts that have no frontmatter. Options:
  (a) add a YAML block to nine files, creating a second metadata carrier next to the comment;
  (b) extend the existing comment, creating a quote-aware parser. Recommendation and choice: (b) —
  one carrier, no format fork, existing comments keep their meaning. The nine values migrate
  unchanged, including the three containing `;`.
- **Drift means content equality, not mtime or link presence.** A real directory copy that was edited
  in the host is exactly the failure this increment exists to catch.
- **Absolute symlink targets.** Relative targets survive a repo move but differ by root depth; the
  host layout on this machine is fixed, and absolute targets make `wrongly linked` diagnostics
  unambiguous.
- **`--link` refuses rather than deletes.** Contract: never delete, move or rewrite anything in the
  host dir. Replacing a symlink is not deleting content; replacing a real directory would be.
- **Working-tree diff in `check_changelog`.** A merge-base + working-tree comparison answers the
  contract's question ("did this increment change VERSION without a changelog entry") in CI and
  locally, without requiring a commit first.
- **Patch bump to 0.1.30.** CI requires every PR to be exactly one patch above `origin/main`
  (0.1.29) and the merge guard requires the tag to be free; `v0.1.29` is taken, `v0.1.30` is not.

## 4. Out of scope (with reasons)

- Bot `allowed_skills`, `config.yaml`, `skills.disabled`: runtime policy is an operator action
  (contract §4).
- `$XDG_CONFIG_HOME/<skill>/config.yaml` loader: next increment (contract §4).
- Producer-side contract-graph rules, README architecture rewrite, model judge: later increments
  (contract §4). Only the README sentences that would become factually false about summary sourcing
  are corrected.
- Adding the eight skills to this machine's live host install: the operator runs it; proof here is a
  temp root that mirrors the host layout.
- Automatic installation into host dirs from CI: there is no host in CI.

## 5. Evidence plan

1. Unit tests: `scripts.test_install_host_skills` (absent / linked / wrong link / drift / refusal /
   idempotence / check-writes-nothing), `scripts.test_generate_index` (frontmatter summaries,
   `summary_zh` fallback, description fallback, quote-aware comment values), `scripts.test_check_changelog`
   (both directions + no-version-change), `scripts.test_version`.
2. Temp-root proof mirroring this machine's host: build a root with 32 of the 40 skills, run
   `--check` (expect exit 1 and the 8 absent names), `--link` (expect exit 0 and 8 links),
   `--check` (expect exit 0), second `--link` (expect `nothing to do`).
3. `index.md` diff restricted to the two `spec-convergence` rows; `--check` green afterwards.
4. Full gate list from the stage template, each with its real exit code, recorded in
   `docs/evidence/2026-11-11-host-install-and-catalog-truth.md`.

## 6. Close ritual

In the same tree as the code:

- move the contract file **unchanged** to `docs/goals/archive/`;
- add `docs/goals/README.md` as the goal index (active / archived, state, link);
- record evidence under `docs/evidence/`;
- reconcile the generator's docstring, README/README.zh summary sentences, and
  `workflows/adopt-a-pattern.md` step 5.
