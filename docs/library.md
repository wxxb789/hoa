# Small reference library

> **English** · [简体中文](library.zh-CN.md) · [Repository home](../README.md)

These are standalone examples to adapt by hand when assembling an agent
workflow, not installable skills or runtime settings.

| Surface | Start here |
|---|---|
| Agent role and authority | [Skill scout](../agents/skill-scout.md) |
| Orchestration pattern | [Typed verification gates](../orchestration/typed-verification-gates.md) |
| One-shot task templates | [Prompts](../prompts/) |
| Finite outcome-oriented recipe | [Adopt a pattern](../workflows/adopt-a-pattern.md) |

Harness engineering treats capability as model × harness: context, tools,
control loop, memory, permissions, and output handling all matter. hoa
provides portable components, not a complete harness. Orchestration covers
retry, continuation, termination, handoff, fan-out/fan-in, and best-of-N;
loops are one form of orchestration, not a separate library folder.
See the [repository architecture](architecture.md) for placement guidance.
