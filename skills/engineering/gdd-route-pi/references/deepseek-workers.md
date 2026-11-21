# Directing DeepSeek workers on Pi

Confirmed operating notes for Pi with a DeepSeek model at high thinking levels, as of 2026-11-21. Each note was
observed in two or more runs.

## Budget time, not tokens

DeepSeek at `max` thinking takes about ten times the wall time of other runtimes on the same task. Give trials and
stages their own timeout, roughly ten times another runtime's: the necessity runner defaults Pi to 3000 seconds.
Never reuse another runtime's timeout. When the provider is free, spend the extra tokens on verification and
retries, and spend design effort on wall time.

## Isolation needs a filesystem boundary

Redirecting `HOME`, XDG directories, `PI_CODING_AGENT_DIR` and the session directory does not hide anything.
DeepSeek explores by absolute path: it read host skill directories outside the redirected home in natural-mode
control arms. Anything the worker must not see needs a real boundary, such as the necessity runner's
`--sandbox wsl` (an unprivileged user in Bubblewrap with no Windows drives), or it must not be on disk during the run.
Audit session logs afterwards in either case.

## Hand over the gate as one runnable command

Give the worker one command that runs the acceptance gate end to end, and state that it must pass. With that, Pi
workers iterated on their own failures to a passing gate without operator intervention in both arms of a
multi-hour .NET change. Without it, prose acceptance criteria are easy to claim and hard to check.

## Shape the brief for a bounded job

DeepSeek on Pi delivered reviewed, gate-passing work on bounded jobs: authoring an eval task with a fixture, and
fixing one reviewed defect in a build harness. Briefs that worked named the exact files to create or change, pointed
at real examples to copy, asked for a test that fails before the change and passes after, gave the runnable checks
that must pass, listed what not to touch, and fixed the report format. It follows a brief literally, including the
brief's mistakes: check every path and convention in the brief against the repository before sending, and ask it to
report conflicts instead of working around them. Keep open-ended design and judgment calls for a stronger model.

## Pair it with an independent reviewer

For a feature larger than one defect, split the work into one-change briefs. Have a stronger model review the
combined diff read-only, then give DeepSeek one more brief that applies the review findings. Its own tests prove what
the brief asked for, not the design behind it: two green batches still had review findings, including correctness
gaps that came from the spec itself. Review the spec's failure modes before the first brief, such as detached,
failed or resumed runs, untrusted path segments, shell shims, and key collisions. When a file has a hard size cap,
say where overflow text goes; under a cap it otherwise rewraps unrelated lines to fit.

Have the spec pre-review return replacement text that a literal implementer can follow without making its own
design decisions, and paste that text into the brief verbatim. Two specs handled this way drew 0 and 1 P1 in code
review, against 4 for a spec that was not pre-reviewed. The one P1 was an invariant the spec stated only in prose
("never echo the matched value"). For each such invariant, the brief asks for a test that checks it on every output
path. On Windows, also list `git ls-files --eol <new files>` among the gates: a new file can be committed with CRLF
line endings and still pass the other checks.
