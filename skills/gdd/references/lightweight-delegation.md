# Lightweight delegation: CLI selection and evidence

Use for a single bounded coding or review task or for independent CLI comparisons. There is no
full goal contract, stage ledger or shipping step.

- Use a separate Git worktree at a recorded base for each worker. Write a brief with permitted
  paths, non-goals, acceptance checks and expected artifacts. No shared configuration writes.
- Agree on who may stop the run, how and at what deadline before launching. Record command,
  cwd, run handle, logs and exit status. Stop on scope drift, unsafe actions or the agreed limit.
  An unknown or cancelled run is not success.
- Choose a supported print, exec, or run mode for a one-shot handoff, or an approved detached
  launcher if the job must outlive the session. Use interactive mode only when a terminal is
  available and needed. Check the installed CLI's version and help for prompt input, cwd,
  permissions, output and stop controls. Do not adopt a route's full-delivery approval settings
  by default: a Git worktree isolates edits, not permissions.
- For a configured GDD headless route, use the direct launcher contract in
  [transport.md](transport.md), not `gdd.py stage`. Verify the selected route's actual command
  and permission mode; if it is too broad, use the CLI directly with tighter permissions or
  stop. Do not substitute another CLI, provider or model without agreement.
- When using a custom provider, verify each CLI/profile separately. A configuration read proves
  provisioning; a minimal identity reply only probes connectivity. Neither proves acceptance.
  Isolate configuration diagnostics and check startup or tool-schema errors before blaming the model.
- Preserve the original report and parse error. If a successful, in-scope delivery has the required
  artifacts and facts but only the report format is wrong, allow one same-session format-only
  restatement with no tools or writes. Missing facts or artifacts, unknown state and failed runs
  are not formatting errors.
- Independently inspect the complete diff, including untracked files, verify the write scope,
  and rerun the acceptance checks. Return the evidence and keep the worktree pending separately
  authorized integration or abandonment.
