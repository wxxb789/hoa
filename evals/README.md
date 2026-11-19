# Evaluations

`run_trigger_evals.py` validates the routing cases and recorded routing baseline
offline. `run_necessity_eval.py` measures outcomes instead: can the same headless
agent complete the same task with and without a particular catalog skill?

## Run a necessity trial

Use uv with Python 3.13 or newer and a native Claude Code executable supporting
`--restricted` (verified with 2.1.328). Supply endpoint credentials through
`ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN`, and optionally
`ANTHROPIC_BASE_URL`. Existing logins, hooks and user settings are not copied.

```sh
uv run --script evals/run_necessity_eval.py evals/tasks/claim-audit.json --model MODEL
```

Default: one trial per arm. `--repeats 3` alternates which arm goes first and
reports the mean, sample standard deviation and `pass^k` (all trials passed,
not any trial passed). Set `--max-turns`, `--max-budget-usd` and `--timeout`
per invocation; model-provider caches can differ between trials. Use the same
model and limits within a comparison. `--acceptance` runs only the installed
arm and enables the file-writing tool for artifact-based checks.

Run only trusted fixtures, prompts, executables and providers. HOME/USERPROFILE,
XDG homes, APPDATA/LOCALAPPDATA, CLAUDE_CONFIG_DIR, CODEX_HOME, and temp directories
are fresh per trial. Only an allowlisted environment is inherited. The Claude
tool set excludes shells, subagents and web; strict MCP configuration supplies
no servers. This is profile and tool isolation, not an OS sandbox for the native
executable or a way to override administrator-managed policy. Shell-dependent
tasks and skills with sibling dependencies are not supported. Use an unmanaged
installation if policy adds tools, plugins or hooks.

Results are written to `evals/results/<local-date>-<task-id>.{json,md}`; existing
files are not overwritten. Use `--results DIR` for repeated experiments on the
same date. Review the recorded responses and artifact excerpts for secrets before
committing. The runner records Claude's reported model, usage and cost, not a
provider invoice. A trial requiring tool calls should leave evidence in the
trace. No observed skill access in the baseline is a necessary contamination
check, not a system-level file-access audit.

## Add a task

1. Put a small, non-sensitive fixture directory and task JSON under `evals/tasks/`.
   Keep the task JSON outside the fixture so agents never see the answer key.
   Both arms receive a fresh snapshot; Git metadata, symlinks, junctions and
   fixture skill installs are not available. For an explicit-invocation test,
   ask for the named skill *if available* in the identical prompt to both arms.
2. Set `id`, `skill` (a catalog directory name), `fixture` (relative to the
   task JSON), `prompt` and a nonempty `rubric` keyed by check ID. Each check
   is either `{"field":"answer","equals":42}` against a top-level field of a
   bare JSON response, or `{"file":"report.md","contains":"expected text"}`
   against a UTF-8 artifact no larger than 64 KiB. File names are relative to the
   copied workspace. Freeze the rubric before running and test decisions or
   outcomes rather than prose style.
3. Use a fixture with an observable failure the skill might prevent. The same
   deterministic judge scores both arms without seeing labels. The win rule is
   one arm passing every check on every trial, the other not, with a successful
   skill load or SKILL.md read in each installed trial and no invalid trials. Ties, unobserved
   treatment and invalid trials are inconclusive; execution errors or suspected
   contamination also produce a nonzero exit.

See [pilot notes](results/RESULTS.md) for what the initial runs did and did not verify.
