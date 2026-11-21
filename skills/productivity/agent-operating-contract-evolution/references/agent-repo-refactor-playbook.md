# Refactoring a user-owned agent-contract / control-plane repo — execution playbook

Execution counterpart to `agent-contract-system-review.md` (review/judgment method). Use when the owner asks you to CARRY OUT the refactor: unify scattered per-project scripts, flip the kernel file, consolidate docs, rotate logs/archives, retire legacy — on a repo whose product is an agent contract or research control plane.

## Kernel flip: replacing a legacy agent file with the kernel file

- Flip as real file + compatibility symlink, never immediate removal: `git mv <legacy> <kernel> && ln -s <kernel> <legacy> && git add <legacy>`. Every tool still probing the legacy name keeps working through the symlink; the commit's mode-change lines (100644 → 120000 and reverse) confirm the flip happened.
- Prove zero content change: `git show HEAD:<legacy> | diff - <kernel>` must come back empty. Any "fix the header wording" edit after the flip needs this diff first — direction-agnostic header text ("<kernel> is entry point; preserve symlink relationship; edit the authoritative target") is already correct in both states, and the kernel's edit-protection gates will (correctly) block the redundant patch. Do not retry a blocked header edit before diffing against the pre-flip canonical content.
- Update only LIVING docs (README, onboarding, ownership/authority tables) to describe the new roles. Leave raw/_meta historical provenance files byte-stable — they record what was true at capture time.

## Unifying scattered per-project scripts into one CLI

- Classify scripts by PATTERN, not by project (discovery runners / draft fan-out / QA checkers / source-unit ingest). The pattern is the reusable core; per-project variance becomes config: a project manifest + a machine-readable QA contract spec at the project root. Transport quirks live in code; stable facts (models, endpoints) in a JSON registry.
- Parity is the deletion gate. The unified engine must reproduce every historical metric per artifact — lengths, in-text citation counts, reference-table counts, FAIL sets — one parity report per project, diffed against the historical QA report. No parity, no deletion.
- Mine ALL historical artifacts for format variance BEFORE writing parsers. The same logical section arrives as a bare `参考文献` line, `## 参考文献`, and `## 8. 参考文献`; a regex tightened to one observed shape silently zeroes other projects' metrics. Anchor parsers to whole lines and accept every observed historical shape.
- Parity reports go to NEW files (`...-engine-parity.md`), never over the historical report — overwriting destroys the provenance the parity proof depends on. If a historical report gets clobbered, `git checkout --` it immediately.
- Write the PROVENANCE record (what moved where, parity evidence, retired file list) BEFORE deleting anything.
- Deletion safety sweep, in order: (1) grep hash-bound control files (method-profiles, manifests) for the script paths — live bindings must not break; (2) sweep every remaining reference and split historical narrative ("was validated by scripts/qa_final.py" — keep) from current-state layout lines ("scripts/ …" directory listings — update to the unified CLI); (3) byte-compare suspected duplicates before removing them — a root-level copy of a wiki page goes only after `diff` proves identity with the canonical page.

## Validator exemption wiring

- The decision rule (wire an existing exemption registry instead of re-anchoring bindings) lives in `agent-contract-system-review.md`. Execution shape: exemption default-on in the validator with a raw-view escape hatch (`--no-frozen`) for audit; structural checks (index, duplicate-id, frontmatter shape) stay non-exempt; diagnosis tools (doctor) call the validator with exemptions OFF so their frozen-vs-live classification still sees the full raw set. Exempting at the validator alone would blind the doctor.

## Archive / log rotation

- Use the repo's own rotation tool when one exists; hand-splitting drifts the format. When merging overlapping archives: dedupe by entry header, keep entry text verbatim, regenerate digests with the repo's own digest function, and count entries in vs out to prove zero loss.
- Read a helper's function signatures before reusing it — assuming a return shape (list of strings vs list of tuples) writes a silently corrupt output file. Rebuild a corrupted generated file from its git-tracked sources rather than patching the corruption.

## Verification gates before commit

- Full test suite: failures must match the recorded baseline EXACTLY; attribute platform/env-only failures (Windows path guards on Linux; optional deps via `uv run --with <dep>`) instead of "fixing" them.
- The repo's own gates: lint + system validator + doctor — green or baseline-matched.
- Staged-change census: A/D/M/R counts from `git status --porcelain` sanity-checked against intent before `git commit`.
- Portability smoke: run the unified CLI from OUTSIDE the repo (`cd /tmp && python3 <repo>/.harness/<cli>.py doctor`) to catch baked-in cwd/host assumptions; env-dependent tools must degrade with a fix hint, not fail hard.
- Commit and push are per-session owner-authorized on the owner's repo: never push without that session's explicit authorization, and when authorized push direct to the main branch — no PR unless the owner asks for one.
