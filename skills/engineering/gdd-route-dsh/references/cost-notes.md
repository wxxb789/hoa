# DSH cost notes (measured on one host)

- A small increment: 20–90 s, 7–10 steps, 6–20 tool calls, 3–17 k output tokens.
- Resuming an unrelated increment re-sent the accumulated context: about 8× the first-step input of a
  fresh session, for no benefit.
- A one-file scanner/audit task: 6 shell calls (native executor) vs 1 `run_code` call (PTC) for the
  same correct answer. PTC halved the round trips but roughly doubled non-cached input.
- A large increment in one turn (adapter + tests + docs) ran 23 min / 122 tool calls. Splitting it
  into two invocations kept it observable.
