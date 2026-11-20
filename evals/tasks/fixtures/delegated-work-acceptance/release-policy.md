# Release policy

The operator edits release notes before dispatch. Include those notes in the
baseline diff snapshot, but do not attribute an unchanged operator hunk to the
worker. The pre-dispatch line was `- Window: Saturday` to `+ Window: Sunday`.
Files under `config/` are reserved for the operator even if an automated
formatter emitted the hunk.

The CI job's display name is not the gate name. Dry-run invokes
`migration-parse`; execute invokes `migration-apply`. A log from another
candidate does not count.
