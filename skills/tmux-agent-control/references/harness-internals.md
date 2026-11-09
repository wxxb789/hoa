# TUI harness internals (worked example: omp)

Paths, formats and commands for driving or auditing an interactive harness session. A harness
installed by a version manager is usually absent from a non-interactive PATH;
`readlink -f /proc/<pane-pid>/exe` names the build a pane is actually running. State roots below are
written as `${OMP_HOME:-$HOME/.omp}` because omp is the worked example — substitute the harness's
own documented root (or its XDG default) for any other CLI.

## Live state

| What | Where |
|---|---|
| Version the running TUI reports | footer/banner `vX.Y.Z`; the version manager's `omp --version` |
| Staged self-update | `${OMP_HOME:-$HOME/.omp}/update/auto-update.json` `{phase, version, target}`; `auto-update.log` records the patched sha and the install path |
| Session logs (debug/usage) | `${OMP_HOME:-$HOME/.omp}/logs/omp.<YYYY-MM-DD>.<pid>.log`, JSON lines |
| Provider errors | grep that log for `agent turn ended with provider error` / `prefill_cap_refused`; recovery appears as `agent.continue scheduled … source=automatic-retry` |
| Models and providers | `${OMP_HOME:-$HOME/.omp}/agent/models.yml` → `providers.<name>.models` |
| Config | `${OMP_HOME:-$HOME/.omp}/agent/config.yml` (`modelRoles.default`, `update.auto`) |

## Session transcripts (history archaeology)

`${OMP_HOME:-$HOME/.omp}/agent/sessions/-<repo-path-slug>/<timestamp>_<session-id>.jsonl`, one JSON
object per line:

- `{type:"title", title}` — the auto-title. Titles carry the phase convention (`🔍 REVIEW: …`,
  `🧹 SIMP/SIMPL: …`, `✅ CHECK: …`, `🛂 BNDR: …`), the fastest way to see which pipeline phase a
  past session belonged to.
- `{type:"session", id, timestamp, cwd}` — the id for `omp --resume`.
- `{type:"message", message:{role, content}}` — `content` is a list of `{type:"text"|"thinking", …}`
  blocks; tool calls/results sit in `{type:"custom"}` records.

Read-only recipe for the operator's real asks in a past session (drop blocks starting with `<`,
which are injected reminders):

```python
import glob, json, os
root = os.environ.get("OMP_HOME", os.path.expanduser("~/.omp"))
pattern = os.path.join(root, "agent", "sessions", "*", "*.jsonl")
for f in sorted(glob.glob(pattern), key=os.path.getmtime)[-5:]:
    print('=' * 80, f)
    for line in open(f):
        d = json.loads(line)
        if d.get('type') != 'message' or d['message'].get('role') != 'user':
            continue
        text = ' '.join(c.get('text', '') for c in d['message']['content'] if c.get('type') == 'text')
        if text and not text.startswith('<'):
            print('-', text[:400].replace('\n', ' ⏎ '))
```

## Commands worth knowing

- Resume on another model after a provider stall (conversation is preserved):
  `omp --resume <session-id> --model <provider>/<model> --approval-mode yolo`.
- Provider families and model ids are host configuration: read them from `models.yml` (or the
  harness's equivalent registry); never assume an id, and pass the pairing the host is known to run.
- One-shot generation: `omp -p --no-tools --no-skills --model <provider>/<model> @prompt.md > out.md`.
- Modes: `--approval-mode yolo|write|always-ask`, `--goal="…"` (goal mode with success criteria and
  a token budget), `--plan-yolo` (read-only plan, auto-approve, then implement).
