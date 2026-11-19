"""Guard native Windows test processes and the Python children they launch."""

import os
import runpy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

if os.name == "nt":
    guard_dir = HERE / "nowindow"
    runpy.run_path(str(guard_dir / "sitecustomize.py"))
    guard = str(guard_dir)
    paths = [path for path in os.environ.get("PYTHONPATH", "").split(os.pathsep) if path]
    if guard not in paths:
        # A host guard, when explicitly supplied, still takes precedence in children.
        os.environ["PYTHONPATH"] = os.pathsep.join([*paths, guard])
