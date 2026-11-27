# Surgical rollback baseline

Restore only these replaced rules in SKILL.md; do not replace the whole skill or unrelated subsequent edits.

3. **Agent-run jobs are self-contained**: fresh session, no chat context, cannot ask questions; the final
   response *is* the delivery. Name the deliverable and the proof path; silence is a valid monitor result.

18. **`jobs.json` is shared mutable state — diff it at the end of any refactor.** Other sessions and
    profiles create jobs while you work (measured: four new jobs appeared within hours of a 20→14
    consolidation). Finish with a backup-vs-live diff, report jobs you did not create, and never state a
    job count you have not just re-read.
