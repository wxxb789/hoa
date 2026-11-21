# Operating Contract Evolution — case study

This reference captures reusable lessons from a session where the owner asked the orchestrator to research
an agent-design article, evolve the agent's identity file, then review and evolve its operating protocol.

## Source pattern

The useful pattern from the article was not “add one section to the identity file.” It was a layered agent
architecture:

- the identity file is the identity/persona layer.
- memory holds stable facts and preferences.
- skills hold reusable procedures.
- curator-style cleanup removes duplicate/stale rules.
- GEPA-style improvement uses execution traces and failure analysis, not self-congratulation.
- profiles/team agents specialize roles.
- scheduled/background execution supports autonomous work.

When applying an external article or design note, extract the architecture and adapt it to the local agent.
Do not just mirror the current file structure.

## Owner corrections from the session

1. **Question-like sections were meant structurally, not as a single added bullet**
   - Bad response: add one bullet saying “Section 像提问”.
   - Correct response: redesign the whole identity-file structure as multiple question-named sections, then ask owner choices section by section.

2. **Use choice-based co-design for subjective identity/ops changes**
   - Ask one section at a time.
   - Prefer multiple-choice prompts.
   - Accept combined answers, e.g. “A and C”, and synthesize.
   - If the owner asks for a draft before applying, do not write files yet.

3. **The operating protocol should be an operating router, not a persona file**
   - Keep identity/vibe in the identity file.
   - Keep execution protocol, routing, safety, async, artifacts, team usage in the operating protocol.

4. **Async-first needs gates**
   - The owner prefers async/background work and reduced blocking.
   - But the robust rule is: reduce owner blocking without hiding progress.
   - Async when work is >60s, parallelizable, safe without owner decisions, and verifiable later by process/job/session id.
   - Do not async quick checks, safety-critical decisions, steps whose output determines next action, or tasks requiring owner input.

5. **Maximize team-agent leverage, not ceremony**
   - Use the research specialist for facts/evidence/source verification.
   - Use the finance specialist for finance/market/portfolio judgment support.
   - Use the strategy specialist for strategy/priority/decision synthesis.
   - The orchestrator remains executor/orchestrator.
   - Fast path direct action is preferred for simple, low-risk, well-scoped tasks.

6. **Filesystem hygiene is an operating rule**
   - Default artifacts under the designated artifact workspace.
   - Use descriptive kebab-case directories.
   - Group evidence, drafts, backups, finals when tasks grow.
   - After a task, leave final artifacts plus useful evidence/backups/diffs; remove throwaway temp files unless needed for audit.
   - Do not rewrite archived task/research docs unless the owner asks; prioritize active runtime docs, skills, team docs, and current project docs.

## Code-review heuristics for the operating protocol

Review it like code:

- Blocking issue: rules that can cause wrong behavior or overfire.
- Major issue: rules that are too abstract to execute, or whose blast radius is unclear.
- Minor issue: style, redundancy, tone, or prompt-bloat concerns.

Common findings:

- “Always async” is too absolute; add gates.
- “Maximize team agents” can cause over-delegation; add cost/latency gates.
- “Do not answer before reading context” can cause ritual reads; scope it to grounded/context-dependent questions.
- Model leverage rules should be heuristic-based, not hardcoded to stale model names.

## Good final shape for an operating protocol

A strong operating contract includes:

1. Rule priority
2. Runtime layout
3. Context loading by trigger
4. Response shape
5. Async-first execution with gates
6. Decision routing
7. Action gates by blast radius/reversibility
8. Persistence routing
9. Orchestration/delegation/model routing
10. Team routing
11. Files/artifacts hygiene
12. ADHD support
13. Self-evolution / optimization order
14. Hard limits

## Proof discipline

For durable edits to identity/protocol/config/skills/team docs:

- backup first
- apply patch/write
- read back or verify
- return final path + backup path + summary/diff

If a patch fails, inspect the file region before retrying. Do not loop the same failed patch blindly.
