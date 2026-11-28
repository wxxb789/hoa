# Reading a red required step

One leg red, every other step green, the annotation naming only the step. Get the assertion, the cause and
the block classification before reporting anything — "CI is red" without a cause sends the next session to
the wrong file.

- **The pretty log elides the assertion.** A gate that abbreviates its own nested output (an inserted `…`,
  a collapsed runner summary) leaves the hosted log with the step name and nothing else. Per-job logs come
  from `gh api repos/<owner>/<repo>/actions/jobs/<job-id>/logs`, which refuses with "the response contains
  terminal escape sequences" unless `--allow-escape-sequences` is passed; job ids come from
  `gh run view <run-id> --json jobs`. An unread log is unknown, not a pass.
- **Separate the root cause from its cascade.** Several failing cases inside one required step are often
  one cause: a self-test that asserts over a nested runner reports the nested failure once
  (`broken: <case>`) while every outer case wrapping that run fails with it. Report the named cause and the
  cases it took down, not N defects.
- **Check whether the failing step is even the failure.** A step the log marks skipped, partial or
  boundary on one platform (a checkout a path length defeats, a missing toolchain) is a disclosed
  boundary; naming it as the red is a false finding.
- **Distinguish a host-level block from the project's own rule.** Read
  `gh pr view --json mergeable,mergeStateStatus` and the base branch's protection (`gh api
  repos/<owner>/<repo>/branches/<branch>/protection`). A mergeable pull request on an unprotected base is
  not blocked by the platform — the block is a repo rule (an all-green required gate, an operator-owned
  merge), and saying which one is what decides the fix.
- **Read the repo's own review lanes and decision record for that head before re-deriving.** A standing
  review lane has usually already named the cause and what each earlier fix round resolved; the decision
  record says which of its findings were accepted. Still read the code line a finding cites before
  relaying it as fact, and cite the lane's report path beside your own reading.
- **Report the cause, the single next change, and what closes the loop.** Say what one edit would move the
  leg green, and name the platform whose oracle only the hosted leg can supply — an increment that touches a
  premise only the foreign leg can settle costs one full CI round per assertion, which is a reason to
  state the round's premise coverage up front rather than discover it a leg at a time.
