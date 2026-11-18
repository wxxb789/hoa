#!/usr/bin/env bash
# omp-run.sh — forwarder to the bundled launcher.
#
# The launcher implementation is maintained once, with skill gdd, because gdd.py's
# default launcher points there and two copies would drift: since the loop went
# cross-platform that default is `scripts/adapters/omp-run.py` (stdlib Python, no
# bash, no setsid, no tmux), with `scripts/adapters/omp-run.sh` kept beside it as
# the POSIX reference and the one with the attachable `tmux` backend. Install both
# skills from this repo, or set OMP_RUN_SH to pin a launcher.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIBLING_PY="$HERE/../../gdd/scripts/adapters/omp-run.py"
CATEGORIZED_PY="$HERE/../../software-development/gdd/scripts/adapters/omp-run.py"
SIBLING="$HERE/../../gdd/scripts/adapters/omp-run.sh"
CATEGORIZED="$HERE/../../software-development/gdd/scripts/adapters/omp-run.sh"
PYTHON="$(command -v python3 || command -v python || true)"

# OMP_RUN_SH first (any launcher the operator pinned); then the bundled adapters
# in the two layouts skills are installed under; then the reference script on PATH.
if [[ -n "${OMP_RUN_SH:-}" && -x "${OMP_RUN_SH}" ]]; then
  exec "$OMP_RUN_SH" "$@"
fi
if [[ -n "$PYTHON" ]]; then
  for candidate in "$SIBLING_PY" "$CATEGORIZED_PY"; do
    if [[ -f "$candidate" ]]; then
      exec "$PYTHON" "$candidate" "$@"
    fi
  done
fi
for candidate in "$SIBLING" "$CATEGORIZED"; do
  if [[ -x "$candidate" ]]; then
    exec "$candidate" "$@"
  fi
done

if command -v omp-run.sh >/dev/null 2>&1; then
  exec "$(command -v omp-run.sh)" "$@"
fi

{
  echo "omp-run: launcher not found. Tried:"
  echo "  1. OMP_RUN_SH=${OMP_RUN_SH:-<unset>}"
  echo "  2. $SIBLING_PY (through ${PYTHON:-python3, not on PATH})"
  echo "  3. $CATEGORIZED_PY (through ${PYTHON:-python3, not on PATH})"
  echo "  4. $SIBLING"
  echo "  5. $CATEGORIZED"
  echo "  6. omp-run.sh on PATH"
  echo "Install skill 'gdd' or set OMP_RUN_SH."
} >&2
exit 127
