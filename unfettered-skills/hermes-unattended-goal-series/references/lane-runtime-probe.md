# Probing a lane runtime

How to establish what a headless agent CLI actually does before a goal series depends on it — plus the
facts one such probe settled for the DSH runtime. Re-run the probe after a CLI upgrade; every line below
came from a real three-round run (one session, real code + tests), not from vendor docs.

## The four properties, and the controls that prove them

| Property | Probe | What a report omits |
|---|---|---|
| Invocation shape | dispatch one trivial task; read the exit code, the artifact it wrote, and what happens with no task at all | the empty-input case is a usage error, exit 1, no artifacts |
| Event schema | one run with the CLI's machine-readable mode; enumerate the event `type`s and the fields of each | which event is absent on failure — a missing final message is not an exit class |
| Session binding | resume the same session id from a **different directory** | refusal + exit 1 + both paths named; a session id is not portable across worktrees |
| Failure exits | unknown session id, empty input, a task the CLI rejects before starting | the run writes nothing, so “no output” must not read as “still running” |
| Option binding | run once with the mode/preset flag and once without, and compare **inventories** | a flag that loads while its service never binds looks identical to the default run |

Continuity itself needs its own evidence: after several rounds in one session, require the later round's
own report to cite a fact from an earlier one (the tree state it left, the approach it rejected). A shared
session file proves only that a log grew.

## DSH runtime, as probed

```bash
dsh --profile headless --json --permission-mode workspace-write --approval-policy never - < prompt.md
```

- `--json` emits NDJSON events; without it only the final text prints at exit. `-` reads the task from
  stdin, so the prompt is a FILE (dispatch rule), never an argv blob.
- Event types: `session{sessionId,cwd}` · `status{turn,step,phase,reason,usage}` · `thinking{text}` ·
  `text{text}` · `tool_call{callId,tool,input}` · `tool_result{callId,status,result,truncated}` ·
  `final{sessionId,reason.kind,text}` · `error{message}`.
- `final` is absent on failure: derive the exit class from the `error` event plus the process status.
  Unknown session id and empty stdin both give `error` + exit 1 and write no run artifacts.
- One JSONL per session, keyed by the directory it was created in; each invocation appends its own
  `turn/start … turn/end`. Resuming from another directory is refused, exit 1, naming both paths — so the
  CLI enforces one worktree per goal by itself.
- Agent loop shared with the GUI entry (the two entry lists differ only by GUI-only entries), so headless
  does not shrink the tool set. Headless resolves credentials from the launch env, then `cwd/.env`, then the
  CLI home `.env`.
- A preset flag is accepted while its service never binds (`<preset>: pending (waiting for service: …)`),
  after which behaviour is byte-identical to the default: compare tool inventories, never the load line.
- Per-step `status.usage` = `{inputTokens,outputTokens,totalTokens,cacheReadTokens}`. Resuming re-sends the
  accumulated history at every step (prompt cache absorbs most), so continuity saves re-exploration steps,
  not tokens, and the cached share falls when invocations are far apart. A context nowhere near the
  compaction threshold is not evidence about compaction — report that as not tested, not as verified.

## Probe recipe

1. Throwaway repo with a real acceptance suite and one unimplemented function; `git worktree add -b
   goal/0001-… <worktree>` so the session's cwd is a dedicated tree.
2. Round 1 implements; capture the event log; then **re-run the suite yourself** — the run's green claim is
   not evidence.
3. Round 2 resumes the same session id with a correction that first adds a failing acceptance test; it must
   pass without re-reading the whole repo.
4. Round 3 resumes for a verification round that adds its own test file and reports a criterion→test map.
5. Negative controls in the same pass: resume from another directory, unknown session id, empty input, and
   the inventory comparison with/without the preset flag.
6. After every round check the write boundary: `git status --porcelain` against the surface the prompt
   named. An orchestrator-owned test file touched by the agent is a rule violation to report, not to fix.
