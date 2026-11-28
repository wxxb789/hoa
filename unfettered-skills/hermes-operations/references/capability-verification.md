# Capability source verification


## Capability source verification

When the user asks whether Hermes supports a feature, whether a config key is real, or whether a quoted doc/blog/issue claim is true, verify against current source/runtime behavior before answering. Docs and tool return values can lag; implementation and live objects are ground truth.

Workflow:
1. Load `hermes-agent` for the current public interface and docs links, but treat docs as a lead, not final proof.
2. Locate implementation in the active source tree with targeted searches for command names, config keys, tool schemas, environment variables, and runtime classes.
3. Read the actual code path that constructs or dispatches the feature, including profile/config/env resolution and secondary clients.
4. If feasible, run a minimal live probe (`hermes config check`, `hermes tools list`, `hermes mcp list`, a dry-run command, or a direct unit-level import) to confirm runtime shape.
5. Report confidence with evidence paths/commands and explicitly separate "documented", "implemented", and "verified live".

Pitfalls:
- Similar terms can refer to different subsystems (ACP vs Kanban, MCP native client vs mcporter, provider model config vs credential pools).
- A feature may exist in source but be disabled by config/toolset/profile/gateway context.
- Gateway and cron runs may load a different profile/home than the current CLI session.

Reference: `references/acp-vs-kanban.md` was absorbed from the old capability-verification skill and captures one concrete term-confusion case.
