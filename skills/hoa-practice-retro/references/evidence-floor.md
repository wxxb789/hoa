# Evidence floor for practice findings

A practice finding describes the owner's behaviour, so it needs more than one sighting.

## Admission

- At least **two independent origins** per finding. Independence means different underlying events:
  a transcript, its auto-summary, a synced copy, a session branch, or two excerpts of one session count
  once. For bundle records, independence is `origin_fingerprint` inequality.
- Cite history records as `bundle:<origin_fingerprint>#<file>?line=N` (`offset=`, `index=`,
  `table=T&rowid=N` for other locator kinds). Cite other sources by stable id: `nmem:<id>`,
  `git:<repo>@<sha>`, a PR URL, `ledger:<subject>/<date>#<finding-id>`.
- Run `uv run scripts/audit.py --bundle <bundle> --run <run>` after the find files exist and before
  the verifiers. It writes `verify-citations.json`, refuting any finding with an unresolvable bundle
  citation or fewer than two distinct origins. It counts distinct non-bundle entries as origins
  without judging them; the adversarial verifier decides whether two commits of one PR, or two notes
  about one event, are really one origin.
- Seek counter-evidence before keeping a finding. Zero findings is a complete retro.

## Labels inside a finding's claim

- **Observation**: directly visible, bounded fact.
- **Inference**: a cautious reading of observations; say why the counter-evidence did not defeat it.
- **Speculation**: a question for On the Horizon. Never evidence, never a finding.

No clinical, personality or motive claims; phrase behaviour so the owner can verify or falsify it.

## Coverage

Every conclusion names its window and available sources. A source whose manifest status is not
`available` is a coverage gap, never negative evidence: "not found" does not show non-use.
