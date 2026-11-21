#!/usr/bin/env python3
"""worktree-scope.py must never spawn a visible console on Windows.

Run: python -m pytest skills/delegated-work-acceptance/scripts/tests/test_no_window.py
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "worktree-scope.py"
WINDOW_FLAG = 0x08000000  # subprocess.CREATE_NO_WINDOW

spec = importlib.util.spec_from_file_location("worktree_scope_under_test", SCRIPT)
worktree_scope = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worktree_scope)


class NoWindowTests(unittest.TestCase):
    def test_git_spawns_request_no_window(self) -> None:
        for platform, expected in (("nt", WINDOW_FLAG), ("posix", 0)):
            calls: list[dict] = []

            def fake_run(*args, **kwargs):
                calls.append(kwargs)
                return subprocess.CompletedProcess(args[0], 0, stdout=b"/tmp/repo\n", stderr=b"")

            with (patch.object(subprocess, "run", fake_run),
                  patch.object(os, "name", platform),
                  patch.object(subprocess, "CREATE_NO_WINDOW", WINDOW_FLAG, create=True)):
                # Call the spawn helper directly: Path() picks WindowsPath from os.name, so
                # repo_root() cannot run on POSIX with os.name patched to "nt".
                worktree_scope._git(SCRIPT.parent, "rev-parse", "--show-toplevel")
            self.assertEqual([kwargs.get("creationflags", 0) for kwargs in calls],
                             [expected], platform)


if __name__ == "__main__":
    unittest.main()
