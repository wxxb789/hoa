# Decision board

Gather the outcome, verified facts, live/eliminated hypotheses, next probe,
and parked side quests into JSON. After the operator confirms rendering, run
`uv run "$S" map --input -`, with `S` defined in [Commands](commands.md):

```json
{
  "outcome": "Single user-visible result requested",
  "verified_facts": ["fact with file:line or command exit"],
  "hypotheses": [
    {"text": "live guess", "status": "live", "note": "optional note"},
    {"text": "dead guess", "status": "eliminated"}
  ],
  "probe": {"command": "read-only command", "pass": "what a pass proves", "fail": "what a fail proves"},
  "side_quests": [{"title": "parked side quest", "note": "optional note"}]
}
```

The rendered board is self-contained static HTML (inline CSS, no scripts, no
external assets, dark/light via `prefers-color-scheme`). Its three columns
show the target outcome and verified facts; the active fork (live hypotheses,
the single discriminating probe, and the 3-way action summary); and the
eliminated hypotheses and parked side quests. Rendering does not run the
probe or authorize any of the board's actions.
