# Handing an adjudicated spec to the implementation run

Rules for the step between "a model produced a design" and "an implementer is working on it". Each one
was paid for by a stage that had to be redone.

## Choose the route before you write the prompt

- **Never dispatch a run through the component that run is changing.** Hardening or replacing launcher X
  by running X makes the object under test the harness executing the edit, has the run edit its own
  running supervisor's source, and leaves the run's own artifacts unattestable. Dispatch through a
  different route (or a pristine copy) and write one line in the report saying why that route was
  chosen — the choice is evidence, not trivia.
- Prefer the route whose own code is untouched by the change, even when the dogfooding route is the one
  the increment exists to prove: the proof can come from the acceptance run afterwards.

## Verify the run actually started before reporting it dispatched

- A `started: <slug>` line is printed before the agent's first token. It is not evidence.
- Confirm, in this order: `status <slug>` leaving the starting state and showing `state: running`; the
  event log (`events.ndjson`) growing; and — the real signal — the last few events carrying thinking or
  tool activity that names symbols from the files the task is about. An agent thinking about a
  different file than the one you asked about is a prompt problem caught in minute two instead of hour
  two.
- Report "dispatched" only after that check. On a JSON-mode run, poll `status`, never `tail`: each event
  can carry the full prompt of every sub-agent, so one tail floods the context for no signal.

## Give every long run a watcher

- Background loop: poll `status <slug>` every 30 s, exit when `state` leaves `running`, cap the loop
  just above `--max-time`, then print `result <slug>` on exit. With completion notification enabled this
  turns a multi-hour stage into one ping.
- A detached run outlives the watcher: if the watcher dies with the session you lose the ping, not the
  run. Re-attach by polling `status` again — never by restarting the run.
- Do not poll in the foreground with a sleep cap: a foreground wait blocks the channel for the whole
  stage and gives nothing the background watcher does not.

## Freeze the round's scope in the prompt

- Name the files the run may change, and require it to **stop and report** rather than widen scope
  itself. An allowed-file list is also what makes `git status --porcelain` reviewable at acceptance.
- Ask for the two honest outputs: a per-rule table (rule → where implemented → test → the mutation that
  makes that test fail) and an explicit "what is NOT done" section. A run that cannot finish everything
  in one round must stop at a clean boundary — suite green, tree compiling, gaps listed. A silent
  partial is a failure; an honest partial is an acceptable round.
- State the interpreter/runner quirks of the host in the prompt (which python has the gate's
  dependencies, which commands are expected to fail locally) so a false alarm does not come back as a
  finding.
