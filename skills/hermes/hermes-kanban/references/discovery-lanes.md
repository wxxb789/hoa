# Parallel discovery lanes (2026-11-21)

Write one shared evidence guide first, then one card and one distinct output
file per lane. Keep workers read-only apart from their own output. Give the
verifier every lane as a parent; it deduplicates by source family, records
contradictions and ranks candidates. The orchestrator owns the final verdict.
For searches ranked by relevance, put the time window into the query and
record publisher, date and URL on each finding.

Read the card and run log if review stalls. When a prior review request names
an existing artifact and a later worker was lost, verify the artifact against
the acceptance criteria; record the verification and complete with a result
only when justified. Unblock only after supplying the missing input. If a
dependency has become unnecessary, unlink parent from child rather than
leaving the child parked. Archive a superseded card rather than repeatedly
blocking work the orchestrator has already taken over.
