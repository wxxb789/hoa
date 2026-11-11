#!/usr/bin/env bash
# Hermetic self-test for the goal-driven delivery scripts.
#
# Everything runs against temp roots and fake launchers: no real agent run, no
# tmux, no network. Covers the ledger, run discovery across the canonical and
# legacy layouts, stale locks, env-default resolution, template resolution from
# the script location, the launch path (success and failure), the concurrency
# guard, and the merge-gate fixtures.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS="$(cd "$HERE/.." && pwd)"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/gdd-selftest.XXXXXX")"
TODAY="$(date +%F)"
TASK_ROOT="$TMP/tasks"
RUN_ROOT="$TMP/runs"
PASS=0
TOTAL=0
LOCK_PID=""

cleanup() {
  [ -n "$LOCK_PID" ] && kill "$LOCK_PID" 2>/dev/null
  rm -rf "$TMP"
}
trap cleanup EXIT

check() {
  TOTAL=$((TOTAL + 1))
  if [ "$1" -eq 0 ]; then
    PASS=$((PASS + 1))
    echo "ok $TOTAL - $2"
  else
    echo "FAIL $TOTAL - $2"
    [ -n "${3:-}" ] && printf '%s\n' "$3" | sed 's/^/    | /'
  fi
}

export GDD_TASK_ROOT="$TASK_ROOT"
export GDD_RUN_ROOT="$RUN_ROOT"
export GDD_STATE_FILE="$TMP/ledger.tsv"
export XDG_CONFIG_HOME="$TMP/config-home"
mkdir -p "$XDG_CONFIG_HOME"
unset GDD_GOAL_GLOB

# --- fixtures ---------------------------------------------------------------

ORIGIN="$TMP/origin.git"
REPO="$TMP/workrepo"
git init -q --bare "$ORIGIN"
git -C "$ORIGIN" symbolic-ref HEAD refs/heads/main
git clone -q "$ORIGIN" "$REPO" 2>/dev/null
gitc() { git -C "$REPO" -c user.email=selftest@example.com -c user.name=selftest "$@"; }
gitc commit -q --allow-empty -m base
gitc push -q origin main
gitc checkout -q -b feat/increment
gitc commit -q --allow-empty -m "increment"
mkdir -p "$REPO/docs/goals"
printf '# 0001 goal\n' >"$REPO/docs/goals/0001-goal.md"
REPO_REAL="$(cd "$REPO" && pwd -P)"

# --- 1. ledger append / show ------------------------------------------------

"$SCRIPTS/delivery-state.py" append --state-file "$TMP/s.tsv" \
  --repo "$REPO" --goal 9999-selftest --stage implement \
  --base abc1234 --head def5678 --gates "test rc=0" >"$TMP/append.out" 2>&1
check $? "append exits 0"

SHOW="$TMP/show.out"
"$SCRIPTS/delivery-state.py" show --goal 9999-selftest --state-file "$TMP/s.tsv" \
  --repo "$REPO" --task-root "$TASK_ROOT" --run-root "$RUN_ROOT" >"$SHOW" 2>&1
check $? "show exits 0"

grep -q '^stage: implement$' "$SHOW" && grep -q '^base_sha: abc1234$' "$SHOW"
check $? "LATEST block has stage and base_sha"

HIST_LINES="$(awk '/^HISTORY$/{flag=1;next} /^LIVE$/{flag=0} flag && NF{n++} END{print n+0}' "$SHOW")"
[ "$HIST_LINES" -eq 1 ]
check $? "HISTORY has exactly 1 line (got $HIST_LINES)"

BRANCH="$(awk '/^branch: /{sub(/^branch: /,""); print; exit}' "$SHOW")"
[ -n "$BRANCH" ] && [ "${BRANCH#unknown}" = "$BRANCH" ]
check $? "LIVE branch is a real branch name (got '$BRANCH')"

STATE_MD="$TASK_ROOT/$TODAY/workrepo-9999-selftest/state.md"
[ -f "$STATE_MD" ] && grep -q '^LATEST$' "$STATE_MD"
check $? "state.md written under workrepo-9999-selftest task dir"

"$SCRIPTS/delivery-state.py" append --state-file "$TMP/bad.tsv" \
  --repo "$REPO" --goal x --stage nonsense >/dev/null 2>&1
[ $? -eq 2 ]
check $? "invalid stage exits 2"

# --- 2. merge-gate fixtures -------------------------------------------------

PR_OUT="$("$SCRIPTS/pr-merge-check.py" --selftest 2>&1)"
PR_RC=$?
PR_COUNTS="$(printf '%s\n' "$PR_OUT" | sed -n 's/^selftest: \([0-9]*\)\/\([0-9]*\) ok$/\1 \2/p')"
PR_OK="$(printf '%s' "$PR_COUNTS" | awk '{print ($1 == $2 && $2 > 0) ? 1 : 0}')"
[ "$PR_RC" -eq 0 ] && [ "$PR_OK" = 1 ]
check $? "pr-merge-check --selftest passes every fixture" "$PR_OUT"

printf '%s\n' "$PR_OUT" | grep -q 'custom-marker-present' \
  && printf '%s\n' "$PR_OUT" | grep -q 'marker-absent-allowed' \
  && printf '%s\n' "$PR_OUT" | grep -q 'marker-absent-blocked'
check $? "merge-gate fixtures cover --marker and --allow-no-machine-review" "$PR_OUT"

# --- 3. template root resolves from the script location ---------------------

IMPL_OUT="$TMP/impl.out"
env -u GDD_TEMPLATES "$SCRIPTS/gdd.py" stage --repo "$REPO" --goal 0001 \
  --stage implement --dry-run >"$IMPL_OUT" 2>&1
IMPL_RC=$?
IMPL_PROMPT="$(awk -F'prompt: ' '/^prompt: /{print $2; exit}' "$IMPL_OUT")"
[ "$IMPL_RC" -eq 0 ] && [ -n "$IMPL_PROMPT" ] && [ -f "$IMPL_PROMPT" ] \
  && grep -q 'You are implementing one written increment' "$IMPL_PROMPT"
check $? "template root resolves from the script location" "$(cat "$IMPL_OUT")"

case "$IMPL_PROMPT" in
  "$TASK_ROOT/$TODAY/workrepo-0001/prompts/"*) ;;
  *) IMPL_PROMPT="" ;;
esac
[ -n "$IMPL_PROMPT" ]
check $? "dry-run prompt lands under <task_root>/<date>/<repo>-<goal>/prompts"

STAGE_OUT="$("$SCRIPTS/gdd.py" stage --repo "$REPO" --goal 0001 --stage simplify --dry-run 2>&1)"
STAGE_RC=$?
[ "$STAGE_RC" -eq 0 ]
check $? "gdd simplify --dry-run exits 0" "$STAGE_OUT"

PROMPT_FILE="$(printf '%s\n' "$STAGE_OUT" | awk -F'prompt: ' '/^prompt: /{print $2; exit}')"
[ -n "$PROMPT_FILE" ] && [ -f "$PROMPT_FILE" ]
check $? "dry-run prompt file exists ($PROMPT_FILE)"

if [ -n "$PROMPT_FILE" ] && [ -f "$PROMPT_FILE" ]; then
  ! grep -q '\${' "$PROMPT_FILE"
  check $? "prompt contains no unresolved \${...}"

  grep -q 'Stage template' "$PROMPT_FILE"
  check $? "prompt came from the packaged stage template"

  grep -Eq '^Range: .*\.\.' "$PROMPT_FILE"
  check $? "prompt mentions the simplify range"
else
  check 1 "prompt contains no unresolved \${...}" "missing prompt file"
  check 1 "prompt came from the packaged stage template" "missing prompt file"
  check 1 "prompt mentions the simplify range" "missing prompt file"
fi

APP_OUT="$("$SCRIPTS/gdd.py" stage --repo "$REPO" --goal 0001 --stage apply --dry-run 2>&1)"
APP_RC=$?
[ "$APP_RC" -eq 2 ] && printf '%s\n' "$APP_OUT" | grep -q -- '--findings is required'
check $? "apply without --findings exits 2 with the right message" "$APP_OUT"

# --- 4. launch path through a fake launcher ---------------------------------

FAKE_LAUNCHER="$TMP/fake-launcher.sh"
cat >"$FAKE_LAUNCHER" <<'FAKE'
#!/usr/bin/env bash
# Hermetic stand-in for the launcher contract: records a finished run and
# prints the lines gdd.py parses.
set -uo pipefail
[ -n "${FAKE_ARGS:-}" ] && printf '%s ' "$@" >"$FAKE_ARGS"
name="" prompt="" cwd=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --name) name="${2:-}"; shift 2 ;;
    --prompt) prompt="${2:-}"; shift 2 ;;
    --cwd) cwd="${2:-}"; shift 2 ;;
    *) shift ;;
  esac
done
[ -n "$name" ] || { echo "fake: --name required" >&2; exit 9; }
[ -n "$prompt" ] && [ -f "$prompt" ] || { echo "fake: prompt missing: $prompt" >&2; exit 9; }
[ -n "$cwd" ] && [ -d "$cwd" ] || { echo "fake: cwd missing: $cwd" >&2; exit 9; }
root="${GDD_RUN_ROOT:-${XDG_STATE_HOME:-$HOME/.local/state}/gdd/runs}"
run_dir="$root/$(date +%F)/$name"
mkdir -p "$run_dir"
python3 - "$run_dir" "$name" "$cwd" <<'PY'
import json
import sys
from datetime import datetime, timezone

run_dir, name, cwd = sys.argv[1:4]
now = datetime.now(timezone.utc).isoformat()
state = {
    "name": name,
    "state": "done",
    "exit": 0,
    "cwd": cwd,
    "started": now,
    "ended": now,
    "duration_s": 1,
}
with open(run_dir + "/state.json", "w", encoding="utf-8") as handle:
    json.dump(state, handle)
with open(run_dir + "/answer.md", "w", encoding="utf-8") as handle:
    handle.write("fake run finished\n")
PY
echo "started: $name"
[ "${FAKE_NO_RUN_DIR:-0}" = 1 ] || echo "  run dir   : $run_dir"
FAKE
chmod +x "$FAKE_LAUNCHER"

LAUNCH_OUT="$TMP/launch.out"
env GDD_LAUNCHER="$FAKE_LAUNCHER" GDD_STATE_FILE="$TMP/launch.tsv" timeout 60 \
  "$SCRIPTS/gdd.py" stage --repo "$REPO" --goal 0001 --stage simplify \
  --base abc1234 --head def5678 --wait >"$LAUNCH_OUT" 2>&1
LAUNCH_RC=$?
[ "$LAUNCH_RC" -eq 0 ]
check $? "launch via the fake launcher with --wait exits 0" "$(cat "$LAUNCH_OUT")"

grep -qx 'run: workrepo-0001-simplify' "$LAUNCH_OUT"
check $? "launch prints the run name"

grep -qx "run_dir: $RUN_ROOT/$TODAY/workrepo-0001-simplify" "$LAUNCH_OUT" \
  && grep -qx 'finished: state=done exit=0 dur=1' "$LAUNCH_OUT"
check $? "launch prints run_dir and --wait observes the fake done state" "$(cat "$LAUNCH_OUT")"

LEDGER_ROWS="$(awk -F'\t' '$3=="0001" && $4=="simplify"' "$TMP/launch.tsv" | wc -l)"
[ "$LEDGER_ROWS" -eq 2 ] && grep -q 'exit=0 dur=1' "$TMP/launch.tsv"
check $? "ledger has the stage row plus the --wait result row (got $LEDGER_ROWS)"

LAUNCH_PROMPT="$(ls "$TASK_ROOT/$TODAY/workrepo-0001/prompts/"simplify-*.md 2>/dev/null | head -n1)"
[ -n "$LAUNCH_PROMPT" ] && grep -Fq "$REPO_REAL/docs/goals/0001-goal.md" "$LAUNCH_PROMPT"
check $? "launch prompt resolved the contract file"

# Model / thinking / max-time must be pass-through only, never defaulted.
FAKE_ARGS="$TMP/launch-args.txt"
rm -f "$FAKE_ARGS"
env -u GDD_MODEL -u GDD_THINKING -u GDD_MAX_TIME FAKE_ARGS="$FAKE_ARGS" \
  GDD_LAUNCHER="$FAKE_LAUNCHER" GDD_STATE_FILE="$TMP/launch2.tsv" \
  "$SCRIPTS/gdd.py" stage --repo "$REPO" --goal 0001 --stage simplify \
  --base abc1234 --head def5678 >/dev/null 2>&1
[ -s "$FAKE_ARGS" ] \
  && ! grep -q -- '--model' "$FAKE_ARGS" \
  && ! grep -q -- '--thinking' "$FAKE_ARGS" \
  && ! grep -q -- '--max-time' "$FAKE_ARGS"
check $? "launch passes no model/thinking/max-time unless supplied"

rm -f "$FAKE_ARGS"
env FAKE_ARGS="$FAKE_ARGS" GDD_MODEL=demo-model GDD_THINKING=high GDD_MAX_TIME=5m \
  GDD_LAUNCHER="$FAKE_LAUNCHER" GDD_STATE_FILE="$TMP/launch3.tsv" \
  "$SCRIPTS/gdd.py" stage --repo "$REPO" --goal 0001 --stage simplify \
  --base abc1234 --head def5678 >/dev/null 2>&1
[ -s "$FAKE_ARGS" ] \
  && grep -q -- '--model demo-model' "$FAKE_ARGS" \
  && grep -q -- '--thinking high' "$FAKE_ARGS" \
  && grep -q -- '--max-time 5m' "$FAKE_ARGS"
check $? "GDD_MODEL / GDD_THINKING / GDD_MAX_TIME are passed through"

STATUS_OUT="$("$SCRIPTS/gdd.py" status --repo "$REPO" --goal 9999-selftest 2>&1)"
printf '%s\n' "$STATUS_OUT" | grep -q '^LATEST$'
check $? "gdd status delegates to delivery-state.py show" "$STATUS_OUT"

# --- 5. concurrency guard ---------------------------------------------------

BUSY_DIR="$RUN_ROOT/$TODAY/busy-run"
mkdir -p "$BUSY_DIR"
python3 - "$BUSY_DIR" "$REPO_REAL" <<'PY'
import json
import sys

run_dir, cwd = sys.argv[1:3]
with open(run_dir + "/state.json", "w", encoding="utf-8") as handle:
    json.dump(
        {"name": "busy-run", "state": "running", "exit": None, "cwd": cwd, "duration_s": None},
        handle,
    )
PY
GUARD_OUT="$TMP/guard.out"
env GDD_LAUNCHER="$FAKE_LAUNCHER" GDD_STATE_FILE="$TMP/guard.tsv" \
  "$SCRIPTS/gdd.py" stage --repo "$REPO" --goal 0001 --stage simplify \
  --base abc1234 --head def5678 >"$GUARD_OUT" 2>&1
GUARD_RC=$?
[ "$GUARD_RC" -eq 3 ] && grep -q 'busy-run' "$GUARD_OUT"
check $? "concurrency guard exits 3 naming the active run (rc=$GUARD_RC)" "$(cat "$GUARD_OUT")"
rm -rf "$BUSY_DIR"

# --- 6. archived contract resolution ---------------------------------------

ARCH_REPO="$TMP/archrepo"
mkdir -p "$ARCH_REPO/docs/goals/archive"
git init -q "$ARCH_REPO"
git -C "$ARCH_REPO" -c user.email=selftest@example.com -c user.name=selftest \
  commit -q --allow-empty -m base
printf '# archived 0001\n' >"$ARCH_REPO/docs/goals/archive/0001-goal.md"
ARCH_REAL="$(cd "$ARCH_REPO" && pwd -P)"
ARCH_OUT="$TMP/arch.out"
env GDD_LAUNCHER="$FAKE_LAUNCHER" GDD_STATE_FILE="$TMP/arch.tsv" \
  "$SCRIPTS/gdd.py" stage --repo "$ARCH_REPO" --goal 0001 --stage simplify --dry-run \
  --base abc1234 --head def5678 >"$ARCH_OUT" 2>&1
ARCH_RC=$?
[ "$ARCH_RC" -eq 0 ] \
  && grep -Fq "$ARCH_REAL/docs/goals/archive/0001-goal.md" "$ARCH_OUT"
check $? "GOAL_FILE resolves to docs/goals/archive" "$(cat "$ARCH_OUT")"

# --- 7. live facts: ahead / behind / base ----------------------------------

D1_ORIGIN="$TMP/d1-origin.git"
D1_REPO="$TMP/d1repo"
git init -q --bare "$D1_ORIGIN"
git -C "$D1_ORIGIN" symbolic-ref HEAD refs/heads/main
git clone -q "$D1_ORIGIN" "$D1_REPO" 2>/dev/null
gitd() { git -C "$D1_REPO" -c user.email=selftest@example.com -c user.name=selftest "$@"; }
gitd commit -q --allow-empty -m base
gitd push -q origin main
gitd checkout -q -b feat/behind
gitd commit -q --allow-empty -m "feature commit"
gitd checkout -q main
gitd commit -q --allow-empty -m "main advance"
gitd push -q origin main
gitd checkout -q feat/behind
D1_REAL="$(cd "$D1_REPO" && pwd -P)"

D1_STATE="$TMP/d1.tsv"
D1_SHOW="$TMP/d1-show.out"
"$SCRIPTS/delivery-state.py" show --repo "$D1_REPO" --goal 0001 \
  --state-file "$D1_STATE" --task-root "$TMP/d1tasks" --run-root "$TMP/d1runs" >"$D1_SHOW" 2>&1
D1_RC=$?

grep -qx 'ahead_of_origin_main: 1' "$D1_SHOW"
check $? "D1 keeps ahead_of_origin_main: 1" "$(cat "$D1_SHOW")"

[ "$D1_RC" -eq 0 ] && grep -qx 'behind_origin_main: 1' "$D1_SHOW"
check $? "D1 shows behind_origin_main: 1" "$(cat "$D1_SHOW")"

grep -qx 'base_is_origin_main: no' "$D1_SHOW"
check $? "D1 shows base_is_origin_main: no for a stale base" "$(cat "$D1_SHOW")"

gitd checkout -q -B feat/synced origin/main
D1_SYNCED="$TMP/d1-synced.out"
"$SCRIPTS/delivery-state.py" show --repo "$D1_REPO" --goal 0001 \
  --state-file "$D1_STATE" --task-root "$TMP/d1tasks2" --run-root "$TMP/d1runs" >"$D1_SYNCED" 2>&1
grep -qx 'behind_origin_main: 0' "$D1_SYNCED"
check $? "D1 shows behind_origin_main: 0 when the branch is at origin/main" "$(cat "$D1_SYNCED")"

grep -qx 'base_is_origin_main: yes' "$D1_SYNCED"
check $? "D1 shows base_is_origin_main: yes when merge-base is origin/main" "$(cat "$D1_SYNCED")"

# --- 8. run discovery: legacy omp-runs layout and goal preference ----------

D2_ROOT="$TMP/d2tasks"
D2_OLD="$D2_ROOT/2026-11-08/omp-runs/fs-0001-apply"
D2_NEW="$D2_ROOT/2026-11-09/omp-runs/tools-work"
mkdir -p "$D2_OLD" "$D2_NEW"
python3 - "$D2_OLD" "$D2_NEW" "$D1_REAL" <<'PY'
import json
import sys

old_dir, new_dir, cwd = sys.argv[1:4]
with open(old_dir + "/state.json", "w", encoding="utf-8") as handle:
    json.dump(
        {
            "name": "fs-0001-apply",
            "state": "running",
            "exit": None,
            "duration_s": None,
            "cwd": cwd,
        },
        handle,
    )
with open(new_dir + "/state.json", "w", encoding="utf-8") as handle:
    json.dump(
        {
            "name": "tools-work",
            "state": "done",
            "exit": 0,
            "duration_s": 411.1,
            "cwd": cwd,
        },
        handle,
    )
PY
touch -d '2026-11-08 18:03:00' "$D2_OLD/state.json"
touch -d '2026-11-09 03:00:00' "$D2_NEW/state.json"

D2_SHOW="$TMP/d2-show.out"
"$SCRIPTS/delivery-state.py" show --repo "$D1_REPO" --goal 0001 \
  --state-file "$D1_STATE" --task-root "$D2_ROOT" --run-root "$TMP/d2runs" >"$D2_SHOW" 2>&1
grep -qx 'last_run: fs-0001-apply running exit=- dur=-' "$D2_SHOW"
check $? "legacy omp-runs layout is scanned; goal match wins over a newer run" "$(cat "$D2_SHOW")"

D2_ANY="$TMP/d2-any.out"
"$SCRIPTS/delivery-state.py" show --repo "$D1_REPO" --goal 7777 \
  --state-file "$D1_STATE" --task-root "$D2_ROOT" --run-root "$TMP/d2runs" >"$D2_ANY" 2>&1
grep -qx 'last_run: tools-work done exit=0 dur=411.1' "$D2_ANY"
check $? "falls back to the newest run when no name mentions the goal" "$(cat "$D2_ANY")"

mkdir -p "$TMP/d2none"
D2_NONE="$TMP/d2-none.out"
"$SCRIPTS/delivery-state.py" show --repo "$TMP/d2none" --goal 0001 \
  --state-file "$D1_STATE" --task-root "$D2_ROOT" --run-root "$TMP/d2runs" >"$D2_NONE" 2>&1
grep -qx 'last_run: none (no runs for this repo)' "$D2_NONE"
check $? "prints none (no runs for this repo) when nothing matches" "$(cat "$D2_NONE")"

# --- 8b. remaining run layouts: runs/ and <repo>-<goal>/... ----------------

RUNS_ROOT="$TMP/runslayout"
RUNS_DIR="$RUNS_ROOT/2026-11-08/runs/run-named-runs"
mkdir -p "$RUNS_DIR"
python3 - "$RUNS_DIR" "$D1_REAL" <<'PY'
import json
import sys

run_dir, cwd = sys.argv[1:3]
with open(run_dir + "/state.json", "w", encoding="utf-8") as handle:
    json.dump(
        {"name": "run-named-runs", "state": "done", "exit": 0, "duration_s": 2.5, "cwd": cwd},
        handle,
    )
PY
RUNS_SHOW="$TMP/runs-show.out"
"$SCRIPTS/delivery-state.py" show --repo "$D1_REPO" --goal 0001 \
  --state-file "$D1_STATE" --task-root "$RUNS_ROOT" --run-root "$TMP/emptyruns" >"$RUNS_SHOW" 2>&1
grep -qx 'last_run: run-named-runs done exit=0 dur=2.5' "$RUNS_SHOW"
check $? "run dirs named runs/ are scanned" "$(cat "$RUNS_SHOW")"

NESTED_ROOT="$TMP/nestedtasks"
NESTED_DIR="$NESTED_ROOT/2026-11-08/workrepo-0001/nested-run"
mkdir -p "$NESTED_DIR"
python3 - "$NESTED_DIR" "$D1_REAL" <<'PY'
import json
import sys

run_dir, cwd = sys.argv[1:3]
with open(run_dir + "/state.json", "w", encoding="utf-8") as handle:
    json.dump(
        {"name": "nested-run", "state": "done", "exit": 0, "duration_s": 3.5, "cwd": cwd},
        handle,
    )
PY
NESTED_SHOW="$TMP/nested-show.out"
"$SCRIPTS/delivery-state.py" show --repo "$D1_REPO" --goal 0001 \
  --state-file "$D1_STATE" --task-root "$NESTED_ROOT" --run-root "$TMP/emptyruns" >"$NESTED_SHOW" 2>&1
grep -qx 'last_run: nested-run done exit=0 dur=3.5' "$NESTED_SHOW"
check $? "<task_root>/<date>/<repo>-<goal>/... layout is scanned" "$(cat "$NESTED_SHOW")"

# --- 9. failed launch keeps the ledger honest ------------------------------

FAIL_LAUNCHER="$TMP/fake-fail.sh"
cat >"$FAIL_LAUNCHER" <<'FAKE'
#!/usr/bin/env bash
# Fails before it can create any run state.
echo "fake: launcher start failed: no agent session" >&2
exit 1
FAKE
chmod +x "$FAIL_LAUNCHER"
FAIL_OUT="$TMP/fail.out"
env GDD_LAUNCHER="$FAIL_LAUNCHER" GDD_STATE_FILE="$TMP/fail.tsv" \
  GDD_TASK_ROOT="$TMP/failtasks" GDD_RUN_ROOT="$TMP/failruns" \
  "$SCRIPTS/gdd.py" stage --repo "$REPO" --goal 0001 --stage simplify \
  --base abc1234 --head def5678 >"$FAIL_OUT" 2>&1
FAIL_RC=$?
[ "$FAIL_RC" -eq 3 ]
check $? "failed launch exits 3 (rc=$FAIL_RC)" "$(cat "$FAIL_OUT")"

grep -q 'launch failed: fake: launcher start failed: no agent session' "$FAIL_OUT"
check $? "failed launch prints the launcher error" "$(cat "$FAIL_OUT")"

FAIL_BLOCKED="$(awk -F'\t' '$3=="0001" && $4=="blocked" && $13=="launch-failed: fake: launcher start failed: no agent session"' "$TMP/fail.tsv" | wc -l)"
FAIL_STARTED="$(awk -F'\t' '$3=="0001" && $4=="simplify"' "$TMP/fail.tsv" | wc -l)"
[ "$FAIL_BLOCKED" -eq 1 ] && [ "$FAIL_STARTED" -eq 0 ]
check $? "failed launch writes one blocked row and no started row (blocked=$FAIL_BLOCKED started=$FAIL_STARTED)" "$(cat "$TMP/fail.tsv" 2>/dev/null)"

[ ! -e "$TMP/failruns/$TODAY/workrepo-0001-simplify" ]
check $? "failed launch wrote no run directory"

# --- 10. env-default resolution --------------------------------------------

XDG="$TMP/xdg"
mkdir -p "$XDG"
env -u GDD_STATE_FILE -u GDD_TASK_ROOT -u GDD_RUN_ROOT XDG_STATE_HOME="$XDG" \
  "$SCRIPTS/delivery-state.py" append --repo "$REPO" --goal 0002 --stage implement \
  --base abc1234 --head def5678 >"$TMP/xdg-append.out" 2>&1
[ -f "$XDG/gdd/ledger.tsv" ] && grep -q '0002' "$XDG/gdd/ledger.tsv"
check $? "GDD_STATE_FILE default resolves under XDG_STATE_HOME"

env -u GDD_STATE_FILE -u GDD_TASK_ROOT -u GDD_RUN_ROOT XDG_STATE_HOME="$XDG" \
  "$SCRIPTS/delivery-state.py" show --repo "$REPO" --goal 0002 >"$TMP/xdg-show.out" 2>&1
XDG_STATE_MD="$XDG/gdd/tasks/$TODAY/workrepo-0002/state.md"
[ -f "$XDG_STATE_MD" ] && grep -q '^LATEST$' "$XDG_STATE_MD"
check $? "GDD_TASK_ROOT default resolves under XDG_STATE_HOME"

XDG_RUN_OUT="$TMP/xdg-run.out"
env -u GDD_STATE_FILE -u GDD_TASK_ROOT -u GDD_RUN_ROOT \
  XDG_STATE_HOME="$XDG" GDD_LAUNCHER="$FAKE_LAUNCHER" FAKE_NO_RUN_DIR=1 timeout 60 \
  "$SCRIPTS/gdd.py" stage --repo "$REPO" --goal 0002 --stage simplify \
  --base abc1234 --head def5678 --wait >"$XDG_RUN_OUT" 2>&1
grep -qx "run_dir: $XDG/gdd/runs/$TODAY/workrepo-0002-simplify" "$XDG_RUN_OUT"
check $? "GDD_RUN_ROOT default drives the fallback run dir" "$(cat "$XDG_RUN_OUT")"

# --- 11. lock honesty -------------------------------------------------------

# Pin the finished run older so "newest run" selection cannot depend on timing.
touch -d '2026-01-01 00:00:00' "$RUN_ROOT/$TODAY/workrepo-0001-simplify/state.json" 2>/dev/null

LOCK_DIR="$RUN_ROOT/$TODAY/workrepo-0001-simplify-lock"
mkdir -p "$LOCK_DIR"
DEAD_PID="$(python3 -c 'import os; print(os.getpid())')"
python3 - "$LOCK_DIR" "$REPO_REAL" "$DEAD_PID" <<'PY'
import json
import sys

run_dir, cwd, pid = sys.argv[1:4]
with open(run_dir + "/state.json", "w", encoding="utf-8") as handle:
    json.dump(
        {
            "name": "workrepo-0001-simplify-lock",
            "state": "running",
            "exit": None,
            "cwd": cwd,
            "started": "2026-01-01T00:00:00+00:00",
            "ended": None,
            "duration_s": None,
        },
        handle,
    )
with open(run_dir + "/lock", "w", encoding="utf-8") as handle:
    json.dump({"pid": int(pid), "tmux": None}, handle)
PY
touch "$LOCK_DIR/state.json"

LOCK_SHOW="$TMP/lock-show.out"
"$SCRIPTS/delivery-state.py" show --repo "$REPO" --goal 0001 \
  --state-file "$TMP/s.tsv" --task-root "$TASK_ROOT" --run-root "$RUN_ROOT" >"$LOCK_SHOW" 2>&1
grep -qx 'last_run: workrepo-0001-simplify-lock stale lock exit=- dur=-' "$LOCK_SHOW"
check $? "a lock file with a dead process reports stale lock" "$(cat "$LOCK_SHOW")"

sleep 30 &
LOCK_PID=$!
LIVE_DIR="$RUN_ROOT/$TODAY/workrepo-0001-simplify-live"
mkdir -p "$LIVE_DIR"
python3 - "$LIVE_DIR" "$REPO_REAL" "$LOCK_PID" <<'PY'
import json
import sys

run_dir, cwd, pid = sys.argv[1:4]
with open(run_dir + "/state.json", "w", encoding="utf-8") as handle:
    json.dump(
        {
            "name": "workrepo-0001-simplify-live",
            "state": "running",
            "exit": None,
            "cwd": cwd,
            "started": "2026-01-01T00:00:00+00:00",
            "ended": None,
            "duration_s": None,
        },
        handle,
    )
with open(run_dir + "/lock", "w", encoding="utf-8") as handle:
    json.dump({"pid": int(pid), "tmux": None}, handle)
PY
touch "$LIVE_DIR/state.json"

LIVE_SHOW="$TMP/live-show.out"
"$SCRIPTS/delivery-state.py" show --repo "$REPO" --goal 0001 \
  --state-file "$TMP/s.tsv" --task-root "$TASK_ROOT" --run-root "$RUN_ROOT" >"$LIVE_SHOW" 2>&1
grep -qx 'last_run: workrepo-0001-simplify-live running exit=- dur=-' "$LIVE_SHOW"
check $? "a lock file with a live process reports running" "$(cat "$LIVE_SHOW")"
kill "$LOCK_PID" 2>/dev/null
wait "$LOCK_PID" 2>/dev/null
LOCK_PID=""

STALE_DIR="$RUN_ROOT/$TODAY/workrepo-0001-simplify-guarded"
mkdir -p "$STALE_DIR"
python3 - "$STALE_DIR" "$REPO_REAL" "$DEAD_PID" <<'PY'
import json
import sys

run_dir, cwd, pid = sys.argv[1:4]
with open(run_dir + "/state.json", "w", encoding="utf-8") as handle:
    json.dump(
        {"name": "workrepo-0001-simplify-guarded", "state": "running", "exit": None, "cwd": cwd},
        handle,
    )
with open(run_dir + "/lock", "w", encoding="utf-8") as handle:
    json.dump({"pid": int(pid), "tmux": None}, handle)
PY
GUARD2_OUT="$TMP/guard2.out"
env GDD_LAUNCHER="$FAKE_LAUNCHER" GDD_STATE_FILE="$TMP/guard2.tsv" \
  "$SCRIPTS/gdd.py" stage --repo "$REPO" --goal 0001 --stage simplify \
  --base abc1234 --head def5678 >"$GUARD2_OUT" 2>&1
GUARD2_RC=$?
[ "$GUARD2_RC" -eq 0 ]
check $? "a stale lock does not block a new run (rc=$GUARD2_RC)" "$(cat "$GUARD2_OUT")"

# --- 12. adapter contract and help text ------------------------------------

ADAPTER="$SCRIPTS/adapters/omp-run.sh"
ADAPTER_HELP="$("$ADAPTER" --help 2>&1)"
printf '%s\n' "$ADAPTER_HELP" | grep -q 'status SLUG | result SLUG | answer SLUG | kill SLUG'
check $? "adapter help prints the launcher contract"

OMP_BIN="$TMP/no-such-agent" "$ADAPTER" start --name x --prompt "$IMPL_PROMPT" \
  --cwd "$TMP" >"$TMP/adapter.out" 2>&1
[ $? -eq 1 ] && grep -q 'agent binary not found' "$TMP/adapter.out"
check $? "adapter refuses to start without an agent binary" "$(cat "$TMP/adapter.out")"

GDD_HELP="$("$SCRIPTS/gdd.py" --help 2>&1)"
printf '%s\n' "$GDD_HELP" | grep -q 'GDD_LAUNCHER' \
  && printf '%s\n' "$GDD_HELP" | grep -q 'status SLUG'
check $? "gdd --help states the env vars and the launcher contract"

DS_HELP="$("$SCRIPTS/delivery-state.py" --help 2>&1)"
printf '%s\n' "$DS_HELP" | grep -q 'GDD_STATE_FILE' \
  && printf '%s\n' "$DS_HELP" | grep -q 'GDD_RUN_ROOT'
check $? "delivery-state --help states its env vars"

PR_HELP="$("$SCRIPTS/pr-merge-check.py" --help 2>&1)"
printf '%s\n' "$PR_HELP" | grep -q -- '--marker' \
  && printf '%s\n' "$PR_HELP" | grep -q -- '--allow-no-machine-review'
check $? "pr-merge-check --help documents marker and allow-no-machine-review"

# --- 13. operator config file ----------------------------------------------

CFG_HOME="$XDG_CONFIG_HOME"
CFG_DIR="$CFG_HOME/goal-driven-delivery"
CFG_FILE="$CFG_DIR/config.yaml"
CFG_LEDGER="$TMP/config-ledger.tsv"
mkdir -p "$CFG_DIR"
printf 'GDD_STATE_FILE: %s\n' "$CFG_LEDGER" >"$CFG_FILE"

CFG_RUN_OUT="$TMP/config-run.out"
env -u GDD_STATE_FILE -u GDD_LAUNCHER XDG_CONFIG_HOME="$CFG_HOME" \
  GDD_LAUNCHER="$FAKE_LAUNCHER" \
  "$SCRIPTS/gdd.py" stage --repo "$REPO" --goal 0003 --stage simplify \
  --base abc1234 --head def5678 >"$CFG_RUN_OUT" 2>&1
CFG_RC=$?
[ "$CFG_RC" -eq 0 ] && [ -f "$CFG_LEDGER" ] && grep -q '0003' "$CFG_LEDGER"
check $? "config-file GDD_STATE_FILE is honoured (rc=$CFG_RC)" "$(cat "$CFG_RUN_OUT")"

CFG_SHOW="$TMP/config-show.out"
env -u GDD_STATE_FILE -u GDD_LAUNCHER XDG_CONFIG_HOME="$CFG_HOME" \
  "$SCRIPTS/gdd.py" status --repo "$REPO" --goal 0003 >"$CFG_SHOW" 2>&1
grep -qx 'stage: simplify' "$CFG_SHOW"
check $? "gdd status reads the config-file ledger" "$(cat "$CFG_SHOW")"

ENV_LEDGER="$TMP/env-ledger.tsv"
env GDD_STATE_FILE="$ENV_LEDGER" GDD_LAUNCHER="$FAKE_LAUNCHER" \
  XDG_CONFIG_HOME="$CFG_HOME" \
  "$SCRIPTS/gdd.py" stage --repo "$REPO" --goal 0004 --stage simplify \
  --base abc1234 --head def5678 >"$TMP/env-run.out" 2>&1
[ $? -eq 0 ] && [ -f "$ENV_LEDGER" ] && grep -q '0004' "$ENV_LEDGER" \
  && ! grep -q '0004' "$CFG_LEDGER"
check $? "environment beats the config file" "$(cat "$TMP/env-run.out")"

printf 'GDD_STATE_FILE: %s\nGDD_LAUNCHER: /nonexistent-launcher\n' "$CFG_LEDGER" >"$CFG_FILE"
CLI_OUT="$TMP/cli-wins.out"
env -u GDD_STATE_FILE -u GDD_LAUNCHER XDG_CONFIG_HOME="$CFG_HOME" \
  "$SCRIPTS/gdd.py" stage --repo "$REPO" --goal 0005 --stage simplify \
  --base abc1234 --head def5678 --launcher "$FAKE_LAUNCHER" >"$CLI_OUT" 2>&1
CLI_RC=$?
[ "$CLI_RC" -eq 0 ] && grep -q '0005' "$CFG_LEDGER"
check $? "explicit --launcher beats the config file (rc=$CLI_RC)" "$(cat "$CLI_OUT")"

printf 'nested:\n  child: value\n' >"$CFG_FILE"
BAD_OUT="$TMP/bad-config.out"
env -u GDD_STATE_FILE -u GDD_LAUNCHER XDG_CONFIG_HOME="$CFG_HOME" \
  "$SCRIPTS/gdd.py" stage --repo "$REPO" --goal 0006 --stage simplify \
  --base abc1234 --head def5678 --launcher "$FAKE_LAUNCHER" >"$BAD_OUT" 2>&1
BAD_RC=$?
[ "$BAD_RC" -eq 2 ] && grep -q "$CFG_FILE:1:" "$BAD_OUT"
check $? "malformed config exits 2 naming path and line (rc=$BAD_RC)" "$(cat "$BAD_OUT")"

# --- 13b. config-file run root reaches the launcher -------------------------

CFG_RUN_ROOT="$TMP/config-runs"
CFG_TASK_ROOT="$TMP/config-runs-tasks"
CFG_RUN_LEDGER="$TMP/config-runs-ledger.tsv"
CFG_LAUNCHER="$TMP/fake-run-root.sh"
CFG_RECORD="$TMP/launcher-run-root.txt"
cat >"$CFG_LAUNCHER" <<'FAKE'
#!/usr/bin/env bash
# Records the run root it received and creates the run under it, like a real
# launcher. Refuses to guess when the variable is absent.
set -uo pipefail
printf '%s' "${GDD_RUN_ROOT:-}" >"$FAKE_RECORD"
[ -n "${GDD_RUN_ROOT:-}" ] || { echo "fake: GDD_RUN_ROOT not exported" >&2; exit 9; }
name="" cwd=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --name) name="${2:-}"; shift 2 ;;
    --cwd) cwd="${2:-}"; shift 2 ;;
    *) shift ;;
  esac
done
run_dir="$GDD_RUN_ROOT/$(date +%F)/$name"
mkdir -p "$run_dir"
python3 - "$run_dir" "$name" "$cwd" <<'PY'
import json
import sys

run_dir, name, cwd = sys.argv[1:4]
with open(run_dir + "/state.json", "w", encoding="utf-8") as handle:
    json.dump(
        {
            "name": name,
            "state": "running",
            "exit": None,
            "cwd": cwd,
            "started": None,
            "ended": None,
            "duration_s": None,
        },
        handle,
    )
PY
echo "started: $name"
echo "  run dir   : $run_dir"
FAKE
chmod +x "$CFG_LAUNCHER"

printf 'GDD_STATE_FILE: %s\nGDD_TASK_ROOT: %s\nGDD_RUN_ROOT: %s\n' \
  "$CFG_RUN_LEDGER" "$CFG_TASK_ROOT" "$CFG_RUN_ROOT" >"$CFG_FILE"
CFG_ROOT_OUT="$TMP/config-run-root.out"
env -u GDD_STATE_FILE -u GDD_TASK_ROOT -u GDD_RUN_ROOT -u GDD_LAUNCHER \
  XDG_CONFIG_HOME="$CFG_HOME" FAKE_RECORD="$CFG_RECORD" \
  GDD_LAUNCHER="$CFG_LAUNCHER" \
  "$SCRIPTS/gdd.py" stage --repo "$REPO" --goal 0007 --stage simplify \
  --base abc1234 --head def5678 >"$CFG_ROOT_OUT" 2>&1
CFG_ROOT_RC=$?
[ "$CFG_ROOT_RC" -eq 0 ] && [ "$(cat "$CFG_RECORD" 2>/dev/null)" = "$CFG_RUN_ROOT" ]
check $? "config-file GDD_RUN_ROOT is exported to the launcher (rc=$CFG_ROOT_RC)" "$(cat "$CFG_ROOT_OUT")"

CFG_RUN_STATUS="$TMP/config-run-root-status.out"
env -u GDD_STATE_FILE -u GDD_TASK_ROOT -u GDD_RUN_ROOT -u GDD_LAUNCHER \
  XDG_CONFIG_HOME="$CFG_HOME" \
  "$SCRIPTS/gdd.py" status --repo "$REPO" --goal 0007 >"$CFG_RUN_STATUS" 2>&1
grep -qx 'last_run: workrepo-0007-simplify running exit=- dur=-' "$CFG_RUN_STATUS"
check $? "gdd status discovers the run under the config-file run root" "$(cat "$CFG_RUN_STATUS")"

CFG_RUN_GUARD="$TMP/config-run-root-guard.out"
env -u GDD_STATE_FILE -u GDD_TASK_ROOT -u GDD_RUN_ROOT -u GDD_LAUNCHER \
  XDG_CONFIG_HOME="$CFG_HOME" FAKE_RECORD="$CFG_RECORD" \
  GDD_LAUNCHER="$CFG_LAUNCHER" \
  "$SCRIPTS/gdd.py" stage --repo "$REPO" --goal 0008 --stage simplify \
  --base abc1234 --head def5678 >"$CFG_RUN_GUARD" 2>&1
CFG_GUARD_RC=$?
[ "$CFG_GUARD_RC" -eq 3 ] && grep -q 'workrepo-0007-simplify' "$CFG_RUN_GUARD"
check $? "concurrency guard sees the run under the config-file run root (rc=$CFG_GUARD_RC)" "$(cat "$CFG_RUN_GUARD")"

echo "selftest: $PASS/$TOTAL ok"
[ "$PASS" -eq "$TOTAL" ]
