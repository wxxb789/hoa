# Is the dispatched run alive, or hung?

Use when a delegated run (agent CLI, batch harness, sub-agent fan-out) has produced no output for
minutes and "is it still working?" must be answered with evidence rather than a guess. Probe in this
order; each step is independent evidence, and step 1 alone usually decides it.

## 1. Event file: mtime and totals, never size alone

```bash
stat -c '%n %s %y' <run>/events.ndjson    # sample twice, 30-60 s apart
cat <run>/events.stats.json               # total_bytes / retained_bytes / dropped_bytes / max_bytes
```

- Advancing mtime = the run is producing events.
- **Shrinking bytes is a ring buffer, not a hang.** Harnesses cap the retained stream (8 MB is a common
  default, with an env knob such as `<TOOL>_RUN_EVENTS_MAX_BYTES`); the total keeps climbing while the
  oldest events are dropped. Judge progress from the totals file, not from `ls -l`.
- A fan-out run (5 parallel read-only reviewers) legitimately emits tens of MB in minutes — a >100 MB
  stream in ~11 minutes was healthy.

## 2. Sub-agent progress, read from the payload

The last `tool_execution_update` of the in-flight call carries that tool's partial result. For a
task/sub-agent tool it includes `contextTokens`, `cost`, `resolvedModel` and `lastIntent`:

- tokens climbing **and** `lastIntent` changing between two samples → progress;
- frozen `lastIntent` with a flat token count → the hang signal.

Do not print the event stream to get this: each event can carry every sub-agent's full prompt, so one
`tail` floods the context. Filter by event type and look at the last matching line.

## 3. Process-level activity

```bash
ps -o pid,etime,%cpu,stat -p <pid>
ss -tnp | grep "pid=<pid>"        # established socket to the provider endpoint = model stream open
ps --ppid <pid> -o pid,cmd        # spawned children show what it is doing right now
```

With a version-manager shim the pid you would grep for is not the running binary — take the pid from the
harness's own state file, not from `pgrep` on the shim path.

## 4. Respect the self-imposed deadline

A run launched with `--max-time 2h` ends itself; say that instead of calling it stuck — and read
`exit.code` / `runner.log` / `state.json` first, because a finished run needs no liveness argument at all.

## 5. Counting without lying to yourself

- Parsing the NDJSON line by line with `json.loads` and skipping failures **silently undercounts**
  (multi-KB events, a truncated head, a line that parses to a non-dict). Guard with `isinstance(o, dict)`.
- Count the event type that occurs exactly once per call (`tool_execution_start`), not the `*_update`
  events that stream per token.
- Take byte/line totals from the stats file, never from your own parse. A hand-rolled count an order of
  magnitude low is what makes a healthy run read as "barely working".
