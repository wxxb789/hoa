#!/usr/bin/env bash
# Hermetic stale-lane test for the launcher adapter.
#
# Synthesizes run dirs under a temp OMP_RUN_ROOT: no agent, no tmux session
# creation, no network. Proves that a run whose pane and pid are gone is
# finalized as failed (exit -1) exactly once, that list never reports it as
# running, that a run with a `finalized` marker is untouched, and that the
# forwarder resolves the launcher in both install layouts.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADAPTER="$(cd "$HERE/../adapters" && pwd)/omp-run.sh"
FORWARDER="$(cd "$HERE/../../../omp-headless-orchestration/scripts" && pwd)/omp-run.sh"
TODAY="$(date +%F)"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/omp-run-stale.XXXXXX")"
RUN_ROOT="$TMP/runs"
N=0

cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

ok() { N=$((N + 1)); echo "ok $N - $*"; }
fail() { echo "FAIL: $*" >&2; exit 1; }

export OMP_RUN_ROOT="$RUN_ROOT"

# make_run SLUG STATE [FINALIZED_EXIT]
make_run() {
  local slug="$1" state="$2" marker="${3:-}" dir="$RUN_ROOT/$TODAY/$1"
  mkdir -p "$dir"
  python3 - "$dir" "$slug" "$state" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone

run_dir, slug, state = sys.argv[1:4]
with open(os.path.join(run_dir, "state.json"), "w", encoding="utf-8") as handle:
    json.dump(
        {
            "name": slug,
            "state": state,
            "exit": 0 if state == "done" else None,
            "cwd": os.getcwd(),
            "started": datetime.now(timezone.utc).isoformat(),
            "ended": None,
            "duration_s": None,
            "tmux": "omp-absent-" + slug,
            "pid": 999999,
        },
        handle,
        indent=2,
    )
open(os.path.join(run_dir, "events.ndjson"), "w", encoding="utf-8").close()
PY
  [ -n "$marker" ] && printf '%s\n' "$marker" >"$dir/finalized"
  printf '%s\n' "$dir"
}

# --- 1. a dead lane is finalized as failed ---------------------------------

RUN1="$(make_run stale-run running)"
OUT1="$(bash "$ADAPTER" status stale-run 2>&1)"
RC1=$?
[ "$RC1" -eq 0 ] || fail "status on a dead run must exit 0 (rc=$RC1): $OUT1"
printf '%s\n' "$OUT1" | grep -q '"state": "failed"' \
  || fail "status must report failed: $OUT1"
printf '%s\n' "$OUT1" | grep -q 'stale_recovered: true' \
  || fail "status must print stale_recovered: true: $OUT1"
[ -f "$RUN1/finalized" ] || fail "status must write the finalized marker"
grep -q -- '^-1$' "$RUN1/finalized" || fail "finalized must hold exit -1"
python3 - "$RUN1" <<'PY' || fail "state.json must record the recovery"
import json
import os
import sys

state = json.load(open(os.path.join(sys.argv[1], "state.json"), encoding="utf-8"))
assert state["state"] == "failed", state
assert state["exit"] == -1, state
assert state.get("recovered_stale") is True, state
assert "disappeared without finalizing" in (state.get("note") or ""), state
PY
ok "status finalizes a dead lane as failed (stale_recovered)"

# --- 2. recovery is idempotent ---------------------------------------------

SUM1="$(cksum "$RUN1/state.json")"
OUT2="$(bash "$ADAPTER" status stale-run 2>&1)"
RC2=$?
SUM2="$(cksum "$RUN1/state.json")"
[ "$RC2" -eq 0 ] || fail "second status must exit 0 (rc=$RC2): $OUT2"
[ "$SUM1" = "$SUM2" ] || fail "second status must not rewrite state.json"
printf '%s\n' "$OUT2" | grep -q 'stale_recovered' \
  && fail "second status must not re-finalize: $OUT2"
ok "a finalized marker is respected (no second finalize)"

# --- 3. list reports the recovered run as failed/stale ---------------------

LIST_OUT="$(bash "$ADAPTER" list 2>&1)"
RC3=$?
[ "$RC3" -eq 0 ] || fail "list must exit 0 (rc=$RC3): $LIST_OUT"
RUN_LINE="$(printf '%s\n' "$LIST_OUT" | grep 'stale-run')"
[ -n "$RUN_LINE" ] || fail "list lost the run: $LIST_OUT"
printf '%s\n' "$RUN_LINE" | grep -q 'failed(stale)' \
  || fail "list must show failed(stale): $RUN_LINE"
printf '%s\n' "$RUN_LINE" | grep -q 'running' \
  && fail "list must not show a dead run as running: $RUN_LINE"
ok "list reports the dead run as failed(stale), not running"

# --- 4. a marked run is untouched by result --------------------------------

RUN4="$(make_run done-run done 0)"
SUM4="$(cksum "$RUN4/state.json")"
OUT4="$(bash "$ADAPTER" result done-run 2>&1)"
RC4=$?
SUM4_AFTER="$(cksum "$RUN4/state.json")"
[ "$RC4" -eq 0 ] || fail "result on a finished run must exit 0 (rc=$RC4): $OUT4"
[ "$SUM4" = "$SUM4_AFTER" ] || fail "result mutated a finalized run"
printf '%s\n' "$OUT4" | grep -q '"state": "done"' \
  || fail "result must report done: $OUT4"
printf '%s\n' "$OUT4" | grep -q 'stale_recovered' \
  && fail "result must not recover a marked run: $OUT4"
ok "a finalized run is untouched by result"

# --- 5. the forwarder finds the launcher -----------------------------------

STUB="$TMP/stub-omp-run.sh"
printf '#!/usr/bin/env bash\nprintf "forwarded\\n"\nexit 0\n' >"$STUB"
chmod +x "$STUB"
OUT5="$(OMP_RUN_SH="$STUB" bash "$FORWARDER" list 2>&1)"
RC5=$?
[ "$RC5" -eq 0 ] || fail "forwarder with OMP_RUN_SH must exit 0 (rc=$RC5): $OUT5"
printf '%s\n' "$OUT5" | grep -q '^forwarded$' \
  || fail "forwarder did not run the OMP_RUN_SH launcher: $OUT5"
ok "forwarder honours OMP_RUN_SH"

mkdir -p "$TMP/empty-runs"
OUT6="$(env -u OMP_RUN_SH OMP_RUN_ROOT="$TMP/empty-runs" bash "$FORWARDER" list 2>&1)"
RC6=$?
[ "$RC6" -eq 0 ] || fail "forwarder must find the installed launcher (rc=$RC6): $OUT6"
printf '%s\n' "$OUT6" | grep -q '(no runs recorded)' \
  || fail "forwarder did not reach the real launcher: $OUT6"
ok "forwarder finds the sibling launcher with OMP_RUN_SH unset"

# A categorized install: only the third candidate exists.
TREE="$TMP/tree"
COPY="$TREE/skills/omp-headless-orchestration/scripts/omp-run.sh"
CAT_STUB="$TREE/skills/software-development/gdd/scripts/adapters/omp-run.sh"
mkdir -p "$(dirname "$COPY")" "$(dirname "$CAT_STUB")"
cp "$FORWARDER" "$COPY"
printf '#!/usr/bin/env bash\nprintf "categorized\\n"\nexit 0\n' >"$CAT_STUB"
chmod +x "$COPY" "$CAT_STUB"
OUT7="$(env -u OMP_RUN_SH bash "$COPY" list 2>&1)"
RC7=$?
[ "$RC7" -eq 0 ] || fail "categorized forwarder must exit 0 (rc=$RC7): $OUT7"
printf '%s\n' "$OUT7" | grep -q '^categorized$' \
  || fail "forwarder did not resolve the categorized launcher: $OUT7"
ok "forwarder resolves the categorized launcher path"

echo "stale-test: $N/$N ok"
