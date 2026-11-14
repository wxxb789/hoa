# Catalog plan correction evidence — 2026-11-14

This record supports the corrected plan, not acceptance of its future implementation phases.
No host configuration or current installation state is part of this evidence.

## Inputs and measurement

- Original audit baseline: `3131458`; separately produced report contents recovered locally.
  Reading them does not establish execution isolation/independence.
- Revised-plan review input: head `1e88a3c63150adec5241e997db140a49140b0825`,
  tree `2afc9a61645e608889532cc21726b314679dfdbf`.
- Pinned catalog input: `cabf8c63bdd770f8a663250156ce2aaa130f4a55`,
  tree `0cd6dc11bf42c29fcd86d0077e0cc8bf754560a1`. SKILL bodies match the review input;
  subsequent channel/version changes are not silently folded into this snapshot.
- Original report A SHA256: `ddf2f7e2243686a6a9c27e524d05222995c24c0097b3453d5c448abe166baa65`.
- Original report B SHA256: `7c67b5b58ea69f06b06c68e1b215f0f938065d38050193a5d8f6756dbd97392d`.
- Simplify report S SHA256: `f5b171162868b9e4e417d409d803298c92cf7e8b4bc3d274b7b1a445483cc8bb`.
- Code-review report R SHA256: `ab09c5e0cedd452356f4c935a975c50d48cf2e777fbb279409a82ff3f20dc110`.
- Raw reports remain operator-held because they contain installation details. Corrected attributable
  conclusions and every finding disposition are recorded below.

From the repo root with existing `scripts/requirements.txt` dependencies:

```text
python docs/evidence/catalog_measurement.py --ref cabf8c6
python scripts/test_catalog_measurement.py
```

The helper reads Git blobs without checkout, network, skill execution or configuration reads. JSON
includes commit/tree, every skill's body/full-file lines, whitespace words, fence-aware ATX H2, kinds,
queue/stubs and tracked code over 600 lines. Strip YAML frontmatter/exterior blank lines, then
`splitlines()`/`split()` including code; p90 is nearest rank. Body total/median/p90/max:
9,164/131/305/503; full-file: 10,124/143/323/516. There are 35 bodies over 120 and 21 in 121–200.
The queue predicate selects 13. `skill-library-curation` is 186 lines; `github-code-review` is
468 lines, 1,806 words, six H2 outside fences: both are excluded.

Other static inventories use pinned tracked source, not host installation:

- Parse the 59 flat SKILL YAML blocks. Legal TARGETS come from `scripts/generate_index.py` (eight);
  three values are used, four skills runtime-specific. Registry counts are external 4/terminal 4/shared 0.
  `check_frontmatter.py` delegates parsing; explicit kind remains required by AGENTS.md and R2/R7.
- Test presence: enumerate script skills and named own test/eval entrypoints. The plan lists the
  disjoint six-own-test and two-additional-eval sets: 21−8=13, not measured branch coverage.
  Compare CI command/cwd/module/package forms, not basenames. Baseline test job has 33 run steps plus
  three setup actions; runtime coverage reconciliation remains future A acceptance.
- References: enumerate 107 tracked Markdown references. Twelve lack full-path direct entry mention,
  nine in GDD. Follow explicit file/directory declarations from entries and reachable references.
  GDD's declared stage-template directory exposes five children: directory-aware graph leaves three
  orphans, strict file-edge graph eight. `.gitignore` is outside this Markdown universe.
- Scoped-path probes: four transport/adapter/dispatcher/template references explicitly name GDD
  ownership and resolve in `skills/gdd/`; the fifth approval file and `resolve_approval` symbol exist
  under `hoa-introspect-distill`. Symbol suffixes are not filenames.
- Inspect import/parsing/control flow before help execution. Office business imports, event writer
  directory argument, example fetcher's networking and watcher polling establish unsafe-help boundaries.
- `scripts/install_host_skills.py` exposes parity inspection and refuses differing real directories.
  Current host counts and an automatic rematerialization service were not verified.

## Simplify dispositions: S1–S13

| ID | Decision and applied plan correction |
|---|---|
| S1 | ACCEPT: §1.2 withdraws five dead paths; §5/§10 retain them as positive scoped fixtures and require true missing negatives. |
| S2 | ACCEPT: §7 separates universal syntax from safe-help remediation; heavy dependencies stay outside root CI requirements. |
| S3 | ACCEPT: §4/§11 retain Ubuntu/POSIX reference CI; new/changed skill portability is admission, not legacy fact. |
| S4 | ACCEPT: §1/§6 share trimmed-body/fence-aware measurements and 13-row queue; distinguish full files. |
| S5 | ACCEPT: §1 disjoint 6+2 test-presence sets, not overlapping 6+4 coverage. |
| S6 | ACCEPT: §1.2/§5 specify 12 direct absences, nine GDD, three directory-aware orphans versus strict eight. |
| S7 | ACCEPT: §5 mandatory kind/R2/R7 retained, optional-kind withdrawn. |
| S8 | ACCEPT: §5 reuses one existing definition each, no fictitious three-copy consolidation. |
| S9 | ACCEPT: §4 named shell patterns and covered_by prevent independent child duplication. |
| S10 | ACCEPT: §3/§8 sources.py depends on C2/L1; other A′/A″ work is independent. |
| S11 | ACCEPT: input/report fingerprints and attribution above; unsupported current-host 59/31 counts removed; independence not claimed verified. |
| S12 | ACCEPT: §4 item 8 is sole full A acceptance; §10 links it. CI step reduction is not acceptance. |
| S13 | ACCEPT: CHANGELOG withdraws false claims and cites refuting checker code, never claims that code was removed. |

## Code-review dispositions: R1–R6, all 19 subpoints

| ID | Decision and applied plan correction |
|---|---|
| R1.a | ACCEPT: named shell whitelist/covered_by remove dispatch-guard double scheduling. |
| R1.b | ACCEPT: worktree-scope, Paseo Python suite and four plugin tests enter reconciliation via explicit Vitest package commands. |
| R1.c | ACCEPT: custom adapters require positive counts; declared unittest rejects zero; module invocations preserved. |
| R1.d | ACCEPT: whole-suite optional SKIP distinct from PASS with subcase skips; runtime/import failures are ERROR, required empty cannot pass. |
| R2.a | ACCEPT: trimmed-body statistics and compact examples (21, html 172, writing 143). |
| R2.b | ACCEPT: full-file 10,124/max 516 versus body 9,164/max 503; pinned snapshot replaces stale total. |
| R2.c | ACCEPT: queue 13 excludes curation/fenced pseudoheadings; highlighted words 3,362/4,445/3,019. |
| R3.a | ACCEPT issue, CORRECT detail: eight legal targets, three used values, four runtime-specific skills, not four used values. |
| R3.b | ACCEPT: terminal four, not five: acceptance-verdict, chain-plan, implementation, scope-seal. |
| R3.c | ACCEPT false premise; no compulsory relocation of one-definition enums; reuse existing parser/definitions. |
| R3.d | ACCEPT: queue 10 entries/2 mechanisms/1 stage; §10 forbids mechanisms in must_pick and tests stage/caller integration. |
| R4.a | ACCEPT: explicit kind/R2/R7 unchanged; no default-entry workaround. |
| R4.b | ACCEPT core: universal syntax, declared safe-help remediation, legacy/admission distinction. Incorrect Hermes example corrected below. |
| R5.a | ACCEPT: approval file:symbol/anchor are scoped positive fixtures, not missing files. |
| R5.b | ACCEPT: repo/cross-skill/external/example/output scope distinguished instead of treating every scripts token locally. |
| R5.c | ACCEPT: Markdown universe and directory-aware graph specified; direct absence is not orphanhood. |
| R6.a | ACCEPT: installation-specific consumer/parity/drift refusal contract, not private profile/hygiene guarantees. |
| R6.b | ACCEPT: complete 12-file >600 inventory below; teams 591 is below threshold; responsibilities still need evidence. |
| R6.c | ACCEPT: 38 gitlinks, stale README 35 and manual mirror policy stated; generated bilingual drift/same-commit regeneration preserved. |

Report-detail corrections do not dismiss their underlying issues: R's untrimmed body convention
(9,225/132/308/504) differs from the explicit trim convention; S's 14 count includes fenced H2.
R's Hermes `audit-config-drift.py` example is not a top-level Hermes import: parsing precedes that
import inside main. The setsid suite skips optional tmux subcases, not its whole process. README has
a manual Chinese mirror policy even though no CI mirror checker was identified. Original reports'
"change one thing" recommendations were related, not identical; optional-kind/universal-help were not
existing unanimous contracts. The corrected plan retains safety/governance issues without these errors.

## Complete pinned tracked code inventory over 600 lines

| file | splitlines() |
|---|---:|
| skills/gdd/scripts/adapters/omp-run.py | 2070 |
| skills/gdd/scripts/tests/test_omp_run_python.py | 1609 |
| skills/gdd/scripts/tests/run-gdd-selftest.sh | 1168 |
| skills/gdd/scripts/gdd.py | 1029 |
| skills/gdd/scripts/adapters/omp-run.sh | 965 |
| skills/gdd/scripts/pr-merge-check.py | 838 |
| scripts/test_version.py | 704 |
| skills/gdd/scripts/delivery-state.py | 684 |
| skills/grounded-citations/scripts/sources.py | 676 |
| paseo-plugins/gdd-run-observer/client/runs-browser.tsx | 648 |
| skills/m365-copilot-cdp/scripts/copilot.ts | 642 |
| skills/gdd/scripts/tests/test_paseo_run_python.py | 604 |

No future discoverer/fault injection, C1/C2 checker, split behavior/install/routing acceptance or
host migration is claimed complete. This PR's acceptance is corrected attributable facts, dispositions,
reproducible measurements and the repository's real PR gates/review.
