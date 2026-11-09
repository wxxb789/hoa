#!/usr/bin/env bash
# omp-run.sh — forwarder to the reference launcher.
#
# The launcher implementation is maintained once, with skill goal-driven-delivery
# (`scripts/adapters/omp-run.sh`), because gdd.py's default launcher points there and
# two copies would drift. Install both skills from this repo, or set OMP_RUN_SH.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${OMP_RUN_SH:-$HERE/../../goal-driven-delivery/scripts/adapters/omp-run.sh}"

if [[ -x "$TARGET" ]]; then
  exec "$TARGET" "$@"
fi

if command -v omp-run.sh >/dev/null 2>&1; then
  exec "$(command -v omp-run.sh)" "$@"
fi

echo "omp-run: launcher not found at $TARGET — install skill 'goal-driven-delivery' or set OMP_RUN_SH" >&2
exit 127
