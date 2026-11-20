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
