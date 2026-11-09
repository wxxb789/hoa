# Tutorial / Docs

For how-tos, setup guides, runbooks, API docs, READMEs.

## Structure
- **Outcome (1 line):** what the reader will have/be able to do when done.
- **Prerequisites:** versions, deps, accounts, OS. Be exact ("Node ≥ 20", "Python 3.11").
- **Numbered steps:** one action per step + its expected result. Sequential = numbered list.
- **Verification:** how to confirm it worked (a command + the output to expect).
- **Troubleshooting:** common errors → cause → fix, as a table or list.
- **Next steps:** where to go from here.

## Tone
- Imperative, second person: "Run…", "你会看到…". Zero ambiguity.
- Exact commands, exact paths, exact expected output. No "configure as appropriate".
- Call out OS/version/shell differences explicitly when they matter.

## Formatting
- Numbered lists for sequences; code blocks for **every** command (copy-pasteable).
- Show both the command AND its output, so readers can compare.
- ⚠️ callouts for gotchas/destructive steps; ✅ for "you should now see…".
- One command per code block when the reader runs them one at a time.

## Don'ts
- No "simply just" / "easy" — it's never simple for the stuck reader.
- No skipped steps, no implied knowledge ("obviously you'd…").
- No untested commands. If you can't verify, mark `[UNVERIFIED]` and say so.
- Don't bury the prerequisite that makes everything else fail.

## AI-smell to watch
- Over-smooth prose padding between steps. Tutorials want terse, scannable, exact — cut filler.
- Fake confidence on edge cases you didn't test — flag uncertainty instead.

## Quick checklist
- [ ] Outcome + prerequisites stated first
- [ ] Each step = one action + expected result
- [ ] Verification command + expected output included
- [ ] Troubleshooting for the obvious failure modes
- [ ] Commands are real/tested (or marked UNVERIFIED)
