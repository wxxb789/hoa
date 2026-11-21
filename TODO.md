# Maintenance

- **Compatibility candidates:** Check external callers before removing the hidden `start` flags
  registered in `main` in [agent_run.py](skills/gdd/scripts/agent_run.py). The
  [OMP route](skills/gdd-route-omp/scripts/route.py) accepts `--backend` (warns)
  and forwards `--profile`; the [DSH route](skills/gdd-route-dsh/scripts/route.py)
  accepts `--session-id` as a resume alias. The tracked direct calls are in
  `test_legacy_start_flags` in the respective route suites.
- **Keep the OMP forwarder:** `skills/gdd-route-omp/scripts/omp-run.sh` is a documented POSIX
  entry point in [gdd-route-omp's detach rules](skills/gdd-route-omp/SKILL.md#rule-never-launch-omp-as-a-bare-background-job-of-the-session).
  See `test_t15_omp_headless_forwarder_resolves_the_sibling_runner` in
  [test_agent_run.py](skills/gdd/scripts/tests/test_agent_run.py).
- **2027-04: Ubuntu 22.04 leaves standard support.** Raise `TMUX_MIN_VERSION` to 24.04's 3.4
  in [agent_run.py](skills/gdd/scripts/agent_run.py). Update the 3.2a documentation in
  [transport.md](skills/gdd/references/transport.md#headless-platform-rules),
  [run-failure-modes.md](skills/gdd/references/run-failure-modes.md) (detach-mode table),
  [gdd-route-omp](skills/gdd-route-omp/SKILL.md#rule-never-launch-omp-as-a-bare-background-job-of-the-session),
  and [gdd-route-dsh](skills/gdd-route-dsh/SKILL.md#configuration). Update the default version
  in `SUPERVISOR` and the cases in `test_tmux_version_floor` in
  [test_detach_supervisors.py](skills/gdd/scripts/tests/test_detach_supervisors.py).
- **Managed resume deferred:** `gdd.py stage --resume-run` is not implemented; the design is in the
  2026-11-21 GDD resume-cap pre-review.
