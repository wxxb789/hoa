#!/usr/bin/env bash
# Hermetic test for the launcher's setsid backend.
#
# Uses a stub agent CLI that emits one session event and then sleeps: no
# network, no model, no real agent. Proves the setsid contract end to end:
#
#   1. start --backend setsid makes the run its own session/process-group
#      leader with no controlling terminal, and the lock names that pid,
#      not a wrapper that already exited;
#   2. status reports running while the pid lives;
#   3. kill ends the whole process group and list reports GONE with the
#      resume hint;
#   4. a run killed from outside the launcher is finalized as failed by
#      recover_stale, never left reading as running;
#   5. --backend tmux still starts and reports; skipped loudly when tmux is
#      unavailable.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADAPTER="$(cd "$HERE/../adapters" && pwd)/omp-run.sh"
TODAY="$(date +%F)"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/omp-run-setsid.XXXXXX")"
RUN_ROOT="$TMP/runs"
STUB="$TMP/bin/stub-omp"
PROMPT="$TMP/prompt.md"
SLUG_A="setsid-a-$$"
SLUG_B="setsid-b-$$"
SLUG_C="setsid-c-$$"
SLUG_TMUX="tmux-a-$$"
SLUG_ENV="tmux-env-$$"
N=0
SKIPPED=0

cleanup() {
  local lock pid sess
  for lock in "$RUN_ROOT"/*/*/lock; do
    [[ -f "$lock" ]] || continue
    pid="$(jq -r '.pid // empty' "$lock" 2>/dev/null)"
    [[ -n "$pid" ]] && kill -KILL -- "-$pid" 2>/dev/null
    sess="$(jq -r '.tmux // empty' "$lock" 2>/dev/null)"
    [[ -n "$sess" ]] && tmux kill-session -t "$sess" 2>/dev/null
  done
  rm -rf "$TMP"
}
trap cleanup EXIT

ok() { N=$((N + 1)); echo "ok $N - $*"; }
skip() { SKIPPED=$((SKIPPED + 1)); echo "skip - $*"; }
fail() { echo "FAIL: $*" >&2; exit 1; }

mkdir -p "$TMP/bin"
cat >"$STUB" <<'STUB'
#!/usr/bin/env bash
# Stub OMP CLI: one session event and one assistant message, then stay alive
# so the launcher's pid (and its process group) can be observed and killed.
printf '%s\n' '{"type":"session","id":"stub-session"}'
printf '%s\n' '{"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":"stub answer"}]}}'
while :; do sleep 1; done
STUB
chmod +x "$STUB"
printf 'stub prompt\n' >"$PROMPT"

launch() {
  env OMP_BIN="$STUB" OMP_RUN_ROOT="$RUN_ROOT" OMP_LEDGER="$TMP/ledger.tsv" \
    bash "$ADAPTER" "$@"
}

run_dir() { printf '%s/%s/%s\n' "$RUN_ROOT" "$TODAY" "$1"; }

json_get() { python3 -c 'import json, sys; print(json.load(open(sys.argv[1])).get(sys.argv[2]))' "$1" "$2"; }

# wait_group_gone PID — 0 once no process remains in that process group.
wait_group_gone() {
  local pid="$1" _
  for _ in $(seq 1 50); do
    kill -0 -- "-$pid" 2>/dev/null || return 0
    sleep 0.1
  done
  return 1
}

wait_file() {
  local path="$1" _
  for _ in $(seq 1 100); do
    [[ -e "$path" ]] && return 0
    sleep 0.1
  done
  return 1
}

# --- 1. setsid start: own session and process group ------------------------

START_A="$(launch start --backend setsid --name "$SLUG_A" --prompt "$PROMPT" --cwd "$TMP" 2>&1)"
[[ $? -eq 0 ]] || fail "start --backend setsid must exit 0: $START_A"
DIR_A="$(run_dir "$SLUG_A")"
[[ -f "$DIR_A/lock" ]] || fail "start must write a lock: $START_A"

python3 - "$DIR_A" <<'PY' || fail "lock/state must record the setsid identity"
import json
import os
import sys

run = sys.argv[1]
lock = json.load(open(os.path.join(run, "lock"), encoding="utf-8"))
assert isinstance(lock.get("pid"), int) and lock["pid"] > 0, lock
assert lock.get("tmux") is None, lock
assert lock.get("backend") == "setsid", lock
assert lock.get("started_at"), lock
state = json.load(open(os.path.join(run, "state.json"), encoding="utf-8"))
assert state.get("state") == "running", state
assert state.get("pid") == lock["pid"], state
assert state.get("tmux") is None, state
assert state.get("backend") == "setsid", state
PY

PID_A="$(json_get "$DIR_A/lock" pid)"
kill -0 "$PID_A" 2>/dev/null || fail "the lock pid must be live (pid=$PID_A)"
# setsid puts the run in a new session: pid == pgid == sid, no tty. The pid
# must be the shell that owns the agent child, not the setsid wrapper.
PS_A="$(ps -o pid=,pgid=,sid=,tty= -p "$PID_A")"
read -r PS_PID PS_PGID PS_SID PS_TTY <<<"$PS_A"
[[ "$PS_PID" = "$PID_A" && "$PS_PGID" = "$PID_A" && "$PS_SID" = "$PID_A" && "$PS_TTY" = "?" ]] \
  || fail "run must be a session/group leader with no tty (got: $PS_A)"
tr '\0' ' ' <"/proc/$PID_A/cmdline" | grep -q "$DIR_A/run.sh" \
  || fail "the locked pid must run run.sh, not an exited wrapper"
ps -eo pgid=,args= | awk -v p="$PID_A" '$1 == p' | grep -q "$STUB" \
  || fail "the stub agent must be in the run's process group"
ok "setsid start records a live session leader that owns the agent"

# --- 2. status reports running while the pid lives -------------------------

STATUS_A="$(launch status "$SLUG_A" 2>&1)"
[[ $? -eq 0 ]] || fail "status must exit 0 for a live run: $STATUS_A"
python3 - "$STATUS_A" <<'PY' || fail "status must report a live setsid run as running"
import json
import sys

text = sys.argv[1]
doc = json.loads(text[text.index("{"):])
assert doc.get("state") == "running", doc
assert doc.get("alive") is True, doc
assert doc.get("backend") == "setsid", doc
assert doc.get("tmux") is None, doc
PY
ok "status reports running while the setsid pid lives"

# --- 3. kill ends the process group; list reports GONE ---------------------

KILL_A="$(launch kill "$SLUG_A" 2>&1)"
[[ $? -eq 0 ]] || fail "kill must exit 0: $KILL_A"
printf '%s\n' "$KILL_A" | grep -q "killed: $SLUG_A (pid $PID_A)" \
  || fail "kill must name the process group it ended: $KILL_A"
wait_group_gone "$PID_A" || fail "kill must end the whole process group"
ps -eo pgid=,args= | awk -v p="$PID_A" '$1 == p' | grep -q "$STUB" \
  && fail "the stub agent survived the group kill"

LIST_RC=1
for _ in $(seq 1 50); do
  LIST_OUT="$(launch list 2>&1)" && LIST_RC=0
  [[ $LIST_RC -eq 0 ]] || break
  printf '%s\n' "$LIST_OUT" | grep "$SLUG_A" | grep -q 'GONE (resume with -r stub-session' && break
  sleep 0.1
done
[[ $LIST_RC -eq 0 ]] || fail "list must exit 0: $LIST_OUT"
LINE_A="$(printf '%s\n' "$LIST_OUT" | grep "$SLUG_A")"
printf '%s\n' "$LINE_A" | grep -q 'GONE (resume with -r stub-session' \
  || fail "list must report the killed run as GONE with a resume hint: $LINE_A"
printf '%s\n' "$LINE_A" | grep -q ' running' \
  && fail "list must not report the killed run as running: $LINE_A"
[[ "$(json_get "$DIR_A/state.json" state)" = "failed" ]] \
  || fail "list recovery must finalize the killed run as failed"
grep -q -- '^-1$' "$DIR_A/finalized" 2>/dev/null \
  || fail "list recovery must write the finalized marker"
ok "kill ends the group and list reports GONE (resume with -r ...)"

# --- 4. an externally killed run is finalized by recover_stale --------------

START_B="$(launch start --backend setsid --name "$SLUG_B" --prompt "$PROMPT" --cwd "$TMP" 2>&1)"
[[ $? -eq 0 ]] || fail "second setsid start must exit 0: $START_B"
DIR_B="$(run_dir "$SLUG_B")"
PID_B="$(json_get "$DIR_B/lock" pid)"
kill -KILL -- "-$PID_B" 2>/dev/null
wait_group_gone "$PID_B" || fail "could not kill the second run's group"
[[ "$(json_get "$DIR_B/state.json" state)" = "running" ]] \
  || fail "the crash must leave state.json saying running"

STATUS_B="$(launch status "$SLUG_B" 2>&1)"
[[ $? -eq 0 ]] || fail "status on a crashed run must exit 0: $STATUS_B"
python3 - "$STATUS_B" <<'PY' || fail "status must finalize an externally killed run as failed"
import json
import sys

text = sys.argv[1]
assert "stale_recovered: true" in text, text
doc = json.loads(text[text.index("{"):])
assert doc.get("state") == "failed", doc
assert doc.get("exit") == -1, doc
assert doc.get("recovered_stale") is True, doc
assert "disappeared without finalizing" in (doc.get("note") or ""), doc
PY
grep -q -- '^-1$' "$DIR_B/finalized" || fail "recover_stale must write the finalized marker"
LINE_B="$(launch list 2>&1 | grep "$SLUG_B")"
printf '%s\n' "$LINE_B" | grep -q 'failed(stale)' \
  || fail "list must report the recovered run as failed(stale): $LINE_B"
printf '%s\n' "$LINE_B" | grep -q ' running' \
  && fail "list must not report the recovered run as running: $LINE_B"
ok "an externally killed run is finalized as failed, never reported running"

# --- 5. default backend is setsid ------------------------------------------

START_C="$(launch start --name "$SLUG_C" --prompt "$PROMPT" --cwd "$TMP" 2>&1)"
[[ $? -eq 0 ]] || fail "start without --backend must exit 0: $START_C"
DIR_C="$(run_dir "$SLUG_C")"
[[ "$(json_get "$DIR_C/lock" backend)" = "setsid" ]] \
  || fail "the default backend must be setsid"
launch kill "$SLUG_C" >/dev/null 2>&1 || fail "kill must end the default-backend run"
wait_group_gone "$(json_get "$DIR_C/lock" pid)" || fail "default run's group must end"
ok "the default backend is setsid (OMP_RUN_BACKEND unset)"

# --- 6. tmux backend still starts and reports ------------------------------

tmux_usable() {
  command -v tmux >/dev/null 2>&1 || return 1
  tmux new-session -d -s "omp-probe-$$" true 2>/dev/null || return 1
  tmux kill-session -t "omp-probe-$$" 2>/dev/null
  return 0
}

if ! tmux_usable; then
  skip "tmux backend: tmux is unavailable on this host (not silently passed)"
else
  START_T="$(launch start --backend tmux --name "$SLUG_TMUX" --prompt "$PROMPT" --cwd "$TMP" 2>&1)"
  [[ $? -eq 0 ]] || fail "start --backend tmux must exit 0: $START_T"
  DIR_T="$(run_dir "$SLUG_TMUX")"
  python3 - "$DIR_T" "$SLUG_TMUX" <<'PY' || fail "tmux start must write the same lock contract"
import json
import os
import sys

run, slug = sys.argv[1:3]
lock = json.load(open(os.path.join(run, "lock"), encoding="utf-8"))
assert isinstance(lock.get("pid"), int) and lock["pid"] > 0, lock
assert lock.get("tmux") == "omp-" + slug, lock
assert lock.get("backend") == "tmux", lock
assert lock.get("started_at"), lock
state = json.load(open(os.path.join(run, "state.json"), encoding="utf-8"))
assert state.get("pid") == lock["pid"], state
assert state.get("tmux") == "omp-" + slug, state
assert state.get("backend") == "tmux", state
PY
  STATUS_T="$(launch status "$SLUG_TMUX" 2>&1)"
  [[ $? -eq 0 ]] || fail "status on a tmux run must exit 0: $STATUS_T"
  python3 - "$STATUS_T" <<'PY' || fail "status must report the tmux backend as running"
import json
import sys

text = sys.argv[1]
doc = json.loads(text[text.index("{"):])
assert doc.get("state") == "running", doc
assert doc.get("alive") is True, doc
assert doc.get("tmux_alive") is True, doc
assert doc.get("backend") == "tmux", doc
PY
  launch kill "$SLUG_TMUX" >/dev/null 2>&1 || fail "kill must end the tmux run"
  wait_file "$DIR_T/finalized" || fail "the tmux run must finalize after kill"
  [[ "$(json_get "$DIR_T/state.json" state)" = "killed" ]] \
    || fail "a Ctrl-C'd tmux run must finalize as killed"
  ! tmux has-session -t "omp-$SLUG_TMUX" 2>/dev/null \
    || fail "kill must remove the tmux session"
  ok "--backend tmux starts, reports running and finalizes on kill"

  START_E="$(env OMP_BIN="$STUB" OMP_RUN_ROOT="$RUN_ROOT" OMP_LEDGER="$TMP/ledger.tsv" \
    OMP_RUN_BACKEND=tmux bash "$ADAPTER" start --name "$SLUG_ENV" --prompt "$PROMPT" --cwd "$TMP" 2>&1)"
  [[ $? -eq 0 ]] || fail "OMP_RUN_BACKEND=tmux start must exit 0: $START_E"
  [[ "$(json_get "$(run_dir "$SLUG_ENV")/lock" backend)" = "tmux" ]] \
    || fail "OMP_RUN_BACKEND must be the default for --backend"
  launch kill "$SLUG_ENV" >/dev/null 2>&1 || fail "kill must end the env-backend run"
  ok "OMP_RUN_BACKEND=tmux selects the tmux backend"
fi

if [[ $SKIPPED -gt 0 ]]; then
  echo "setsid-test: $N ok, $SKIPPED skipped (tmux unavailable)"
else
  echo "setsid-test: $N/$N ok"
fi
