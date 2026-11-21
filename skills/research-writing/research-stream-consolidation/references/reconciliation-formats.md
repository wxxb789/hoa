# Reconciliation formats (sidecar memo)

Use these in the sidecar evolution memo, never inside the deliverable.

## Conflict disposition table

| Point | Streams | Disposition |
|---|---|---|
| <program / claim> | A: <wording> / B: <wording> | <which wording wins + why; or "keep both, labeled"> |

Rules: a status claim resolves to the *lower* tier unless evidence supports the higher one.
"Both streams agree" strengthens a judgment; it never upgrades a fact's tier.

## Provenance map

| New ref id | Source stream | Source id (claim / ref) |
|---|---|---|
| <n> | <stream A or B> | <claim id or ref number> |

Keep it compact (ranges are fine) — it exists so a reader can trace every merged reference
back to the stream that produced it.

## Not-included log

| Item | Why not included | Where it lives |
|---|---|---|
| <claim / figure> | rejected by both streams / no display ref yet / quarantined | <path> |

Any item cut for budget or blocked by missing provenance gets a row here, so a later pass can
revisit it without re-deriving the decision.
