"""Exercise discovery and dispatch from installed skill layouts."""

import os
import shutil
import sys
import time
from pathlib import Path

import pytest

from runner_cases import RunnerCase, route_fixture
import agent_run
import gdd_process
from gdd_test_support import finalized, stop_headless, wait_for_json


def test_discovers_all_six_routes():
    installed = agent_run.discover_routes()
    assert set(installed) == {"omp", "dsh", "codex", "claude", "pi", "opencode"}
    for name in installed:
        assert agent_run.load_route(name).name == name


@pytest.mark.parametrize(("source", "field"), [
    ("NOT_A_ROUTE = None", "missing ROUTE"),
    ("ROUTE = {}", "invalid ROUTE"),
    ("from agent_run import Route\nROUTE = Route('broken', 'stdin', lambda a, e: [])", "fold"),
    ("from agent_run import Route\n"
     "ROUTE = Route('broken', 'pipe', lambda a, e: [], lambda a, e: None, 'marker', bool)",
     "ROUTE.prompt"),
    ("from agent_run import Route\n"
     "ROUTE = Route('broken', 'stdin', lambda a, e: [], None, 'marker', bool)", "ROUTE.fold"),
])
def test_malformed_route_names_module_and_field(tmp_path, source, field):
    module = tmp_path / "gdd-route-broken" / "scripts" / "route.py"
    module.parent.mkdir(parents=True)
    module.write_text(source, encoding="utf-8")
    with pytest.raises(agent_run.RouteError) as error:
        agent_run.load_route("broken", tmp_path)
    assert str(module) in str(error.value)
    assert field in str(error.value)


def layout_runner(tmp_path, mode):
    installed = tmp_path / "installed"
    installed.mkdir()
    source = agent_run.SKILLS_ROOT
    canonical = tmp_path / "canonical"
    for name in ("gdd", "gdd-route-omp", "gdd-route-dsh"):
        if mode == "copy" and name == "gdd-route-dsh":
            continue
        target = (installed if mode == "copy" else canonical) / name
        shutil.copytree(source / name, target, ignore=shutil.ignore_patterns("__pycache__", "tests"))
        if mode == "copy" or name == "gdd-route-dsh":
            continue
        link = installed / name
        if mode == "junction":
            result = gdd_process.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
                                     capture_output=True, encoding="utf-8", errors="replace", timeout=10)
            if result.returncode:
                pytest.skip(f"cannot create a Windows junction: {result.stderr.strip()}")
        else:
            try:
                link.symlink_to(target, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                pytest.skip(f"cannot create a directory symlink: {exc}")
    return installed / "gdd" / "scripts" / "agent_run.py"


class MissingRouteTests(RunnerCase):
    def test_missing_route_start_exits_before_creating_a_run(self):
        runner = layout_runner(Path(self.tmp), "copy")
        for route in ("dsh", "nobody"):
            result = gdd_process.run([sys.executable, "-B", str(runner), "start",
                                      "--name", "missing", "--prompt", self.prompt],
                                     env={**self.env, "GDD_AGENT": route}, cwd=self.work,
                                     capture_output=True, encoding="utf-8", timeout=15)
            self.assertEqual(result.returncode, 1)
            self.assertIn(f"{route!r}", result.stderr)
            self.assertIn("installed: omp", result.stderr)
            self.assertIn(f"npx skills add wxxb789/hoa -s gdd-route-{route}", result.stderr)
            self.assertFalse(Path(self.root).exists())


@pytest.mark.parametrize("mode", ["copy", "symlink"] + (["junction"] if os.name == "nt" else []))
def test_installed_route_runs_from_an_unrelated_cwd(tmp_path, mode):
    runner = layout_runner(tmp_path, mode)
    work = tmp_path / "work"
    work.mkdir()
    prompt = tmp_path / "prompt"
    prompt.write_text("Do the task.", encoding="utf-8")
    root = tmp_path / "runs"
    stub = agent_run.SCRIPT_DIR / "tests" / "stub_agent.py"
    env = {key: value for key, value in os.environ.items() if not key.startswith(("GDD_", "STUB_"))}
    env.update(GDD_RUN_ROOT=str(root), XDG_CONFIG_HOME=str(tmp_path / "config"),
               GDD_RUN_DETACH="windows" if os.name == "nt" else "setsid",
               OMP_BIN=str(stub), STUB_FIXTURE=route_fixture("omp"))
    command = [sys.executable, "-B", str(runner)]
    try:
        help_result = gdd_process.run([*command, "--help"], cwd=work, env=env, check=True,
                                      capture_output=True, encoding="utf-8", timeout=15)
        assert "omp" in help_result.stdout and "dsh" not in help_result.stdout
        result = gdd_process.run([*command, "start", "--name", "installed", "--prompt", str(prompt)],
                                 cwd=work, env=env, capture_output=True, encoding="utf-8", timeout=30)
        assert result.returncode == 0, result.stderr
        run_dir, = root.glob("*/installed")
        state = wait_for_json(run_dir / "state.json", lambda s: finalized(run_dir, s), time.monotonic() + 15)
        assert (state["agent"], state["state"], state["exit"]) == ("omp", "done", 0)
    finally:
        stop_headless(root)
