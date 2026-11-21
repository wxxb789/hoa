"""Shared stdlib-only listing of curated skill packages.

A curated skill lives at `skills/<category>/<name>/SKILL.md`. This module is
the single place that turns a curated root into package-directory candidates;
callers decide whether a candidate without a manifest is an error (frontmatter,
index) or is simply skipped (links, revisions, evals).
"""
from __future__ import annotations

from pathlib import Path


def skill_dirs(skills_root: Path) -> list[Path]:
    """Directory candidates under `skills_root`, sorted by name then path.

    Candidates are the second-level directories (`<category>/<name>`). Every
    caller must filter on `SKILL.md` presence unless it owns the missing-manifest
    diagnostic itself.
    """
    return sorted((path for path in skills_root.glob("*/*") if path.is_dir()),
                  key=lambda path: (path.name, path.as_posix()))
