# Porting host/profile skills into a self-contained repo

Use when a repo's contract says its agent methodology lives in the repo (a kernel file plus a
`skills/` ownership clause) and the host profile has accumulated the real copies.

## Decide ownership per skill BEFORE moving anything

The expensive mistake is the split, and it is expensive in both directions: a general capability
moved into a project repo pollutes that repo, and methodology left in the host profile violates the
repo's own contract.

- **Repo-owned**: useless outside this repo — it binds the repo's validator, harness modules, study
  layout, provider registry, or control records. Port it.
- **General cross-project capability**: stays external even when this repo uses it constantly.
  "Used by" is not "owned by". Port the *repo-specific lessons* out of it into the repo's owning
  layer; do not move the skill itself.
- Present the split to the owner as a multiple-choice question with your recommended split first.
  "Port everything" and "port only the exclusive ones" are different commits.

## Port procedure

1. **Read the repo's contract first.** The kernel and the doc that owns skill placement state the
   requirements — supporting files, provenance, dependency checks, real loading verification. Copy
   those, do not invent your own acceptance bar.
2. **Move each skill with ALL its supporting files** (`references/`, `templates/`, `scripts/`). A
   SKILL.md alone is a broken port.
3. **Sanitize host-local bytes out**: absolute checkout paths, home directories, host-only tool and
   skill names, secrets. Where a fact previously lived in a host location, re-point it at the repo's
   own owner (its module, registry, or contract doc) — a multi-harness repo must not depend on a
   single harness's names.
4. **Match the neighbouring repo skill's frontmatter shape.** Trim host-only fields (`version`,
   `author`, `license`, harness-specific `metadata:`) if the repo's existing skill carries none.
5. **Repair what you inherit.** A copied skill can describe repo history that has since changed
   (retired files, renamed symlinks). Verify every referenced fact against the repo before
   publishing; a stale example is a documentation defect you are shipping.
6. **Index the new skills from the repo's router skill**, and renumber its sections rather than
   appending an unnumbered block.
7. **Repair the placement contract** when the kernel authorizes a layer the layout/ownership doc
   omits — that omission is a doc conflict, and the kernel's own rule is to fix the focused file.
8. **Record the port as a maintenance record + change-log entry**: source→destination map,
   sanitization table, verification output, rollback unit. Never invent research or acceptance
   state for a maintenance action.

## Sanitization pitfall

The sanitization log is the easiest place to REINTRODUCE what you just removed: a "before" column
quoting the original host path or host tool name puts those bytes straight back into the repo.
Describe each removed item generically.

## Editing an existing repo's files (fidelity)

- **Check the repo's real line-ending state first**:
  `git ls-files --eol | awk '{print $1}' | sort | uniq -c`. Mixed repos are normal; the newest files
  are often LF while older ones are CRLF.
- **New files → LF** (matches the newest commits and keeps `git diff --check` clean).
  **Edited existing files → preserve their CRLF**, so the diff holds only the changed lines.
- **Do not use a find/replace path that normalizes line endings** on a CRLF file — a whole-file EOL
  diff destroys reviewability. Edit bytes with a small script that asserts the exact occurrence
  count of every target string and aborts before writing on mismatch, then rewrites the same
  encoding. The assertion is what catches a wrong format assumption instead of corrupting the file.
- **Whitespace check on a mixed repo needs the repo's own convention**:
  `git -c core.whitespace=cr-at-eol diff --check`. Plain `--check` reports CRLF as trailing
  whitespace and buries the real findings in noise.

## Binding safety before touching shared repo files

Control-plane repos commonly bind file hashes into frozen records. Before editing any file, grep the
frozen records for its path:

    grep -rn '"skills/' studies/ --include=method-profile.json

Empty output → free to edit. Non-empty → the edit still validates via the commit-blob fallback, but
it is a recorded method-profile deviation, so follow the repo's anchor/deviation procedure (record
it; keep the frozen anchor reachable) rather than treating validator-green as blanket permission.

## Verification that actually counts

- **Validator/regression before AND after, diffed.** Capture the baseline to a file first
  (`... > before.txt`), then `diff <(grep ERROR before.txt) <(grep ERROR after.txt)` and require the
  sets to be identical. A bare error *count* hides findings that swapped.
- **Run the repo's suite through its documented env** (pinned requirements / `uv run
  --with-requirements ...`), never system python — missing optional dependencies surface as errors,
  which reads as "I broke it".
- **Regenerable report files written as a side effect are out of scope** (lint/health reports):
  delete them so the change stays scoped, or commit them deliberately as their own change.
- **Host side**: open the pointer skill through the runtime's skill loader and confirm every path it
  names resolves.
- **Read the remote back after pushing** (`git ls-remote origin refs/heads/main` vs `HEAD`) — a
  push exit code is not proof the commit landed.

## Host-side outcome

The host keeps at most ONE thin discovery pointer (locate the checkout → read the repo kernel and
`skills/`), carrying no methodology of its own. Before deleting the moved copies, tarball them
outside the skills directory as rollback evidence. Then confirm the profiles still resolve their
category symlink and the layer-reconcile check comes back clean.
