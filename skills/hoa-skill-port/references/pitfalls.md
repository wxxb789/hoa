# Destination intake and branch publication (2026-11-21)

Before writing, inspect the destination's instructions, generated-file sources,
workflow steps, ignore patterns and a nearby package. Inspect each reference as
part of the port; a link in the source is not proof its target exists. When two
packages appear similar, compare behavior before proposing a merge. Do not silently
fold them together. Use the repository's existing mechanism for genuinely shared
helpers rather than duplicating them.

Use generators to update their outputs and rerun their drift checks. If regeneration
obscures the diff through line endings, use the repository's convention; surface a
generator defect separately rather than hand-editing the generated file. Bump only
touched skill revisions when the repo requires them. Use the repo's version command
where it owns a version.

## Publish only with authority

1. Confirm which of push, PR creation, watching, merging, and branch cleanup the
   current task authorizes. Leave unapproved steps to the operator.
2. Publish from a dedicated branch, never directly to the default branch. The PR
   should carry scope, configuration decisions, acceptance output, and known limits.
3. On CI failure, read the actual failed job log, reproduce its gate, and fix forward
   on the same branch without force-pushing.
4. If merging and cleanup are separately authorized, follow the destination's merge
   policy and refresh from the default branch before the next increment.
