# Pi natural-mode screen in the WSL sandbox, 2026-11-21

First necessity runs with `--runtime pi --sandbox wsl`: Pi 1.6.0, `tencent-litellm/deepseek-v4.1-flash-fast`,
thinking `max`, k=3, set-b tasks, run serially on 2026-11-20 (UTC). Earlier natural-mode Pi runs were invalid because
control arms read host skills by absolute path; in the sandbox they cannot.

| Task | Mode | Verdict | Passed none / terse / skill | Skill loaded (skill arm) |
|---|---|---|---|---|
| gdd-route-omp | forced | **skill-wins** | 0/3 / 0/3 / 3/3 | 3/3 |
| gdd-route-omp | natural | inconclusive | 0/3 / 0/3 / 2/3 | 2/3 |
| ghc-search | natural | inconclusive (1 control trial flagged) | 0/2 valid / 0/3 / 3/3 | 3/3 |
| ghc-search (rerun with path capture) | natural | **skill-wins** | 0/3 / 0/3 / 3/3 | 3/3 |
| hoa-skill-curate | natural | no-difference | 0/3 / 0/3 / 1/3 (mean 0.22 / 0.33 / 0.78) | 3/3 |
| report-claim-audit | natural | no-difference | 3/3 / 0/3 / 2/3 | 3/3 |
| official-document-verification | natural | inconclusive | 3/3 / 3/3 / 3/3 | 1/3 |

Reading:

- Natural selection works for most rewritten descriptions: the model picked the skill unprompted in every trial
  for four of five tasks. `official-document-verification` was loaded 1/3, and its task is too easy to discriminate
  (every arm passed).
- `gdd-route-omp` and `ghc-search` show the skill doing work no prompt does. `hoa-skill-curate` raises the mean score
  but rarely passes in full; `report-claim-audit` adds nothing on this task, and the terse hint hurts.
- One `ghc-search` control trial was flagged `host-skill-read` inside the sandbox, where no host skills exist. The
  trace did not keep the path, so the flag could not be audited; traces now record `contamination_paths`. The rerun
  had no flags.

Caveats: one task per skill, k=3, one model. A timed benchmark shared the host during part of the run; Pi's work is
remote, so wall times here are not comparable across runs.
