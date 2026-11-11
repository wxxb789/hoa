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
# "ended","duration_s","pid","tmux","backend"} and state in
# running|done|killed|failed. gdd.py polls that file; a missing state.json is
# unknown, never success.
#
# A run is finished only once `finalized` (holding the exit code) sits next to
# state.json. When that marker is absent, state.json still says `running`, and
# the lock's pid (and recorded tmux session, if any) are gone, the process died
# before finalize.py could run: status/list/result/answer finalize it as failed
# with exit -1, set `recovered_stale`, and print `stale_recovered: true`. A
# marker is never mutated, so recovery is idempotent.
#
# This file is the reference adapter for an OMP-style CLI: it runs the agent in
# a detached session (so the run outlives the caller), streams the CLI's
# `--mode=json` NDJSON events to events.ndjson, and finalizes state.json +
# answer.md when the process exits. To adapt it for another agent CLI:
#   1. point OMP_BIN at that CLI (or edit the command in cmd_start);
#   2. map --model / --thinking / --max-time to that CLI's own flags;
#   3. adapt the finalize.py written below to that CLI's event stream — it must
#      still write state.json with the fields above and answer.md with the final
#      assistant text;
#   4. keep start/status/result/answer/kill and the exit codes.
#
# Why a detached session: a background job that is a child of the calling
# session dies with it, and one-shot CLI mode only prints at exit — one kill
# loses the whole run. A detached backend outlives the caller, and the NDJSON
# event log makes progress observable while the run is still going. Two
# backends implement it:
#   setsid (default)  the run gets its own session and process group with no
#                     controlling terminal. Nothing a caller's terminal or a
#                     tmux server does can SIGHUP it; `kill` signals the whole
#                     group. Use this where a tmux server may die mid-run.
#   tmux              a detached tmux session, which also lets a human attach
#                     to watch the agent. Keep it where attaching matters.
#
# Usage:
#   omp-run.sh start --name SLUG --prompt FILE [--cwd DIR] [--resume ID]
#                    [--backend setsid|tmux]
#                    [--model M] [--thinking L] [--max-time D] [--profile P]
#                    [--extra "FLAG ..."] [--replace]
#   omp-run.sh list                 # every recorded run + liveness
#   omp-run.sh status [SLUG]        # one run, or all live ones
#   omp-run.sh tail SLUG [N]        # last N event lines (default 20)
#   omp-run.sh result SLUG          # state summary + answer head
#   omp-run.sh answer SLUG          # only the final assistant text
#   omp-run.sh kill SLUG            # tmux: Ctrl-C then kill-session; setsid: TERM the group
#
# Environment:
#   OMP_BIN       agent binary (default: omp)
#   OMP_RUN_BACKEND  default for start --backend: setsid | tmux (default: setsid)
#   OMP_RUN_ROOT  base run root (default: $GDD_RUN_ROOT or
#                 ${XDG_STATE_HOME:-$HOME/.local/state}/gdd/runs)
#   OMP_LEDGER    finished-run ledger (default: <run_root>/ledger.tsv)
#   OMP_RUN_EVENTS_MAX_BYTES  ceiling for the rolling event tail in bytes
#                 (default: 8388608). The first 64 KiB of events are kept in
#                 addition, so the session event survives. state.json/status
#                 report events_bytes (retained), events_bytes_total,
#                 events_truncated and events_dropped_bytes; the writer's
#                 sidecar is events.stats.json.
#
# Model / thinking / max-time have no default here: the flag is omitted when it
# is not supplied. Run artifacts: <run_root>/<date>/<SLUG>/ = prompt.md, run.sh,
# events-writer.py, finalize.py, events.ndjson, events.stats.json, stderr.log,
# state.json, exit.code, session.id, lock, answer.md (setsid also writes
# launcher.log, the backend wrapper's own stderr). `lock` holds
# {"pid","tmux","backend","started_at"}; `tmux` is null under setsid and `pid`
# is the run's own session leader, so liveness is decided by pid first and the
# tmux session second.
set -uo pipefail

OMP_BIN="${OMP_BIN:-omp}"
BACKEND_DEFAULT="${OMP_RUN_BACKEND:-setsid}"
RUN_ROOT_BASE="${OMP_RUN_ROOT:-${GDD_RUN_ROOT:-${XDG_STATE_HOME:-$HOME/.local/state}/gdd/runs}}"
RUNDIR_ROOT="$RUN_ROOT_BASE/$(date +%F)"
export OMP_LEDGER="${OMP_LEDGER:-$RUN_ROOT_BASE/ledger.tsv}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EVENTS_WRITER="$SCRIPT_DIR/events-writer.py"

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

pid_alive() {
  local pid="${1:-}"
  [[ "$pid" =~ ^[0-9]+$ ]] && [[ "$pid" -gt 0 ]] || return 1
  kill -0 "$pid" 2>/dev/null
}

# lock_value RUN_DIR KEY — a top-level field of the JSON lock, empty if absent.
lock_value() {
  [[ -f "$1/lock" ]] || return 0
  jq -r --arg k "$2" '.[$k] // empty' "$1/lock" 2>/dev/null
}

# kill_pid_group PID — TERM the run's process group, KILL it after a bounded
# wait. The pid is the setsid session leader, so its process group is the run.
kill_pid_group() {
  local pid="$1" i
  kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
  for i in $(seq 1 20); do
    kill -0 -- "-$pid" 2>/dev/null || return 0
    sleep 0.25
  done
  kill -KILL -- "-$pid" 2>/dev/null || true
  for i in $(seq 1 20); do
    kill -0 -- "-$pid" 2>/dev/null || return 0
    sleep 0.25
  done
  return 1
}

# recover_stale RUN_DIR — finalize a run whose tmux session and pid both died
# without finalize.py running. Prints `stale_recovered: true` when it acted and
# nothing otherwise. A run with a `finalized` marker is never touched.
recover_stale() {
  python3 - "$1" <<'PY'
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

run = sys.argv[1]
state_path = os.path.join(run, "state.json")
marker_path = os.path.join(run, "finalized")
try:
    with open(state_path, encoding="utf-8") as handle:
        state = json.load(handle)
except (OSError, ValueError):
    sys.exit(0)
if state.get("state") != "running" or os.path.exists(marker_path):
    sys.exit(0)

try:
    with open(os.path.join(run, "lock"), encoding="utf-8") as handle:
        lock = json.load(handle)
except (OSError, ValueError):
    lock = {}
if not isinstance(lock, dict):
    lock = {}
sess = (lock["tmux"] if "tmux" in lock else state.get("tmux")) or ""
backend = lock.get("backend") or state.get("backend") or ("tmux" if sess else "setsid")

try:
    pid = int(lock.get("pid") or state.get("pid"))
except (TypeError, ValueError):
    pid = None
if pid and pid > 0:
    try:
        os.kill(pid, 0)
    except PermissionError:
        sys.exit(0)
    except ProcessLookupError:
        pass
    except OSError:
        pass
    else:
        sys.exit(0)
if sess:
    try:
        alive = subprocess.run(
            ["tmux", "has-session", "-t", str(sess)], capture_output=True
        ).returncode == 0
    except OSError:
        alive = False
    if alive:
        sys.exit(0)

# Dead lane: the run's own finalizer keeps state/answer/ledger consistent.
finalizer = os.path.join(run, "finalize.py")
if os.path.exists(finalizer):
    subprocess.run(
        [sys.executable, finalizer, run, "-1"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

try:
    with open(state_path, encoding="utf-8") as handle:
        state = json.load(handle)
except (OSError, ValueError):
    state = {}
now = datetime.now(timezone.utc)
if state.get("state") == "running":
    started = state.get("started") or ""
    try:
        duration = round((now - datetime.fromisoformat(started)).total_seconds(), 1)
    except ValueError:
        duration = None
    state.update(
        {"state": "failed", "exit": -1, "ended": now.isoformat(), "duration_s": duration}
    )
state["recovered_stale"] = True
state["note"] = (
    f"process disappeared without finalizing (backend {backend}; tmux "
    f"'{sess or '-'}' and pid {pid or '-'} are gone); finalized with exit -1"
)
with open(state_path, "w", encoding="utf-8") as handle:
    json.dump(state, handle, indent=2, ensure_ascii=False)

answer_path = os.path.join(run, "answer.md")
if not os.path.exists(answer_path):
    with open(answer_path, "w", encoding="utf-8"):
        pass
if not os.path.exists(marker_path):
    with open(marker_path, "w", encoding="utf-8") as handle:
        handle.write("-1")

print("stale_recovered: true")
PY
}

cmd_start() {
  local name="" prompt_file="" cwd="$PWD" resume="" model="" thinking=""
  local max_time="" profile="" extra="" replace=0 backend="$BACKEND_DEFAULT"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --name) name="${2:-}"; shift 2 ;;
      --prompt) prompt_file="${2:-}"; shift 2 ;;
      --cwd) cwd="${2:-}"; shift 2 ;;
      --resume) resume="${2:-}"; shift 2 ;;
      --backend) backend="${2:-}"; shift 2 ;;
      --model) model="${2:-}"; shift 2 ;;
      --thinking) thinking="${2:-}"; shift 2 ;;
      --max-time) max_time="${2:-}"; shift 2 ;;
      --profile) profile="${2:-}"; shift 2 ;;
      --extra) extra="${2:-}"; shift 2 ;;
      --replace) replace=1; shift ;;
      *) die "start: unknown arg '$1'" ;;
    esac
  done

  case "$backend" in
    setsid|tmux) ;;
    *) die "start: --backend must be setsid or tmux (got '$backend')" ;;
  esac

  [[ -n "$name" ]] || die "start: --name is required"
  [[ -n "$prompt_file" && -f "$prompt_file" ]] || die "start: --prompt FILE is required and must exist"
  [[ -d "$cwd" ]] || die "start: --cwd '$cwd' is not a directory"
  [[ -x "$OMP_BIN" ]] || die "start: agent binary not found at $OMP_BIN (set OMP_BIN)"
  [[ -f "$EVENTS_WRITER" ]] || die "start: bounded event writer not found at $EVENTS_WRITER"
  [[ "$backend" == setsid ]] && ! command -v setsid >/dev/null 2>&1 \
    && die "start: setsid not found (use --backend tmux)"

  name="$(sanitize "$name")"
  [[ -n "$name" ]] || die "start: name sanitized to empty"

  local sess="omp-$name"
  local run="$RUNDIR_ROOT/$name"

  local lock_pid="" lock_backend=""
  if [[ -f "$run/lock" ]]; then
    lock_pid="$(lock_value "$run" pid)"
    lock_backend="$(lock_value "$run" backend)"
  fi

  if tmux_alive "$sess"; then
    if [[ $replace -eq 1 ]]; then
      tmux kill-session -t "$sess" 2>/dev/null
    else
      die "start: tmux session '$sess' is already running (use --replace to restart)"
    fi
  fi
  # A setsid run has no session to name it: only its lock pid proves it lives.
  if [[ "$lock_backend" == setsid || "$backend" == setsid ]] \
     && pid_alive "$lock_pid"; then
    if [[ $replace -eq 1 ]]; then
      kill_pid_group "$lock_pid" || die "start: could not stop run '$name' (pid $lock_pid)"
    else
      die "start: run '$name' is still running (pid $lock_pid; use --replace to restart)"
    fi
  fi
  [[ -d "$run" ]] && mv "$run" "$run.prev-$(date +%H%M%S)" 2>/dev/null
  mkdir -p "$run" || die "start: cannot create $run"

  cp "$prompt_file" "$run/prompt.md"
  cp "$EVENTS_WRITER" "$run/events-writer.py"
  # A resumed agent keeps its recorded id until its own session event arrives.
  [[ -n "$resume" ]] && printf '%s\n' "$resume" > "$run/session.id"
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


def load_stats(run_dir):
    """Sidecar counters from the bounded writer; {} for older run dirs."""
    try:
        with open(os.path.join(run_dir, "events.stats.json"), encoding="utf-8") as handle:
            stats = json.load(handle)
    except (OSError, ValueError):
        return {}
    return stats if isinstance(stats, dict) else {}


def load_sidecar(run_dir, name):
    try:
        with open(os.path.join(run_dir, name), encoding="utf-8") as handle:
            text = handle.read().strip()
    except OSError:
        return ""
    return text.splitlines()[0].strip() if text else ""


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
    stats = load_stats(run_dir)

    session_id = state.get("session_id") or load_sidecar(run_dir, "session.id")
    answer = ""
    cost = 0.0
    tool_calls = 0
    turns = 0
    errors = []
    marker = {}

    for event in iter_events(events_path):
        kind = event.get("type") or ""
        if kind == "truncated":
            # The writer's splice marker: a counter boundary, not an event.
            marker = event
            continue
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

    # The sidecar is exact at a normal exit. Without it (older runs, or a
    # writer that died) the marker still tells us how many bytes are missing.
    retained = os.path.getsize(events_path) if os.path.exists(events_path) else 0
    total_bytes = stats.get("total_bytes")
    if not isinstance(total_bytes, int) or total_bytes < 0:
        dropped = marker.get("dropped_bytes")
        total_bytes = retained + (dropped if isinstance(dropped, int) and dropped > 0 else 0)
    dropped_bytes = stats.get("dropped_bytes")
    if not isinstance(dropped_bytes, int) or dropped_bytes < 0:
        dropped = marker.get("dropped_bytes")
        dropped_bytes = dropped if isinstance(dropped, int) and dropped > 0 else 0
    truncated = bool(stats.get("truncated")) or bool(marker) or dropped_bytes > 0

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
            "events_bytes": retained,
            "events_bytes_total": total_bytes,
            "events_truncated": truncated,
            "events_dropped_bytes": dropped_bytes,
            "tool_calls_partial": truncated,
            "turns_partial": truncated,
            "cost_partial": truncated,
        }
    )
    with open(os.path.join(run_dir, "state.json"), "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, ensure_ascii=False)
    with open(os.path.join(run_dir, "answer.md"), "w", encoding="utf-8") as handle:
        handle.write(answer)
    if session_id and not os.path.exists(os.path.join(run_dir, "session.id")):
        with open(os.path.join(run_dir, "session.id"), "w", encoding="utf-8") as handle:
            handle.write(session_id + "\n")
    # Finished, not to be mistaken for a live run: the marker holds the exit code.
    with open(os.path.join(run_dir, "finalized"), "w", encoding="utf-8") as handle:
        handle.write(str(exit_code))

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
    if [[ -n "${OMP_RUN_EVENTS_MAX_BYTES:-}" ]]; then
      printf 'export OMP_RUN_EVENTS_MAX_BYTES=%q\n' "$OMP_RUN_EVENTS_MAX_BYTES"
    fi
    printf '%q ' "$OMP_BIN" "${args[@]}"
    printf '"$(cat %q)"' "$run/prompt.md"
    printf ' 2>> %q | python3 %q %q 2>> %q\n' \
      "$run/stderr.log" "$run/events-writer.py" "$run" "$run/stderr.log"
    printf 'ec=$?\n'
    printf 'printf "%%s\\n" "$ec" > %q\n' "$run/exit.code"
    printf 'python3 %q %q "$ec"\n' "$run/finalize.py" "$run"
    printf 'exit "$ec"\n'
  } > "$run/run.sh"
  chmod +x "$run/run.sh"

  python3 - "$run" "$name" "$cwd" "$model" "$thinking" "$max_time" "$resume" "$sess" "$backend" <<'PY'
import json
import sys
from datetime import datetime, timezone

run, name, cwd, model, thinking, max_time, resume, sess, backend = sys.argv[1:10]
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
    "tmux": sess if backend == "tmux" else None,
    "backend": backend,
    "run_dir": run,
    "session_id": resume or "",
    "resumed_from": resume or None,
    "events_bytes": 0,
    "events_bytes_total": 0,
    "events_truncated": False,
    "events_dropped_bytes": 0,
}
with open(run + "/state.json", "w", encoding="utf-8") as handle:
    json.dump(state, handle, indent=2, ensure_ascii=False)
PY

  local run_pid="" pane_pid="" i
  if [[ "$backend" == tmux ]]; then
    local run_cmd
    run_cmd="bash $(printf '%q' "$run/run.sh")"
    tmux new-session -d -s "$sess" -c "$cwd" "$run_cmd" \
      || die "start: tmux new-session failed"
    for i in $(seq 1 20); do
      pane_pid="$(tmux list-panes -t "$sess" -F '#{pane_pid}' 2>/dev/null | head -n1)"
      [[ -n "$pane_pid" ]] && break
      sleep 0.2
    done
    run_pid="$pane_pid"
  else
    # setsid gives the run its own session and process group with no
    # controlling terminal. The child records its own pid *after* setsid and
    # then execs run.sh, so the lock names the shell that owns the agent — not
    # the setsid wrapper, which may fork and exit.
    local pidfile="$run/setsid.pid"
    rm -f "$pidfile"
    setsid bash -c 'printf "%s\n" "$$" > "$1"; exec bash "$2"' \
      omp-run "$pidfile" "$run/run.sh" </dev/null >>"$run/launcher.log" 2>&1 &
    for i in $(seq 1 50); do
      [[ -s "$pidfile" ]] && break
      sleep 0.1
    done
    run_pid="$(cat "$pidfile" 2>/dev/null || true)"
    rm -f "$pidfile"
    [[ -n "$run_pid" ]] || die "start: setsid run did not start (see $run/launcher.log)"
  fi

  # The lock names the process behind the run: a state.json that still says
  # `running` while this pid is gone is reported as `stale lock`, not running.
  python3 - "$run" "$run_pid" "$sess" "$backend" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone

run, pid, sess, backend = sys.argv[1:5]
pid = int(pid) if pid.isdigit() else None
lock = {
    "pid": pid,
    "tmux": sess if backend == "tmux" else None,
    "backend": backend,
    "started_at": datetime.now(timezone.utc).isoformat(),
}
with open(os.path.join(run, "lock"), "w", encoding="utf-8") as handle:
    json.dump(lock, handle, indent=2)
state_path = os.path.join(run, "state.json")
try:
    with open(state_path, encoding="utf-8") as handle:
        state = json.load(handle)
except (OSError, ValueError):
    state = {}
state["pid"] = pid
state["tmux"] = lock["tmux"]
state["backend"] = backend
with open(state_path, "w", encoding="utf-8") as handle:
    json.dump(state, handle, indent=2)
PY

  # The bounded writer persists the session event's id as soon as it sees it.
  # Fall back to scanning the log head only when that sidecar is absent.
  local sid=""
  for i in $(seq 1 40); do
    sid=""
    if [[ -s "$run/session.id" ]]; then
      sid="$(head -n 1 "$run/session.id" 2>/dev/null)"
    elif [[ ! -e "$run/session.id" && -s "$run/events.ndjson" ]]; then
      sid="$(head -c 65536 "$run/events.ndjson" 2>/dev/null | jq -r 'select(.type=="session") | .id' 2>/dev/null | head -n1)"
      [[ "$sid" == "null" ]] && sid=""
    fi
    if [[ -n "$sid" ]]; then
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
    sleep 0.5
  done

  echo "started: $name"
  echo "  backend   : $backend"
  if [[ "$backend" == tmux ]]; then
    echo "  tmux      : $sess"
  else
    echo "  pid       : $run_pid"
  fi
  echo "  run dir   : $run"
  echo "  session id: $(cat "$run/session.id" 2>/dev/null || echo '(pending)')"
  echo "  events    : tail -F $run/events.ndjson"
  echo "  summary   : $0 result $name"
}

cmd_list() {
  local d any=0 run
  for d in "$RUN_ROOT_BASE"/*/*/state.json \
           "$RUN_ROOT_BASE"/*/runs/*/state.json \
           "$RUN_ROOT_BASE"/*/omp-runs/*/state.json; do
    [[ -f "$d" ]] || continue
    any=1
    run="$(dirname "$d")"
    local recovered
    recovered="$(recover_stale "$run")"
    python3 - "$run" "$recovered" <<'PY'
import json
import os
import subprocess
import sys

run, recovered = sys.argv[1], bool(sys.argv[2])
with open(os.path.join(run, "state.json"), encoding="utf-8") as handle:
    state = json.load(handle)
try:
    with open(os.path.join(run, "lock"), encoding="utf-8") as handle:
        lock = json.load(handle)
except (OSError, ValueError):
    lock = {}
if not isinstance(lock, dict):
    lock = {}
sess = (lock["tmux"] if "tmux" in lock else state.get("tmux")) or ""
pid = lock.get("pid") or state.get("pid")


def pid_alive(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return False
    if value <= 0:
        return False
    try:
        os.kill(value, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def tmux_alive(name):
    if not name:
        return False
    try:
        return subprocess.run(
            ["tmux", "has-session", "-t", str(name)], capture_output=True
        ).returncode == 0
    except OSError:
        return False


alive = pid_alive(pid) or tmux_alive(sess)
started = (state.get("started") or "")[:19].replace("T", " ")
state_name = state.get("state")
if recovered:
    # Just finalized by recover_stale: report what was observed, not the
    # bookkeeping that was written.
    state_name = "GONE (resume with -r %s)" % (state.get("session_id") or "?")
elif state.get("recovered_stale"):
    state_name = "failed(stale)"
elif state_name == "running" and not alive:
    state_name = "GONE (resume with -r %s)" % (state.get("session_id") or "?")
print(
    f"{started}  {state.get('name', '?'):<28} {state_name} exit={state.get('exit')} "
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
  recover_stale "$run"
  python3 - "$run" <<'PY'
import json
import os
import subprocess
import sys

run = sys.argv[1]
with open(os.path.join(run, "state.json"), encoding="utf-8") as handle:
    state = json.load(handle)
try:
    with open(os.path.join(run, "lock"), encoding="utf-8") as handle:
        lock = json.load(handle)
except (OSError, ValueError):
    lock = {}
if not isinstance(lock, dict):
    lock = {}
sess = (lock["tmux"] if "tmux" in lock else state.get("tmux")) or ""
pid = lock.get("pid") or state.get("pid")
backend = lock.get("backend") or state.get("backend") or ("tmux" if sess else "setsid")


def pid_alive(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return False
    if value <= 0:
        return False
    try:
        os.kill(value, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def tmux_alive(name):
    if not name:
        return False
    try:
        return subprocess.run(
            ["tmux", "has-session", "-t", str(name)], capture_output=True
        ).returncode == 0
    except OSError:
        return False


tmux_up = tmux_alive(sess)
alive = pid_alive(pid) or tmux_up
events = os.path.join(run, "events.ndjson")
retained = os.path.getsize(events) if os.path.exists(events) else 0
try:
    with open(os.path.join(run, "events.stats.json"), encoding="utf-8") as handle:
        stats = json.load(handle)
except (OSError, ValueError):
    stats = {}
total = stats.get("total_bytes")
if not isinstance(total, int):
    total = state.get("events_bytes_total")
if not isinstance(total, int) or total < retained:
    # Before the first sidecar write, the retained bytes are the only
    # lower bound on what the agent has emitted.
    total = retained
dropped = stats.get("dropped_bytes", state.get("events_dropped_bytes", 0))
if not isinstance(dropped, int):
    dropped = 0
truncated = stats.get("truncated")
if not isinstance(truncated, bool):
    truncated = bool(state.get("events_truncated")) or dropped > 0
print(
    json.dumps(
        {
            **state,
            "backend": backend,
            "alive": alive,
            "tmux_alive": tmux_up,
            "events_bytes": retained,
            "events_bytes_total": total,
            "events_truncated": truncated,
            "events_dropped_bytes": dropped,
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
  recover_stale "$run"
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
  recover_stale "$run"
  cat "$run/answer.md" 2>/dev/null || die "answer: not finished yet"
}

cmd_kill() {
  local name; name="$(sanitize "${1:?kill: slug required}")"
  local run; run="$(find_run_dir "$name")" || die "kill: no run '$name'"
  local pid sess backend
  pid="$(lock_value "$run" pid)"
  sess="$(lock_value "$run" tmux)"
  backend="$(lock_value "$run" backend)"
  [[ -z "$pid" ]] && pid="$(jq -r '.pid // empty' "$run/state.json" 2>/dev/null)"
  [[ -z "$sess" ]] && sess="$(jq -r '.tmux // empty' "$run/state.json" 2>/dev/null)"

  # setsid: one signal to the process group reaches the run shell, the agent
  # and the event writer. tmux: today's Ctrl-C then kill-session.
  if [[ "$backend" == setsid || -z "$sess" ]]; then
    pid_alive "$pid" || die "kill: no live process group recorded for '$name'"
    kill_pid_group "$pid" || die "kill: process group $pid survived SIGKILL"
    echo "killed: $name (pid $pid)"
    return 0
  fi

  if tmux_alive "$sess"; then
    tmux send-keys -t "$sess" C-c 2>/dev/null
    local i
    for i in $(seq 1 20); do tmux_alive "$sess" || break; sleep 1; done
    tmux_alive "$sess" && tmux kill-session -t "$sess" 2>/dev/null
    echo "killed: $name ($sess)"
    return 0
  fi

  # The tmux server is gone but the pane process may still be alive.
  if pid_alive "$pid"; then
    kill_pid_group "$pid" || die "kill: process group $pid survived SIGKILL"
    echo "killed: $name (pid $pid)"
    return 0
  fi
  die "kill: run '$name' is already gone (no tmux session, pid $pid is dead)"
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
