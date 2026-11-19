# Goal-mode cards, swarm, and triage auto-decompose

- **Goal-mode card** — `kanban_create(goal_mode=True)` / CLI `--goal [--goal-max-turns N]`
  (default 20): the worker runs the `/goal` Ralph loop *inside its one session*, judge-checking the
  card's title+body as acceptance criteria each turn. An exhausted budget **blocks** the card for
  human review (never a silent exit); a card judged unachievable-as-written blocks immediately. Use
  for iteration-shaped acceptance (get CI green, fix every lint error), not one-shot cards.
- **Standing multi-session goals live on the board**, not in chat: a root card stays parent of its
  graph — when the graph completes it re-promotes to `ready` and its owner
  (`kanban.orchestrator_profile`, else the card's assignee, else the active default profile) judges
  completion and adds follow-up tasks. A chat `/goal` is single-session only and never creates or
  moves cards.
- **Triage + auto-decompose** — with `kanban.auto_decompose: true`, the dispatcher runs the
  decomposer on triage cards each tick (cap `auto_decompose_per_tick`, default 3; aux model
  `auxiliary.kanban_decomposer`): drop a one-liner in triage and walk away.
  `board kanban specify <id>` = single-card spec rewrite; `board kanban decompose <id>` /
  `/kanban decompose <id>` = one-shot fan-out.
- **`board kanban swarm <goal> --worker PROFILE:TITLE[:SKILLS]… --verifier P --synthesizer P`**
  builds the canonical workers→verifier→synthesizer graph in one command — prefer it over
  hand-building that topology.
