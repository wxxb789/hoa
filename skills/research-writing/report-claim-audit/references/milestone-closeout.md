# Milestone closeout checklist

Use this read-only pass at a project phase boundary, even when there is no closeout memo.

1. Inventory before reading summary prose: enumerate goal/task files and statuses, then reconcile
   index and archive rows. Include open PRs/issues, live runs and inherited obligations. Separate
   recorded completion, unrecorded completion, unfinished work, in-flight work and deliberate deferrals.
2. Reconcile what was recorded with what was measured, the changelog with the published tag or
   registry version, and that release with what users actually load. Resolve the deploy pipeline's
   effective dependency, generator or tool pin to its version or commit, date and lag from release.
   Inspect the materialized output when generation is involved.
3. Look for post-deploy proof on the serving host: the shipped artifact is reachable, boots or
   loads, and real usage exercises the changed capability. Check live host behavior (such as
   response headers) when it matters. A green build, publish or deploy does not prove this;
   mark unproven behavior and skipped checks explicitly.
4. Rank remaining items by cost of leaving them, with evidence, execution order and blockers
   such as active runs. Include cleanup candidates without acting on them. State the completion
   verdict and recommend the one owner decision that clears the phase, if any.
