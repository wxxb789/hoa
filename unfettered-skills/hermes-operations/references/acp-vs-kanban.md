# Hermes: ACP vs Kanban — source-verified comparison

Verified against local Hermes HEAD `74239b494` (== remote main, SHA256 `7e51ca63…`), 2026-06.
They are NOT competitors — different layers. ACP = how to talk to one agent. Kanban = how to orchestrate many.

## Essence (source quotes)

**ACP** — `hermes_cli/subcommands/acp.py:18-19`
> help="Run Hermes Agent as an ACP (Agent Client Protocol) server"
> description="...for editor integration (VS Code, Zed, JetBrains)"

`agent/copilot_acp_client.py:1-6`
> OpenAI-compatible shim that forwards Hermes requests to `copilot --acp`. ... **Each request starts a short-lived ACP session**, sends the formatted conversation as a single prompt, collects text chunks...

Two directions, both stateless protocol bridging:
- Hermes **as server** (`hermes acp`): IDE drives Hermes via JSON-RPC over stdio (`session/new`, `session/prompt`, `fs/`, `terminal/`, `permission`).
- Hermes **as client** (`copilot_acp_client.py`): `delegate_task(acp_command='copilot')` treats Copilot CLI as an OpenAI-compatible model backend.

**Kanban** — `hermes_cli/kanban_swarm.py:1-15`
> Kanban Swarm v1: thin swarm topology helpers on top of Kanban. ... writes a small task graph into the existing Kanban kernel:
> planning root → parallel specialist workers → verifier (waits for all workers) → synthesizer.
> shared blackboard is ... structured JSON comments on the root task ... all state in existing task_comments/task_events rows.

`tools/kanban_tools.py:1-6`
> Kanban tools — structured tool-call surface for worker + orchestrator agents. A normal `hermes chat` session still sees **zero** [kanban tools].

## Comparison

| Dimension | ACP | Kanban |
|---|---|---|
| Essence | protocol bridge (agent↔agent) | multi-agent task orchestration |
| Solves | how to talk to another agent runtime | how to dispatch + track work across many workers |
| State | stateless (short-lived session/request) | stateful (sqlite board: tasks/comments/events) |
| Source size | 2 files (lightweight shim) | 8+ files + toolset + gateway watcher + dashboard plugin |
| Parallel | no | yes (parallel specialist workers) |
| Dependencies | none | yes (todo→ready→done; verifier/synthesizer gating) |
| Transport | JSON-RPC over stdio | process spawn + shared sqlite (no new service) |
| Triggered by | IDE / `delegate_task(acp_command=)` | dispatcher / orchestrator profile / CLI / dashboard |
| Multi-model | no (single external runtime) | **yes — each worker bound to a profile** |

## Kanban multi-model mechanism (the key capability)

`kanban_swarm.py:29-38` — first field of a worker spec is the profile:
```python
@dataclass(frozen=True)
class SwarmWorkerSpec:
    profile: str          # ← each worker bound to a profile → its own config.yaml → its own model
    title: str
    body: str
    skills: list[str]
    priority: int = 0
    max_runtime_seconds: Optional[int] = None
```
CLI: `--worker profile:title[:skill,skill]` (`kanban_swarm.py:271-279`). Chain: worker `assignee = spec.profile` → dispatcher spawns an independent Hermes process per profile (injects `HERMES_KANBAN_TASK` env) → each profile has its own model. Granularity = **profile/process**, not subagent.

## Worker vs Orchestrator roles (`kanban_tools.py:65-86`)

Kanban tools are hidden by default; registered only when:
1. `HERMES_KANBAN_TASK` env is set (dispatcher-spawned worker), OR
2. the active profile explicitly enables the `kanban` toolset (orchestrator, e.g. `techlead`).

| Role | Condition | Tools |
|---|---|---|
| Worker (task-scoped) | `HERMES_KANBAN_TASK` set | own card only: `kanban_complete`/`block`/`comment`/`heartbeat` |
| Orchestrator (no task scope) | kanban toolset on, no task scope | board routing: `kanban_list`/`unblock`/`create` |

Board-routing tools are deliberately withheld from workers so they can't mutate global board state.

## When to use which

- **ACP**: use Hermes as an IDE coding backend (`hermes acp`), or route a specific subagent through Copilot CLI (`delegate_task(acp_command='copilot')`). Single, stateless, external-runtime.
- **Kanban**: split a big task into parallel subtasks across different-model/skill workers, with dependencies + tracking + verify/synthesize. Or a long-lived orchestrator profile routing incoming work to worker profiles.
- **They compose**: a Kanban worker can itself be an ACP harness session (dispatcher supports `runtime: acp`) — i.e. orchestrate a swarm of workers running on Copilot/Claude Code.

## Profile-communication correction

Profiles do NOT communicate via ACP (a common misconception). ACP is editor/Copilot integration. Profile collaboration is via: shared filesystem (`~/claw/...`), or Kanban sqlite blackboard, or an orchestrator profile routing through the board. The only built-in profile↔profile coupling is a shared `auth.json` credential pool.
