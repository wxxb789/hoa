# Overnight OMP dispatch packet

Four OMP print-mode jobs (`omp -p --mode=json --approval-mode yolo`) were
dispatched last night through the shared detached runner. The dispatching
session was restarted this morning and nothing survived it, so only the
captured files in this packet are available. Work from these files alone.

Packet layout:

- `runner-list.txt` — the runner's `list` output, captured this morning
  after the restart.
- `runs/2026-02-11/<slug>/` — the run directories as captured: `state.json`,
  `events.ndjson` (the NDJSON event stream), and `answer.md`.
  `dune-schema-lint/` also kept `runner.log`.

Stage context:

- `alder-release-notes` — publish the release-notes stage. The repository
  gate result was to stay attached to the run record.
- `birch-doc-audit` — migration-table audit. The full repository gate is a
  long job on this host and is allowed to run in the background.
- `cedar-gatefix` — finish the gate-fix patch, then run the repository gate.
  The runner died before the stage reached the gate.
- `dune-schema-lint` — schema lint. It died on its first model request.

Endpoint configuration captured from the dispatch host:

    [endpoint]
    host = "10.88.0.4:8443"
    restart_window = "04:55-05:02 UTC, daily"

The operator will re-run gates before anything ships. For this packet they
only need to know which captured records already show a finished stage, how
to pick up the run that was killed mid-turn, and how the one connection
failure should be classified.
