#!/usr/bin/env bash
# Observe one pane and optionally submit one single-line instruction.
set -uo pipefail

: "${TARGET:?set TARGET to the pane identified by the operator}"
: "${EXPECTED_PANE_PID:?set EXPECTED_PANE_PID to the verified pane PID}"
: "${RESTART_CHECK:?set RESTART_CHECK to an executable harness-state check}"
MSG="${MSG:-}"
OUT="${OUT:-$PWD}"
POLL_S="${POLL_S:-15}"
IDLE_TIMEOUT_MIN="${IDLE_TIMEOUT_MIN:-65}"
TURN_TIMEOUT_MIN="${TURN_TIMEOUT_MIN:-90}"
COMPOSER_PREFIX="${COMPOSER_PREFIX:-❯}"
FORMAT='#{pid} #{pane_id} #{pane_pid} #{pane_dead}'
SPIN='⠋|⠙|⠹|⠸|⠼|⠴|⠦|⠧|⠇|⠏|⠿|⡿|⣟|⣯|⣷|⣻|⢿|⡷|⣾|⣽|⣶|⣇|⣏'

if [[ $MSG == *[[:cntrl:]]* || ! -x $RESTART_CHECK ]]; then
  printf '%s\n' 'Refusing control characters in MSG or an unavailable RESTART_CHECK' >&2
  exit 3
fi
for interval in "$POLL_S" "$IDLE_TIMEOUT_MIN" "$TURN_TIMEOUT_MIN"; do
  [[ $interval =~ ^[1-9][0-9]*$ ]] || exit 3
done
umask 077
mkdir -p "$OUT" || exit 7
LOG="$OUT/watch.log"
log() { printf '%s %s\n' "$(date '+%F %T')" "$*" >>"$LOG" || exit 7; }
snapshot() { printf '%s\n' "$pane" >"$OUT/$1" || exit 7; }

identity=$(tmux display-message -p -t "$TARGET" "$FORMAT") || exit 2
if [[ ! $identity =~ ^[0-9]+\ (%[0-9]+)\ ([0-9]+)\ 0$ ]]; then
  log "REFUSED: target did not resolve to a live pane"
  exit 2
fi
pane_id=${BASH_REMATCH[1]}
pane_pid=${BASH_REMATCH[2]}
if [[ $pane_pid != "$EXPECTED_PANE_PID" ]]; then
  log "REFUSED: expected pane PID $EXPECTED_PANE_PID, got $pane_pid"
  exit 2
fi

check_target() {
  local listed
  # The pane ID survives session renames and regrouping; never fall back to TARGET.
  if ! listed=$(tmux list-panes -a -F "$FORMAT") ||
    [[ $'\n'$listed$'\n' != *$'\n'"$identity"$'\n'* ]]; then
    log "REFUSED: pane identity changed or vanished ($identity)"
    return 2
  fi
  if ! "$RESTART_CHECK" "$pane_id" "$pane_pid"; then
    log "REFUSED: restart, continuation or unknown harness state for $pane_id"
    return 3
  fi
}

capture() {
  check_target || return $?
  if ! pane=$(tmux capture-pane -p -t "$pane_id") || [[ -z ${pane//[[:space:]]/} ]]; then
    log "REFUSED: no visible capture from $pane_id"
    return 2
  fi
}

busy() {
  local signals="$SPIN|Subagents · [1-9][0-9]* running|waiting on [1-9][0-9]* job|Working…|[Ee]sc.*(close|back|quit)|q to quit|[Pp]ress .*continue"
  [[ $footer =~ $signals ]]
}

read_composer() {
  local line rest count=0
  footer=$(tail -n 10 <<<"$pane") || return 1
  composer=
  busy && return 1
  while IFS= read -r line; do
    if [[ $line == "$COMPOSER_PREFIX"* ]]; then
      rest=${line#"$COMPOSER_PREFIX"}
      composer=${rest#" "}
      count=$((count + 1))
    fi
  done <<<"$footer"
  [[ $count -eq 1 ]]
}

wait_idle() {
  local deadline=$((SECONDS + $1)) snap=$2 timeout=$3 previous= stable=0
  while (( SECONDS < deadline )); do
    capture || return $?
    if read_composer && [[ $composer != *[![:blank:]]* && $pane != "$before_send" ]]; then
      if [[ $pane == "$previous" ]]; then stable=$((stable + 1)); else stable=1; fi
      if (( stable >= 3 )); then
        snapshot "$snap"
        log "IDLE: $snap"
        return 0
      fi
      previous=$pane
    else
      previous=
      stable=0
      if [[ -n $MSG && -z $before_send && -n $composer ]]; then
        snapshot pane-abort.txt
        log "REFUSED: composer already has a draft"
        return 3
      fi
    fi
    sleep "$POLL_S"
  done
  snapshot pane-timeout.txt
  log "TIMEOUT: $snap"
  return "$timeout"
}

pane=
before_send=
log "WATCH: $identity"
wait_idle "$((IDLE_TIMEOUT_MIN * 60))" pane-idle.txt 4 || exit $?
if [[ -n $MSG ]]; then
  before_send=$pane
  capture || exit $?
  if [[ $pane != "$before_send" ]]; then
    snapshot pane-abort.txt
    log "REFUSED: pane changed after idle"
    exit 3
  fi
  check_target || exit $?
  if ! tmux send-keys -t "$pane_id" -l -- "$MSG"; then
    log "FAILED: literal send; Enter not attempted"
    exit 6
  fi
  sleep 1
  capture || exit $?
  if ! read_composer || [[ "$composer" != "$MSG" ]]; then
    snapshot pane-abort.txt
    log "REFUSED: draft readback did not match; Enter not attempted"
    exit 3
  fi
  check_target || exit $?
  if ! tmux send-keys -t "$pane_id" Enter; then
    log "FAILED: Enter; inspect composer before retrying"
    exit 6
  fi
  log "SENT: both tmux sends succeeded for $pane_id"
  capture || exit $?
  snapshot pane-after-send.txt
  wait_idle "$((TURN_TIMEOUT_MIN * 60))" pane-turn-done.txt 5 || exit $?
fi
log "DONE: verify the task outcome separately"
