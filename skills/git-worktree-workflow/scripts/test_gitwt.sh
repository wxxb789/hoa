#!/usr/bin/env bash
# Regression tests for references/gitwt, covering the four defects found in PR #2:
#   1. main-worktree path truncated at the first space (awk $2)
#   2. two branch names slugging to one directory -> commits landing on the wrong branch
#   3. .envrc written only into the main checkout, which worktrees never discover
#   4. glob copy patterns tested as literal filenames, so they matched nothing
#
# Usage:  bash skills/git-worktree-workflow/scripts/test_gitwt.sh
#         GITWT=/path/to/gitwt bash .../test_gitwt.sh    # test another copy
set -uo pipefail

GITWT="${GITWT:-$(cd "$(dirname "$0")/../references" && pwd)/gitwt}"
[ -f "$GITWT" ] || { echo "gitwt not found at $GITWT" >&2; exit 1; }
ROOT="$(mktemp -d)"
trap 'rm -rf "$ROOT"' EXIT
PASS=0; FAIL=0
ok()   { echo "  PASS: $1"; PASS=$((PASS+1)); }
bad()  { echo "  FAIL: $1"; FAIL=$((FAIL+1)); }
# check <ok-msg> <fail-msg> <test-command...> -- an if, not `A && ok || bad`:
# the latter runs `bad` whenever `ok` fails, and shellcheck flags it (SC2015).
check() {
  local good="$1" bad_msg="$2"; shift 2
  if "$@"; then ok "$good"; else bad "$bad_msg"; fi
}

# ---- fixture: repo path containing a space (thread 1) ----------------------
REPO="$ROOT/repo with space"
mkdir -p "$REPO"
git init -q "$REPO"
git -C "$REPO" config user.email t@t
git -C "$REPO" config user.name t
git -C "$REPO" config core.hooksPath /dev/null
mkdir -p "$REPO/sub"
printf 'x\n' > "$REPO/sub/.env.example"
printf 'secret\n' > "$REPO/.env"
printf '.env\n.envrc\n' > "$REPO/.gitignore"
printf 'a\n' > "$REPO/a.txt"
git -C "$REPO" add -A
git -C "$REPO" commit -qm init

run() { ( cd "$REPO" && "$GITWT" "$@" ); }

echo "== thread 1: main-root parsing survives spaces =="
# git-bash reports Windows-style paths (Q:/tmp/...) where mktemp gave /tmp/..., so
# compare the tail, which is what the space bug truncated.
MAIN="$(run path main 2>/dev/null)"
case "$MAIN" in
  */.wt/"repo with space"/main-*) ok "base dir keeps the space: $MAIN" ;;
  *) bad "base dir truncated: $MAIN" ;;
esac

echo "== thread 2: distinct branches get distinct dirs =="
A="$(run path 'feature/one')"; B="$(run path 'feature-one')"
check "feature/one != feature-one" "slug collision: $A" [ "$A" != "$B" ]
C1="$(run path 'feature/one')"
check "slug is stable across calls" "slug unstable" [ "$A" = "$C1" ]
CJK="$(run path '分支')"
check "non-ASCII branch gets a non-empty dir: ${CJK##*/}" \
      "non-ASCII branch slugged to empty" [ -n "${CJK##*/}" ]
CJK2="$(run path '分支2')"
check "two non-ASCII branches differ" "non-ASCII collision" [ "$CJK" != "$CJK2" ]

echo "== thread 2b: reuse is verified against the branch =="
D1="$(run new 'feature/one' 2>/dev/null | tail -1)"
check "worktree created at $D1" "worktree not created" [ -d "$D1" ]
HEADB="$(git -C "$D1" rev-parse --abbrev-ref HEAD 2>/dev/null || echo NONE)"
check "checked out on feature/one" "on $HEADB" [ "$HEADB" = "feature/one" ]
D2="$(run new 'feature-one' 2>/dev/null | tail -1)"
check "second branch got its own dir" "reused the wrong checkout" [ "$D2" != "$D1" ]
HEADB2="$(git -C "$D2" rev-parse --abbrev-ref HEAD 2>/dev/null || echo NONE)"
check "checked out on feature-one" "on $HEADB2" [ "$HEADB2" = "feature-one" ]
# stale directory that is not a worktree must be refused, not returned
STALE="$(run path stale-br)"
mkdir -p "$STALE"
if run new stale-br >/dev/null 2>&1; then bad "stale dir silently reused"; else ok "stale dir refused"; fi
rmdir "$STALE" 2>/dev/null || true

echo "== thread 4: glob patterns expand =="
git -C "$REPO" config --add gitwt.copy '**/.env.example'
printf '.env\n' > "$REPO/.worktreeinclude"
D3="$(run new glob-test 2>/dev/null | tail -1)"
check "**/.env.example copied to sub/" "glob pattern copied nothing" [ -f "$D3/sub/.env.example" ]
check ".worktreeinclude plain path still copied" ".env not copied" [ -f "$D3/.env" ]
# a gitignored glob via .worktreeinclude
printf 'local-*.txt\n' > "$REPO/.worktreeinclude"
printf 'local-*.txt\n' >> "$REPO/.gitignore"
printf 'v\n' > "$REPO/local-a.txt"
D4="$(run new wti-glob 2>/dev/null | tail -1)"
check ".worktreeinclude glob expanded" ".worktreeinclude glob not expanded" [ -f "$D4/local-a.txt" ]
# .worktreeinclude copies gitignored matches ONLY (Claude-compatible semantics).
# Assert on the copy log rather than on the file: a tracked file is present in every
# worktree via the checkout, so its existence proves nothing either way.
printf 'a.txt\n' > "$REPO/.worktreeinclude"
LOG="$(run new wti-tracked 2>&1 >/dev/null)"
case "$LOG" in
  *"copied a.txt"*) bad "tracked a.txt was copied" ;;
  *) ok "tracked file not copied by .worktreeinclude" ;;
esac
printf '.env\n' > "$REPO/.worktreeinclude"

echo "== thread 3: .envrc reaches worktrees =="
run env >/dev/null 2>&1
check "main .envrc written" "main .envrc missing" [ -f "$REPO/.envrc" ]
# backfill: worktrees created BEFORE `gitwt env`
check "existing worktree backfilled" "existing worktree has no .envrc" [ -f "$D3/.envrc" ]
# new worktree created AFTER `gitwt env`
D6="$(run new after-env 2>/dev/null | tail -1)"
check "new worktree seeded" "new worktree has no .envrc" [ -f "$D6/.envrc" ]
# the .envrc itself must resolve the main root despite the space
RESOLVED="$( cd "$D6" && git worktree list --porcelain | awk '/^worktree /{print substr($0, 10); exit}' )"
case "$RESOLVED" in
  *"repo with space") ok ".envrc _main resolves with the space intact: $RESOLVED" ;;
  *) bad ".envrc _main = '$RESOLVED'" ;;
esac
# The generated .envrc must carry the space-safe parse too, not `awk NR==1{print $2}`.
if grep -q 'substr..0, 10.' "$D6/.envrc"; then
  ok ".envrc uses the space-safe parse"
else
  bad ".envrc still uses the second-field parse"
fi

echo
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
