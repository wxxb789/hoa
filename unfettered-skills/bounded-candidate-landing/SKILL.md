---
name: bounded-candidate-landing
description: "Use when a reviewer accepts a patch; land and prove it."
version: 1.0.0
license: MIT
metadata:
  hermes:
    tags: [landing, patches, lease, verification, receipts, review]
    category: devops
---

# Bounded candidate landing

Use when a patch you authored has been **accepted** by a reviewer (or by the owner) and the task is to make it
real in a shared checkout: apply, verify, publish if the repository contract allows it, and hand back a receipt
the reviewer can independently check. Candidate acceptance is not a landing, and a clean `git apply --check` is
never evidence that the target changed.

## 0. Re-read the acceptance record before touching anything

The acceptance is usually an amended section of the same review file you were already reading. Re-read it fresh;
it names the exact payload files, the baseline SHA, the excluded surfaces, and the rollback unit. Old rounds do
not authorize this one.

## 1. Pre-apply gate (stop on any mismatch)

- `git fetch`; confirm `HEAD` equals `origin/main` and the baseline SHA the reviewer named.
- Confirm the targets have no other writer's uncommitted change (`git diff --stat -- <paths>` empty).
- `cmp` each target byte-for-byte against the reviewer's pre-apply backup.
- `cmp` the payload you are about to apply against your own candidate bytes; the reviewer copies patches, and a
  silent divergence means you would land something nobody reviewed.
- `git apply --check` each payload from the repo root.
- Any failure: stop and report. Never rebase, hand-edit, normalize, or land part of a payload.

## 2. Lease the exact targets

Take your own single-writer lease naming only the target paths. A reviewer's released lease is not
transferable, and a checkout-wide lease invites collisions. Record the lease id for the receipt; release it
before you report.

## 3. Apply only the frozen payload

No opportunistic edits, no metadata "while we are here", no third file, no re-derived patch. `git apply`
whitespace warnings are expected when the accepted bytes contain them — leave the bytes alone unless the
reviewer asks for a change.

## 4. Read the real files back

- Commit `--numstat` per file, and confirm it equals the payload's `--numstat`.
- Parse frontmatter and compare field-by-field against `HEAD:<path>`; an excluded metadata field must come out
  identical, not merely plausible.
- Quote, from disk, each sentence the review explicitly required.

## 5. Checks

- Write-surface check **per path** (`--path`). A whole-tree run will list the reviewer's own in-flight record
  files as violations; that is their surface, not your breach — name whose files they are instead of claiming a
  dirty run or "cleaning" them.
- Report-writing tools (lint and friends) go in an isolated copy of the tree, and you read the report there.
  Dropping a dated report into another role's directory to inspect it is a write outside your surface.
- Structural validators: run them, quote the exact summary line.

## 6. Publish only inside the contract

Read the repository kernel for whether commit and push are standing-authorized, then: stage **explicit paths**
(never `add -A` in a shared checkout), confirm the commit's own `--numstat` equals the payload and that no other
path rode along, push, then `git fetch` and compare local and remote refs. Never force-push, never rewrite
history, never sweep a reviewer's unpublished records into your commit.

## 7. Release and receipt

Release the lease and quote the empty `status` output. The receipt carries: real `HEAD` and parent, per-file
numstat, every gate and check result with the command that produced it, the exact backup/rollback unit,
ownership of every path still dirty, lease id plus release state, and every item that stays unresolved. Leave
unresolved items unresolved — a successful apply does not upgrade a claim, a tier, or a legal conclusion.

## Content gates to pass before you ever hand bytes to a reviewer

These cost rounds when missed; they are cheap to check while the candidate is still in scratch.

- **Numbers come from Git, not from a line grep.** `grep -c '^+[^+]'` (or any pattern needing a character
after the `+`) silently drops every added *blank* line: a real `+59/-4` gets reported as `+42/-1`. Use
`git apply --numstat <patch>` and `git diff --no-index --numstat <before> <after>`, require agreement, and quote
both with the SHA. Recompute per version; an earlier round's count does not transfer.
- **Every new factual paragraph needs its own in-body anchor**: URL, exact version/status (proposed vs enacted,
EH/RS vs enrolled), locator (figure/section/table row), short verbatim quote. A chat-side evidence table does
not make the page traceable. Link a secondary page to the section carrying the full set instead of duplicating
it; do not touch frontmatter or mint a source page to satisfy this.
- **Name the object a date or limit attaches to.** A period written for one paragraph does not expire the whole
section or a sibling paragraph added elsewhere in it. Quote the paragraph that carries the date, and refuse both
inferences: "everything here sunsets" and "no end date in this paragraph = permanent".
- **Keep bill-section and code-subsection numbering apart.** "Bill §N(c) repeals X" and "proposed §Code(c)
defines Y" are different objects; fusing them reads as a different repeal. State the full amendment action — a
redesignation plus insertion is two steps, and omitting the renumbering breaks every existing cross-reference to
the old subsection. Label such references by legal version instead of merging them.
- **A keyword zero is a search result, not a legal finding.** Search the abbreviation and the full phrase, the
section number and the subject matter; disclose a counterexample you found; scope the statement to the versions
and date you read. "Not in the version I read" is the claim; "not in the law" is not yours to make.
- **Access failures belong to the run.** "This client, this date, this path returned 403", never "the source is
unavailable" or "the channel is closed"; keep index/link state, access gate, alternative public copies, and
whether the document was ever filed as four separate questions.

## Pitfalls

- Reporting a candidate as landed because `git apply --check` passed, before reading the target files back.
- Landing a payload whose bytes no longer match your own candidate — the reviewer's copy drifted or was retyped.
- Counting patch lines with a regex, then defending the number after the reviewer publishes the real one.
- Reading a whole-tree write-surface violation list as your own breach when the paths are the reviewer's records.
- `git add -A` (or an unqualified `commit -a`) in a shared checkout, sweeping another writer's unpublished work
  into your commit and its publication.
- Dropping a lint/report artifact into another role's report directory just to read it.
- Declaring "no active leases" without quoting the emptied `status` output.

## Supporting files

- `references/landing-commands.md` — the ordered command recipe for gates, lease, apply, checks, path-limited
  commit, ref comparison, and lease release.
