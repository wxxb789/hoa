---
name: binder-inspect
description: Inspect an indexed binder or refresh its index on request.
---

# Binder inspect

B-01. Inspect mode is read-only. It creates no file and changes no file in
either the binder or the caller's workspace. Use refresh only when requested.

B-08. Resolve language from the binder header, falling back to the caller's
locale only for binders that have no declared language.

B-11. During inspect, do not update a binder's persisted index.

B-14. Compute the summary. If the caller supplied a destination, deliver
the summary using the named Output Sink from the consumer contract, and
return the sink's handle. Otherwise return the summary inline.

B-18. During refresh, update the persisted index and report its row count.

B-21. Return summary keys in the order: count, language, title.
