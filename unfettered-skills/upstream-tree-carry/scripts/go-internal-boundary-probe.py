#!/usr/bin/env python3
"""Prove, against the local Go toolchain, whether a module may import another module's internal/ packages.

Go decides the internal rule on IMPORT PATHS, not directories: a module whose path is a subpath of the
carrying module's path may import its internal/ packages through a replace, while an unrelated module path
is refused. Run this before pricing a layout that gives a carried upstream tree its own module, so the
choice rests on a probe rather than on a remembered constraint.

Exit codes: 0 = every control behaved as required (the layout is usable),
            1 = a control misbehaved (read the diagnostics),
            2 = no usable toolchain found.
"""
from __future__ import annotations

import argparse
import pathlib
import shutil
import subprocess
import sys
import tempfile

CARRY_MODULE = "go.kenn.io/agentsview"  # the carried tree's own module path
OURS_MODULE = CARRY_MODULE + "/ours"  # ours: a SUBPATH of the carry's path
UNRELATED_MODULE = "example.com/unrelated"  # negative control

CARRY_GO_MOD = f"module {CARRY_MODULE}\n\ngo 1.24\n"
DB_GO = 'package db\n\n// Name gives an importer something to call.\nfunc Name() string { return "db" }\n'
MAIN_GO = (
    "package main\n\n"
    "import (\n"
    '\t"fmt"\n\n'
    f'\t"{CARRY_MODULE}/internal/db"\n'
    ")\n\n"
    "func main() { fmt.Println(db.Name()) }\n"
)


def ours_go_mod(module_path: str, replace_target: str) -> str:
    return (
        f"module {module_path}\n\ngo 1.24\n\n"
        f"require {CARRY_MODULE} v0.0.0\n\n"
        f"replace {CARRY_MODULE} => {replace_target}\n"
    )


def write(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build(directory: pathlib.Path) -> tuple[int, str]:
    proc = subprocess.run(
        ["go", "build", "./..."], cwd=directory, capture_output=True, text=True
    )
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def main() -> int:
    if shutil.which("go") is None:
        print("PROBE: no `go` on PATH -- install a toolchain, or skip the layout question", file=sys.stderr)
        return 2

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", action="store_true", help="keep the scratch tree for inspection")
    args = parser.parse_args()

    root = pathlib.Path(tempfile.mkdtemp(prefix="go-internal-boundary-"))
    try:
        # Shape A: the carried tree in its own folder, ours as a sibling module.
        carry = root / "carry"
        write(carry / "go.mod", CARRY_GO_MOD)
        write(carry / "internal" / "db" / "db.go", DB_GO)
        sibling = root / "ours-sibling"
        write(sibling / "go.mod", ours_go_mod(OURS_MODULE, "../carry"))
        write(sibling / "main.go", MAIN_GO)

        # Shape B: the carried tree at the root, ours in a nested folder module.
        flat = root / "flat"
        write(flat / "go.mod", CARRY_GO_MOD)
        write(flat / "internal" / "db" / "db.go", DB_GO)
        write(flat / "ours" / "go.mod", ours_go_mod(OURS_MODULE, "../"))
        write(flat / "ours" / "main.go", MAIN_GO)

        # Negative control: an unrelated module path must be refused.
        unrelated = root / "unrelated"
        write(unrelated / "go.mod", ours_go_mod(UNRELATED_MODULE, "../carry"))
        write(unrelated / "main.go", MAIN_GO)

        checks = [
            ("A carry in its own folder + subpath sibling module", sibling, 0, None),
            ("B carry at the root + nested subpath module", flat / "ours", 0, None),
            ("C unrelated module path (must be refused)", unrelated, 1, "use of internal package"),
        ]
        failures = 0
        for label, directory, want_code, want_text in checks:
            code, output = build(directory)
            ok = code == want_code and (want_text is None or want_text in output)
            failures += 0 if ok else 1
            print(f"{'PASS' if ok else 'FAIL'}: {label}")
            print(f"      exit={code}")
            if output:
                print("      " + output.replace("\n", "\n      ")[:1200])
        print()
        if failures:
            print("PROBE: a control misbehaved -- do not price the layout on this run")
            return 1
        print(
            "PROBE: a module whose path is a SUBPATH of the carrying module's path may import its\n"
            "       internal/ packages through a replace; an unrelated module path is refused.\n"
            "       => the carry can live in its own folder with its own go.mod, bytes untouched."
        )
        return 0
    finally:
        if args.keep:
            print(f"scratch kept: {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
