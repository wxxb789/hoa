#!/usr/bin/env python3
"""Thin launcher: cron entry point for a script whose real logic lives outside ~/.hermes/scripts/.

`hermes cron --script` accepts only a bare filename under the scripts dir and refuses a path that
resolves outside it, so the job's payload is this file: it owns the argv and the interpreter call and
passes the tool's output through untouched. Keep every decision in the tool, not here.

Copy to ~/.hermes/scripts/<name>.py (write it there directly — writing through a symlink hits the link
target and is refused as a stale write), edit TOOL/ARGS, then self-test:
    /usr/bin/python3 ~/.hermes/scripts/<name>.py <args>
and confirm the silence semantics (empty stdout = nothing delivered) before wiring the job.
"""
import subprocess
import sys
from pathlib import Path

TOOL = Path.home() / "claw/tools/CHANGE_ME/CHANGE_ME.py"
ARGS = ["24"]  # fixed args belong here, not in the cron record
PYTHON = "/usr/bin/python3"  # absolute: cron resolves .py onto its managed venv, not the shebang

def main(argv: list[str]) -> int:
    if not TOOL.is_file():
        sys.stderr.write(f"launcher: tool missing at {TOOL}\n")
        return 1
    r = subprocess.run([PYTHON, str(TOOL), *ARGS, *argv], capture_output=True, text=True, timeout=300)
    # stderr is for cron output files/diagnostics; only stdout is the delivered message.
    sys.stderr.write(r.stderr)
    sys.stdout.write(r.stdout)
    return r.returncode

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
