"""Every test in the suite, and every Python child it launches, runs under the Windows no-window guard."""

import subprocess
import sys

import pytest

_winapi = pytest.importorskip("_winapi", reason="the console guard only exists on Windows")


def test_guard_is_installed_in_the_test_process():
    assert getattr(_winapi.CreateProcess, "_gdd_no_window_guard", False)


def test_python_children_inherit_the_guard():
    probe = "import _winapi; print(getattr(_winapi.CreateProcess, '_gdd_no_window_guard', False))"
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "True"
