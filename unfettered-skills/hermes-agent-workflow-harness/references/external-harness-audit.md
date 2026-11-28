# Auditing an external agent-workflow harness

For repos of the shape "coding-agent workflow + gates + optional eval platform". Output is a verdict
that survives scrutiny, not a feature tour.

## Steps

1. **Shallow clone into scratch.** `git clone --depth 1 <url>` under the scratch dir; disposable.
   Shallow clones hide history — read commit/star/fork counts from the host page instead of `git log`.
2. **Inventory by size and role.** `find . -type f | xargs wc -l | tail -3`, then per-directory counts
   for the entry layer (`commands/`), the workflow bodies, shared methods (`skills/`), `scripts/`, and
   host/plugin adapters. Exclude `.git`, tests, and any vendor toolchain when reporting scale.
3. **Count tests.** `grep -rc 'def test_' <test dirs> | awk -F: '{s+=$2} END {print s}'`. A large
   contract set with a thin test count is an assertion, not an engineering artifact.
4. **Read in this order, stop early:**
   entry command contracts → one stage body (propose or equivalent) → context-loading protocol →
   tool-semantics mapping → host manifest/capability block → gate script function names
   (`grep -n '^def ' scripts/workflow.py`) → telemetry/eval modules.
   Function names before bodies: the subcommand list is the real capability surface.
5. **Multi-agent answer from manifests.** Look for `hosts/*/host.json`, `plugin.json`,
   `.codex-plugin/`, provider dirs. Absence is the answer. Then read which capabilities are
   `emulated` — that is exactly what a new runtime would have to fake.
6. **Shipped vs marketed.** Grep `lite_`, `internal`, `unreleased`, `roadmap`; a trimmed edition's
   docs describe an upper bound.
7. **Answer in this shape:** what it is (with numbers you measured) → architecture boundary → the
   2–5 mechanisms that carry the value → multi-runtime reality → adoption evidence (or its absence)
   → costs/risks → borrow tiers.

## Portability checklist (before promising runtime X)

- command/prompt surface: native slash commands, skills, or plain prompt files?
- subagent dispatch: spawn + wait with count, dependencies, role isolation, failure propagation?
- hooks/lifecycle: does the runtime emit start/stop/failure events, or must the contract record stage
  state itself? (Two official hosts of one real harness had this `unsupported` — plan for it.)
- skill invocation: deterministic load-and-execute, or advisory mention only?
- distribution: plugin marketplace, or copy-a-directory installer?
- telemetry/update adapters: real event source, or `unsupported`?

A runtime missing subagent dispatch **and** gates yields the prose of the workflow with none of its
guarantees; say so instead of shipping an adapter shell.

## Reporting pitfalls

- Judge claims with Fact / Inference / Judgment labels; an adoption story with no numbers is
  Inference even when the repo asserts it.
- Keep the no-borrow list in the artifact — that is the part a reader decides with.
- Do not read the whole contract set; enforcement detail can be sampled once the model is clear.
