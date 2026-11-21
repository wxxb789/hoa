"""All GDD process creation must cross the Windows console boundary."""

import ast
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import gdd_process


def test_windows_run_and_popen_hide_console():
    with patch.object(gdd_process, "IS_WINDOWS", True), patch.object(subprocess, "Popen") as spawn:
        process = spawn.return_value.__enter__.return_value
        process.communicate.return_value = (None, None)
        gdd_process.run(["git", "status"])
        gdd_process.popen(["cmd.exe", "/c", "path with spaces/npm-shim.cmd", "two words"], creationflags=0x200)
    assert [call.kwargs["creationflags"] for call in spawn.call_args_list] == [0x08000000, 0x08000200]
    assert spawn.call_args.args[0] == 'cmd.exe /d /s /c ""path with spaces/npm-shim.cmd" "two words""'
    if hasattr(subprocess, "STARTUPINFO"):
        for call in spawn.call_args_list:
            startup = call.kwargs["startupinfo"]
            assert startup.dwFlags & subprocess.STARTF_USESHOWWINDOW
            assert startup.wShowWindow == subprocess.SW_HIDE


def test_no_process_creation_outside_helper():
    skills = Path(__file__).resolve().parents[3]
    helper = Path(gdd_process.__file__).resolve()
    guard = Path(__file__).resolve().with_name("nowindow") / "sitecustomize.py"
    process_calls = {"Popen", "run", "call", "check_call", "check_output", "getoutput", "getstatusoutput"}
    offenders = []
    for path in skills.glob("gdd*/**/*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        blocked = {
            "subprocess": process_calls,
            "os": {name for name in dir(os)
                   if name.startswith(("exec", "spawn", "posix_spawn"))} | {"system", "startfile", "popen"},
            "asyncio": {"create_subprocess_exec", "create_subprocess_shell"},
        }
        if path == guard:
            blocked["os"].remove("system")  # The guard wraps the original, not a call site.
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.asname and alias.name in blocked:
                        blocked[alias.asname] = blocked[alias.name]
        for node in ast.walk(tree):
            forbidden = isinstance(node, ast.Attribute) and (
                node.attr == "DETACHED_PROCESS"
                or (path.resolve() != helper and isinstance(node.value, ast.Name)
                    and node.attr in blocked.get(node.value.id, ()) and isinstance(node.ctx, ast.Load)))
            if isinstance(node, ast.ImportFrom):
                forbidden |= any(alias.name == "DETACHED_PROCESS" or alias.name in blocked.get(node.module, ())
                                 for alias in node.names)
            if isinstance(node, ast.keyword) and node.arg == "creationflags":
                forbidden |= any(isinstance(part, ast.Constant) and type(part.value) is int and part.value & 8
                                 for part in ast.walk(node.value))
            if forbidden:
                offenders.append(f"{path.relative_to(skills.parent)}:{node.lineno}")
    assert not offenders, "\n".join(offenders)
