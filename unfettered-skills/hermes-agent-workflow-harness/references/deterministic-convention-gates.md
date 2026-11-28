# Deterministic convention gates

How to turn a convention that keeps getting broken into a check an agent cannot argue with. The prose
doc explains *why* the rule exists; the gate is what enforces it, and a rule with no gate is a wish.

## Design checklist

1. **One gate, one convention, deterministic input set.** Read the repo's own working-tree listing
   (tracked *plus* untracked non-ignored, minus ignored), not `git ls-files` alone — a gate over tracked
   files only passes on the tree that has not been staged yet, which is exactly when a new violation
   appears.
2. **Report the item, not a count.** Every failure line is `file:line: <what is wrong> — <how to fix>`.
   `3 violations found` and `pkg/Test: failed` both force the next reader to re-derive the reason.
3. **Exception = inline marker with a mandatory reason.** `// <rule>: allow <why this is fine>`, matched
   within a small lookback (~3 lines) so a multi-line table entry is annotated once. Never a central
   allowlist file: it drifts away from the code it excuses and reviewers stop reading it, so the exception
   becomes invisible while the gate keeps passing.
4. **Self-test both directions in one case.** Feed the gate one unjustified violation next to one
   justified exception and assert exactly one failure, naming the right line and not the justified one. A
   gate that also fires on the justified form is switched off by the first legitimate exception; one that
   misses the violation is a false green wearing a coverage badge.
5. **Name the fix in the message.** `use filepath.Join/t.TempDir` beats `rule PORTABLE_PATHS violated`:
   the gate teaches the rule to the next agent as it rejects it.
6. **Prove the gate fires before shipping it.** Run it against the pre-fix tree (or a crafted fixture) and
   quote the output; a gate added alongside a fix that never demonstrated a red run has unknown
   sensitivity.

## What a gate must never emit

- A test name or numeric count with no payload. Emit the failing item's own output, tail-bounded (last
  ~12 lines). On a multi-OS CI matrix the reader cannot re-run the failing platform locally, so output
  that only names the failure costs one full CI round trip per unknown — and there are usually several.
- A skip that is indistinguishable from a pass. A legitimate skip (a mode-bit assertion on Windows) says
  `skip: <reason>` and counts separately.

## Convention sets worth gating

- **Platform-bound path literals** (`/tmp/…`, `/home/<user> `C:\…`) in any repo whose tests run on more
  than one OS — see below for why this class is expensive.
- **Banned imports / APIs** (network modules in an offline-only tool, shelling out where a library exists).
- **Required file shape** (license header, frontmatter keys, changelog entry on a release branch).
- **Dependency tidiness** (empty `go mod tidy` / lockfile diff, vendored-script drift).

## Platform proof rules (the case behind the path-literal gate)

- The matrix is the only proof. A green local/Linux job says nothing about Windows or macOS; state the
  platform next to every count.
- `/tmp/x` is **not absolute on Windows** (`filepath.IsAbs` is false), so a validator rejects a valid
  fixture and the failure reads as a product bug. Build fixtures with `t.TempDir()` + `filepath.Join`.
- Goldens: decode JSON first, then substitute the temp prefix, then normalise separators, then compare.
  Substituting a path into already-serialised JSON never matches, because the encoder escapes separators
  (`C:\\Users\\<user> — the assertion then passes on POSIX and fails on Windows for a reason invisible in
  the test text.
- Mode bits, signals and process groups are POSIX API. `os.Chmod(0o600)` creates no restrictive ACL on
  Windows: assert a mode only behind a `runtime.GOOS` check and report it as skipped. Deliver cancellation
  through a durable control file the target polls; treat a signal as an optimisation.
- IPv6 loopback arrives bracketed (`[::1]`) from `new URL(...).hostname` and unbracketed from Go's parser:
  normalise before comparing, or one layer accepts an endpoint the other refuses.

## Order of work when CI is the only place it reproduces

1. Fix the gate's reporting first (payload, not name) and re-push — that investment pays back on every
   later failure, including the ones this increment did not cause.
2. Then fix the class the gate named, using a fixture that carries the same meaning on every OS.
3. Re-run the matrix; a fix justified only by "it should now pass" is unverified.
