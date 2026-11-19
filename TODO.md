# Maintenance

- **Compatibility candidates:** Remove the hidden `agent_run.py start` flags only after checking
  external callers. The parser still accepts them (`skills/gdd/scripts/agent_run.py:1536`).
  `--backend` only warns; `--session-id` aliases `--resume` for DSH
  (`skills/gdd/scripts/agent_run.py:1226`), and OMP's `--profile` still reaches the CLI
  (`skills/gdd/scripts/agent_run.py:914`). The legacy-flags test is the only tracked direct caller
  found (`skills/gdd/scripts/tests/test_agent_run.py:224`).
- **Keep the OMP forwarder:** `skills/gdd-route-omp/scripts/omp-run.sh` is a documented POSIX
  entry point (`skills/gdd-route-omp/SKILL.md:59`) exercised by
  `skills/gdd/scripts/tests/test_agent_run.py:632`.
- **2027-04: Ubuntu 22.04 leaves standard support.** Raise `TMUX_MIN_VERSION` to 24.04's 3.4
  (`skills/gdd/scripts/agent_run.py:83`). Update the 3.2a documentation at
  `skills/gdd/references/transport.md:49`, `skills/gdd/references/run-failure-modes.md:121`,
  `skills/gdd-route-omp/SKILL.md:50`, and `skills/gdd-route-dsh/SKILL.md:168`. Update the fake
  tmux version and boundary cases at `skills/gdd/scripts/tests/test_detach_supervisors.py:50`
  and `skills/gdd/scripts/tests/test_detach_supervisors.py:264`.
