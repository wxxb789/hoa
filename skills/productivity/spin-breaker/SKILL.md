---
name: spin-breaker
description: >-
  Manual spin breaker. `lock` runs a 3-element pre-flight lock (target surface,
  observable check, forbidden boundary) before edits or delegation; default
  `rescue` halts loops, parks side quests and 4-line restart breadcrumbs, and
  proposes one discriminating read-only probe; `map` renders a static HTML
  decision board. Use spec-convergence for full spec design, ce-debug for
  root-cause debugging.
disable-model-invocation: true
metadata:
  revision: "1"
  areas: "self-management,software-development"
  targets: "runtime-agnostic"
  summary: "halt pre-execution or mid-session spinning: 3-element execution lock, 5-line reckoning, parked side quests, restart breadcrumbs, static HTML decision board"
  summary_zh: "开工前或中途打转时刹车：3 要素执行锁、5 行现状清点、停放 side quest、重启面包屑与静态 HTML 决策板"
  kind: "entry"
---

# spin-breaker

Explicit-invocation circuit breaker for two failure modes:

- **Pre-execution drift**: edits or delegation start while the target surface,
  the observable acceptance check, or the forbidden boundary is still implicit.
- **Mid-session spinning**: unfalsified guesses accumulate, emergent meta-ideas
  silently widen the acceptance envelope, and repeated `continue` eliminates
  nothing.

## Gates

1. **Immediate write/dispatch freeze.** On invocation, halt code edits, branch
   switches, commits, external memory writes, and background worker dispatches
   until the operator explicitly selects an option in the current turn.
2. **Host UI with plain-text fallback.** Present choices through the host's
   native single-select form control when it exists; if that UI is unavailable
   or disconnects, immediately present numbered plain-text options (`A / B / C`)
   so one short reply resolves the choice.
3. **Side-effect confirmation.** Never run a state-mutating command, discard Git
   changes, or invoke an external parking adapter without explicit operator
   confirmation (`--confirm-external` gates the external adapter).
4. **Artifact containment.** All generated HTML maps and local parked records
   live strictly under `<repo-root>/.tmp-artifacts/<bundle-name>/`; never
   scatter them in the repo root or tracked directories.

## Mode selection

Pick the mode from the user's argument or the conversation state:

- `lock` (or any invocation right before starting implementation or
  delegation): the **pre-flight 15-second execution lock** below.
- Default / `rescue` (invoked mid-session while spinning, after repeated
  `continue`, or after scope creep): the **mid-spin rescue** below.
- `map` (`spin-breaker map`, or when 3+ entangled hypotheses, surfaces, or
  environments make linear chat illegible): the **decision board** below.

### Pre-flight 15-second execution lock

Inspect the pending request and verify three elements before any edit:

1. **Target surface** — the exact client/app/CLI/host/tenant where acceptance
   will be observed, not a proxy cache, mock, or staging ticket.
2. **Observable check** — input `X` produces expected output `Y`, plus what
   visibly fails while the change is absent.
3. **Forbidden boundary** — the files, branches, policies, or manual-vs-auto
   triggers that must NOT change.

If all three are unambiguous, display the 3-line lock card for one-click
confirmation:

```text
Lock — Target: <surface> | Check: <X -> Y; absent-state failure> | Forbidden: <boundary>
Proceed / Adjust
```

If any element is missing or ambiguous, ask only for the missing item(s), with
concrete options and after read-only repo/state inspection, before any edit.

### Mid-spin rescue

Read the recent turns plus read-only `git status --short` and `git diff --stat`.

1. Extract mixed-in **side quests and meta-ideas** that expanded the original
   acceptance envelope; offer to park each via `spin_breaker.py park
   --kind side-quest`.
2. Output **at most 5 lines** of plain reckoning:

| Line | Content |
|---|---|
| 1 `Outcome` | The single original user-visible result requested. |
| 2 `Last verified fact` | The last directly observed fact, with exact `file:line`, command exit, or target surface. |
| 3 `Eliminated vs. live guesses` | Which hypothesis line 2 ruled out (say `0 eliminated` when none), versus the live unfalsified guesses. |
| 4 `Discriminating probe` | One minimal read-only command or observation that splits or falsifies the top live hypothesis, stating what pass vs. fail proves. |
| 5 `Decision` | The 3-way choice: `A. Run probe` (execute only the line-4 read-only probe), `B. Freeze & Park` (write a 4-line restart breadcrumb via `park --kind breadcrumb` and stop cleanly), `C. Retire branch/approach` (record the falsified lesson via `park`, then await explicit rollback authorization before touching Git state). |

### Decision board

When 3+ entangled hypotheses, surfaces, or environments make linear chat
illegible, gather structured JSON of the outcome, verified facts,
live/eliminated hypotheses, next probe, and parked side quests, then run
`uv run scripts/spin_breaker.py map --input <file>`:

```json
{
  "outcome": "Single user-visible result requested",
  "verified_facts": ["fact with file:line or command exit"],
  "hypotheses": [
    {"text": "live guess", "status": "live", "note": "optional note"},
    {"text": "dead guess", "status": "eliminated"}
  ],
  "probe": {"command": "read-only command", "pass": "what a pass proves", "fail": "what a fail proves"},
  "side_quests": [{"title": "parked side quest", "note": "optional note"}]
}
```

The rendered board is a self-contained static HTML file (inline CSS, no
scripts, no external assets, dark/light via `prefers-color-scheme`) with three
columns: target outcome and verified facts; the active fork (live hypotheses,
the single discriminating probe, and the 3-way action summary); eliminated
hypotheses and parked side quests.

## Commands

Run these with the target repository as the current working directory (or pass
`--repo-root <repo>` explicitly). Point `S` at this skill's script — in a
checkout that is `skills/productivity/spin-breaker/scripts/spin_breaker.py`,
installed it is `<skill-dir>/scripts/spin_breaker.py` — and invoke it with `uv`.
Parked records default to
`<repo-root>/.tmp-artifacts/spin-breaker/parked-items.md`. Bundle names are
single safe directory names: no separators, `:`, `..`, trailing dots, or
Windows reserved device names.

```bash
S=<skill-dir>/scripts/spin_breaker.py

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

# Render the decision board from a JSON document on stdin
# (checkout form: uv run skills/productivity/spin-breaker/scripts/spin_breaker.py map ...)
printf '%s' '{"outcome": "…", "verified_facts": [], "hypotheses": [], "side_quests": []}' \
  | uv run "$S" map --repo-root . --input - --bundle board-1
```

Both commands print a compact JSON receipt on stdout. `map` never reuses an
existing `--bundle` directory, and with the flag omitted it picks a fresh
`spin-map-<UTC timestamp>` name (suffixed `-2`, `-3`, … if one already exists).
`--confirm-external` is required before a configured external adapter command
runs; without it the receipt reports `"external_status": "skipped_unconfirmed"`
and no external mutation happens.

## Configuration

Resolution order for every key: CLI flag, then `SPIN_BREAKER_*` environment
variable, then `$XDG_CONFIG_HOME/spin-breaker/config.yaml` (falling back to
`~/.config/spin-breaker/config.yaml`), then the default. See
[references/configuration.md](references/configuration.md).

| Key | Flag | Environment variable | Default |
|---|---|---|---|
| `repo_root` | `--repo-root` | `SPIN_BREAKER_REPO_ROOT` | `.` (current directory) |
| `parking_bundle` | `--parking-bundle` | `SPIN_BREAKER_PARKING_BUNDLE` | `spin-breaker` |
| `external_cmd` | `--external-cmd` | `SPIN_BREAKER_EXTERNAL_CMD` | none (empty; local markdown only) |
| `external_timeout` | `--external-timeout` | `SPIN_BREAKER_EXTERNAL_TIMEOUT` | `15` (seconds) |

`external_cmd` is split with `shlex` and run with `shell=False`, so for direct
executables (`uv`, Python, native binaries) there is no shell expansion and the
item text cannot inject a command. The formatted item text replaces a `{text}`
placeholder inside one argument when the placeholder is present; otherwise it
is piped to the adapter's stdin. On Windows, `.cmd` and `.bat` wrappers are
executed through `cmd.exe` by the OS, so give those adapters the text via
stdin instead of a `{text}` argument. Quote paths that contain backslashes.

Only if a script command fails (for example `uv` is not found), read [references/troubleshooting.md](references/troubleshooting.md).
