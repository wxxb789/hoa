# Stage prompt variables

Prompt text lives in `references/stage-templates/<stage>.md` — **that is the only copy.** `gdd.py`
renders a template with the variables below, refuses to emit a template with an unresolved `${…}`,
archives the rendered prompt under `<task_root>/<date>/<repo>-<goal>/prompts/`, and launches it.

Do not paste prompt bodies into this file, a profile, or a chat message: a second copy is how the
last generation of prompts drifted from the transport it was written for.

## Templates

| Stage | Template | Dispatches an agent | Notes |
|---|---|---|---|
| implement | `implement.md` | yes | full contract + gates + goal-close ritual |
| simplify | `simplify.md` | yes | report only, standalone mode |
| apply | `apply.md` | yes | needs `--findings FILE` (accepted/rejected table) |
| review | `review.md` | yes | report only; start after apply |
| fix | `fix.md` | yes | needs `--findings FILE` |
| verify, gates, pr, babysit, merge | — | no | mechanical; the operator runs them |

## Variables

| Variable | Source |
|---|---|
| `${REPO_PATH}` | `git -C <repo> rev-parse --show-toplevel` |
| `${REPO_NAME}` | basename of the repo path |
| `${GOAL}` | `--goal` (e.g. `0041`) |
| `${GOAL_FILE}` | `--goal-file`, else the profile's contract glob (`GDD_GOAL_GLOB`, default `docs/goals/*<goal>*.md`), else `-` |
| `${BASE_SHA}` | `--base`, default `git merge-base origin/main HEAD` |
| `${HEAD_SHA}` | `--head`, default `git rev-parse HEAD` |
| `${GATES}` | `--gates`, else `$GDD_GATES`, else `-` |
| `${FINDINGS_FILE}` | `--findings` (absolute path) |
| `${DATE}` | local date of dispatch |

## Findings files (apply / fix)

One row per finding, machine-readable enough to survive a re-read:

```text
1 | ACCEPT | src/Foo.cs:42   | duplicated fixture                       | …
2 | SKIP   | tests/Bar.cs:88 | pins contract clause 4; overlap is fine  | reason
```

`ACCEPT`/`FIX` rows must name the file and the change; `SKIP` rows must carry the reason, because a
silently dropped finding reopens in the next review round.

## Add a stage

Add the template file, add the stage to the `gdd.py` allow-list, and add one row to the table above.
Nothing else should need to change — if it does, the protocol is leaking into the tooling.
