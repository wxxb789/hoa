"""Canonical repository names shared by the GDD plan and delivery ledger."""

import os

import gdd_process


def normalize_repo(value, *, default_root=None):
    """Use the Git toplevel basename for a directory, otherwise resolve a short name."""
    path = os.path.expanduser(value)
    if os.path.isdir(path):
        try:
            proc = gdd_process.run(
                ["git", "-C", path, "rev-parse", "--show-toplevel"],
                capture_output=True, text=True,
            )
        except OSError:
            proc = None
        root = (proc.stdout or "").strip() if proc is not None and proc.returncode == 0 else ""
        return os.path.basename(root) if root else os.path.basename(os.path.abspath(path))
    if default_root is None:
        default_root = os.environ.get("GDD_REPO_ROOT") or ""
    if default_root:
        candidate = os.path.join(os.path.expanduser(default_root), value)
        if os.path.isdir(candidate):
            return os.path.basename(os.path.abspath(candidate))
    return value
