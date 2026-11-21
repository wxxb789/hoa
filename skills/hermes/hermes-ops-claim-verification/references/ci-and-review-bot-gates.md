# Verify CI and review evidence

- Match the workflow run, job, platform and checked-out SHA to the claim.
  Inspect the failed step. Separate dependency acquisition failures from
  failures in the changed behavior; a successful rerun without a code change
  is not evidence that a code fix landed. Cite local and CI results separately.
- Read the configured review lane's machine-readable marker from the PR's
  paginated comments, not a prose summary. Validate the exact head, completed
  status and required report/digest against the lane's schema. A stale or
  malformed newest selected marker cannot be replaced with older green evidence.
- Check unresolved inline threads separately when the gate requires it. A
  push or rebase invalidates the old verdict; request a fresh review only
  with authority. If posting is authorized, read back the exact comment or
  thread and retain the evidence ID.
- For GDD's versioned machine-review marker, use GDD's bot review reference;
  do not improvise a reduced marker or change the configured reviewer.
- Verify cited code and reproduce findings before relaying them. If polling
  is needed, use a bounded job with a completion signal and a durable log.
