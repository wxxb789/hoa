# Pre-flight 15-second execution lock

Inspect the pending request and verify three elements before any edit or dispatch:

1. **Target surface** — the exact client/app/CLI/host/tenant where acceptance
   will be observed, not a proxy cache, mock, or staging ticket.
2. **Observable check** — input `X` produces expected output `Y`, plus what
   visibly fails while the change is absent.
3. **Forbidden boundary** — the files, branches, policies, or manual-vs-auto
   triggers that must not change.

If all three are unambiguous, display the lock card for confirmation:

```text
Lock — Target: <surface> | Check: <X -> Y; absent-state failure> | Forbidden: <boundary>
Proceed / Adjust
```

If any element is missing or ambiguous, inspect the repo or state read-only,
then ask only for the missing items, with concrete options. Keep the freeze
until the operator confirms the lock.
