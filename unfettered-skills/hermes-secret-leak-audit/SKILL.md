---
name: hermes-secret-leak-audit
description: "Use when hunting leaked secrets in repos or machines."
version: 1.0.0
author: Zoe
license: MIT
metadata:
  hermes:
    tags: [security, secrets, credentials, redaction, audit, git, sqlite]
    category: devops
---

# Secret-Leak Audit

Find → classify → redact → verify → report. Two entry modes: the **pre-commit sweep** (before the
first push of a new tree) and the **post-incident recheck** ("recheck for leakages": scope everywhere
a leaked value could have landed — working tree, git history, the remote, and the machine's own
stores). Receipt-level scanning during provider work is covered by `agent-harness-model-gateways`
pitfall 8; this skill owns the full audit.

## When to Use

- "recheck for leakages", "any leaks?", "is this safe to push", "did key X leak" — after a
  credential turns up in a file, receipt, or log.
- Before the first push of a new tree — sweep in the same session that stages the commit.
- After rotating a key, to prove the old value is gone or say precisely where it survives.

## Rules (every instance)

1. **Standalone-token regex, never a bare `sk-`.** `sk-[A-Za-z0-9_\-]{30,}` false-fires on ordinary
   text (`task-orders`, `risk-managed`, `Novorossiysk-…`). Anchor it:
   `(?<![A-Za-z0-9_])sk-[A-Za-z0-9_\-]{30,}`; add the other token families (ghp_/github_pat_/AKIA/
   AIza/xox/PEM/hf_/r8_/xai-/JWT). Classify each hit by its ~10-char pre-context before acting on it.
2. **Scan all candidates; never sample.** A LIMIT-50 sample inside 900 `LIKE '%sk-%'` candidates
   silently missed 11 real hits because the noise sorted first. Prefilter with the LIKE, then
   regex-verify EVERY row in Python.
3. **Mask every hit you print** — prefix + length only (`sk-cdz…(len67)`, `…(len67)`). Your output is
   itself persisted (chat log, session DB); a scan that leaks the secret defeats itself. Print
   counts, rowids, file paths — never values or suffixes.
4. **Redact before the FIRST push; rotation is the real fix.** Local redaction is defense-in-depth —
   any key that ever sat in a file should be rotated. State explicitly when the value never reached a
   remote; that distinction is what the owner actually needs.
5. **Never scrub operational credential stores** — tool credential tables, `.env`, `auth.json`, env
   snapshots. Scrub only LOG/transcript layers (session messages, `.err`/`.out` receipts, tool state
   DBs). Editing a running tool's credential store breaks the tool.
6. **Do not touch mechanism files.** Env-snapshot scripts (`hermes-snap-*.sh` in scratch) restore the
   terminal's exported environment between calls — redacting them breaks the session; they are
   600-perm local-by-design, same trust level as `.env`.
7. **Timeline dismisses false positives.** A file older than the key's creation cannot contain it
   (byte coincidences in old binaries/images). Check dates before investigating a binary hit.
8. **Keep an audit log** (in scratch): scope scanned, redactions by rowid/count, residue re-checks —
   counts and handles only, never values.

## Sweep procedure

1. **Working tree** — include ignored dirs (leaks ignore `.gitignore`): `python3
   scripts/scan_secrets.py <root>` (masked output; standalone-token patterns; binary/size skip).
2. **Git history** — a tree-only sweep is a half-sweep; history keeps secrets after cleanup:
   `git log --all -S '<fragment>' --oneline` for known fragments; broad scan
   `git grep -lE '<pattern>' $(git rev-list --all)`.
3. **Remote** — verify the pushed blob, not the local file:
   `git show origin/main:<path> | grep -c '<fragment>'`.
4. **Machine surfaces** — Hermes install: `~/.hermes/{cache/terminal-output,logs,sessions,scratch}`
   + `state.db` (scan ALL tables/columns); opencode:
   `~/.local/share/opencode/{opencode.db,log,shell,snapshot,tool-output}`; `~/.pi`; dotfile dirs;
   shell histories.
5. **Classify → redact → re-verify** per surface. Flat files: in-place regex sub. SQLite stores
   (full key found in a message/log table): `references/sqlite-redaction-recipe.md`.

## Report shape

Masked findings table per surface → executed redactions with zero-residue re-check evidence →
retained items with the reason (operational stores, mechanism files) → rotation recommendation for
every key that ever sat in a file → caveat: SQLite may retain old bytes in WAL/free pages until
checkpoint/VACUUM (`VACUUM` only on a quiesced store, never casually on a live one — rotation
supersedes it anyway).

Support files: `scripts/scan_secrets.py` (reusable masked tree scanner),
`references/sqlite-redaction-recipe.md` (surgical DB redaction).
