# hermes-cron — case notes

Compressed case notes: signal, cause, fix, proof — 5–8 lines each. The rules live in `SKILL.md`;
treat these commands as leads to re-verify against the current build.

## Cron no-agent watchdog: silent dependency fallback

- **Signal**: a `no_agent` job delivered `resource watchdog unavailable: psutil import failed: No module named 'psutil'` to Discord.
- **Cause**: the script `print()`ed an optional-import diagnostic and exited 0 — with `no_agent`, stdout *is* the user-facing message.
- **Fix**: empty stdout = healthy; never print setup/dependency diagnostics; degrade silently or fall back to `/proc` (`comm`, `cmdline`, `statm` pages × `os.sysconf("SC_PAGE_SIZE")`).
- **Prove**: `python ~/.hermes/scripts/<w>.py; echo $?` and `PYTHONNOUSERSITE=1 python -S ~/.hermes/scripts/<w>.py; echo $?`; a healthy run records `Status: silent (empty output)`.
- **Pitfall**: "psutil was missing that day" is not durable knowledge — the contract (stdout = delivery) is.

## Generated decisions panel: every real task replaced by placeholder text

- **Signal**: the daily panel rendered normally, but its "Top 3" were generic boilerplate for days while
  the producing job reported `ok` on every run and no log line showed an error.
- **Cause**: two silent degradations in the same generator. (a) The candidate-source directory was a bare
  literal still naming the pre-migration location, so the extractor returned zero candidates and the
  generator fell back to placeholder lines. (b) The inbox extractor skipped any bullet that looked like a
  checkbox, which also matched source-tagged bullets (`- [Studio] …`, `- [CFO] …`) — every tagged item
  was dropped, leaving only the untagged remainder.
- **Fix**: source path → env override + candidate list taking the first existing directory, fallback text
  labelled as fallback, checkbox filter narrowed to real checkboxes so tagged bullets survive.
- **Prove**: load the pre-edit copy and the patched copy in one interpreter against the same fixture file
  and compare extractor counts (measured: 1 → 3 items returned, the genuine checkbox still excluded).
  The pre-edit backup is the control; with no copy of the old version there is no before/after to show.
- **Pitfall**: `importlib.util.spec_from_file_location` returns `None` for a copy whose suffix is not
  `.py` (`<script>.py.bak-<ts>`) → `AttributeError: 'NoneType' object has no attribute 'loader'`. Use
  `SourceFileLoader(name, path)` + `importlib.util.spec_from_loader` so both versions load side by side.
- **Pitfall**: a panel marked read-only is fixed at the generator and regenerated in the same turn — the
  stale artifact keeps lying to every session that reads it until then, and hand-editing it hides the bug.
- **Pitfall**: proof files created next to the sources they back up (inside a synced content tree) become
  stray files for that tree's own gates; keep them under the task directory instead.
