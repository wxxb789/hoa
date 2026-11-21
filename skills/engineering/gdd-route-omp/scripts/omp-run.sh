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
# uv runs the PEP 723 script on its declared Python; ~/.local/bin is uv's default install dir,
# which a non-login shell (systemd-run, wsl -e) may not have on PATH.
UV="$(command -v uv || true)"
if [[ -z "$UV" && -x "$HOME/.local/bin/uv" ]]; then UV="$HOME/.local/bin/uv"; fi
export GDD_AGENT=omp

if [[ -n "${OMP_RUN_SH:-}" && -x "${OMP_RUN_SH}" ]]; then
  exec "$OMP_RUN_SH" "$@"
fi
if [[ -n "$UV" ]]; then
  for candidate in "$SIBLING" "$CATEGORIZED"; do
    if [[ -f "$candidate" ]]; then
      exec "$UV" run -q --script "$candidate" "$@"
    fi
  done
fi

{
  echo "omp-run: launcher not found. Tried:"
  echo "  1. OMP_RUN_SH=${OMP_RUN_SH:-<unset>}"
  echo "  2. $SIBLING (through ${UV:-uv, not on PATH or in ~/.local/bin})"
  echo "  3. $CATEGORIZED (through ${UV:-uv, not on PATH or in ~/.local/bin})"
  echo "Install skill 'gdd' and uv, or set OMP_RUN_SH."
} >&2
exit 127
