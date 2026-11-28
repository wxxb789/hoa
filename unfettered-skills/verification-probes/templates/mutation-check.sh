#!/usr/bin/env bash
# Mutation check with a guaranteed restore: break the rule, prove a test goes red, put the tree back.
#
# Copy beside the artifact under test, patch the PATCH-ME values, then run it as a FILE:
#   bash mutation-check.sh 2>&1 | tee mutation-check.log
#
# Never paste this in as an inline foreground cell: a cell killed at the harness cap abandons what it
# already did, and the restore below deliberately lives after the mutation. Serialize it too — nothing
# else may read this tree (gate, build, CI, another agent) while it runs, and any gate that ran inside
# the window is VOID and must be re-run afterwards on the restored tree, not quoted.

set -u
cd "$(git rev-parse --show-toplevel)"

F="PATCH-ME/path/to/file_under_test"        # the file whose rule is being pinned
ANCHOR='PATCH-ME exact text, must occur exactly once'
REPLACEMENT='PATCH-ME text that breaks the rule'
TEST_CMD=(PATCH-ME the single package or test that must go red)   # e.g. go test -count=1 -run TestX ./pkg/

BAK="$(mktemp -d)/original"
OUT="$(mktemp)"
cp -f "$F" "$BAK" || { echo "cannot back up $F"; exit 2; }

hash_of() { sha256sum "$1" | awk '{print $1}'; }
restore()  { cp -f "$BAK" "$F" 2>/dev/null; }
# Restore runs on every exit path: clean, error, or killed.
trap 'restore; printf "\nsha256 restored : %s\n" "$(hash_of "$F")"' EXIT

BEFORE="$(hash_of "$F")"
printf 'sha256 before   : %s\n' "$BEFORE"

python3 - "$F" "$ANCHOR" "$REPLACEMENT" <<'PY'
import pathlib, sys
path, anchor, repl = sys.argv[1], sys.argv[2], sys.argv[3]
p = pathlib.Path(path)
s = p.read_text()
n = s.count(anchor)
assert n == 1, f"anchor occurs {n} times — make it unique before trusting this check"
p.write_text(s.replace(anchor, repl))
print("MUTATION APPLIED")
PY
printf 'sha256 mutated  : %s\n' "$(hash_of "$F")"

"${TEST_CMD[@]}" >"$OUT" 2>&1
RC=$?
printf 'test exit       : %s\n' "$RC"
tail -8 "$OUT"

restore
AFTER="$(hash_of "$F")"
if [ "$AFTER" = "$BEFORE" ]; then echo "RESTORE OK (byte-identical)"; else echo "*** RESTORE MISMATCH ***"; fi
if [ "$RC" -ne 0 ]; then
  echo "VERDICT: mutation detected — the test pins the rule"
else
  echo "VERDICT: NOT DETECTED — the pin is decoration, or the mutation missed the rule"
fi
DIRTY="$(git status --porcelain)"
if [ -n "$DIRTY" ]; then printf 'WARNING: tree not clean after restore:\n%s\n' "$DIRTY"; fi
