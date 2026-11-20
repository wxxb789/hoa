# Result reader notes

For the Feb 26 slot the child moved its JSON from `latest.json` into a
per-attempt directory. The readLatest adapter still checks the old top-level
name and then scans the slot cache. Rows 64 and 96 had cache files from a
rehearsal; 128 had no cached output. Exit 23 says the child stopped but does
not carry the overshoot, bound or retry outcome. readStdout is not affected.
The Feb 19 child and reader used the same top-level filename.

Legacy package refused the production instrument because it does not ship the
new index. The pilot instead observed pointerover to visible in the old page;
the current build recorded its own page observer in addition to the controller
stopwatch. No other repeats of the current middle-sized pilot survived.
