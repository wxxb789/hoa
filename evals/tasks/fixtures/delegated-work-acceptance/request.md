# Import batch M42

Worker writes are limited to:

- `migrations/041_queue.sql`
- `migrations/042_owner.sql`
- `migrations/043_receipt.sql`

Convert each migration to use the local slot table. A migration counts only if
its content changes; a rename from the historical archive does not implement a
conversion. A live apply against the fixture, logged by the operator on the
candidate, is required. See `release-policy.md` for ownership and gate labels.
