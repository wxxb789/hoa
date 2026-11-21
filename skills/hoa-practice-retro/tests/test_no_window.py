"""safety.py must never spawn a visible console on Windows."""
from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "safety.py"
WINDOW_FLAG = 0x08000000  # subprocess.CREATE_NO_WINDOW

spec = importlib.util.spec_from_file_location("safety_under_test", SCRIPT)
safety = importlib.util.module_from_spec(spec)
spec.loader.exec_module(safety)


def test_git_spawns_request_no_window(tmp_path, monkeypatch):
    calls: list[dict] = []

    def fake_run(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(returncode=128, stdout="", stderr="fatal: not a git repository")

    monkeypatch.setattr(subprocess, "run", fake_run)
    for platform, expected in (("nt", WINDOW_FLAG), ("posix", 0)):
        with monkeypatch.context() as inner:
            inner.setattr(os, "name", platform)
            inner.setattr(subprocess, "CREATE_NO_WINDOW", WINDOW_FLAG, raising=False)
            safety.output_is_safe(tmp_path)
        assert calls[-1].get("creationflags", 0) == expected, platform
