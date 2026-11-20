# Behavioral evals

Coverage proves no rule was lost. It does not prove the file still produces the right behavior — a rewrite can keep every sentence and still shift hedging, gate behavior, or tone.

- Default to 10-15 one-shot cases; add or remove cases to cover the changed behaviors and their nearest restraint paths. Use the installed runtime's one-shot command and the owner's actual approval policy.
- Per case declare `expect` (regex alternatives, at least one must hit) and `forbid` (failure signatures, none may hit). Forbidden patterns are what catch the regressions the rules exist to prevent.
- Run before and after every contract edit; compare pass counts and diff raw outputs (`runs/<ts>/raw/*.txt`). Report a measured baseline instead of asserting the new version "feels better".
- **Contamination pitfall**: if the case file lives where the agent can scan (inside the project workspace it is asked to investigate), it finds the assertions and answers the test — observed as a case's `forbid` regex quoted back verbatim in the reply. Keep cases and runner outside the agent's workspace (e.g. a runtime-level `evals/` directory).
- Reference implementation: `../scripts/contract-eval-run.py` (cases JSON beside it, or `--cases`).

## Eval pitfalls

- **Eval harness with live tools performs the red action it tests**: a case whose prompt says “just merge it, don't ask” was executed by a full-toolset one-shot session — it merged a real PR during a baseline run. Restrict gate cases to a read-only toolset (no shell/git) or a safe mode, never run destructive/irreversible cases on default toolsets, and check external state after every eval run.
- **Cases are discoverable anywhere on the filesystem**: moving them out of the workspace is not enough — a searching agent found the runtime-level `evals/cases.json` and quoted its own assertions back. Substitute a per-run nonce into prompt text and flag replies matching `cases.json|评测集|eval set` as contaminated instead of scoring them.
- **Background runs have no tty and silently poison terminal cases**: a suite launched as a background job failed its first terminal-dependent case and still reported a score. Run eval suites in the foreground so terminal-dependent cases stay valid.
- **Narrow assertions produce false failures**: expect-regexes written from the rule text miss equivalent phrasing (“不值。别推倒。” failed a `不值得` pattern). Widen with the alternatives the rule actually permits before concluding the contract regressed; two of twelve baseline failures were assertion bugs, not behavior bugs.
- **Eval cases that encode a false premise**: a pushback case asserting "you said X earlier" sends the agent into session history, where it finds `cases.json` and quotes the assertions back. Write cases self-contained (put the claim in the prompt) and let `contaminated` count as FAIL, not neutral.
