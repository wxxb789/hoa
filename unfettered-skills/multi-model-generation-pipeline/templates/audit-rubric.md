# Audit rubric template (copy and adapt per task)

Give this to the auditor verbatim, replacing only the bracketed material. Each item must be answerable
yes/no per candidate; nothing left as "per the contract".

```
You are the auditor for this deliverable. Three candidates follow, all written to the same contract.
Do not write or revise body text — produce findings only.

For EACH candidate, answer these in order, one line each, with the offending sentence quoted:

A. Provenance — is every factual sentence traceable to the supplied material? Name any sentence that
   adds an explanation, an actor, or a cause the material never states.
B. Sources/liveness — are there at least [N] external references, does each anchor text say what the
   reader will see, and is any URL invented?
C. Opening — does the first paragraph start from the concrete thing (an event, a quoted line, a number)?
   Flag any opening that lists what the reader will be able to do afterwards.
D. Stated uncertainty — is exactly one unverified assumption named, and is its blast radius stated?
E. Hard quotas — [sentence length] / [per-paragraph limits] / [number-of-precise-figures cap] /
   [section count]. Count them, do not estimate.

Then output exactly:

SELECTED: <TAG>
WHY: one sentence, naming which hard item it won on
REJECTED: one sentence per candidate, naming which hard item killed it
UNSOURCED:
  <TAG>: <verbatim sentences with no material behind them, or "none">
  <TAG>: ...
  <TAG>: ...
```

## Grading rules for the harness around it

- A candidate whose `UNSOURCED` line is not `none` **cannot be SELECTED**. If all three are non-empty,
  delete those sentences from each and re-run the audit rather than picking the least-bad one.
- Parse `SELECTED:` mechanically. Unparseable ⇒ exit non-zero. Never fall back to the first candidate.
- The auditor's `E` answers are advisory. Recount quotas with your own script and publish those numbers
  beside the verdict; where they disagree, the script's count is the one that ships.
- Link checks: `curl -sL -o /dev/null -w '%{http_code}' --max-time 25 <url>`, retry once on non-200. A 200
  on a generic index page counts as reachable and as a weak citation — call that out separately.
