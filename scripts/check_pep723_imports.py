#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Verify that every PEP 723 non-test script declares all third-party imports it uses.

Statically parses each PEP 723 script's AST imports and `# /// script`
`dependencies` block (recursively following sibling local-module imports in the
same script directory), ensuring no third-party module is imported without
being declared in `# /// script`. Runs in milliseconds with zero subprocesses.

Usage:
    uv run scripts/check_pep723_imports.py

Exit codes: 0 all scripts pass, 1 at least one script has undeclared imports.
"""
from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
TEST_PREFIXES = ("test_", "test-")

PEP723_BLOCK_RE = re.compile(
    r"(?m)^# /// script\s*\r?\n((?:#(?: .*)?\r?\n)+?)# ///\s*$"
)
DIST_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+")

# Map normalized PyPI distribution names -> top-level import package names when they differ.
DIST_TO_MODULES: dict[str, set[str]] = {
    "pyyaml": {"yaml"},
    "pillow": {"PIL"},
    "beautifulsoup4": {"bs4"},
    "python-dateutil": {"dateutil"},
    "scikit-learn": {"sklearn"},
}

STDLIB = set(sys.stdlib_module_names) | {"__future__"}

# Runtime-injected host packages loaded via sys.path at runtime (e.g. Hermes install tree).
HOST_RUNTIME_MODULES: dict[str, set[str]] = {
    "skills/hermes/": {"hermes_cli"},
}


def discover_scripts(root: Path) -> list[Path]:
    out = subprocess.check_output(
        ["git", "-C", str(root), "ls-files", "-z", "scripts", "skills"],
        creationflags=NO_WINDOW,
    )
    found: list[Path] = []
    for raw in out.split(b"\0"):
        if not raw:
            continue
        rel = raw.decode("utf-8", "surrogateescape")
        if not rel.endswith(".py"):
            continue
        p = root / rel
        if not p.is_file():
            continue
        parts = Path(rel).parts
        if "tests" in parts or p.name.startswith(TEST_PREFIXES):
            continue
        head = p.read_text(encoding="utf-8", errors="replace")[:600]
        if "# /// script" in head:
            found.append(p)
    return sorted(found)


def parse_declared_modules(text: str) -> set[str]:
    match = PEP723_BLOCK_RE.search(text)
    if not match:
        return set()
    body = "\n".join(
        line[2:] if line.startswith("# ") else line[1:]
        for line in match.group(1).splitlines()
    )
    meta = tomllib.loads(body)
    modules: set[str] = set()
    for dep in meta.get("dependencies") or []:
        m = DIST_NAME_RE.match(str(dep).strip())
        if not m:
            continue
        norm = m.group(0).lower().replace("_", "-")
        modules.add(norm.replace("-", "_"))
        modules.update(DIST_TO_MODULES.get(norm, set()))
    return modules


def _direct_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".", 1)[0])
    return names


def _resolve_local_module(directory: Path, name: str) -> Path | None:
    # Check both the script's directory and its immediate parent (e.g. scripts/adapters -> scripts/).
    for candidate_dir in (directory, directory.parent):
        py = candidate_dir / f"{name}.py"
        if py.is_file():
            return py
        pkg = candidate_dir / name / "__init__.py"
        if pkg.is_file():
            return pkg
    return None


def collect_third_party_imports(path: Path) -> set[str]:
    """Return all non-stdlib, non-local top-level imports reachable via sibling local modules."""
    visited: set[Path] = set()
    queue = [path.resolve()]
    third_party: set[str] = set()
    while queue:
        cur = queue.pop()
        if cur in visited:
            continue
        visited.add(cur)
        for mod in _direct_imports(cur):
            if mod in STDLIB:
                continue
            local = _resolve_local_module(cur.parent, mod)
            if local is not None:
                queue.append(local.resolve())
            else:
                third_party.add(mod)
    return third_party


def check_repo(root: Path) -> list[str]:
    errors: list[str] = []
    for path in discover_scripts(root):
        text = path.read_text(encoding="utf-8")
        declared = parse_declared_modules(text)
        needed = collect_third_party_imports(path)
        rel = path.relative_to(root).as_posix()
        host_ok = {
            mod
            for prefix, mods in HOST_RUNTIME_MODULES.items()
            if rel.startswith(prefix)
            for mod in mods
        }
        missing = sorted(needed - declared - host_ok)
        if missing:
            errors.append(
                f"{rel}: imports {', '.join(missing)} not declared in PEP 723 dependencies"
            )
    return errors


def main() -> int:
    scripts = discover_scripts(ROOT)
    errors = check_repo(ROOT)
    for err in errors:
        print(err)
    if errors:
        print(f"check_pep723_imports: {len(errors)}/{len(scripts)} script(s) failed", file=sys.stderr)
        return 1
    print(f"check_pep723_imports: {len(scripts)} script(s) OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
