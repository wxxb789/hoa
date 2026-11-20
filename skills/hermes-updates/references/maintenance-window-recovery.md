# Recover an interrupted state migration

Use with an approved maintenance window. Keep update and restart mechanisms
frozen through verification; capture and later restore their original state.
Use the install's supervisor rather than assuming a particular OS or service
manager.

1. From outside the affected runtime, identify served profile stores, open
   readers/writers and any missing or deleted SQLite DB/WAL/SHM generation.
   Record process, file identity, size and timestamps. Stop approved writers
   only. If a necessary deleted generation has its last live descriptor in
   an approved owner process, hold that process idle until an authorized
   recovery captures and validates the whole generation.
2. Preserve physical DB/WAL/SHM snapshots and a logical SQLite backup. Keep
   copies private and validate read-only. For a live descriptor capture,
   require two identical captures and stable descriptor identities. If
   generations differ by a type-preserving schema/row comparison or ownership
   is uncertain, preserve both and stop. Row counts alone are insufficient.
3. Checkpoint only with writers and readers stopped. Let SQLite manage the
   sidecars, record the checkpoint result, and verify logical state is
   unchanged. On failure keep service stopped and restore all touched state,
   not just the last failed file.
4. Verify config and data before start. Check fresh service identity, store
   availability, reconnects and new errors using this invocation's log
   boundary. Use the supported health adapter; inspect exit status and
   output separately. Record a post-start safety snapshot.
5. If new traffic has arrived in a healthy store, do not overwrite it with
   a pre-start copy. Confirm permanent cleanup and re-enabling unattended
   update separately, accounting for any missed-run catch-up. Report only
   file metadata, counts and statuses, not message content or credentials.
