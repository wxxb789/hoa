"""contract-eval-run.py must never spawn a visible console on Windows."""
from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

SCRIPT = Path(__file__).resolve().parents[1] / "contract-eval-run.py"
WINDOW_FLAG = 0x08000000  # subprocess.CREATE_NO_WINDOW

spec = importlib.util.spec_from_file_location("contract_eval_run_under_test", SCRIPT)
contract_eval_run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract_eval_run)


def test_eval_runs_request_no_window(monkeypatch):
    calls: list[dict] = []

    def fake_run(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    case = {"id": "no-window", "prompt": "hi", "expect": ["ok"], "forbid": []}
    for platform, expected in (("nt", WINDOW_FLAG), ("posix", 0)):
        with monkeypatch.context() as inner:
            inner.setattr(os, "name", platform)
            inner.setattr(subprocess, "CREATE_NO_WINDOW", WINDOW_FLAG, raising=False)
            contract_eval_run.run_case(case, 5, ".", ["agent", "-z"], None)
        assert calls[-1].get("creationflags", 0) == expected, platform
