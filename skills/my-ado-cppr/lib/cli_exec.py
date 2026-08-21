#!/usr/bin/env python3
"""Cross-platform command execution for Azure CLI and GitHub CLI.

Handles Windows Git Bash/MSYS/Cygwin where stdout capture issues exist.
"""

from __future__ import annotations

import functools
import os
import platform
import shutil
import subprocess
import sys
from typing import Sequence


class CommandError(RuntimeError):
    """Raised when a command execution fails."""

    def __init__(self, message: str, returncode: int = 1, stderr: str = ""):
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr


@functools.cache
def is_windows_posix_shell() -> bool:
    """Check if we're in Windows Git Bash/MSYS/Cygwin.

    Uses os.path.basename() for robust shell name extraction instead of
    fragile suffix matching that can fail with different path formats.
    Result is cached since it cannot change within a process lifetime.
    """
    if platform.system().lower() != "windows":
        return False
    if os.environ.get("MSYSTEM"):
        return True
    if os.environ.get("OSTYPE", "").lower().startswith(("msys", "cygwin")):
        return True
    shell = os.environ.get("SHELL", "")
    if shell:
        name = os.path.basename(shell).lower()
        if name in ("bash", "bash.exe", "sh", "sh.exe"):
            return True
    return False


def _ps_quote(arg: str) -> str:
    """Quote for PowerShell: wrap in single quotes, escape ' as ''."""
    return "'" + arg.replace("'", "''") + "'"


def run_command(
    args: Sequence[str],
    *,
    use_pwsh_on_windows_posix: bool = False,
    debug: bool = False,
    check: bool = True,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    timeout_sec: int | None = None,
) -> subprocess.CompletedProcess[str]:
    """Execute a command with cross-platform compatibility."""
    if not args:
        raise ValueError("args must not be empty")

    if timeout_sec is None:
        try:
            timeout_sec = int(os.environ.get("CPR_TIMEOUT_SEC", "120"))
        except (TypeError, ValueError):
            timeout_sec = 120

    if use_pwsh_on_windows_posix and is_windows_posix_shell():
        pwsh = shutil.which("pwsh")
        if not pwsh:
            raise CommandError("pwsh not found. Install PowerShell 7+.")
        cmd_str = " ".join(_ps_quote(a) for a in args)
        # The '& ' prefix is the PowerShell call operator, required to invoke
        # executables whose path is quoted.
        cmd = [pwsh, "-NoProfile", "-Command", f"& {cmd_str}"]
    else:
        cmd = list(args)

    if debug:
        sys.stderr.write(f"[platform] Running: {cmd}\n")

    run_env = None
    if env:
        run_env = os.environ.copy()
        run_env.update(env)

    try:
        cp = subprocess.run(
            cmd,
            cwd=cwd,
            env=run_env,
            text=True,
            capture_output=True,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as e:
        raise CommandError(f"Command timed out after {timeout_sec}s") from e
    except FileNotFoundError as e:
        raise CommandError(f"Command not found: {args[0]}") from e

    if debug:
        sys.stderr.write(f"[platform] rc={cp.returncode}\n")
        if cp.stderr:
            sys.stderr.write(f"[platform] stderr: {cp.stderr[:4000]}\n")
        if cp.stdout:
            sys.stderr.write(f"[platform] stdout: {cp.stdout[:1000]}\n")

    if check and cp.returncode != 0:
        err = (cp.stderr or cp.stdout or "").strip()
        raise CommandError(
            f"Command failed (rc={cp.returncode}): {err}" if err else f"Command failed (rc={cp.returncode})",
            returncode=cp.returncode,
            stderr=cp.stderr or "",
        )

    return cp


def breadcrumb(msg: str) -> None:
    """Write a one-line progress message to stderr (always, not debug-gated)."""
    sys.stderr.write(f"[cppr] {msg}\n")
    sys.stderr.flush()


def _make_tool_exec(tool_name: str, *, use_pwsh: bool):
    """Create a CLI tool executor with cached path lookup."""

    @functools.cache
    def _which() -> str:
        return shutil.which(tool_name) or tool_name

    def tool_exec(
        args: Sequence[str],
        *,
        debug: bool | None = None,
        check: bool = True,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_sec: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        dbg = debug if debug is not None else bool(os.environ.get("CPR_DEBUG"))
        return run_command(
            [_which(), *args],
            use_pwsh_on_windows_posix=use_pwsh,
            debug=dbg,
            check=check,
            cwd=cwd,
            env=env,
            timeout_sec=timeout_sec,
        )

    tool_exec.__doc__ = f"Execute {tool_name} command."
    tool_exec.__name__ = f"{tool_name}_exec"
    return tool_exec


az_exec = _make_tool_exec("az", use_pwsh=True)
gh_exec = _make_tool_exec("gh", use_pwsh=False)
