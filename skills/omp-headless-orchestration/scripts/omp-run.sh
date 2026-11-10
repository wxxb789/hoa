#!/usr/bin/env bash
# omp-run.sh — forwarder to the reference launcher.
#
# The launcher implementation is maintained once, with skill goal-driven-delivery
# (`scripts/adapters/omp-run.sh`), because gdd.py's default launcher points there and
# two copies would drift. Install both skills from this repo, or set OMP_RUN_SH.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIBLING="$HERE/../../goal-driven-delivery/scripts/adapters/omp-run.sh"
CATEGORIZED="$HERE/../../software-development/goal-driven-delivery/scripts/adapters/omp-run.sh"

# OMP_RUN_SH first; then the two layouts skills are installed under; then PATH.
for candidate in "${OMP_RUN_SH:-}" "$SIBLING" "$CATEGORIZED"; do
  if [[ -n "$candidate" && -x "$candidate" ]]; then
    exec "$candidate" "$@"
  fi
done

if command -v omp-run.sh >/dev/null 2>&1; then
  exec "$(command -v omp-run.sh)" "$@"
fi

{
  echo "omp-run: launcher not found. Tried:"
  echo "  1. OMP_RUN_SH=${OMP_RUN_SH:-<unset>}"
  echo "  2. $SIBLING"
  echo "  3. $CATEGORIZED"
  echo "  4. omp-run.sh on PATH"
  echo "Install skill 'goal-driven-delivery' or set OMP_RUN_SH."
} >&2
exit 127
