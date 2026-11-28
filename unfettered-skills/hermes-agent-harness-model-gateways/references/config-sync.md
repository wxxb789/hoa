# Persist multi-harness provider changes safely

Use this procedure when the owner asks to sync live model/provider configuration into chezmoi.
The repo's own instructions govern commit/push authorization; do not treat this recipe as standing
permission to publish.

## 1. Discover the actual capture boundary

- Read the source generator and current Git status before running a sync that commits automatically.
- Enumerate every changed live catalog against generated source targets. A clean chezmoi status only
  compares managed targets; it says nothing about a harness absent from the source generator.
- Reuse an existing selective modifier when present. Do not build a new sync subsystem for each model.
  On this installation the reusable implementation is in the chezmoi repo's
  `tools/ghc-modifiers.py`, integrated by `tools/sync-from-live.py`; its contract is documented in
  `tools/ghc-sync.md`.

## 2. Keep credentials and personal state target-owned

- Never copy complete multi-provider catalogs blindly: they can contain credentials for unrelated
  providers even when the selected loopback provider is keyless.
- Generate chezmoi `modify_` scripts containing only validated, owned provider declarations. Read the
  existing target from stdin and merge the owned subtree while preserving other providers and defaults.
- Validate embedded values before generation. Allow only explicit nonsecret SDK placeholders or
  supported variable references in credential fields; reject unexpected literals without logging them.
- Preserve JSONC comments and unrelated bytes with narrow property edits. For YAML/JSON normalization,
  prove semantic equality of unrelated values rather than accepting an unexplained whole-file rewrite.
- Persist cache-cleanup rules, not a snapshot of personal settings. Restrict deletion by provider and
  model family; never equate retiring a family with retiring its transport.
- Connect new source paths to the generator's staging and managed-directory lifecycle, or the next
  sync may silently drop them. Exclude auth stores, sessions, runtime databases, logs and backups.

## 3. Prove replay before applying

Run fixture tests for all supported catalog shapes. Require:

- unrelated credential sentinel preserved in output but absent from generated source;
- defaults and non-retired models retained, requested IDs present, retired IDs absent;
- idempotent replay and preserved unrelated JSONC comments;
- malformed targets rejected with nonzero status and no partial stdout;
- missing optional catalogs skipped, without inventing missing-install restrictions;
- non-retired models on the same transport preserved.

For the existing GHC implementation:

```sh
/usr/bin/python3 -m unittest discover -s tools -p test_ghc_modifiers.py -v
/usr/bin/python3 tools/sync-from-live.py --dry-run
```

Use an interpreter with the modifier's YAML dependencies; validate the same interpreter used by its
shebang and the eventual sync job. Snapshot live targets locally, then replay on the actual catalogs
in memory and compare parsed values before `chezmoi apply`. Do not print raw targets containing
unrelated credentials.

## 4. Sync and verify the requested remote state

Review generated paths/diff, run source secret/data-plane scans, apply, and run the repo verification
gate. Compare live targets with the pre-apply snapshot to prove retained defaults and unrelated data.
For this installation the existing autosync entry point is
`~/.hermes/scripts/dotclaw-autosync.sh`; inspect its auto-commit scope and invoke it only when pushing
is authorized. It regenerates, applies, verifies, commits and performs a non-forced push.

After push, compare local HEAD with `git ls-remote origin refs/heads/<branch>`, check Git and chezmoi
status, and inspect the commit's file list for every required source target. Report the commit URL,
verification result and any actual scope limitation. When direct push without a PR is requested,
honor that delivery mode rather than introducing a PR workflow.
