#!/usr/bin/env bash
# Hook commands must retain their variables until they run inside a worktree.
# shellcheck disable=SC2016
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

echo "== thread 5: failed hooks cannot launch agents =="
export GITWT_TEST_ROOT="$ROOT"
git -C "$REPO" config --add gitwt.hook 'printf "first\n" >> "$GITWT_TEST_ROOT/hook-first.log"'
git -C "$REPO" config --add gitwt.hook 'printf "attempt\n" >> "$GITWT_TEST_ROOT/hook-second.log"; [ -f "$GITWT_TEST_ROOT/hook-ready" ]'
HOOK_DIR="$(run path hook-gated)"
if run new hook-gated >"$ROOT/hook-out" 2>"$ROOT/hook-err"; then
  bad "failed hook reported a successful worktree"
else
  ok "failed hook stops creation"
fi
check "failed checkout remains for inspection" "failed checkout was deleted" [ -d "$HOOK_DIR" ]
check "failed hook emitted no success path" "failed hook emitted a usable path" [ ! -s "$ROOT/hook-out" ]
if run run touch hook-gated -- "$ROOT/agent-launched" >/dev/null 2>&1; then
  bad "agent ran despite failed setup"
else
  ok "failed setup blocks agent launch"
fi
check "agent was not launched" "agent was launched after failed hook" [ ! -e "$ROOT/agent-launched" ]
check "successful hook did not replay" "successful hook replayed on retry" \
      [ "$(wc -l < "$ROOT/hook-first.log")" -eq 1 ]
if ( cd "$REPO" && eval "$(run --shell)" && gitwt hook-gated >/dev/null 2>&1 ); then
  bad "bare gitwt branch entered after failed setup"
else
  ok "bare gitwt branch preserves setup failure"
fi
git -C "$REPO" config --unset-all gitwt.hook
if run new hook-gated >"$ROOT/no-hooks-out" 2>/dev/null; then
  bad "removing hook config made a failed checkout ready"
else
  ok "failed checkout stays blocked when hook config is removed"
fi
check "failed checkout still emitted no path" "failed checkout emitted a path after config change" \
      [ ! -s "$ROOT/no-hooks-out" ]
git -C "$REPO" config --add gitwt.hook 'printf "first\n" >> "$GITWT_TEST_ROOT/hook-first.log"'
git -C "$REPO" config --add gitwt.hook 'printf "attempt\n" >> "$GITWT_TEST_ROOT/hook-second.log"; [ -f "$GITWT_TEST_ROOT/hook-ready" ]'
touch "$ROOT/hook-ready"
if run run touch hook-gated -- "$ROOT/agent-launched" >/dev/null 2>&1; then
  bad "retry replayed partially completed setup without inspection"
else
  ok "retry refuses failed checkout even after hook becomes healthy"
fi
check "unverified checkout did not launch agent" "unverified checkout launched agent" \
      [ ! -e "$ROOT/agent-launched" ]
check "failed checkout did not replay completed hooks" "failed checkout replayed setup" \
      [ "$(wc -l < "$ROOT/hook-first.log")" -eq 1 ]
if run rm hook-gated --force >/dev/null 2>&1; then
  ok "manual removal permits fresh setup"
else
  bad "failed checkout could not be deliberately removed"
fi
if run run touch hook-gated -- "$ROOT/agent-launched" >/dev/null 2>&1; then
  ok "fresh checkout runs hooks before launching agent"
else
  bad "fresh setup did not launch after deliberate removal"
fi
check "agent launched after fresh setup" "agent did not launch after fresh setup" \
      [ -e "$ROOT/agent-launched" ]
check "fresh setup ran both hooks again" "fresh setup skipped a hook" \
      [ "$(wc -l < "$ROOT/hook-first.log")" -eq 2 ]
run new hook-gated >/dev/null 2>&1
check "ready worktree reuses without replaying hooks" "ready worktree reran setup" \
      [ "$(wc -l < "$ROOT/hook-second.log")" -eq 2 ]

echo "== thread 6: readiness belongs to the actual checkout =="
FIRST_BEFORE="$(wc -l < "$ROOT/hook-first.log")"
git -C "$REPO" worktree remove --force "$HOOK_DIR"
git -C "$REPO" worktree add "$HOOK_DIR" hook-gated >/dev/null 2>&1
if run new hook-gated >"$ROOT/recreated-out" 2>"$ROOT/recreated-err"; then
  bad "rawly recreated checkout inherited readiness"
else
  check "unverified checkout emitted no ready path" "unverified checkout emitted a path" \
        [ ! -s "$ROOT/recreated-out" ]
fi
check "raw replacement did not replay hooks" "raw replacement replayed setup automatically" \
      [ "$(wc -l < "$ROOT/hook-first.log")" -eq "$FIRST_BEFORE" ]

git -C "$REPO" config --unset-all gitwt.hook
git -C "$REPO" config --add gitwt.hook '[ -f "$GITWT_TEST_ROOT/pending-ready" ]'
PENDING_DIR="$(run path pending-config)"
if run new pending-config >/dev/null 2>&1; then
  bad "pending hook unexpectedly succeeded"
else
  ok "pending hook blocked initial checkout"
fi
git -C "$REPO" worktree remove --force "$PENDING_DIR"
git -C "$REPO" config --unset-all gitwt.hook
git -C "$REPO" config --add gitwt.hook 'printf "fresh\n" >> "$GITWT_TEST_ROOT/new-hook.log"'
if run new pending-config >"$ROOT/pending-recreate-out" 2>"$ROOT/pending-recreate-err"; then
  check "removed pending checkout accepts new setup" "new hook did not run" \
        [ -s "$ROOT/new-hook.log" ]
else
  bad "stale pending fingerprint blocked a fresh checkout"
fi

echo "== thread 6b: a later command cannot mask a failed hook =="
git -C "$REPO" config --unset-all gitwt.hook
git -C "$REPO" config --add gitwt.hook 'false; printf "late\n" >> "$GITWT_TEST_ROOT/masked-hook.log"'
MASKED_DIR="$(run path masked-hook)"
if run new masked-hook >"$ROOT/masked-hook-out" 2>"$ROOT/masked-hook-err"; then
  bad "a later successful command masked hook failure"
else
  ok "nonterminal hook failure blocks readiness"
fi
check "failed compound hook kept its checkout" "failed compound hook deleted its checkout" \
      [ -d "$MASKED_DIR" ]
check "failed compound hook emitted no path" "failed compound hook emitted a ready path" \
      [ ! -s "$ROOT/masked-hook-out" ]
check "commands after an unhandled failure were not run" "hook continued after failure" \
      [ ! -e "$ROOT/masked-hook.log" ]

echo "== thread 7: setup excludes concurrent removal =="
git -C "$REPO" config --unset-all gitwt.hook
git -C "$REPO" config --add gitwt.hook 'touch "$GITWT_TEST_ROOT/concurrent-started"; while [ ! -e "$GITWT_TEST_ROOT/concurrent-release" ]; do sleep 0.1; done'
CONCURRENT_DIR="$(run path concurrent-setup)"
( run new concurrent-setup >"$ROOT/concurrent-out" 2>"$ROOT/concurrent-err" ) &
CREATOR_PID=$!
for ((attempt=0; attempt<100; attempt++)); do
  [ -e "$ROOT/concurrent-started" ] && break
  sleep 0.1
done
if [ ! -e "$ROOT/concurrent-started" ]; then
  bad "hook never reached the concurrent setup barrier"
else
  if run rm concurrent-setup --force >/dev/null 2>&1; then
    bad "rm removed a worktree while setup was running"
  else
    ok "rm refused concurrent setup"
  fi
  run clean --merged --force >"$ROOT/concurrent-clean-out" 2>&1
  check "clean preserved concurrent setup" "clean removed worktree during setup" \
        [ -d "$CONCURRENT_DIR" ]
fi
touch "$ROOT/concurrent-release"
if wait "$CREATOR_PID"; then
  check "setup completed with intact checkout" "setup completed without its checkout" \
        [ -d "$CONCURRENT_DIR" ]
else
  bad "setup did not recover after concurrent removal attempts"
fi

echo "== thread 8: copies and unmanaged checkouts fail safely =="
git -C "$REPO" config --unset-all gitwt.hook
mkdir -p "$REPO/local-seed/sub"
printf 'seed\n' > "$REPO/local-seed/sub/fixture.txt"
git -C "$REPO" add local-seed
git -C "$REPO" commit -qm 'tracked seed for copy test'
git -C "$REPO" config --add gitwt.copy local-seed
COPY_DIR="$(run new copy-present 2>/dev/null)"
check "tracked copy source still exists" "tracked copy source was lost" \
      [ -f "$COPY_DIR/local-seed/sub/fixture.txt" ]
check "copy-on-create did not nest an existing directory" "tracked directory was nested" \
      [ ! -e "$COPY_DIR/local-seed/local-seed" ]
LEGACY_DIR="$(run path unmanaged)"
git -C "$REPO" worktree add "$LEGACY_DIR" -b unmanaged >/dev/null 2>&1
if run new unmanaged >"$ROOT/unmanaged-out" 2>"$ROOT/unmanaged-err"; then
  bad "markerless manual checkout was reported ready"
else
  check "manual checkout emitted no ready path" "manual checkout emitted a path" \
        [ ! -s "$ROOT/unmanaged-out" ]
fi

echo "== thread 8b: automatic cleanup preserves unverified checkouts =="
git -C "$REPO" config --add gitwt.hook '[ -e "$GITWT_TEST_ROOT/clean-ready" ]'
CLEAN_PENDING_DIR="$(run path clean-pending)"
if run new clean-pending >"$ROOT/clean-pending-out" 2>"$ROOT/clean-pending-err"; then
  bad "cleanup fixture unexpectedly completed setup"
else
  ok "cleanup fixture retains incomplete setup"
fi
run clean --merged --force >"$ROOT/clean-out" 2>&1
check "cleanup removes a ready merged worktree" "cleanup kept a ready merged worktree" \
      [ ! -d "$COPY_DIR" ]
if git -C "$REPO" show-ref --verify --quiet refs/heads/copy-present; then
  bad "cleanup kept the merged ready branch"
else
  ok "cleanup deletes the merged ready branch"
fi
check "cleanup preserves failed setup" "cleanup removed failed setup" \
      [ -d "$CLEAN_PENDING_DIR" ]
check "cleanup preserves failed branch" "cleanup deleted failed branch" \
      git -C "$REPO" show-ref --verify --quiet refs/heads/clean-pending
check "cleanup preserves markerless checkout" "cleanup removed markerless checkout" \
      [ -d "$LEGACY_DIR" ]
git -C "$REPO" config --unset-all gitwt.hook

echo "== thread 9: output failure cannot strand a removal lock =="
if [ -e /dev/full ]; then
  OUTPUT_DIR="$(run new output-failure 2>/dev/null)"
  OUTPUT_LOCK="$(dirname "$OUTPUT_DIR")/.gitwt-locks/$(basename "$OUTPUT_DIR").lock"
  if run rm output-failure --force >/dev/full 2>"$ROOT/output-full-err"; then
    bad "full output device did not report removal failure"
  else
    ok "removal reported output failure"
  fi
  check "output failure released branch lock" "output failure stranded a lock" \
        [ ! -d "$OUTPUT_LOCK" ]
  if run new output-failure >/dev/null 2>&1; then
    ok "branch can be recreated after output failure"
  else
    bad "stale removal lock blocked recreation"
  fi
fi

echo
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
