#!/usr/bin/env bash
# Watch a tmux-hosted TUI agent (omp/pi/opencode): wait until it goes idle, optionally send one
# instruction, then watch the resulting turn to completion. Snapshots + log go to $OUT.
#
#   TARGET=main-2:1.0 MSG="one-line instruction" OUT=$HOME/tasks/<task> \
#     bash tmux-agent-watch.sh
#
# Env: TARGET (required, session:window.pane)  MSG (optional; empty = monitor only)
#      OUT (artifact dir, default $PWD)  POLL_S (default 15)
#      IDLE_TIMEOUT_MIN (default 65)  TURN_TIMEOUT_MIN (default 90)
# Exit: 0 turn complete | 2 session gone | 3 refused to type blind | 4 idle timeout | 5 turn timeout
set -uo pipefail

: "${TARGET:?set TARGET=session:window.pane}"
MSG="${MSG:-}"
OUT="${OUT:-$PWD}"
POLL_S="${POLL_S:-15}"
IDLE_TIMEOUT_MIN="${IDLE_TIMEOUT_MIN:-65}"
TURN_TIMEOUT_MIN="${TURN_TIMEOUT_MIN:-90}"
mkdir -p "$OUT"
LOG="$OUT/watch.log"
SPIN='⠋|⠙|⠹|⠸|⠼|⠴|⠦|⠧|⠇|⠏|⠿|⡿|⣟|⣯|⣷|⣻|⢿|⡷|⣾|⣽|⣶|⣇|⣏'

log() { printf '%s %s\n' "$(date '+%F %T')" "$*" >>"$LOG"; }
cap() { tmux capture-pane -p -t "$TARGET" -S "${1:--200}" 2>/dev/null; }

busy() {
  printf '%s\n' "$1" | grep -qE "$SPIN" && return 0
  printf '%s\n' "$1" | grep -qE 'Subagents · [0-9]+ running' && return 0
  printf '%s\n' "$1" | grep -qE 'waiting on [0-9]+ job' && return 0
  return 1
}

# wait_idle <max_seconds> <snapshot_name>
wait_idle() {
  local max_s=$1 snap=$2 i=0 last="" stable=0 pane="" h
  while [ $((i * POLL_S)) -lt "$max_s" ]; do
    if ! tmux has-session -t "${TARGET%%:*}" 2>/dev/null; then
      log "FATAL session ${TARGET%%:*} gone"; return 2
    fi
    pane=$(cap -200)
    h=$(printf '%s' "$pane" | md5sum | cut -d' ' -f1)
    if [ "$h" = "$last" ]; then stable=$((stable + 1)); else stable=0; fi
    last="$h"
    if ! busy "$pane" && [ "$stable" -ge 2 ]; then
      printf '%s\n' "$pane" >"$OUT/$snap"
      log "idle after $((i * POLL_S))s -> $snap"
      return 0
    fi
    if [ $((i % 40)) -eq 0 ]; then printf '%s\n' "$pane" >"$OUT/pane-progress.txt"; fi
    i=$((i + 1)); sleep "$POLL_S"
  done
  printf '%s\n' "$pane" >"$OUT/pane-timeout.txt"
  log "timeout after ${max_s}s waiting for idle"
  return 4
}

log "watch start target=$TARGET msg=${MSG:+set}"
wait_idle $((IDLE_TIMEOUT_MIN * 60)) pane-idle.txt; rc=$?
[ "$rc" -ne 0 ] && exit "$rc"

if [ -n "$MSG" ]; then
  pane=$(cap -80)
  for try in 1 2 3; do
    if printf '%s\n' "$pane" | tail -8 | grep -qiE 'esc.*(close|back|quit)|q.*quit|press .*continue'; then
      log "modal hint, sending Escape (try $try)"
      tmux send-keys -t "$TARGET" Escape 2>/dev/null; sleep 2
      pane=$(cap -80)
    else
      break
    fi
  done
  if ! printf '%s\n' "$pane" | tail -10 | grep -q '❯'; then
    printf '%s\n' "$pane" >"$OUT/pane-abort.txt"
    log "ABORT: composer prompt not visible, refusing to type blind"
    exit 3
  fi
  tmux send-keys -t "$TARGET" -l "$MSG" 2>/dev/null; sleep 1
  tmux send-keys -t "$TARGET" Enter 2>/dev/null
  log "SENT: $MSG"
  sleep 20
  cap -60 >"$OUT/pane-after-send.txt"
  wait_idle $((TURN_TIMEOUT_MIN * 60)) pane-turn-done.txt; rc=$?
  [ "$rc" -ne 0 ] && exit 5
fi

log "done"
exit 0
