---
name: repo-gate-execution
description: Execute a declared gate spec against a repository checkout and record an evidence-backed
  gate result. Use when a gate-spec artifact names the commands, scope and expected evidence for a
  verification pass, and the outcome must be reported without inventing commands, editing code, or
  rerunning until green. Not for designing gates, diagnosing failures, or repairing the repository.
metadata:
  version: "0.1.19"
  areas: "software-development"
  targets: "runtime-agnostic"
  kind: "mechanism"
  consumes: "gate-spec"
  produces: "gate-result"
---

# Repo gate execution

A mechanism, not a router: it consumes one `gate-spec` and produces one `gate-result`. It never
decides which gate applies and never changes the repository to make a gate pass.

## 1. Read the spec, do not fill its gaps

- Require the checkout path, the ordered commands with their `cwd`/environment, the timeout, the
  expected evidence, and the output path.
- Treat a missing field as `blocked`. Do not substitute a familiar command, a default timeout, or a
  nearby checkout.
- Record the spec's source and version beside every result so a later run can be compared.

## 2. Freeze the checkout fingerprint

- Record the commit SHA, branch, and `git status --short` before the first command.
- If the spec pins a revision, require that revision. Never check out, stash, reset, or clean on the
  spec's behalf.
- Record the interpreter/tool versions the spec names; an unrecorded version is an unverifiable
  result.

## 3. Execute exactly the declared commands

- Run each command once, in order, from the declared directory. Do not add flags, pipe through a
  convenience filter, or retry beyond the spec's own retry rule.
- Capture exit code, duration, stdout, and stderr per command into the run's evidence directory.
- A timeout, a missing prerequisite, or a command that never started is `blocked`; an executed
  command with a non-zero exit code is `fail`.
- Keep partial evidence. A run interrupted after the first command is not a pass for the remaining
  commands.

## 4. Classify the result

- `pass` only when every required command succeeded under the spec's success rule and every named
  evidence file exists.
- `fail` when an executed check failed or its required evidence is absent.
- `blocked` when the spec, checkout, or prerequisites prevent execution.
- Never upgrade `blocked` to `fail` or `pass`, and never report an unrun command as a skip that
  counts toward success.

## 5. Emit the gate result

The `gate-result` artifact contains:

- gate id and spec source;
- checkout fingerprint (SHA, branch, dirty state);
- a command table: command, cwd, exit code, duration, evidence path;
- the verdict (`pass` / `fail` / `blocked`) and the exact rule that produced it;
- every deviation from the spec, including missing evidence and interrupted runs.

Stop at the result. Do not fix the code, widen the scope, or rerun to manufacture a different
verdict; hand the result back to the caller.
