# Landing a gated write to an instruction file in ONE approval

Depth for rule 3: how to make a protected write (identity file, operating protocol, team doc) land with one
owner click, and how to prove the bytes before spending that click.

## What the gate is

- Protected agent-instruction files can be refused: the write raises an interactive approval prompt, and a
  prompt that times out is **not** consent. Do not retry that write, and do not reach the same file through
  a shell, script, editor or alternate tool — report the blocked state and re-issue only on the owner's word.
- The prompt is granted **per call**: one multi-hunk / multi-file patch call costs one click. N separate
  calls cost N clicks and leave the file half-updated whenever only some are answered.
- While blocked, the gate returns *before* any apply, so a blocked attempt must leave the file
  byte-identical and the tree clean. Prove it instead of assuming it: `sha256sum <file>` against the
  pre-attempt hash, plus `git status --short` in the worktree, and put that in the report.
- Two consent routes — offer both as one choice when the owner asks for a re-send:
  1. They answer the card (the runtime's own escape hatch is a `/approve` reply while it is pending).
  2. They authorise in-thread that the repository's own lane lands the agreed content (`git apply` + its own
     commit) — the content is already fixed, so the card is not the only path.
- A repeated timeout is a finding, not noise: record mechanism + what did and did not land in the task's
  decision ledger so the next session does not re-derive the gate.

## Collapse every pending change into one call

- Gather all outstanding edits to that file — including a hunk another lane is holding for the same file —
  into a single patch; they are approved together or not at all.
- One multiple-hunk patch through the write tool's patch mode is the shape: `*** Begin Patch`,
  `*** Update File: <absolute path>`, hunks, `*** End Patch`.
- The tool schema still demands `old_string`/`new_string` on that path; they are ignored there. Pass a
  harmless line that exists in the target for both rather than fighting the schema.

## Multi-hunk syntax traps (each one bounces the whole patch)

- Hunk splitting: `@@ @@` (empty) is accepted. Do **not** rely on a text hint (`@@ <heading> @@`) to anchor
  an insertion — the hint is searched literally and fails as `hint '<text>' not found`.
- Context lines carry one leading marker character, then the file's own indentation. For a line whose content
  is indented by two spaces (markdown continuation lines), write **three** spaces. One missing space turns
  the hunk into `not found`.
- Because of that, prefer starting and ending hunks on lines whose content begins with a non-space character
  (`-`, `#`, or a `+`/`-` changed line): markers on those are unambiguous and need no space counting.
- An **addition-only** hunk is rejected as ambiguous — `addition-only hunk context hint ' ' is ambiguous (N
  occurrences)`. Convert the insertion into a replacement hunk: remove the line the new block precedes and
  re-emit it after the added lines, which anchors the block and keeps the order explicit.
- The failure report names the failing hunk and its neighbourhood. Use it to fix the context; do not widen
  the patch or fall back to editing the file another way.

## Pre-validate the exact text, then spend the card

1. Build a byte-identical scratch copy of the target (`cp -p <file> <scratch>/<name>.try`) and a
   deterministic reference for the *intended* end state — e.g. copy the pre-state, apply the canonical diff
   (`patch -p1 < intended.patch`), then apply any separately agreed block with the same tooling.
2. Run the SAME patch text against the scratch copy, changing only the file path. An unprotected path
   validates with no prompt, so every failure is free — iterate until it applies.
3. Compare bytes and `sha256sum` of the scratch result with the reference. Only on an exact match is the
   patch text proven; then issue the real call, re-copying the text verbatim.
4. Put the proof in the card request: "content verified byte-identical — <sha256>, <bytes>, carrying <what
   changed>". The owner then approves known bytes instead of a leap.
5. Re-validate before every re-issue, and fold any newly accumulated change into the same patch — a
   re-issued patch that no longer matches the agreed content is what causes a wrong approval.

## Issuing it

- Time the card against the owner's presence: the window is time-boxed from the moment of the call, so tell
  them the card is coming and then make the write the first action of that turn — never after minutes of
  preparation.
- On a timeout: hash the target, confirm it is untouched, and hand the owner the two consent routes as one
  numbered choice. Do not retry the same call in the hope of a different result.
