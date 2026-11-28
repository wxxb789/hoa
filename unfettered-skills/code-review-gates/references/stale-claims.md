# Stale claims — finding and repairing prose that has rotted

Use when a review round returned "a literal contradiction between a comment and the code beside it", when
the deferred follow-up list from an earlier increment gets the *fix it now* decision, or whenever you are
editing a comment/docstring/README whose job is to describe current behaviour. The finding side lives in
the SKILL.md rule on repairing a stale claim; this file is the *repair*.

## 1. Three forms a rotted claim takes — and what settles each

| Form | Looks like | What settles it |
|---|---|---|
| **Absolute negation about behaviour** | "does not write anything into the user's repository", "never touches the network", "no files are created" | Read the input's **default** and the step that **consumes** it: an `inputs.<name>.default` plus the `run:` that passes it is where such a sentence is falsified. The true, smaller claim is usually adjacent — nothing is *deployed / pushed / committed* — and the excluded act belongs to the artifact's consumer, not to the author's code. |
| **Pinned count** | "553 resolved entries", "all 11 dependencies", "the 4 files it reads" | The command that produced the number, run **this session**: `grep -c 'integrity:' pnpm-lock.yaml`, a manifest parse, a `find | wc -l`. Quote the command and both numbers in the report; never re-state a total you did not re-measure. |
| **Lifecycle tense** | "while the package is unpublished", "will be published under a different name", "before release", "once X is installed" | The lifecycle event that already happened (a publication, a rename, a migration). Rewrite as the property, with no state attached — the property that made the sentence worth writing is usually still true. |

A class can also be introduced by the fix itself: an edit that adds an enumeration (released versions, workspaces, supported platforms) has just created a count that expires. Fix by naming the mechanism the reader can derive the list from, not by freezing today's list.

## 2. Locate the claim before editing it

- Re-locate the construct in the tree yourself (`search_files` for a distinctive phrase, then read the
  whole comment block). Line numbers from a lane's report are a claim, and two lanes citing two different
  line pairs for one construct means at most one is right.
- Read the block, not the line: neighbouring sentences in the same paragraph usually carry the *same*
  expired premise (two counts, one negation, one tense in one paragraph is the ordinary shape).
- Confirm what the code actually does at the same time you confirm the claim is false — otherwise the
  replacement sentence is a second unverified claim.

## 3. Sweep for the class, then classify the residue

One pattern per class, over the tree, excluding vendored and built trees:

```bash
cd <worktree> && grep -rniE 'unpublished|not yet published|will be published|no release tag|nothing has been published|does not write|never writes|does not touch' \
  --include=*.ts --include=*.yml --include=*.md --exclude-dir=node_modules --exclude-dir=dist --exclude-dir=.git .
```

- Expect the search word to have a **second meaning inside the same repo**: in a publishing tool,
  `unpublished` is mostly the site pipeline's own link outcome (`publish: false` targets, withheld images)
  and has nothing to do with the package's publication state. Classify every hit as *same defect* or
  *different meaning* and report the classification — an unclassified sweep reads as shallow, and a
  reviewer will re-run it.
- Do not narrow the pattern until it stops finding the second meaning; narrow it only when the hit cannot
  be a claim about state at all. Report the pattern you used, verbatim.
- Also sweep for the *other* form the same premise takes: a version/tag claim usually keeps a **ref form**
  (a pin example, a workflow tag) that is still true and must not be "fixed".

## 4. The fix, then the wrap

- Every edited sentence in a hard-wrapped comment block gets re-wrapped to the block's own column width
  (check `awk 'length > 80' <file>` or just read the diff). A long line left behind by a patch is visible
  noise in a purely prose diff, and it is the first thing a reviewer flags — fix it in the same commit
  rather than in a follow-up round.
- A reflow moves the `--stat` numbers the stage report and any out-of-repo record quote; refresh those
  records yourself (see the SKILL.md rule on prose reflow invalidating recorded counts).
- Keep the diff to prose. A comment fix has no behavioural half: if the sentence is false because the
  *code* is wrong, that is a different increment with its own contract, and merging it here hides the
  defect inside a docs diff.

## 5. What the PR/report body must carry

Per statement: **what was false** (quote the old text) → **what it says now** → **the measurement**, command
and both numbers → the **file:line** you re-located yourself. Then, separately:

- the sweep result (pattern + classification counts), so the reader can see the class was closed and not
  just the raised instances;
- **what was deliberately not changed** — the site-pipeline hits, the code path behind the false claim, the
  true ref-form pins — named so a reviewer does not report them as missed deliverables;
- the constraints the fix had to respect (`action.yml`/manifest scans that forbid a package-name or version
  literal in the touched file, an assertion that counts occurrences, a doc that pins a command's flags):
  state them as constraints held, with the test that holds them, since they are why the natural fix was
  unavailable.

## Pitfalls

- Correcting a count to today's value. It is true for one dependency bump; the form is true until the
  mechanism changes.
- Fixing the raised statements and stopping — the neighbouring sentence in the same paragraph usually
  carries the same expired premise.
- Rewriting a sentence into a new absolute ("never", "only", "always") without the mechanism that makes it
  hold; the replacement then rots in the same way on the next change.
- Editing a *published* record (release notes, a changelog entry, an already-merged report) instead of the
  live file: the record is evidence of what shipped at that moment, not a description of now.
- Treating the sweep's other meaning as a false positive and deleting it — deleting the site's own
  `unpublished` vocabulary is the failure the classification exists to prevent.
