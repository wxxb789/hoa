"""Tests for scripts/check_public_privacy.py."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

CHECKER = Path(__file__).resolve().parent / "check_public_privacy.py"
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
BS = chr(92)


def _git(cwd: Path, *args: str) -> None:
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                   env=env, creationflags=NO_WINDOW)


def _run(root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECKER), "--root", str(root), *extra],
        capture_output=True, text=True, encoding="utf-8", creationflags=NO_WINDOW,
    )


def test_detects_real_home_path_and_allows_synthetic(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "clean.md").write_text(
        f"Example: C:{BS}Users{BS}ExampleUser{BS}.gitconfig and <trial>/home/.pi/agent\n",
        encoding="utf-8",
    )
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "clean")
    res = _run(tmp_path)
    assert res.returncode == 0, res.stdout + res.stderr

    (tmp_path / "docs" / "leak.md").write_text(
        f"Leak: C:{BS}Users{BS}realperson{BS}.gitconfig\n", encoding="utf-8",
    )
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "leak")
    res = _run(tmp_path)
    assert res.returncode == 1
    assert "docs/leak.md:1: home-path" in res.stdout


def test_base_catches_intermediate_commit_leak(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    (tmp_path / "README.md").write_text("ok\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "base")
    base_sha = subprocess.check_output(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True, creationflags=NO_WINDOW,
    ).strip()

    token = "gh" + "p_" + "A" * 22
    (tmp_path / "secret.txt").write_text(token + "\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "oops")

    (tmp_path / "secret.txt").unlink()
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "remove oops")

    # Worktree scan alone is clean, but --base catches the intermediate blob.
    assert _run(tmp_path).returncode == 0
    res = _run(tmp_path, "--base", base_sha)
    assert res.returncode == 1
    assert "github-token" in res.stdout
