#!/usr/bin/env bash
# Candidate patches with stable labels: pristine copy on the left, the round's edit on the right.
#
# The deliverable of a revision round is bytes plus anchors, and the anchors must survive a re-run —
# `diff -u` without labels prints temp paths and timestamps, so two runs of the same pair differ.
#
# Usage:
#   candidate_diff.sh <pristine-file> <edited-file> <out.patch> [label-vN]
#   candidate_diff.sh <pristine-dir>  <edited-dir>  <out-dir-or-.patch> [label-vN]
set -euo pipefail

[ "$#" -ge 3 ] || { printf 'usage: %s <pristine> <edited> <out> [label]\n' "$0" >&2; exit 2; }

pristine=$1
edited=$2
out=$3
label=${4:-candidate}

[ -e "$pristine" ] || { printf 'candidate_diff: missing %s\n' "$pristine" >&2; exit 2; }
[ -e "$edited" ] || { printf 'candidate_diff: missing %s\n' "$edited" >&2; exit 2; }

if [ -d "$pristine" ] && [ -d "$edited" ]; then
  mkdir -p "$out"
  # -N: a file only on one side is shown as added/removed rather than skipped; -r recurses.
  diff -ruN --label "a/$label" --label "b/$label" "$pristine" "$edited" >"$out/$(basename "$pristine").patch" || true
  printf 'candidate_diff: %s\n' "$out/$(basename "$pristine").patch"
  exit 0
fi

[ -f "$pristine" ] && [ -f "$edited" ] || { printf 'candidate_diff: mixed file/dir inputs\n' >&2; exit 2; }
mkdir -p "$(dirname "$out")"
diff -u --label "a/$label" --label "b/$label" "$pristine" "$edited" >"$out" || true
printf 'candidate_diff: %s (%s anchored hunks)\n' "$out" "$(grep -c '^@@' "$out" || true)"
