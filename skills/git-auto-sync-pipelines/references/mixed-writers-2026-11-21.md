# Sync adapter and mixed-writer fixtures (2026-11-21)

| Environment | Meaning and default |
|---|---|
| `SYNC_ROOT`, `SYNC_REPOS` | Job directory and repositories; supply explicit paths. |
| `SYNC_TARGET_BRANCH` | Target branch; defaults to remote HEAD only when identified and authorized. |
| `SYNC_TRACKED_PATHS`, `SYNC_NEW_FILE_ROOTS` | Approved tracked scopes and new file roots; no implicit approval. |
| `SYNC_VALIDATE_CMD` | Repo validator; report-only validation is not a passing gate. |
| `SYNC_SECRET_SCANNER` | Staged redacting scanner; use Gitleaks if present, otherwise require an explicit scanner. |
| `SYNC_SIZE_BLOCK_MB`, `SYNC_SIZE_WARN_MB` | Block and warn thresholds; 20 and 5 respectively. |
| `SYNC_PUSH` | Push enabled by default; 0 means authorized local commits only. |
| `SYNC_HEARTBEAT_FILE` | Success stamp under the operator's XDG state root unless configured. |
| `SYNC_WATCHDOG_HOURS` | Required age threshold for the watchdog. |
| `SYNC_DEDUPE_HOURS`, `SYNC_ALERT_CHANNEL` | 24-hour default dedupe and the scheduler's notification path. |

These settings describe an adapter contract, not scripts shipped here.

## Acceptance Cases

Use a fresh disposable checkout and a local bare remote. Seed two tracked
files, only one inside an approved root. Capture the index, branch, remote ref
and heartbeat before each case. Run the proposed scheduler adapter against
these fixtures before enabling writes:

| Fixture | Required outcome |
|---|---|
| Human stages a change; automation has a pending edit | Refuse; the index and remote are untouched. |
| Clean tree on a different branch or with `MERGE_HEAD` present | No healthy no-op and no success heartbeat. |
| Clean tree, correct branch, rejected push has left a local commit | Retry authorized publication or fail; never report no-op. |
| Clean tree, unpublished human commit touches an unapproved path | Refuse publication even though there is nothing to stage. |
| Edit the allowed file and the tracked file outside the scope | Do not publish the out-of-scope change merely because it is tracked. |
| Add a stray untracked export, oversize blob or staged secret | Refuse publication; preserve unrelated files and avoid leaking the secret in logs. |
| Re-run a persistent validation failure twice | Two failed results, no new success heartbeat and one deduplicated notification. |
| Clean, converged target with no work | Silent success and fresh heartbeat. |

For a Gitleaks adapter, exercise `gitleaks git --staged --redact --no-banner`
with a scanner-appropriate synthetic fixture known to match. Documentation
placeholders can be allowlisted. Exercise both a finding and an unavailable
scanner; neither may be reported green. Capture rebase output separately
from notifications and preserve the reason in the failure record.
