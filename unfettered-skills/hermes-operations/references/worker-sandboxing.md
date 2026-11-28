# Isolating an agent worker (blind verification / untrusted input)

Goal: a worker that cannot read the board, the canonical data, or the producer's identity.

## Run it outside the dispatcher

- The runtime injects `kanban_*` into **every** worker it spawns (env `HERMES_KANBAN_TASK` set) *before* the
  profile toolset is consulted, so `toolsets` / `disabled_toolsets` cannot remove them — and patching the
  runtime to try is off-limits. The only sound way to get a tool-less, board-blind worker is to launch it
  yourself as a one-shot headless process with `HERMES_KANBAN_TASK` unset (e.g. from a gate/reconcile script).
- Own that job's lifecycle in your own state file (pid, wall-clock deadline, retry count) instead of on the
  board, and post a read-only summary to the board only after the verdict lands.
- Also strip **shared memory read/write and session persistence** from that profile: injected long-term
  memory or prior-session context leaks the producer's identity, so discipline alone is theater.

## bwrap on an Ubuntu/Debian host

- Symptom: `bwrap: setting up uid map: Permission denied` (often after `loopback: Failed RTM_NEWADDR`) even
  though `/usr/bin/bwrap` exists and `kernel.unprivileged_userns_clone=1`. Cause: Ubuntu ships
  `kernel.apparmor_restrict_unprivileged_userns=1`, which blocks unprivileged user namespaces for binaries
  that have no AppArmor profile.
- Fix that keeps the global restriction — add a profile scoped to bwrap only, then load it:
  ```
  # /etc/apparmor.d/bwrap
  abi <abi/4.0>,
  include <tunables/global>
  profile bwrap /usr/bin/bwrap flags=(unconfined) {
    userns,
    include if exists <local/bwrap>
  }
  ```
  `sudo apparmor_parser -r /etc/apparmor.d/bwrap`
- Do NOT just set `kernel.apparmor_restrict_unprivileged_userns=0`: that weakens userns hardening for every
  binary on the box.
- This needs `sudo`, so it is an owner-confirmed action: name the file written, the exact command, and the
  rollback (`sudo apparmor_parser -R /etc/apparmor.d/bwrap`).

## Minimal mount surface for a blind verifier

- `--ro-bind` only what the runtime needs (`/usr`, `/bin`, `/lib`, `/lib64`, CA bundle + `/etc/resolv.conf`)
  plus the scrubbed input bundle at `/bundle`; `--bind` a writable output dir at `/out`; `--tmpfs /tmp`;
  `--proc /proc --dev /dev`.
- `--clearenv`, then hand it a fresh `HOME=/tmp` and `HERMES_HOME=/tmp/hermes` holding only the stripped
  profile. Keep `--share-net` only if the worker must reach an LLM API.
- Inside an unprivileged userns `NO_NEW_PRIVS` is set, so an account with passwordless sudo cannot escalate
  inside the sandbox.
- Residual (state it, do not hide it): any process running as the same unix user *outside* the sandbox can
  still invoke `bwrap`; this is honest-but-leaky containment, not hostile-root containment.
