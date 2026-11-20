# Evaluations

`run_trigger_evals.py` validates the routing cases and recorded baseline offline.
`judge_trigger_evals.py` runs the trigger suite against a configured OpenAI-compatible
`/chat/completions` endpoint by default, or against an opt-in `/decisions` endpoint
when `--api decisions` (`EVALS_API=decisions` or `api: decisions` in
`$XDG_CONFIG_HOME/evals/config.yaml`) is set.
`run_necessity_eval.py` compares outcomes on the same task with no skill (`none`),
frozen short instructions (`terse`), and the installed skill (`skill`).

## Run a necessity comparison

Use uv with Python 3.13 or newer and a native executable, not a batch shim.
Screening defaults to Pi (tested with 1.5.2),
`tencent-litellm/deepseek-v4.1-flash-fast`, and `--thinking max`.
`--model` can select another model in `tencent-litellm`; only an explicit
Pi `--thinking` changes the thinking level. The provider is free to the owner, so
time is the only cost: Pi trials default to `--timeout 3000` (ten times the other
runtimes), and any `--max-total-tokens` cap for Pi should be about ten times the
cap you would give Claude or Codex, because DeepSeek thinks at length.
Claude Code needs `--restricted` (tested with 2.1.329) and
`ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN`, optionally
`ANTHROPIC_BASE_URL`. Codex needs a configured model provider; the runner uses
`gpt-6.2-sol` by default.

```sh
uv run --script evals/run_necessity_eval.py evals/tasks/claim-audit.json --runtime pi --mode forced
uv run --script evals/run_necessity_eval.py evals/tasks/claim-audit.json --runtime pi --mode natural
uv run --script evals/run_necessity_eval.py evals/tasks/claim-audit.json --runtime claude --model claude-haiku-5.5 --mode forced
uv run --script evals/run_necessity_eval.py evals/tasks/claim-audit.json --runtime codex --model gpt-6.2-sol --mode forced
uv run --script evals/run_necessity_eval.py evals/tasks/claim-audit.json --runtime claude --model claude-haiku-5.5 --mode natural
uv run --script evals/run_necessity_eval.py evals/tasks/claim-audit.json --runtime codex --model gpt-6.2-sol --mode natural
```

- `forced` (default) explicitly asks the skill arm to read and follow the named
  skill. No observed load invalidates that trial.
- `natural` gives every arm the identical user prompt. The terse text goes in
  the Claude or Pi system prompt or the Codex developer instructions in either
  mode, never in the common user prompt. Skill misses in natural mode are recorded as misses, not
  individually invalidated.
- Each repeat runs all three arms, reversing order on every other repeat.
  `--repeats` defaults to 3. Use `--timeout` on any runtime; Claude also accepts
  `--max-turns` and `--max-budget-usd`. Use matching limits within a comparison.
- `--max-total-tokens N` stops starting trials once their cumulative CLI-reported
  tokens reach the positive limit. There is no cap by default. A running trial
  can exceed the remaining budget, and unreported usage does not count toward
  the cap. The report lists each skipped arm and repeat.

Each trial gets a fresh workspace, HOME/USERPROFILE, runtime profiles, XDG
homes, APPDATA/LOCALAPPDATA and temp directories. On Windows, HOMEDRIVE and
HOMEPATH together point to the trial's USERPROFILE. Claude uses strict empty MCP
configuration. Codex `exec --json` uses an isolated `CODEX_HOME` and copies only
`model_provider` and its matching `model_providers` table from the operator's
`$CODEX_HOME/config.toml` (default `~/.codex/config.toml`). Environment credentials
named by that provider may be inherited; auth files, other providers, plugins and
MCP settings are not copied. Use a provider that does not require existing login
state or an executable auth command. Codex bypasses approvals and sandboxing,
and disables the dispatch integrations, web search, subagents and bundled skills.

Pi uses the checkout's gdd Pi route for JSON mode and the success marker.
Every Pi arm in both modes uses `<trial>/home/.pi/agent` as
`PI_CODING_AGENT_DIR` and redirects `PI_CODING_AGENT_SESSION_DIR` to a separate
directory under the same isolated home. The runner copies only the
`tencent-litellm` entry from `~/.pi/agent/models.json` and the matching entry
from `auth.json`, when present. Only environment variables referenced by that
provider's credentials or headers are forwarded as provider credentials.
Credential commands are rejected. No other providers, sessions or extensions
are copied. Pi disables session persistence, MCP, extensions, project trust and
context-file loading. The real Pi agent directory is read-only to the runner.
Controls always use `--no-skills`. The forced skill arm uses `--no-skills` with
an explicit `--skill` pointing at the installed copy. Only the natural skill arm
allows discovery, with the copy in `<trial>/home/.pi/agent/skills/<name>/SKILL.md`.
Neither control has an installed copy. These settings isolate default home
lookups, not explicit file access outside the trial.

Codex CLI 0.171.0 still discovers `$CODEX_HOME/skills/<name>/SKILL.md`, the
legacy user root intentionally used here. On Windows it also enumerates the real
Known Folder profile's `.agents/skills`; the runner excludes those documents
via path-based skill disable rules instead of modifying the profile. For Claude,
a successful `Skill` result for the named skill or `Read` of the installed
`SKILL.md` is load evidence; success comes from the matching `tool_result`.
For Codex, a successful named `Skill` tool result or a completed shell read
of the installed document with the skill header in `aggregated_output` is load
evidence. Pi uses the matching successful `tool_execution_end` for a skill read
or load, and requires returned skill text for shell-based load evidence.
Plain mentions and untraced automatic injection do not establish a load.

Searches or listings for skills (for example `Glob`, `Grep`, `ls`, or
`rg --files`) and failed `Skill` calls are probes, not contamination. Control
contamination requires a successful `Skill` call or an observed successful content
read of an external `SKILL.md` or a file in a skill directory. This includes catalog
sources, installed copies, and host skill directories. Paths inside the fixture
workspace do not count. Relative paths are interpreted from the workspace.
The JSON report (schema 3) records `skill_probe_count` once per trial and lists
distinct `contamination_reasons` for invalidated controls: `skill-load`,
`catalog-read`, `host-skill-read`, or `installed-copy-read`. The trace summary
does not store command arguments or paths.

This tool-trace check is necessary for a valid comparison, but is not an OS-level
file-access audit; it does not reconstruct all shell behavior or observe untraced reads.

Run only trusted tasks, skills, executables and providers in an unmanaged
environment. Profile and tool isolation do not constrain an arbitrary native
process or a shell command to the temporary workspace. Do not opt in to shells
for tasks that can modify the real host, start servers, spawn background
processes, or open windows. Sibling skill dependencies are not installed.

## Score and interpret

The deterministic judge sees only the output and trial workspace, not the arm.
The score is the fraction of checks passed. Report mean and sample standard
deviation (undefined for one repeat), mean gaps, and `pass^k` (all checks passed
in all repeats). Invalid arms have no aggregate score or `pass^k`. The report
also flags checks that are non-discriminating or flip within an arm.

For field checks, the judge parses bare JSON, then the last JSON-labeled
fenced block if it contains valid JSON, then the last complete top-level JSON
object in the reply. Each trial records `answer_format` as `bare`, `fenced`,
`extracted`, or `none`. Field checks require an object with the expected
fields; file checks are unchanged.

The runner records [the frozen thresholds](necessity-thresholds.json) or an
explicit `--thresholds FILE`. Rules are evaluated in this order:

1. **inconclusive** if any trial is skipped or invalid (including control contamination),
   no load was observed, or the skill load rate is below `min_natural_load_rate`.
   In forced mode, every skill trial must be valid regardless of this threshold.
2. **skill-wins** if the skill meets `min_pass_rate` and its mean exceeds each
   control by at least `min_mean_gain`.
3. **terse-suffices** if terse meets `min_pass_rate`, exceeds none by at least
   `min_mean_gain`, and trails skill by no more than `max_terse_gap`.
4. **no-difference** otherwise: neither advantage met the frozen criteria.
   This is not a statistical equivalence claim.

Results: `evals/results/<local-date>-<task-id>-<runtime>-<mode>.{json,md}`.
Use `--results DIR` to avoid overwriting a comparison. Review response and
artifact excerpts for secrets before committing. Raw traces and stderr are
not persisted. Token counts are CLI-reported; Codex cached input and reasoning
output are subsets, not added a second time. Pi sums uncached input, output,
cache reads and cache writes from completed assistant messages and records
the process exit code. Claude's CLI cost is not an invoice.
Exit 1 indicates skipped or invalid trials; exit 2 indicates setup failure. Otherwise
inspect the verdict, including natural comparisons with unobserved treatment.

## Author a task

1. Put a small non-sensitive fixture directory and task JSON in `evals/tasks/`.
   Keep the answer key outside the fixture. The workspace snapshot excludes Git
   metadata and rejects symlinks, junctions and local agent installations.
2. Set `id`, `skill` (a catalog directory name), `fixture` (relative to the
   task JSON), `prompt` (no invocation instruction), and `terse` (the frozen
   short substitute, not the answer key). Freeze both instructions and the
   rubric before running.
3. Set a nonempty `rubric` keyed by check ID. Checks are
   `{"field":"answer","equals":42}` against a top-level field of the JSON answer,
   or `{"file":"report.md","contains":"expected text"}` against a relative UTF-8
   artifact no larger than 64 KiB. File checks enable Claude's Write and Pi's
   write/edit tools.
4. Shells are off by default. Set `"shell": true` to enable them for all
   runtimes, or `"shell": ["codex"]` for Codex only. Codex 0.171.0 has no
   general-purpose file reader without its shell tool, so opt in for Codex
   tasks that need fixture or skill reads.

See the [pilot notes](results/RESULTS.md) for what the initial runs verified.
