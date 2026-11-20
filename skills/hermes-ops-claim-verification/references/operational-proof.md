# Operational proof

- **Scheduled vs manual:** Match job identity, scheduled timestamp, effective
  runtime, payload exit code and payload output. A scheduler's own completion
  message does not establish payload success. A manual run can reproduce a
  mechanism; record its executable, interpreter, PATH and exit code separately.
- **Baseline vs effect:** Establish the previous revision, failing observation
  and affected population. Compare the same observation after the change,
  controlling for unrelated runtime changes. A green check that never
  exercised the original fault is not evidence of an effect.
- **Restoration:** Verify multiple natural runs at their normal cadence, not
  several hand-run retries. Record timestamps and dependency identity; inspect
  interpreter paths, symlinks or provisioning changes when outcomes diverge.
  For intermittent faults, track the trend, last occurrence and matched sampling
  windows. A quiet sample is not recovery. For access faults, distinguish
  accepted authentication from attempts; use dedicated access forensics.
- **Unrelated or pre-existing failure:** Rerun the exact failing command at
  the candidate and unchanged baseline in isolated worktrees, with the same
  inputs and environment. Record the test and error on each. Check the CI
  workflow really runs that command on the relevant platform. A known failure
  is not an implicit waiver; report any unresolved gate and ask only for the
  decision that remains.
