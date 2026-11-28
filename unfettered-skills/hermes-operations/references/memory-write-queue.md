# Memory write queue (`~/.hermes/pending/memory/`) — attended handling

## Why items appear there

`tools/memory_tool.py::_background_delete_gate` is a fail-closed rule for **unattended
background-review forks**: `add` is allowed, but `patch` / `remove` (single or inside a batch) are
**never applied unattended** — they are staged as `<id>.json` under `$HERMES_HOME/pending/memory/`.
Note this is NOT `memory.write_approval` (that key is `false` here): foreground writes by the agent
apply immediately either way. Approval used to be owner-only (`/memory approve <id>` slash command);
there is no `hermes memory approve` CLI subcommand.

Owner decision (2026-11-14, policy **A**): keep the gate as-is, and make the handling as automated
as possible for the attended agent.

## What is automated and where the human boundary lies

- Automated: detection, per-item diff, apply-if-still-valid, reject-with-archive, receipts
  (`~/.hermes/scripts/memory-queue.py`).
- Automated by the tool: the pin check (an op whose `matched_entry` changed since staging is refused)
  and the char-budget check — both are real safety rails, not decoration.
- NOT automated (and this is the point): **content judgement**. A proposal can pin perfectly and
  still be wrong (a 2026-11-14 batch wanted to delete the hoa rubric/guard facts that really exist).
  The agent reviews each item and re-creates the *intent* with a foreground write when the text is
  worth keeping.

## Staleness rule (the thing that makes replays fail)

A proposal is staged against a snapshot of MEMORY.md / USER.md. Any foreground write in between
breaks its `old_text` pins, and the batch is all-or-nothing — so **proposals older than the last
memory-file mtime are stale by construction**. Observed 2026-11-14: 6 of 6 staged batches were
unappliable or wrong; the useful intents (compression, the `pi --provider ghc-proxy-chat --model
gemini-4-carbon` audit channel, the decision-question preference, the codex→carbon fix) were
re-created live with the `memory` tool in one atomic batch each, then the pendings were rejected.

## Commands

```bash
python3 ~/.hermes/scripts/memory-queue.py list
python3 ~/.hermes/scripts/memory-queue.py approve <id> [<id>...] --note "why"
python3 ~/.hermes/scripts/memory-queue.py reject  <id> [<id>...] --note "why"   # archives a copy first
```

Receipts: `~/.hermes/logs/memory-queue/ledger.jsonl` (before/after sha256 of both memory files +
the applied proposal text). Rejected proposals are archived under
`~/.hermes/logs/memory-queue/rejected/` — never silently deleted.

## Report shape for the owner

One line of conclusion (`N applied / M rejected, queue empty`) plus, per rejected item, where its
intent went. Ask the owner only for items where the *content* is contested — never for a batch that
mechanically failed on a stale pin.
