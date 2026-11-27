# Commands and external parking adapters

Run with the target repo as the current directory or pass `--repo-root <repo>`.
Set `S` to the installed `<skill-dir>/scripts/spin_breaker.py`, or to
`skills/productivity/spin-breaker/scripts/spin_breaker.py` from a checkout of
the skill repository. Invoke it with `uv` after operator confirmation.

Parked records default to `<repo-root>/.tmp-artifacts/spin-breaker/parked-items.md`.
Bundle names are single safe directory names: no separators, `:`, `..`, trailing
dots, or Windows reserved device names.

```bash
S='<skill-dir>/scripts/spin_breaker.py'

# Park a side quest (append-only; never touches Git state)
uv run "$S" park --kind side-quest \
  --title "Idea that widened the envelope" \
  --why-deferred "Not needed for the current outcome" \
  --origin-outcome "Original user-visible result" \
  --locator "src/module.py:120"

# Freeze with a 4-line restart breadcrumb
uv run "$S" park --kind breadcrumb \
  --outcome "Original user-visible result" \
  --last-fact "scripts/check.py:42 exits 0 against the live surface" \
  --eliminated "stale config cache" \
  --next-command "rg -n 'live-surface' scripts/"

# Render a decision board from JSON on stdin
printf '%s' '{"outcome": "…", "verified_facts": [], "hypotheses": [], "side_quests": []}' \
  | uv run "$S" map --repo-root . --input - --bundle board-1
```

Both commands print a compact JSON receipt on stdout. `map` never reuses an
existing `--bundle` directory. Without the flag it picks a fresh
`spin-map-<UTC timestamp>` name (suffixed `-2`, `-3`, … on collision).

## External parking adapter

Pass `--confirm-external` only after the operator explicitly confirms the
external mutation. Without it, a configured adapter is not run and the
receipt reports `"external_status": "skipped_unconfirmed"`.

`external_cmd` is split by a deterministic quote-aware tokenizer and run with
`shell=False`. One pair of outer quotes per token is removed. Inside double
quotes only `\"` unescapes to `"`; all other backslashes stay verbatim, including
in quoted Windows paths (`"C:\Tools\my-adapter.exe"`), UNC paths
(`"\\server\share\my-adapter.exe"`), and unquoted `C:\Tools\my-adapter.exe`.
Quote paths that contain spaces. For direct executables (`uv`, Python, native
binaries) there is no shell expansion and item text cannot inject a command.

The formatted item replaces `{text}` inside one argument, or goes to stdin
when no placeholder is present. On Windows `.cmd` and `.bat` adapters must
receive the entry via stdin: a `{text}` argument is rejected (exit 2) because
`cmd.exe` interprets the argument text.

An empty `--external-cmd ""` or empty `SPIN_BREAKER_EXTERNAL_CMD` counts as not
supplied and falls through to `config.yaml`. To disable a configured adapter
permanently, remove or comment out `external_cmd` in `config.yaml`. To skip it
once, omit `--confirm-external`.
