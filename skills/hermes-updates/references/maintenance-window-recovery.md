# Maintenance-window recovery for live Hermes state

Use this recipe when a live Hermes install reports a deleted `state.db`, WAL, or SHM generation. It
is deliberately fail-closed: preserving an uncertain generation is safer than guessing which database
is newer.

## Sequence

1. Start from an external shell, not a gateway-handled turn or the interactive owner process whose
   descriptors are being inspected.
2. Record the gateway PID/cgroup, systemd `HERMES_HOME`, served profiles, update-timer/service state,
   and all `/proc/*/fd` links containing `state.db`.
3. Record each candidate descriptor's PID, fd number, device/inode, size, and deleted marker. Re-scan
   before capture; a changed inode or size is a concurrent-writer signal.
4. Stop the unattended update timer/service first, then runtime-mask both units; confirm no
   auto-update PID/cgroup, queued activation, or waiting timer remains. Keep the original
   enabled/active/masked/Persistent state for restoration.
5. Stop the gateway and any other process proven to hold a served DB. Wait for the cgroup/PIDs to
   exit, then create a post-freeze filesystem-plus-`/proc` inventory; expected descriptor
   disappearance is allowed only for approved stopped writers. Do not kill unrelated processes.
6. If an approved owner/CLI PID still holds the deleted generation, keep that PID alive but explicitly
   idle while an external shell copies its unique main/WAL/SHM descriptors into an owner-only scratch
   directory. Capture the complete triple twice; require stable `fstat` identity, byte-identical
   hashes, and read-only SQLite validation before the PID exits.
7. Let the owner process exit only after capture and validation succeed. Re-scan descriptors and
   require all deleted DB inodes to be gone; any unresolved descriptor or inventory drift is a
   fail-closed abort.
8. For every post-freeze served DB, create both a physical main/WAL/SHM snapshot and a SQLite
   `Connection.backup()` copy. Close every backup/validation connection, then re-scan descriptors
   before checkpoint or restore.
9. Compare visible and deleted generations using a deterministic schema/table/row manifest that
   preserves SQLite types, NULL/BLOB bytes, composite keys, and no-rowid ordering. Counts and max
   timestamps are supporting evidence only. The automatic path accepts only exact logical equality;
   if content differs, preserve both and abort rather than selecting a generation by intuition.
10. With every writer/reader stopped, run `pragma wal_checkpoint(TRUNCATE)` on the verified visible
    generation. Record the three return values, reopen it, and require the post-checkpoint manifest to
    equal the pre-checkpoint baseline. Let SQLite manage sidecars; do not remove them with `rm`.
11. Keep the gateway inactive on any failure. Restore every modified DB from its physical snapshot and
    validate against its logical backup; if the gateway has already accepted new traffic and its DB is
    healthy, preserve that post-start DB and never restore an older pre-start copy over it.
12. Start the gateway only after DB/config verification. Confirm a fresh PID, systemd invocation
    identity, session-store availability, platform reconnection, and absence of new SQLite fatal
    errors; create a post-start safety snapshot before accepting traffic.
13. Perform all profile/provider/model/context probes, health checks, cockpit checks, and
    archive/quarantine verification while the update timer remains frozen. Treat permanent archive
    deletion and timer restoration as separate owner-confirmed gates; Persistent/missed-run
    uncertainty keeps the timer frozen.

## Evidence that must not leak content

Store only paths, metadata, hashes, counts, schema names, timestamps, return codes, and status. Do not
print message bodies, tokens, auth files, cookies, or archive contents. Keep temporary copies and
archives owner-only (`umask 077`).

## Health-check rules

- Open SQLite using a read-only URI (`file:<path>?mode=ro`, `uri=True`) for integrity checks.
- Invoke the install's cockpit/health check with
  `subprocess.run(..., capture_output=True, text=False)` and check return code, stdout bytes, and
  stderr bytes separately; do not use `cockpit | wc -c` because a pipeline can hide cockpit failure.
- Use a gateway invocation ID or journal cursor plus the gateway active timestamp as the log freshness
  baseline; fixed tail windows produce historical false positives and can miss rotation boundaries.
- Treat a healthy cockpit as exit 0 with zero stdout and zero stderr. Keep live error paths visible;
  never silence an error by matching its text alone.

## Rollback contract

Back up root/profile config, scripts, every served DB, and any archive targeted for deletion before
mutation. A rollback means: freeze timer/service, stop all writers/readers, restore all modified
files/DBs—not only the last failed item—verify integrity/counts/manifests, and keep the gateway
stopped until validation passes. If post-start traffic exists and the post-start DB is healthy, roll
back config/scripts/archive only; never overwrite new messages with a pre-start DB snapshot.
