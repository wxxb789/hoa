# Propagating one key to every harness store

Use when the owner fills or rotates the credential in **one** place and every other harness must end up
with the same value — without the value ever entering the transcript, and without a second rotation
being needed because one store was missed.

## 1. Source of truth and the no-read rule

The owner edits one canonical store (on this install: the root `~/.hermes/.env`). Do not `cat` it, do
not `read_file` it, do not echo it. A script reads it in-process, compares fingerprints, and writes the
other stores. Anything the agent prints must be `len=<n> sha256=<12 hex>`, never the value.

```python
key = read_dotenv(Path.home() / ".hermes/.env", VAR)
fp  = lambda v: f"len={len(v)} sha256={hashlib.sha256(v.encode()).hexdigest()[:12]}"
```

Validate the shape before writing anything: a LiteLLM virtual key must start with `sk-`, a wrong-shaped
value written to eleven stores is eleven silent 401s.

## 2. Write a propagation script, not a checklist

- **Enumerate stores at run time** — `Path.home().glob('.hermes/profiles/*/.env')` — because profiles
  are added and removed between rotations. A hardcoded profile list silently skips the new profile and
  reports a deleted one as missing.
- **Back up first**, then write, then read back. The backups are the only copy of the retired value.
- **Upsert per store type, preserving every other byte** (comments, other providers, other env vars):

| Store | Writer |
|---|---|
| `.env` (root, each profile, `~/.omp/agent/.env`, `~/.config/tencent/keys.env`) | replace the `NAME=` line in place, append if absent, `chmod 600` |
| `~/.pi/agent/auth.json`, `~/.omo/agent/auth.json` | `data[provider] = {"type": "api_key", "key": <value>}` |
| `~/.config/opencode/service.json` | `data["env"][NAME] = <value>` |
| `~/.dsh/.credentials.yaml` | text surgery on the `refs:` line — a YAML round-trip drops the comments that document the route |

- **Read back every store and compare to the source**, printing one `OK`/`DRIFT` line per store plus a
  single `RESULT:` line. This is the actual deliverable: “11 stores, one distinct fingerprint”.
- Keep the script idempotent so a second run after a partial failure converges instead of duplicating
  lines.

## 3. Prove it with a request, per harness

A config read proves nothing (parent skill §4). One real generation per runnable harness; dormant
configs are reported as parsed-only, not as verified.

On a 401, **compare the value the harness actually sent against the store fingerprint before touching
config** — gateway errors often echo a partially masked copy (`Received=PAST****HERE`), which names the
placeholder and tells you the store was never read.

## 4. Install a drift watchdog

The stores are copies; rotation is a human action; copies rot. A daily `no_agent` cron job is the cheap
fix, with this contract:

- **Silent when healthy** — empty stdout sends nothing.
- **One alert per finding set**, keyed by a hash of the drifting store names; re-notify after ~7 days,
  not every run, or the channel trains the owner to ignore it.
- **One recovery line** when the drift clears, then reset the state file.
- **Always exit 0** — a non-zero exit adds a cron failure incident on top of the message you already
  printed (skill `hermes-cron`).
- The state file stores only the hash and timestamps, never the value.

On this install the runtime copies are `~/.hermes/scripts/key-drift-check.py` (cron, daily) and the
writer in the task directory that produced it; copy both to a rebuilt host rather than retyping them.

## Pitfalls

1. **A stale export in the shell outranks the store.** After a propagation run, a shell that exported
   the old/placeholder value makes the harness send *that*, and the 401 names the old value even though
   the store is correct. `unset VAR` and retry; a fresh login shell re-sources the keys file. Diagnose by
   fingerprinting `os.environ` next to the store, not by re-editing config.
2. **The profile set moves under you.** A run that started with five profiles and finds six (or five
   minus one) is normal on this machine; glob at run time and report what you found.
3. **Backups contain live secrets.** Keep the backup tree `600`, never commit it, and never print its
   contents while “verifying” the rollback.
4. **Do not delete the old key from every store without a backup** — a rotation that turns out wrong is
   only recoverable from the copy you kept.
5. **Report partial success honestly.** If one store refuses the write, say which one and what the
   read-back showed; “all harnesses updated” on nine of eleven is the failure mode this whole procedure
   exists to prevent.
