# Evidence — host install parity and catalog truth

Contract: [`docs/goals/archive/2026-11-10-host-install-and-catalog-truth.md`](../goals/archive/2026-11-10-host-install-and-catalog-truth.md)
Date: 2026-11-11 · Version: 0.1.30

All commands ran from the repository root on this host. Exit codes are the process exit codes.

## 1. Host install parity on a temp root

The temp root mirrors this machine's host layout: the 32 skills that were installed, plus an
unrelated host skill directory and a `.bundled_manifest` file, with the eight audited skills absent.
No live host directory was read or written.

```text
$ python scripts/install_host_skills.py --root .tmp-artifacts/host-install-proof/host --check
exit=1
absent: define-goal
absent: hoa-introspect
absent: hoa-introspect-distill
absent: hoa-skill-review
absent: hoa-skill-work
absent: m365-copilot-cdp
absent: spec-convergence
absent: teams-cdp
install_host_skills: 8 of 40 skills are not installed at .tmp-artifacts/host-install-proof/host

$ python scripts/install_host_skills.py --root .tmp-artifacts/host-install-proof/host --link
exit=0
linked: define-goal
linked: hoa-introspect
linked: hoa-introspect-distill
linked: hoa-skill-review
linked: hoa-skill-work
linked: m365-copilot-cdp
linked: spec-convergence
linked: teams-cdp
install_host_skills: linked 8, relinked 0 at .tmp-artifacts/host-install-proof/host

$ python scripts/install_host_skills.py --root .tmp-artifacts/host-install-proof/host --check
exit=0
install_host_skills: all 40 skills installed at .tmp-artifacts/host-install-proof/host

$ python scripts/install_host_skills.py --root .tmp-artifacts/host-install-proof/host --link
exit=0
install_host_skills: nothing to do; all 40 skills installed at .tmp-artifacts/host-install-proof/host
```

Drift and refusal are covered by `scripts/test_install_host_skills.py` (13 tests): a real directory
copy is accepted only when identical; a changed copy is reported as `drifted` and refused by
`--link`, with its content left untouched; a symlink elsewhere or a broken link is replaced; a
regular file is refused; `--check` leaves the root tree unchanged.

## 2. Catalog truth

The 49 pre-migration `NOTES` values were captured before editing and the migration was then checked
programmatically: `gi.collect()` returned the same English and Chinese string for all 48 non-stale
entries. The committed-tree proof is the generated index diff — `git diff --numstat index.md
index.zh-CN.md` reports `1 1` for each file, so every other row is byte-identical to the pre-migration
index. The one stale entry is `spec-convergence`, whose row now describes the current protocol.

`index.md` diff — 1 line removed, 1 line added:

```diff
-| spec-convergence | skill | software-development | runtime-agnostic | `skills/spec-convergence/` | converge an unclear request into a confirmed spec: fact-backed decision tree, one numbered round per level, explicit confirmation before writing |
+| spec-convergence | skill | software-development | runtime-agnostic | `skills/spec-convergence/` | converge an unclear request into a confirmed spec: one root concern per round, a capped number of questions per round, every question backed by the fact that makes it real, explicit shared-understanding confirmation before writing |
```

`index.zh-CN.md` diff — 1 line removed, 1 line added:

```diff
-| spec-convergence | skill | software-development | runtime-agnostic | `skills/spec-convergence/` | 把模糊需求收敛为已确认 spec：有事实支撑的决策树、每层一轮编号提问、写前显式确认 |
+| spec-convergence | skill | software-development | runtime-agnostic | `skills/spec-convergence/` | 把模糊需求收敛为已确认 spec：每轮一个根问题、每轮问题数有上限、每问附事实、写前显式确认共同理解 |
```

## 3. Gates

| Command | Output | Exit |
|---|---|---|
| `python -m unittest scripts.test_install_host_skills scripts.test_generate_index scripts.test_check_changelog scripts.test_version` | `Ran 90 tests ... OK` (13 + 29 + 6 + 42) | 0 |
| `python -m unittest scripts.test_check_frontmatter` | `Ran 6 tests ... OK` | 0 |
| `python scripts/generate_index.py --check` | no output | 0 |
| `python scripts/check_contract_graph.py` | `contract graph: 40 skills, 10 artifacts, ok` | 0 |
| `python scripts/check_frontmatter.py` | `check_frontmatter: 40 skills OK` | 0 |
| `python evals/run_trigger_evals.py` | `PASS: 25 trigger cases valid; every must_pick/distractor resolves to a cataloged artifact (49 artifacts)` | 0 |
| `python scripts/check_changelog.py --base origin/main` | `check_changelog: VERSION and CHANGELOG.md both changed` | 0 |
| `python scripts/version.py check` | no output | 0 |
| `python scripts/version.py check-merge` | `0.1.30` | 0 |
| `python scripts/vendor_shared.py --check` | no output | 0 |
| `python scripts/test_check_contract_graph.py` | `Ran 13 tests ... OK` | 0 |
| `python scripts/test_release.py` | `Ran 13 tests ... OK` | 0 |

The changelog rule was also exercised in a disposable clone (base commit `1c4611e`, new script copied
in, tree otherwise untouched):

```text
$ echo 0.1.31 > VERSION && python scripts/check_changelog.py --base <base>
exit=1
check_changelog: VERSION changed but CHANGELOG.md did not; add a changelog entry for this increment

$ printf '\n- proof entry\n' >> CHANGELOG.md && python scripts/check_changelog.py --base <base>
exit=0
check_changelog: VERSION and CHANGELOG.md both changed
```


## 4. Residual risks and limits

- The live host install is the operator's step. This increment proves the tool on a temp root and
  leaves the live host untouched; `--check` against the real host will report the same eight names
  until the operator runs `--link`.
- Symlinks are created with absolute targets. Moving the repository invalidates them; `--check`
  reports each as wrongly linked.
- Drift is byte equality over files, directories and internal symlink targets. A host copy that is
  intentionally edited is treated as drift, not as a local variant.
- Library summary values live in the existing index comment and use double-quoted values; a literal
  `"` inside one must be backslash-escaped (the parser accepts JSON string escapes). None of the
  migrated values contain one.
- The changelog rule compares `VERSION` and `CHANGELOG.md` relative to the merge base. A branch that
  adds its changelog entry in an earlier commit and bumps `VERSION` later is green, which is the
  intended reading of "changed in the increment".
