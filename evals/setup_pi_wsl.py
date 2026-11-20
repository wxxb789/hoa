#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Provision the dedicated Pi trial account and sandbox in an existing WSL distro."""

import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from run_necessity_eval import EVALS, PI_DEFAULT_MODEL, pi_provider, run_process, wsl_pi


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wsl-distro", default=wsl_pi.DISTRO)
    parser.add_argument("--pi-version", default="1.6.0")
    args = parser.parse_args()
    if os.name != "nt":
        print("Pi WSL setup: skipped; Windows-only")
        return 0
    wsl = shutil.which("wsl.exe")
    if not wsl or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", args.pi_version):
        parser.error("setup requires wsl.exe and a numeric Pi release version")
    wsl = Path(wsl).absolute()
    try:
        files, keys, secrets = pi_provider(PI_DEFAULT_MODEL)
        if missing := sorted(key for key in keys if key not in os.environ):
            parser.error(f"missing Pi credential environment variables: {', '.join(missing)}")
        config = {"files": files, "env": {key: os.environ[key] for key in keys},
                  "secrets": sorted({value for value in secrets if value})}
        source = run_process(wsl_pi.wsl_command(wsl, args.wsl_distro, "/usr/bin/wslpath", "-a", "-u",
                                               EVALS / "wsl_pi.py"), capture_output=True, check=True, timeout=30)
        command = wsl_pi.wsl_command(wsl, args.wsl_distro, wsl_pi.PYTHON, "-I", source.stdout.strip(),
                                     "--setup", args.pi_version)
        run_process(command, input=json.dumps(config), cwd=EVALS, check=True, timeout=300)
        sandbox = wsl_pi.WslPi(run_process, wsl, args.wsl_distro, EVALS)
        print(json.dumps(sandbox.call("--probe")))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(2, f"Pi WSL setup failed: {type(error).__name__}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
