# Hermes updater: 2de9f51

Source: [updating.md](https://github.com/NousResearch/hermes-agent/blob/2de9f51b8008a7d49a49221c184f2f11cbfc4af1/website/docs/getting-started/updating.md).
Recheck the installed help and matching docs before using flags or state paths.

| Install | Owning update path |
|---|---|
| Managed source | `hermes update`; use the configured source branch or offered stable tag. See `--check` and `--plan` for preflight. |
| Packaged desktop | Use its desktop updater, App Installer or Microsoft Store as appropriate. |
| Docker / Nix / Termux APT | Pull and recreate preserving data mounts, rebuild the selected profile, or use the package manager respectively. Do not update the image's checkout in place. |

- `updates.pre_update_backup` supports `quick`, `full` and `off`. Quick
  snapshots protect selected state, not code. Inspect the receipt for skips
  or failed snapshots; the updater may continue. Retain the prior commit,
  package or image separately.
- Linux/macOS source updates pause gateways before checkout mutation and
  restart after dependencies and service definitions are ready. Windows
  handles its own pause/restart and restarts after builds. A no-op need not
  stop anything, but can retry an owed restart. Manual backends may require
  separate action; check the fleet and reminders instead of stopping all
  processes up front.
- For source updates, read the matching run under `logs/update_receipts/`
  in the effective Hermes home. Compare pre-update inventory, target and
  final fleet matrix; `latest.json` can belong to a newer run. An exit 0
  with build or gateway follow-up is not full recovery. Verify live version
  and served profiles using the control channel; older releases may use
  gateway state files. A clean process scan is not proof a missing service
  restarted.
- If the launcher will not start, distinguish mixed pre/post-update code
  from an unfinished PM publish, a lock held by a live sync, and digest
  drift in a realized toolchain. Inspect `hermes pm status` or the supported
  diagnostic entry point. Wait for a live lock owner, use the installed
  `pm install` path for unapplied dependency sync, and `pm repair` for
  damaged recorded artifacts only after confirming the symptom and version.
  Read back the executable and restarted processes; a checkout-local venv
  may not be the runtime.
- For a stale scheduler, inspect its invocation, source dirt/branch guards,
  actual remote and error. Retry transient rate limits through the owning
  updater with bounded backoff. Do not invent a retry count or assume
  systemd. Store local tweaks outside managed source; replay only explicitly
  inventoried hooks supported by the installation. Record a skipped hook
  rather than silently treating it as success.
