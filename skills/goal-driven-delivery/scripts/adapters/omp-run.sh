#!/usr/bin/env bash
# omp-run.sh — reference launcher adapter for an OMP-style headless agent CLI.
#
# The goal-driven delivery tools (gdd.py, delivery-state.py) never start an
# agent themselves. They render a prompt and call a launcher that implements
# this contract:
#
#   <launcher> start --name SLUG --prompt FILE [--cwd DIR] [--model M] [--thinking L] [--max-time D]
#   <launcher> status SLUG | result SLUG | answer SLUG | kill SLUG
#
# `start` must exit 0 only after the run actually started, print `started: NAME`
# and `run dir   : DIR`, and create
#
#   <run_root>/<YYYY-MM-DD>/<SLUG>/state.json
#   <run_root>/<YYYY-MM-DD>/<SLUG>/answer.md
#
# with state.json containing at least {"name","state","exit","cwd","started",
# "ended","duration_s"} and state in running|done|killed|failed. gdd.py polls
# that file; a missing state.json is unknown, never success.
#
# This file is the reference adapter for an OMP-style CLI: it runs the agent in
# a detached tmux session (so the run outlives the caller), streams the CLI's
# `--mode=json` NDJSON events to events.ndjson, and finalizes state.json +
# answer.md when the process exits. To adapt it for another agent CLI:
#   1. point OMP_BIN at that CLI (or edit the command in cmd_start);
#   2. map --model / --thinking / --max-time to that CLI's own flags;
#   3. adapt the finalize.py written below to that CLI's event stream — it must
#      still write state.json with the fields above and answer.md with the final
#      assistant text;
#   4. keep start/status/result/answer/kill and the exit codes.
#
# Why tmux: a background job that is a child of the calling session dies with
# it, and one-shot CLI mode only prints at exit — one kill loses the whole run.
# A detached tmux session outlives the caller, and the NDJSON event log makes
# progress observable while the run is still going.
#
# Usage:
#   omp-run.sh start --name SLUG --prompt FILE [--cwd DIR] [--resume ID]
#                    [--model M] [--thinking L] [--max-time D] [--profile P]
#                    [--extra "FLAG ..."] [--replace]
#   omp-run.sh list                 # every recorded run + liveness
#   omp-run.sh status [SLUG]        # one run, or all live ones
#   omp-run.sh tail SLUG [N]        # last N event lines (default 20)
#   omp-run.sh result SLUG          # state summary + answer head
#   omp-run.sh answer SLUG          # only the final assistant text
#   omp-run.sh kill SLUG            # Ctrl-C then kill-session
#
# Environment:
#   OMP_BIN       agent binary (default: omp)
#   OMP_RUN_ROOT  base run root (default: $GDD_RUN_ROOT or
#                 ${XDG_STATE_HOME:-$HOME/.local/state}/gdd/runs)
#   OMP_LEDGER    finished-run ledger (default: <run_root>/ledger.tsv)
#
# Model / thinking / max-time have no default here: the flag is omitted when it
# is not supplied. Run artifacts: <run_root>/<date>/<SLUG>/ = prompt.md, run.sh,
# finalize.py, events.ndjson, stderr.log, state.json, exit.code, session.id,
# lock, answer.md.
set -uo pipefail

OMP_BIN="${OMP_BIN:-omp}"
RUN_ROOT_BASE="${OMP_RUN_ROOT:-${GDD_RUN_ROOT:-${XDG_STATE_HOME:-$HOME/.local/state}/gdd/runs}}"
RUNDIR_ROOT="$RUN_ROOT_BASE/$(date +%F)"
export OMP_LEDGER="${OMP_LEDGER:-$RUN_ROOT_BASE/ledger.tsv}"

die() { echo "omp-run: $*" >&2; exit 1; }

usage() {
  awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"
}

sanitize() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9._-' '-' | sed 's/^-*//; s/-*$//' | cut -c1-48
}

find_run_dir() {
  local slug="$1" d
  for d in "$RUNDIR_ROOT/$slug" "$RUN_ROOT_BASE"/*/"$slug" \
           "$RUN_ROOT_BASE"/*/runs/"$slug" "$RUN_ROOT_BASE"/*/omp-runs/"$slug"; do
    [[ -d "$d" ]] && { printf '%s\n' "$d"; return 0; }
  done
  return 1
}

tmux_alive() { tmux has-session -t "$1" 2>/dev/null; }

cmd_start() {
  local name="" prompt_file="" cwd="$PWD" resume="" model="" thinking=""
  local max_time="" profile="" extra="" replace=0

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --name) name="${2:-}"; shift 2 ;;
      --prompt) prompt_file="${2:-}"; shift 2 ;;
      --cwd) cwd="${2:-}"; shift 2 ;;
      --resume) resume="${2:-}"; shift 2 ;;
      --model) model="${2:-}"; shift 2 ;;
      --thinking) thinking="${2:-}"; shift 2 ;;
      --max-time) max_time="${2:-}"; shift 2 ;;
      --profile) profile="${2:-}"; shift 2 ;;
      --extra) extra="${2:-}"; shift 2 ;;
      --replace) replace=1; shift ;;
      *) die "start: unknown arg '$1'" ;;
    esac
  done

  [[ -n "$name" ]] || die "start: --name is required"
  [[ -n "$prompt_file" && -f "$prompt_file" ]] || die "start: --prompt FILE is required and must exist"
  [[ -d "$cwd" ]] || die "start: --cwd '$cwd' is not a directory"
  [[ -x "$OMP_BIN" ]] || die "start: agent binary not found at $OMP_BIN (set OMP_BIN)"

  name="$(sanitize "$name")"
  [[ -n "$name" ]] || die "start: name sanitized to empty"

  local sess="omp-$name"
  local run="$RUNDIR_ROOT/$name"

  if tmux_alive "$sess"; then
    if [[ $replace -eq 1 ]]; then
      tmux kill-session -t "$sess" 2>/dev/null
    else
      die "start: tmux session '$sess' is already running (use --replace to restart)"
    fi
  fi
  [[ -d "$run" ]] && mv "$run" "$run.prev-$(date +%H%M%S)" 2>/dev/null
  mkdir -p "$run" || die "start: cannot create $run"

  cp "$prompt_file" "$run/prompt.md"
  cwd="$(cd "$cwd" && pwd)"

  local args=(-p --mode=json --approval-mode yolo)
  [[ -n "$model" ]] && args+=(--model "$model")
  [[ -n "$thinking" ]] && args+=(--thinking "$thinking")
  [[ -n "$max_time" ]] && args+=(--max-time "$max_time")
  [[ -n "$resume" ]] && args+=(-r "$resume")
  [[ -n "$profile" ]] && args+=(--profile "$profile")
  [[ -n "$extra" ]] && args+=($extra)

  cat > "$run/finalize.py" <<'PY'
#!/usr/bin/env python3
"""Finalize one launcher run: parse the event log, write state.json + answer.md.

Usage: finalize.py RUN_DIR EXIT_CODE

Contract: state.json keeps name/state/exit/cwd/started/ended/duration_s and
answer.md holds the final assistant text. The event parser assumes an
OMP-style `--mode=json` NDJSON stream; adapt iter_events/text_of for another
agent CLI, not the state fields.
"""
import json
import os
import sys
from datetime import datetime, timezone


def load_state(run_dir):
    path = os.path.join(run_dir, "state.json")
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def iter_events(path):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except ValueError:
                continue


def text_of(parts):
    out = []
    for part in parts or []:
        if isinstance(part, dict) and part.get("type") == "text" and part.get("text"):
            out.append(part["text"])
    return "".join(out)


def main():
    if len(sys.argv) < 3:
        print("usage: finalize.py RUN_DIR EXIT_CODE", file=sys.stderr)
        return 2
    run_dir = os.path.abspath(sys.argv[1])
    try:
        exit_code = int(sys.argv[2])
    except ValueError:
        exit_code = -1

    state = load_state(run_dir)
    events_path = os.path.join(run_dir, "events.ndjson")

    session_id = state.get("session_id") or ""
    answer = ""
    cost = 0.0
    tool_calls = 0
    turns = 0
    errors = []

    for event in iter_events(events_path):
        kind = event.get("type") or ""
        if kind == "session" and not session_id:
            session_id = event.get("id") or session_id
        elif kind == "message_end":
            message = event.get("message") or {}
            if message.get("role") == "assistant":
                text = text_of(message.get("content"))
                if text:
                    answer = text
                usage = message.get("usage") or {}
                charged = usage.get("cost")
                if isinstance(charged, dict):
                    cost += float(charged.get("total") or 0)
                elif isinstance(charged, (int, float)):
                    cost += float(charged)
        elif "tool" in kind:
            if "start" in kind:
                tool_calls += 1
            if "error" in kind:
                errors.append(str(event)[:300])
        elif kind == "turn_end":
            turns += 1

    now = datetime.now(timezone.utc)
    started = state.get("started") or now.isoformat()
    try:
        duration = (now - datetime.fromisoformat(started)).total_seconds()
    except ValueError:
        duration = None

    state.update(
        {
            "state": "done" if exit_code == 0 else ("killed" if exit_code in (130, -2, 137, 143) else "failed"),
            "exit": exit_code,
            "ended": now.isoformat(),
            "duration_s": round(duration, 1) if duration is not None else None,
            "session_id": session_id,
            "cost_usd": round(cost, 4),
            "tool_calls": tool_calls,
            "turns": turns,
            "answer_chars": len(answer),
            "errors": errors[-5:],
        }
    )
    with open(os.path.join(run_dir, "state.json"), "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, ensure_ascii=False)
    with open(os.path.join(run_dir, "answer.md"), "w", encoding="utf-8") as handle:
        handle.write(answer)
    if session_id and not os.path.exists(os.path.join(run_dir, "session.id")):
        with open(os.path.join(run_dir, "session.id"), "w", encoding="utf-8") as handle:
            handle.write(session_id + "\n")

    ledger = os.environ.get("OMP_LEDGER") or os.path.join(os.path.dirname(run_dir), "ledger.tsv")
    header = "ended\tname\tstate\texit\tduration_s\tcost_usd\tsession_id\trun_dir\n"
    try:
        os.makedirs(os.path.dirname(ledger), exist_ok=True)
        fresh = not os.path.exists(ledger)
        with open(ledger, "a", encoding="utf-8") as handle:
            if fresh:
                handle.write(header)
            handle.write(
                "\t".join(
                    [
                        state["ended"],
                        str(state.get("name") or os.path.basename(run_dir)),
                        str(state["state"]),
                        str(exit_code),
                        str(state.get("duration_s")),
                        str(state.get("cost_usd")),
                        session_id,
                        run_dir,
                    ]
                )
                + "\n"
            )
    except OSError as exc:
        print(f"[finalize] ledger append failed: {exc}", file=sys.stderr)

    print(
        f"[finalize] {state.get('name')} state={state['state']} exit={exit_code} "
        f"dur={state.get('duration_s')}s cost=${state.get('cost_usd')} "
        f"tools={tool_calls} session={session_id or '-'}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
PY

  # run.sh: the exact command, replayable by hand after a crash.
  {
    printf '#!/usr/bin/env bash\n'
    printf '# generated by omp-run.sh — replayable: bash this file\n'
    printf 'set -o pipefail\n'
    printf 'cd %q || exit 90\n' "$cwd"
    printf 'export OMP_LEDGER=%q\n' "$OMP_LEDGER"
    printf '%q ' "$OMP_BIN" "${args[@]}"
    printf '"$(cat %q)"' "$run/prompt.md"
    printf ' > >(tee %q) 2> %q\n' "$run/events.ndjson" "$run/stderr.log"
    printf 'ec=$?\n'
    printf 'printf "%%s\\n" "$ec" > %q\n' "$run/exit.code"
    printf 'python3 %q %q "$ec"\n' "$run/finalize.py" "$run"
    printf 'exit "$ec"\n'
  } > "$run/run.sh"
  chmod +x "$run/run.sh"

  python3 - "$run" "$name" "$cwd" "$model" "$thinking" "$max_time" "$resume" "$sess" <<'PY'
import json
import sys
from datetime import datetime, timezone

run, name, cwd, model, thinking, max_time, resume, sess = sys.argv[1:9]
state = {
    "name": name,
    "state": "running",
    "exit": None,
    "cwd": cwd,
    "started": datetime.now(timezone.utc).isoformat(),
    "ended": None,
    "duration_s": None,
    "model": model or None,
    "thinking": thinking or None,
    "max_time": max_time or None,
    "tmux": sess,
    "run_dir": run,
    "session_id": resume or "",
    "resumed_from": resume or None,
}
with open(run + "/state.json", "w", encoding="utf-8") as handle:
    json.dump(state, handle, indent=2, ensure_ascii=False)
PY

  local run_cmd
  run_cmd="bash $(printf '%q' "$run/run.sh")"
  tmux new-session -d -s "$sess" -c "$cwd" "$run_cmd" \
    || die "start: tmux new-session failed"

  # The lock names the process behind the run: a state.json that still says
  # `running` while this pid is gone is reported as `stale lock`, not running.
  local pane_pid="" i
  for i in $(seq 1 20); do
    pane_pid="$(tmux list-panes -t "$sess" -F '#{pane_pid}' 2>/dev/null | head -n1)"
    [[ -n "$pane_pid" ]] && break
    sleep 0.2
  done
  python3 - "$run" "$pane_pid" "$sess" <<'PY'
import json
import os
import sys

run, pid, sess = sys.argv[1:4]
lock = {"pid": int(pid) if pid.isdigit() else None, "tmux": sess}
with open(os.path.join(run, "lock"), "w", encoding="utf-8") as handle:
    json.dump(lock, handle, indent=2)
PY

  # Grab the session id early so an interrupted run is resumable.
  for i in $(seq 1 40); do
    if [[ -s "$run/events.ndjson" ]]; then
      local sid
      sid="$(head -n 5 "$run/events.ndjson" 2>/dev/null | jq -r 'select(.type=="session") | .id' 2>/dev/null | head -n1)"
      if [[ -n "$sid" && "$sid" != "null" ]]; then
        printf '%s\n' "$sid" > "$run/session.id"
        python3 - "$run" "$sid" <<'PY'
import json
import sys

run, sid = sys.argv[1:3]
path = run + "/state.json"
with open(path, encoding="utf-8") as handle:
    state = json.load(handle)
state["session_id"] = sid
with open(path, "w", encoding="utf-8") as handle:
    json.dump(state, handle, indent=2)
PY
        break
      fi
    fi
    sleep 0.5
  done

  echo "started: $name"
  echo "  tmux      : $sess"
  echo "  run dir   : $run"
  echo "  session id: $(cat "$run/session.id" 2>/dev/null || echo '(pending)')"
  echo "  events    : tail -f $run/events.ndjson"
  echo "  summary   : $0 result $name"
}

cmd_list() {
  local d any=0
  for d in "$RUN_ROOT_BASE"/*/*/state.json \
           "$RUN_ROOT_BASE"/*/runs/*/state.json \
           "$RUN_ROOT_BASE"/*/omp-runs/*/state.json; do
    [[ -f "$d" ]] || continue
    any=1
    python3 - "$(dirname "$d")" <<'PY'
import json
import os
import subprocess
import sys

run = sys.argv[1]
with open(os.path.join(run, "state.json"), encoding="utf-8") as handle:
    state = json.load(handle)
sess = state.get("tmux", "")
alive = (
    subprocess.run(["tmux", "has-session", "-t", sess], capture_output=True).returncode == 0
    if sess
    else False
)
started = (state.get("started") or "")[:19].replace("T", " ")
state_name = state.get("state")
if state_name == "running" and not alive:
    state_name = "GONE (crashed/killed — resume with -r %s)" % (state.get("session_id") or "?")
print(
    f"{started}  {state.get('name', '?'):<28} {state_name:<10} exit={state.get('exit')} "
    f"dur={state.get('duration_s')} cost=${state.get('cost_usd', 0)} "
    f"sess={state.get('session_id') or '-'}"
)
PY
  done
  [[ $any -eq 1 ]] || echo "(no runs recorded)"
  echo
  echo "live tmux: $(tmux ls 2>/dev/null | grep -c '^omp-' || true) session(s)"
  tmux ls 2>/dev/null | grep '^omp-' | sed 's/^/  /' || true
}

cmd_status() {
  local name="${1:-}"
  if [[ -z "$name" ]]; then cmd_list; return; fi
  local run; run="$(find_run_dir "$(sanitize "$name")")" || die "status: no run '$name'"
  python3 - "$run" <<'PY'
import json
import os
import subprocess
import sys

run = sys.argv[1]
with open(os.path.join(run, "state.json"), encoding="utf-8") as handle:
    state = json.load(handle)
sess = state.get("tmux", "")
alive = (
    subprocess.run(["tmux", "has-session", "-t", sess], capture_output=True).returncode == 0
    if sess
    else False
)
events = os.path.join(run, "events.ndjson")
print(
    json.dumps(
        {
            **state,
            "tmux_alive": alive,
            "events_bytes": os.path.getsize(events) if os.path.exists(events) else 0,
        },
        indent=2,
        ensure_ascii=False,
    )
)
PY
}

cmd_tail() {
  local name; name="$(sanitize "${1:?tail: slug required}")"
  local n="${2:-20}"
  local run; run="$(find_run_dir "$name")" || die "tail: no run '$name'"
  tail -n "$n" "$run/events.ndjson" 2>/dev/null | jq -rc '
    if .type=="message_update" then (.assistantMessageEvent.type // "update")
    elif .type=="message_end" and .message.role=="assistant" then
      "assistant_end: " + ((.message.content // []) | map(select(.type=="text") | .text) | join("") | .[0:160])
    elif .type=="message_start" then ("message_start: " + (.message.role // "?"))
    else .type end' 2>/dev/null || tail -n "$n" "$run/events.ndjson"
}

cmd_result() {
  local name; name="$(sanitize "${1:?result: slug required}")"
  local run; run="$(find_run_dir "$name")" || die "result: no run '$name'"
  python3 - "$run" <<'PY'
import json
import os
import sys

run = sys.argv[1]
with open(os.path.join(run, "state.json"), encoding="utf-8") as handle:
    state = json.load(handle)
print(json.dumps(state, indent=2, ensure_ascii=False))
answer = os.path.join(run, "answer.md")
if os.path.exists(answer):
    with open(answer, encoding="utf-8", errors="replace") as handle:
        text = handle.read()
    print("\n--- answer (first 1500 chars) ---")
    print(text[:1500])
PY
}

cmd_answer() {
  local name; name="$(sanitize "${1:?answer: slug required}")"
  local run; run="$(find_run_dir "$name")" || die "answer: no run '$name'"
  cat "$run/answer.md" 2>/dev/null || die "answer: not finished yet"
}

cmd_kill() {
  local name; name="$(sanitize "${1:?kill: slug required}")"
  local run; run="$(find_run_dir "$name")" || die "kill: no run '$name'"
  local sess; sess="$(jq -r '.tmux // empty' "$run/state.json")"
  [[ -n "$sess" ]] || die "kill: no tmux session recorded"
  tmux send-keys -t "$sess" C-c 2>/dev/null
  local i
  for i in $(seq 1 20); do tmux_alive "$sess" || break; sleep 1; done
  tmux_alive "$sess" && tmux kill-session -t "$sess" 2>/dev/null
  echo "killed: $name ($sess)"
}

main() {
  local cmd="${1:-}"; shift || true
  case "$cmd" in
    start) cmd_start "$@" ;;
    list) cmd_list ;;
    status) cmd_status "$@" ;;
    tail) cmd_tail "$@" ;;
    result) cmd_result "$@" ;;
    answer) cmd_answer "$@" ;;
    kill) cmd_kill "$@" ;;
    ""|-h|--help|help) usage ;;
    *) die "unknown command '$cmd' (start|list|status|tail|result|answer|kill)" ;;
  esac
}

main "$@"
