"""Guard native Windows test processes and the Python children they launch."""

import os
import runpy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

if os.name == "nt":
    guard_dir = HERE / "nowindow"
    runpy.run_path(str(guard_dir / "sitecustomize.py"))
    guard = str(guard_dir)
    paths = [path for path in os.environ.get("PYTHONPATH", "").split(os.pathsep) if path]
    # Keep an explicit host guard first, but make our entry survive child cwd changes.
    paths = [guard if os.path.normcase(os.path.abspath(path)) == os.path.normcase(guard) else path for path in paths]
    if guard not in paths:
        paths.append(guard)
    os.environ["PYTHONPATH"] = os.pathsep.join(paths)
