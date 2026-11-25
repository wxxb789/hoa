# Phase 5 — commit, gates, PR

1. **Run `gdd.py commit` with explicit publication authority.** Probe the branch, push target,
   and open PR as described below before invoking it.

   ```text
   uv run scripts/gdd.py commit --repo <path> --goal <id> -m "<subject>" --result <result.json> --gate "<command>" --json
   ```

   Repeat `--result` for multiple authoring results, or omit it when everything is already
   committed. Use `-F <file>` to read the subject from a UTF-8 file. Repeat `--gate` in execution
   order, or configure [`GDD_GATES`](../../SKILL.md#configuration). Use `--remote` to name an approved
   remote other than `origin`. For intermediate stage commits, `--no-push` skips gates and push
   but keeps the seal, exact-commit check and leftover inventory.

   The command owns the checks and the push. Use its result and ledger row to reconcile failures:

   | Exit | Codes | Why the command stops |
   |---|---|---|
   | 1 | `SCOPE_DRIFT` | `verify --commit` checks the shipping commit's path set, Git modes, OIDs and paths touched transiently in its history. Inspect the paths and re-review, or record the operator's explicit acceptance in the PR body before proceeding. |
   | 2 | Usage, unexpected Git or scope errors | Fix the named input or command before retrying. |
   | 3 | `ACTIVE_RUN`, `FETCH_FAILED`, `DETACHED_HEAD`, `BEHIND_MAIN` | No concurrent author and no stale or detached base. Ahead-count alone cannot say whether main moved; the fetched main must equal the merge base. |
   | 3 | `NO_BASELINE`, `BASELINE_MISMATCH`, `OVERLAP` | Ancestry does not tell whether a rebase changed the approved baseline. Preserve or resolve original dirt, snapshot the new approved base **before** replaying, then repeat review and gates. Never snapshot the shipping tip. For overlap the operator must decide who owns each path before passing `--accept-overlap`. |
   | 3 | `UNEXPLAINED_CHANGE`, `PHANTOM_CHANGE`, `INDEX_MISMATCH`, `SEAL_FAILED` | Per-path purposes tie pending output to its authoring results. Only pending paths are staged; `seal --index` binds the whole shipping increment, including earlier stage commits and accepted delegate unit commits. Already committed work is not committed again. |
   | 3 | `LEFTOVERS`, `BASELINE_DIRT` | Git objects cannot account for local leftovers. Only `--no-push` permits unchanged baseline dirt. Publication gates require a clean checkout before and after they run; honor any additional profile requirements. |
   | 3 | `NO_GATES`, `HEAD_MOVED` | Resolve gates before staging or committing. Never push without gates on the verified commit, or if HEAD moved while they ran. |
   | 4 | `GATE_FAILED` | Phase 2 checked a working tree; the gates here must succeed on the shipping candidate before it is pushed. |
   | 5 | `PUSH_FAILED`, `LEDGER_FAILED` | The push names the exact verified OID, never a moving ref or a force update. Check `oid` and `pushed` before retrying, especially when a push succeeded but the ledger append failed. |

   Keep local scope and leftover checks here, not in `pr-merge-check.py`, which only judges the
   remote PR. A push does not freeze the version claim: if a sibling PR merges, fetch again and
   re-run the profile's merge-time version gate before asking for a merge (in `hoa`:
   `uv run --no-project --with-requirements scripts/requirements.txt python scripts/version.py check-revisions`).
   Skip this only when the profile declares no such gate.
2. **Check every number on the final tree:** every count, duration or table value in the PR body and
   the evidence record is re-derived on the final tree — never carried over from an earlier stage.
   Record the tree it was measured on (head SHA plus the sealed `scope_sha`).
3. **Optionally draft the body with a PR-writing skill, under gdd's contract.** Where the
   executing runtime's own skill discovery offers `ce-commit-push-pr` — never install it — check
   that the mode composes a body and prints it from the input it is given against the sealed range,
   with no authority to mutate a PR, commit, push or watch. Pass the sealed diff plus gdd's verified
   clause map, evidence and limits, and require the draft to describe exactly that input: a draft
   built from independently discovered input does not qualify. The draft is raw material for the
   body contract below, not a substitute: check it against that shape and the numbers re-derived on
   the final tree, and write the body from the recipe in [`references/pr-body.md`](../pr-body.md)
   directly when the mode is unsupported, the run failed, or the result is mismatched or
   incomplete. **Never run the skill's full shipping path**: it bypasses gdd's pre-push seal check
   and can start a competing CI watcher.
4. The PR body is a contract artifact — shape in [`references/pr-body.md`](../pr-body.md):
   what landed by subsystem, decisions with explicit non-adoptions naming the goal that owns them, one
   evidence table measured on the **final** tree, every "Done when" clause mapped to the command that
   observes it, and a **Known limits** section. Copy the previous goal's merged PR body as the starting
   shape rather than inventing one per goal.
5. **Publish from fresh probes, one direct call per probe.** Re-probe the branch, its target
   repository and any open PR immediately before `gdd.py commit`, and again before opening the PR — an
   earlier snapshot is a hint, not ground truth. Give each probe its own process call: pass the
   program and its arguments directly and read that call's exit status; a semicolon list, a pipe, a
   substitution or a redirect exists only where a POSIX shell parses it, and fails outright under
   Windows PowerShell. Resolve the base repository first and select its remote for the command. Query
   that repository for the unqualified branch name — the `<owner>:<branch>` form silently returns
   `[]` on a fork — and match the head owner and branch name, not the name alone. An exit-0 empty
   list (`[]`) means no open PR for this branch; a probe error is **unknown**, never "no PR" —
   resolve auth or connectivity, or stop rather than open a duplicate. Reuse the exact matching
   open PR; stop on an ambiguous or unknown PR state. After `gdd.py commit` reports a successful
   push, open the PR as the operator's publication act, carrying the composed body.
   If a probe changes the candidate — a rebase or a
   moved head — restart from step 1, discard the gate, seal and number receipts, and redraft the
   body.
6. Treat PR checks as a floor, not a gate — Phase 6 decides.

## Pitfalls this phase answers

- **Never run the full gate chain twice on one commit.** If CI runs the whole chain, give
  `gdd.py commit` only the fast pre-push gate and let CI print the full chain on the pushed commit; if
  CI is only a light cross-OS check and the real gates live in the build harness, pass the full chain
  to `gdd.py commit`, whose gate record is then the only full-chain evidence. One of them is the
  authority.
- **Re-measure the goal record's numbers on the final tree.** Fix rounds applied after the record was
  written leave it certifying an earlier tree — pass counts, bytes and digests all drift — so refresh
  them as the last step before landing.

Probe and drafting methods here adapt Compound Engineering (MIT, Copyright 2025 Every), paraphrased
rather than copied.
