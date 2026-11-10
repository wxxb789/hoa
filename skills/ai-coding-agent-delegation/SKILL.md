---
name: ai-coding-agent-delegation
description: >-
  Hand a bounded coding or review task to an external autonomous coding-agent CLI in its own git
  worktree, then verify the diff, the tests and every acceptance claim yourself before integrating.
  Use when work should outlive the current turn, run isolated from the operator's checkout, or be
  compared across agents. Not for a quick bounded subtask in the current turn, and not for work with
  no written task spec or acceptance command.
metadata:
  version: "0.1.28"
  areas: "software-development,work-management"
  targets: "runtime-agnostic"
  kind: "entry"
---

# AI Coding Agent Delegation

## Overview

This is the umbrella for using external autonomous coding agents from a driving session. It covers
provider-specific CLIs (any print-mode or exec-mode agent) and tool-agnostic worktree workflows for
parallel or isolated implementation. Harness names below are adapter examples, never defaults.

Use this when the best move is to hand a bounded coding/review task to another agent process, monitor
it, verify its output, and integrate only the parts that pass review.

## When to Use

- Independent feature, bugfix, refactor, or PR review tasks that fit a written task spec.
- Parallel issue fixing where each worker should have its own git worktree.
- Long-running coding tasks that should continue outside the current agent turn.
- Comparing multiple agents' solutions or reviews.

Prefer an in-turn subagent for quick bounded subtasks. Prefer a spawned CLI agent/worktree when the
task may take longer, needs interactive tooling, or should be isolated from the parent session.

## Choose the adapter shape

| Shape | Best for | Invocation family |
|---|---|---|
| Print-mode CLI | Deep codebase edits, PR reviews, interactive coding captured non-interactively | `<cli> -p "<prompt>"` |
| Exec CLI | One-shot implementation, review, sandboxed coding | `<cli> exec "<prompt>"` |
| Run CLI | Feature work with the CLI's own model/tool stack | `<cli> run "<prompt>"` |
| In-harness child | Full harness tool access in a child process | `<cli> chat -q "<prompt>"` |
| Generic agent | Any compatible CLI that can read `TASK.md` | worktree + task spec |

Adapter examples (observed forms, not defaults — substitute the CLIs your install actually has):

```bash
claude -p "Read TASK.md and implement. Run tests. Do not merge." --output-format stream-json --verbose
codex exec --sandbox <mode> "Read TASK.md and implement. Run tests. Do not merge."
opencode run "Read TASK.md and implement. Run tests. Do not merge."
hermes chat -q "Read TASK.md and implement. Run tests. Do not merge."
```

Whatever the shape, record the adapter you used in the task record.

## Canonical Worktree Protocol

Use git worktrees when running more than one coding agent or when you need isolation from the user's
current checkout.

```bash
git fetch origin
mkdir -p "${DELEGATION_WORKTREE_ROOT:-.worktrees}" "${DELEGATION_LOG_ROOT:-logs}"
BASE="${DELEGATION_BASE_REF:-origin/HEAD}"
TASK=short-task-name
BRANCH=agent/$TASK
WT="${DELEGATION_WORKTREE_ROOT:-.worktrees}/$TASK"
git worktree add -b "$BRANCH" "$WT" "$BASE"
cat > "$WT/${DELEGATION_TASK_SPEC:-TASK.md}" <<'EOF'
# Goal
<what to build/fix>

# Acceptance Criteria
- <observable result>

# Non-goals
- <what not to touch>

# Commands
- <tests/builds to run>

# Files likely relevant
- <paths>

# Agent instructions
Run tests, keep scope tight, do not merge, summarize changed files and verification.
EOF
```

Then run the agent in that worktree, capture logs to the log root, and keep the command, cwd and exit
status with the task record. Afterward:

```bash
git -C "$WT" status --short
git -C "$WT" diff --stat "$BASE"...
git -C "$WT" diff "$BASE"...
# run verification yourself before adopting anything
```

## Adapter patterns

### Print mode

Use a non-interactive print mode for automation and capture the stream as the log. A PTY caveat
applies: interactive sessions need a real terminal. Use a terminal multiplexer rather than a raw
non-PTY background shell when the UI expects terminal control.

### One-shot exec

Use when you can provide a precise prompt and validation commands. Keep sandbox/approval settings
explicit and appropriate to the repository: an unrestricted sandbox is an intentional choice, never a
default the adapter assumes.

### One-shot run

Use for bounded tasks; use an interactive or background session for larger work. Select the model
explicitly when the CLI allows it — no default model belongs in this protocol.

Always capture:

- command invoked
- worktree path
- exit status
- files changed
- tests run
- agent summary

## Pointing an agent at a custom gateway (provider / model config)

Each CLI keeps its own provider config AND its own credential store. One shared key file is not
enough, and each copy needs its own live check. The protocol is:

1. Read the harness's provider config from its own documented config path (the path is the harness's
   fact, not this skill's default).
2. Put the secret in the harness's credential store, not in a shell export unless the harness
   documents that it reads the shell environment.
3. Probe the route with one trivial request; a config read proves nothing.

Observed adapter notes (labelled examples, keep them for diagnosis, not as defaults):

| Adapter family | Provider config shape | Credential shape |
|---|---|---|
| harness with named providers | `<harness config>` → `providers.<name>` and model aliases | the harness's own env/credential file; each profile may have its own |
| CLI with an explicit service environment | `<harness config>` → `providers.<name>` | the CLI's service environment command; a shell export may not reach the background service |
| CLI with a TOML model-provider table | `<harness config>` → `[model_providers.<name>]` + per-profile config | declared as an env key, exported from the shell that launches it |
| CLI with an overlay patch | `<harness config>` → a provider block | the CLI's credentials file, referenced by name |

One-shot live checks — a config read proves nothing:

```bash
# Substitute the installed CLI and its own flags; each must answer exactly.
<cli> exec -p <profile> --skip-git-repo-check "Reply with exactly: OK"
<cli> run --model <provider>/<model> "Reply with exactly: OK"
<cli> headless --patch <overlay.yml> "Reply with exactly: OK"
```

- A harness that accepts only a Responses-style wire protocol rejects a chat-style provider setting at
  config parse (for example `wire_api = "chat"`). A custom gateway must serve the path the harness
  requires. Probe that path before concluding the harness cannot drive a gateway — an
  OpenAI-compatible gateway answering `/v1/chat/completions` may well answer `/v1/responses` too, and
  a stale config comment claiming 404 is not evidence.
- Tool-schema failures in some harnesses are model-independent: a plugin registering a tool whose JSON
  schema contains a non-keyword such as `"optional"` makes EVERY model fail with
  `Tool N function has invalid 'parameters' schema`, before any provider is called. Verify the route
  with the plugin absent — throwaway config via the CLI's config override env var plus its standalone
  mode — before touching the provider entry.

## Monitoring and Integration

1. Start the agent with a bounded prompt and a clear "do not merge" instruction.
2. Poll logs/process status without interrupting unnecessarily.
3. Inspect the diff yourself. Subagent self-reports are not proof.
4. Run the acceptance tests in the worktree.
5. If adopting changes, commit with a human-readable message and open/review a PR through the project's
   normal publish path.
6. Clean up worktrees only after integration or explicit abandonment.

### A malformed report is not a failed run

When the run terminated successfully, its expected artifacts exist inside the declared write scope, and
the report already contains the business facts, a parse error is an encoding defect, not a failed task.
Ask once, in the **same session**, to restate those facts in the required shape — no tools, no file
reads, no writes, no new investigation. Budget: **1** re-encode per dispatch; keep the original report,
the re-encoded report and the real parse error side by side, because the error is the evidence.

This repair does not apply to a non-zero or cancelled run, to missing or out-of-scope artifacts, or to
a report that never contained the business facts. Those are real failures: stop and report. Re-running
the task cannot conjure a missing fact, and a second re-encode never becomes valid.

## Common Pitfalls

1. Launching agents in the same checkout and causing file conflicts.
2. Giving vague prompts without acceptance criteria or non-goals.
3. Trusting an agent's "tests passed" claim without rerunning tests.
4. Letting agents merge/push destructive changes without review.
5. Forgetting that interactive CLIs often require a PTY/terminal multiplexer.
6. Losing logs; always tee or capture output for long-running work.
7. Reading "one harness works" as "the provider is configured" — provider config and credentials are
   per harness and, where profiles exist, per profile; check each copy.
8. Debugging the provider route before the harness's own layers — a banned wire protocol or an invalid
   tool schema fails before the model is ever called.
9. Counting a background child that ended without a terminal result (`status=unknown`, owner exit,
   compaction, interruption) as a completed check. Its work is **uncovered**, not passed: verify each
   claim yourself or report the gap in coverage, exactly as with a self-reported "tests passed".

## Verification Checklist

- [ ] Worktree/branch/task spec created, or a deliberate no-worktree reason exists.
- [ ] Agent command, cwd, and logs are recorded.
- [ ] Diff inspected by the operator/you, not only by the child agent.
- [ ] Acceptance commands rerun and real output captured.
- [ ] Whether a format-only re-encode was used is recorded; if one was, the budget of **1** per dispatch
      was respected.
- [ ] Each acceptance claim names its level: **provisioned** (files/config exist), **probed** (an
      identity echo answered), or **accepted** (the real path ran and its artifact met its gate).
      "reply with exactly: OK" is a probe, never acceptance.
- [ ] Integration path (commit/PR/cleanup) completed or explicitly deferred.

## Configuration

| Key | Env | Default |
|---|---|---|
| `worktree_root` | `DELEGATION_WORKTREE_ROOT` | `.worktrees` |
| `log_root` | `DELEGATION_LOG_ROOT` | `logs` |
| `task_spec` | `DELEGATION_TASK_SPEC` | `TASK.md` |
| `base_ref` | `DELEGATION_BASE_REF` | `origin/HEAD` |
| `launcher` | `DELEGATION_LAUNCHER` | none — the harness CLI or wrapper to invoke |
| `model` | `DELEGATION_MODEL` | none — passed by the caller when the CLI accepts it |
| `sandbox_mode` | `DELEGATION_SANDBOX` | none — an explicit choice, never a silent fallback |
| `max_time` | `DELEGATION_MAX_TIME` | none — the harness's own limit, when it has one |

Read `$XDG_CONFIG_HOME/ai-coding-agent-delegation/config.yaml` (fallback `~/.config/...`) when
present; a flag or env var overrides the file. This skill never chooses a harness, a model or a
sandbox level on the operator's behalf.
