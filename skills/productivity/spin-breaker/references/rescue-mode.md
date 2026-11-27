# Mid-spin rescue

Read the recent turns plus read-only `git status --short` and `git diff --stat`.

1. Extract mixed-in **side quests and meta-ideas** that expanded the original
   acceptance envelope. Offer to park each via `park --kind side-quest` after
   confirmation; see [Commands](commands.md).
2. Output **at most 5 lines** of plain reckoning:

| Line | Content |
|---|---|
| 1 `Outcome` | The single original user-visible result requested. |
| 2 `Last verified fact` | The last directly observed fact, with exact `file:line`, command exit, or target surface. |
| 3 `Eliminated vs. live guesses` | Which hypothesis line 2 ruled out (say `0 eliminated` when none), versus the live unfalsified guesses. |
| 4 `Discriminating probe` | One minimal read-only command or observation that splits or falsifies the top live hypothesis, stating what pass vs. fail proves. |
| 5 `Decision` | `A. Run probe`: execute only the line-4 read-only probe. `B. Freeze & Park`: write a 4-line restart breadcrumb via `park --kind breadcrumb` and stop cleanly. `C. Retire branch/approach`: record the falsified lesson via `park`, then await explicit rollback authorization before touching Git state. |
