# Board profile policy: Hermes 2de9f51

Check the installed command help and [pinned Kanban docs](https://github.com/NousResearch/hermes-agent/blob/2de9f51b8008a7d49a49221c184f2f11cbfc4af1/website/docs/user-guide/features/kanban.md)
before dispatch. CLI control belongs to the operator; dispatcher workers use
injected tools. Use `create --body-file` for substantial briefs, parse JSON
for card IDs, and check `list`, `show` and `log` before retrying an empty dispatch.

Choose per-board policy rather than imposing these as runtime requirements:

| Choice | Conservative starting policy |
|---|---|
| Board selection | Pin `--board <slug>` in operator commands; workers inherit their board. |
| Dispatch | Use the gateway dispatcher or a standalone daemon, not both against the same DB by default. Deliberate shared-board setups require separate profile claims and verified installation topology. |
| Assignees | Verify each card resolves to a real profile before it becomes ready; use a configured default assignee for approved decomposition, not a mandatory per-card override. |
| Workspace | Preserve isolation; use `dir:<absolute path>` when authorized edits must reach a specific existing publisher. Scratch and worktree changes do not land there by themselves. |

Check dependency state, eligible assignee, workspace access, capacity and
reported skips when a pass spawns nothing. Do not infer a single cause from
`spawned: []`. Review worker and orchestrator profiles separately.
