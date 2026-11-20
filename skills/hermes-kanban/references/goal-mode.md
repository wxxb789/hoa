# Iterative cards (2026-11-21)

Verify goal, triage and swarm commands against the installed release and the
[pinned Kanban docs](https://github.com/NousResearch/hermes-agent/blob/2de9f51b8008a7d49a49221c184f2f11cbfc4af1/website/docs/user-guide/features/kanban.md).
A goal-mode card checks iterative acceptance inside a worker session. Exhausted
budget or an unachievable criterion blocks for review, not silent completion.
A board root coordinates persistent child work; a chat goal alone does not.

Enable auto-decomposition only as an explicit board policy, with owned
assignees and bounded dispatch. For a swarm, verify the generated dependency
graph and evidence ownership before enabling the dispatcher.
