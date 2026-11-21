"""Exercise discovery and dispatch from installed skill layouts."""

import json
import os
import shutil
import sys
import time
from pathlib import Path

import pytest

from runner_cases import STAGE_RESULT, RunnerCase, route_fixture
import agent_run
import gdd_process
from gdd_test_support import finalized, stop_headless, wait_for_json


@pytest.mark.skipif(not (agent_run.SKILLS_ROOT.parent.parent / "scripts" / "check_contract_graph.py").is_file(),
                    reason="hoa source checkout only")
def test_checkout_has_all_eight_routes():
    installed = agent_run.discover_routes()
    assert set(installed) == {"omp", "dsh", "codex", "claude", "pi", "opencode", "omo", "copilot"}
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


def install_route(root, name, source):
    module = root / f"gdd-route-{name}" / "scripts" / "route.py"
    module.parent.mkdir(parents=True)
    module.write_text(source, encoding="utf-8")
    return module


OMP_FIXTURE_ROUTE = """\
from agent_run import Route
def fold(acc, event):
    if event.get("type") == "completed":
        acc["success_marker"] = "completed"
ROUTE = Route("omp", "stdin", lambda args, extra: [], fold, "completed event", bool)
"""


def layout_runner(tmp_path, mode, *, with_route=True):
    installed = tmp_path / "installed"
    link = installed / "gdd"
    target = link if mode == "copy" else tmp_path / "canonical" / "gdd"
    installed.mkdir(parents=True)
    shutil.copytree(agent_run.SCRIPT_DIR, target / "scripts",
                    ignore=shutil.ignore_patterns("__pycache__", "tests"))
    if with_route:
        install_route(installed, "omp", OMP_FIXTURE_ROUTE)
    if mode == "junction":
        result = gdd_process.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
                                 capture_output=True, encoding="utf-8", errors="replace", timeout=10)
        if result.returncode:
            pytest.skip(f"cannot create a Windows junction: {result.stderr.strip()}")
    elif mode == "symlink":
        try:
            link.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            pytest.skip(f"cannot create a directory symlink: {exc}")
    return installed / "gdd" / "scripts" / "agent_run.py"


class MissingRouteTests(RunnerCase):
    def test_missing_route_start_exits_before_creating_a_run(self):
        runner = layout_runner(Path(self.tmp), "copy", with_route=False)
        for route, package in (("omp", "gdd-route-omp"), ("claude", "gdd-route-cc"),
                               ("omo", "gdd-route-omo"), ("copilot", "gdd-route-copilot")):
            result = gdd_process.run([sys.executable, "-B", str(runner), "start",
                                      "--name", "missing", "--prompt", self.prompt],
                                     env={**self.env, "GDD_AGENT": route}, cwd=self.work,
                                     capture_output=True, encoding="utf-8", timeout=15)
            self.assertEqual(result.returncode, 1)
            self.assertIn(f"{route!r}", result.stderr)
            self.assertIn("installed: none", result.stderr)
            self.assertIn(str(runner.parents[2]), result.stderr)
            self.assertIn(f"npx skills add wxxb789/hoa -s {package}", result.stderr)
            self.assertIn(f"npx skills add wxxb789/hoa -g -s {package}", result.stderr)
            self.assertFalse(Path(self.root).exists())

    @pytest.mark.skipif(os.name != "nt", reason="Windows batch shims only")
    def test_native_routes_refuse_batch_shims(self):
        for route in ("omo", "copilot"):
            shim = Path(self.work) / f"{route}.cmd"
            shim.write_text("@exit /b 99\n", encoding="utf-8")
            for override in ("", str(shim)):
                with self.subTest(route=route, override=bool(override)):
                    result = self.cli("start", "--agent", route, "--name", "shim", "--prompt", self.prompt,
                                      env={f"{route.upper()}_BIN": override, "PATH": self.work})
                    self.assertEqual(result.returncode, 1)
                    self.assertIn(f"{route.upper()}_BIN", result.stderr)
                    self.assertFalse(Path(self.root).exists())


@pytest.mark.parametrize("mode", ["copy", "symlink"] + (["junction"] if os.name == "nt" else []))
def test_mixed_layout_starts_from_lexical_and_configured_root(tmp_path, mode):
    runner = layout_runner(tmp_path, mode)
    work = tmp_path / "work"
    work.mkdir()
    prompt = tmp_path / "prompt"
    prompt.write_text("Do the task.", encoding="utf-8")
    root = tmp_path / "runs"
    stub = agent_run.SCRIPT_DIR / "tests" / "stub_agent.py"
    fixture = tmp_path / "events.ndjson"
    fixture.write_text('{"type":"completed"}\n', encoding="utf-8")
    env = {key: value for key, value in os.environ.items() if not key.startswith(("GDD_", "STUB_"))}
    env.update(GDD_RUN_ROOT=str(root), XDG_CONFIG_HOME=str(tmp_path / "config"),
               GDD_RUN_DETACH="windows" if os.name == "nt" else "setsid",
               OMP_BIN=str(stub), STUB_FIXTURE=str(fixture), PYTHONIOENCODING="utf-8")
    host = runner.parents[2]
    canonical = runner.resolve()
    config = tmp_path / "config" / "gdd" / "config.yaml"

    def cli(path, *args, extra=None):
        return gdd_process.run([sys.executable, "-B", str(path), *args], cwd=work,
                               env={**env, **(extra or {})}, capture_output=True, encoding="utf-8", timeout=30)

    try:
        if mode != "copy":
            missing = cli(canonical, "start", "--name", "missing", "--prompt", str(prompt))
            assert missing.returncode == 1
            assert str(canonical.parents[2]) in missing.stderr
            assert not root.exists()
        for label, path, extra in (("lexical", runner, {}), ("env", canonical, {"GDD_SKILLS_ROOT": str(host)}),
                                   ("config", canonical, {})):
            if label != "lexical":
                config.parent.mkdir(parents=True, exist_ok=True)
                config.write_text(f"GDD_SKILLS_ROOT: {json.dumps(str(host if label == 'config' else work))}\n",
                                  encoding="utf-8")
            help_result = cli(path, "--help", extra=extra)
            assert help_result.returncode == 0 and "omp" in help_result.stdout
            result = cli(path, "start", "--name", label, "--prompt", str(prompt), extra=extra)
            assert result.returncode == 0, result.stderr
            run_dir, = root.glob(f"*/{label}")
            assert json.loads((run_dir / "run.json").read_text(encoding="utf-8"))["skills_root"] == str(host)
            state = wait_for_json(run_dir / "state.json", lambda s: finalized(run_dir, s), time.monotonic() + 15)
            assert (state["agent"], state["state"], state["exit"]) == ("omp", "done", 0)
    finally:
        stop_headless(root)


@pytest.mark.parametrize("snapshot", [False, True], ids=["legacy", "snapshot"])
def test_stale_status_recovers_codex_after_route_uninstall(tmp_path, snapshot):
    route = agent_run.discover_routes(agent_run.SKILLS_ROOT).get("codex")
    if route is None:
        pytest.skip("Codex checkout fixture not installed")
    runner = layout_runner(tmp_path, "copy", with_route=False)
    host = runner.parents[2]
    installed = install_route(host, "codex", route.read_text(encoding="utf-8"))
    root = tmp_path / "runs"
    env = {key: value for key, value in os.environ.items() if not key.startswith(("GDD_", "STUB_"))}
    env.update(GDD_RUN_ROOT=str(root), XDG_CONFIG_HOME=str(tmp_path / "config"),
               GDD_RUN_DETACH="windows" if os.name == "nt" else "setsid",
               CODEX_BIN=str(agent_run.SCRIPT_DIR / "tests" / "stub_agent.py"), STUB_FIXTURE=route_fixture("codex"))
    prompt = tmp_path / "prompt"
    prompt.write_text("Do the task.", encoding="utf-8")

    def cli(*args):
        return gdd_process.run([sys.executable, "-B", str(runner), *args], cwd=tmp_path, env=env,
                               capture_output=True, encoding="utf-8", timeout=30)

    try:
        result = cli("start", "--agent", "codex", "--name", "finished", "--prompt", str(prompt))
        assert result.returncode == 0, result.stderr
        finished_dir, = root.glob("*/finished")
        wait_for_json(finished_dir / "state.json", lambda s: finalized(finished_dir, s), time.monotonic() + 15)
        stop_headless(root)
        run = finished_dir.with_name("stale")
        run.mkdir()
        if snapshot:
            for name in ("route.py", "run.json"):
                artifact = finished_dir / name
                if artifact.exists():
                    shutil.copyfile(artifact, run / name)
        recorded = {"session_id": "recorded", "turns": 7, "tool_calls": 3,
                    "usage": {"input_tokens": 44}, "answer_chars": len("Recorded answer")}
        state = {"name": "stale", "agent": "codex", "started": "2000-01-01T00:00:00+00:00",
                 "state": "running", "pid": None, "agent_pid": None, **recorded}
        (run / "answer.md").write_text("Recorded answer", encoding="utf-8")
        (run / "state.json").write_text(json.dumps(state), encoding="utf-8")
        shutil.copyfile(route_fixture("codex"), run / "events.ndjson")
        removed = installed.with_suffix(".removed")
        installed.rename(removed)

        result = cli("status", "stale")
        assert result.returncode == 0, result.stderr
        saved = json.loads((run / "state.json").read_text(encoding="utf-8"))
        answer = (run / "answer.md").read_text(encoding="utf-8")
        if snapshot:
            assert json.loads(answer) == STAGE_RESULT
            assert (saved["turns"], saved["tool_calls"], saved["usage"]["input_tokens"]) == (1, 1, 25409)
            assert (run / "finalized").is_file()
            # Detached startup also uses the snapshot, even with no installed route to resolve.
            replay = run.with_name("replay")
            replay.mkdir()
            for name in ("route.py", "run.json", "prompt.md"):
                shutil.copyfile(finished_dir / name, replay / name)
            (replay / "state.json").write_text(json.dumps({**state, "name": "replay", "spawn": {}}),
                                               encoding="utf-8")
            result = cli("_run", "--run-dir", str(replay))
            assert result.returncode == 0, result.stderr
            assert json.loads((replay / "state.json").read_text(encoding="utf-8"))["state"] == "done"
        else:
            assert answer == "Recorded answer"
            assert {key: saved[key] for key in recorded} == recorded
            assert "refold" in saved["note"] and not (run / "finalized").exists()
            removed.rename(installed)
            assert cli("status", "stale").returncode == 0
            assert json.loads((run / "answer.md").read_text(encoding="utf-8")) == STAGE_RESULT
            assert (run / "finalized").is_file()
    finally:
        stop_headless(root)
