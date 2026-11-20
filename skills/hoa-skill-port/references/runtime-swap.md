# Runtime swap and live drift (2026-11-21)

## Swap the runtime over without a gap

1. Back up the current skill dir and tools to one tarball first.
2. Build and validate the new package before touching the live directory.
3. Use a whole-directory link only if the runtime and filesystem support it. Verify the complete
   sibling closure resolves in the loader layout, then confirm the body and scripts load.
   If there is no supported link, stop the swap and agree on a single-source install method.
4. Make the old entry points thin wrappers (`exec` the canonical script, forward argv and exit code)
   so in-flight work keeps the old paths and the owner's layout.
5. Re-run the repo's own reconciliation/drift scripts afterwards, then **prove** what they changed:
   dump the pre-run backup and the new file for the exact key the script claims to have repaired
   (for a runtime config, the skills enable/disable list and the derived disabled set), and diff those
   two dumps. A `repaired: … applied` line is the script's claim, not evidence — and the
   consumer-visible set (which skills the agent can actually load) can move even when the key you
   diffed is byte-identical.
6. If a ported skill then drops out of the runtime's available list, that is a **policy** question,
   not a porting failure: compare the profile's allowed list against the derived disabled list before
   calling it a regression, and route the edit to the owner — an agent that rewrites its own skill
   policy is how a bot loses the skills it needs.

## Keep the symlinked runtime honest

Once the runtime reads the canonical repo through a symlink, an uncommitted edit in that worktree is
**live but unpublished**: the agent behaves differently while the source of truth says otherwise. Make
that state visible instead of relying on remembering to check it:

1. Attach one probe to an existing periodic health check — never a new job per concern; the rule is one
   check family per schedule.
2. The probe runs `git -C <repo> status --porcelain <skills-path>` and stays silent when clean, and
   when dirty it reports only if the oldest dirty path is older than a threshold
   (`PORTING_DIRTY_AGE_HOURS`, default 24) so an in-flight edit is not noise.
3. Give it a stable finding id (check + scope + violation) so the runner's dedupe emits it once rather
   than every run, and an action line for the operator. Do not have the probe commit or publish.
4. Prove both branches before trusting it: the probe runs clean on a clean tree, and a deliberately
   touched file shows up at the right level.

A dirty signal that fires on every regenerate is not a probe problem — it means the repo's generator is
fighting its own line endings (see [pitfalls](pitfalls.md)). Fix that first, or the probe trains everyone to ignore it.
