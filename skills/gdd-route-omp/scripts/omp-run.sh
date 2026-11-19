#!/usr/bin/env bash
# omp-run.sh — forwarder to the shared detached runner, gdd's scripts/agent_run.py.
#
# The runner is maintained once, with skill gdd, because gdd.py launches through it too;
# this forwarder pins GDD_AGENT=omp. Install both skills from this repo, or set OMP_RUN_SH
# to pin a launcher.
set -uo pipefail

case "$OSTYPE" in
  msys*|cygwin*|win32*)
    printf '%s\n' 'omp-run.sh is POSIX-only; run the shared agent_run.py with --agent omp on Windows.' >&2
    exit 2
    ;;
esac

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIBLING="$HERE/../../gdd/scripts/agent_run.py"
CATEGORIZED="$HERE/../../software-development/gdd/scripts/agent_run.py"
PYTHON="$(command -v python3 || command -v python || true)"
export GDD_AGENT=omp

if [[ -n "${OMP_RUN_SH:-}" && -x "${OMP_RUN_SH}" ]]; then
  exec "$OMP_RUN_SH" "$@"
fi
if [[ -n "$PYTHON" ]]; then
  for candidate in "$SIBLING" "$CATEGORIZED"; do
    if [[ -f "$candidate" ]]; then
      exec "$PYTHON" -B "$candidate" "$@"
    fi
  done
fi

{
  echo "omp-run: launcher not found. Tried:"
  echo "  1. OMP_RUN_SH=${OMP_RUN_SH:-<unset>}"
  echo "  2. $SIBLING (through ${PYTHON:-python3, not on PATH})"
  echo "  3. $CATEGORIZED (through ${PYTHON:-python3, not on PATH})"
  echo "Install skill 'gdd' or set OMP_RUN_SH."
} >&2
exit 127
