# Inline authoring fallback

When discovery finds no compatible runtime creator, author the approved skill directly.
Inline authoring must produce a complete portable skill rather than a stub.

## Required package shape

```text
<skill-name>/
├── SKILL.md
├── references/        # depth that should not dominate the trigger surface
├── scripts/           # deterministic, stdlib-only logic when needed
└── evals/             # executable fixtures when behavior is safety-critical
```

## `SKILL.md` contract

1. Begin with YAML frontmatter containing non-empty `name` and `description` fields.
2. Make the description the trigger: say what the skill does, concrete phrases that
   should invoke it, and negative triggers that route to the correct alternative.
3. Keep the body below 500 lines. Use imperative workflow steps and explain why a
   guardrail exists; move detailed catalogs and long examples into `references/`.
4. State inputs, outputs, success/stop conditions, approval or safety gates, and failure
   behavior. Only encode the approved scope—do not add inferred integrations.
5. Keep tracked content sanitized. Put machine-specific paths, credentials, raw history,
   and user-private examples in untracked locations instead.

Run `python scripts/validate_skill.py <new-skill>/SKILL.md` after authoring. Resolve every
validation error before reporting completion, then compare the approved identity,
contract, workflow, and basis against the created artifact and report any differences.
