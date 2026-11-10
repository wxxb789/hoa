#!/usr/bin/env bash
# watch-pr-checks.sh — bounded CI poller for one PR, with infra-only auto-rerun.
#
# Why: a job that dies in <60 s on a download step (curl 5xx while installing a pinned binary)
# is infra, not your diff. Rerunning it by hand costs a round-trip per occurrence; rerunning it
# unbounded turns a broken job green-adjacent by attrition. This bounds both.
#
# Usage: watch-pr-checks.sh <PR> [max_reruns] [max_polls] [logfile]
#   defaults: max_reruns=2  max_polls=40  logfile=<repo>/ci-watch-<head7>.log
#
# Exit: 0 all checks passed · 1 a check failed for real · 2 still pending · 3 usage/env error
set -uo pipefail
export GH_NO_SPINNER=1   # headless gh otherwise prints 'open terminal failed: not a terminal'

PR="${1:?usage: watch-pr-checks.sh <PR> [max_reruns] [max_polls] [logfile]}"
MAX_RERUNS="${2:-2}"
MAX_POLLS="${3:-40}"
FAST_FAIL_S=60          # a failing job shorter than this is infra, not code
REPO_ROOT="$(git rev-parse --show-toplevel)" || exit 3
HEAD7="$(git -C "$REPO_ROOT" rev-parse --short HEAD)"
LOG="${4:-$REPO_ROOT/ci-watch-$HEAD7.log}"

log() { printf '[%s] %s\n' "$(date -Iseconds)" "$*" | tee -a "$LOG"; }

rerun_seconds() {   # '1m5s' -> 65 · '32s' -> 32 · '5m45s' -> 345
  local d="$1" s=0 m=0
  [[ $d =~ ([0-9]+)m ]] && m="${BASH_REMATCH[1]}"
  [[ $d =~ ([0-9]+)s ]] && s="${BASH_REMATCH[1]}"
  echo $(( m * 60 + s ))
}

log "watching PR #$PR at head $HEAD7 (log: $LOG)"
reruns=0
for poll in $(seq 1 "$MAX_POLLS"); do
  out="$(gh pr checks "$PR" 2>&1)"
  log "poll $poll"; printf '%s\n' "$out" >>"$LOG"

  # Immediately after a push GitHub lists no checks at all and `gh pr checks` exits 1 with
  # "no checks reported", which contains none of the pending words — reading that as "nothing left
  # to wait for" declares a false green before the matrix has even registered, and the merge gate
  # then fails on a job that only just started. Require real rows, then require the merge state to
  # agree with them.
  if grep -qiE 'no checks reported|no check runs found' <<<"$out"; then
    log "  poll $poll: no checks registered yet"
    sleep 30
    continue
  fi
  rows="$(grep -cE $'^[^\t]+\t(pass|fail|pending|skipping)' <<<"$out" || true)"
  if (( ${rows:-0} == 0 )); then
    log "  poll $poll: no parseable check rows yet"
    sleep 30
    continue
  fi

  if ! grep -qE 'pending|queued|in_progress' <<<"$out"; then
    real=0
    while IFS=$'\t' read -r name state dur _rest; do
      [[ "$state" == "fail" ]] || continue
      secs="$(rerun_seconds "$dur")"
      if (( secs < FAST_FAIL_S )) && (( reruns < MAX_RERUNS )); then
        run_id="$(grep -F "$name" <<<"$out" | grep -oE 'runs/[0-9]+' | head -1 | cut -d/ -f2)"
        log "infra-looking fail: $name (${dur}) -> gh run rerun $run_id --failed"
        gh run rerun "$run_id" --failed >>"$LOG" 2>&1
        reruns=$(( reruns + 1 ))
        sleep 20
        continue 2
      fi
      log "real fail: $name (${dur})"
      real=1
    done <<<"$out"
    if (( real == 0 )); then
      state_line="$(gh pr view "$PR" --json mergeable,mergeStateStatus,headRefOid \
        --jq '"\(.mergeable) \(.mergeStateStatus) \(.headRefOid)"' | tee -a "$LOG")"
      observed_head="$(awk '{print $3}' <<<"$state_line")"
      if [[ -n "$observed_head" && "$observed_head" != "$HEAD7"* ]]; then
        log "head moved: watching $HEAD7 but the PR is at $observed_head"
        exit 2
      fi
      if ! grep -qE '^MERGEABLE CLEAN' <<<"$state_line"; then
        log "  poll $poll: checks done, merge state not CLEAN yet"
        sleep 30
        continue
      fi
      log "CI green"
      exit 0
    fi
    log "CI failed after $reruns infra rerun(s)"
    exit 1
  fi
  sleep 30
done
log "still pending after $MAX_POLLS polls"
exit 2
