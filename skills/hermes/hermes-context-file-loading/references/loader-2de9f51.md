# Loader probe: Hermes 2de9f51

Authority: [prompt_builder.py](https://github.com/NousResearch/hermes-agent/blob/2de9f51b8008a7d49a49221c184f2f11cbfc4af1/agent/prompt_builder.py)
and [context docs](https://github.com/NousResearch/hermes-agent/blob/2de9f51b8008a7d49a49221c184f2f11cbfc4af1/website/docs/user-guide/features/context-files.md).
Where the docs compress the order into one list, the source distinguishes
project family selection from filename precedence inside the AGENTS family.

- Git root through cwd: at each directory try `AGENTS.override.md`,
  `AGENTS.md`, then `agents.md`. Unique nonempty contents appear root first,
  deeper last, with provenance labels. Outside Git, inspect cwd only, including
  for `.hermes.md` / `HERMES.md`. Inside Git the latter select the nearest
  directory, with dotfile first within that directory.
- Check containment, file deny-list and content filtering, empty content,
  frontmatter stripping, and per-file and merged caps before explaining an
  omitted section. Do not assume one fixed character limit.
- Distinguish stable identity, project context, and volatile memory/user
  snapshots. Measure a rebuilt prompt rather than assuming every change
  invalidates the same cache or that an existing session reloads files.

With the matching source and dependencies, use a disposable profile and fresh
Git repo. Put distinct sentinel lines in root `AGENTS.md`, child
`AGENTS.md`, and child `AGENTS.override.md`. Run the following in the
installed source environment (set `cwd` to the absolute fixture directory;
do not start a live gateway or request a model response):

```python
from agent.prompt_builder import build_context_files_prompt

print(build_context_files_prompt(cwd=cwd, skip_soul=True))
```

At the root, expect only the root marker. At the child, expect root then
override, without the child base marker. Add a nonempty root `.hermes.md` and
expect its marker alone at the child. In a separate non-Git fixture, expect no
ancestor marker. If actual session behavior is in question, compare the
fresh session's observable context against this loader result, keeping profile
and entry point constant and changing only cwd. Do not dump private prompt text.
