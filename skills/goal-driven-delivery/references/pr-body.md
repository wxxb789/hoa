# PR body for a goal increment

Copy this shape; replace every `<…>`. The previous goal's merged PR body is the best starting
point — open it with `gh pr view <PR> --json body` and reuse its structure.

```markdown
## Goal <NNNN> — <goal title as written in the goal file>

Closes the [<NNNN> goal](docs/goals/archive/<NNNN>-<slug>.md) (moved to `docs/goals/archive/` in
this PR).

**Observable pass condition:** <quote the goal file's pass condition; if it has none, write the one
sentence a stranger could check against the built output>

### What landed

- **<subsystem>** — <mechanism in one or two sentences, naming the files and the decision it makes>.
- **<subsystem>** — …
- **Docs** — <which docs changed and the contract sentence they now carry>.

### Not adopted (deliberate)

- **<thing>** — <which later goal or decision owns it>.
- **<thing>** — <why it is out of scope, not a gap>.

### Evidence (final tree)

| Command | Result |
|---|---|
| `<exact gate command>` | exit 0 — <real counts, files/passed/skipped, bytes, digest> |
| `<exact gate command>` | exit 0 — <real counts> |
| `<packaged/smoke command>` | exit 0 — <what it printed> |

"Done when" → evidence:

1. **<clause 1>** — <the command and the assertion that observes it>.
2. **<clause 2>** — <…>

### Residual limits (recorded in the goal file)

- <what the build does not verify, stated plainly>
- <what remains separately approved / unverified by design>
```

Rules:

- Every number in the evidence table must come from a run on the **final** tree, not from the
  implementation report; a later fix round invalidates both counts and the tarball digest.
- "Not adopted" exists so a reviewer stops asking for the neighbour goal's feature. Name the owner
  goal, not a vague "future work".
- Map each "Done when" clause to the gate that observes it. A clause with no gate behind it is the
  honest finding, not something to phrase around.
- No marketing adjectives, no "comprehensive", no changelog bullets without a mechanism.
