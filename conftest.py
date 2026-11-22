"""Guard native Windows test processes and the Python children they launch, suite-wide."""

import os
import runpy
from pathlib import Path

HERE = Path(__file__).resolve().parent

if os.name == "nt":
    guard_dir = HERE / "skills/engineering/gdd/scripts/tests/nowindow"
    runpy.run_path(str(guard_dir / "sitecustomize.py"))
    guard = str(guard_dir)
    paths = [path for path in os.environ.get("PYTHONPATH", "").split(os.pathsep) if path]
    # Keep an explicit host guard first, but make our entry survive child cwd changes.
    paths = [guard if os.path.normcase(os.path.abspath(path)) == os.path.normcase(guard) else path for path in paths]
    if guard not in paths:
        paths.append(guard)
    os.environ["PYTHONPATH"] = os.pathsep.join(paths)
