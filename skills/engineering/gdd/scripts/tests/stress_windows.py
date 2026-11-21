#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []  # pytest pins come from scripts/requirements.txt: pass --with-requirements
# ///
"""Repeat a focused lifecycle suite in fresh guarded Windows interpreters."""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import gdd_process

ROUNDS = 10
ROUND_TIMEOUT = 240
AUDIT_TIMEOUT = 60
# Leave the workflow's last minute for ending the step and starting the upload.
RUN_TIMEOUT = 19 * 60

CASES = (
    "gdd/scripts/tests/test_agent_run.py::ContractTests::test_concurrent_starts_cannot_move_a_starting_run",
    "gdd/scripts/tests/test_agent_run.py::ContractTests::test_t5_kill_a_hanging_run",
    "gdd/scripts/tests/test_agent_run.py::ContractTests::test_t12_drain_timeout_marks_stream_incomplete",
    "gdd-route-dsh/scripts/tests/test_dsh_route.py::DshIntegrationTests::test_t13_dsh_env_scrub",
    "gdd/scripts/tests/test_agent_run.py::ContractTests::test_t17_detachment_rule",
    "gdd/scripts/tests/test_agent_run.py::RunnerMechanicsTests::test_progress_tick_waits_out_windows_reader_before_replacing",
    "gdd/scripts/tests/test_agent_run.py::RunnerMechanicsTests::test_runner_retries_progress_when_replace_and_in_place_write_fail",
    "gdd/scripts/tests/test_gdd.py::LaunchTests::test_live_run_blocks_and_stale_run_does_not",
    "gdd/scripts/tests/test_paseo_run_python.py::PaseoLauncherTests::test_monitor_finalizes_without_status_and_answer_is_last_assistant",
    "gdd/scripts/tests/test_paseo_run_python.py::PaseoLauncherTests::test_missing_state_file_is_unknown_even_with_an_agent_lock",
    "gdd/scripts/tests/test_paseo_run_python.py::PaseoLauncherTests::test_lifecycle_commands_survive_worktree_removal",
)


def leftovers_in(tmp):
    command = """
$ErrorActionPreference = 'Stop'
$prefix = $env:GDD_STRESS_TMP
function Owned-Processes {
    Get-CimInstance Win32_Process -Filter "CommandLine LIKE '%gdd-stress-run-%'" | Where-Object {
        $_.CommandLine -and $_.CommandLine.IndexOf($prefix, [StringComparison]::OrdinalIgnoreCase) -ge 0
    }
}
foreach ($entry in @(Owned-Processes)) {
    Write-Output "leftover PID $($entry.ProcessId): $($entry.CommandLine)"
    try {
        $process = [Diagnostics.Process]::GetProcessById($entry.ProcessId)
        try {
            # Hold the handle and compare the creation time before signaling this PID.
            $null = $process.Handle
            $ticks = $process.StartTime.ToUniversalTime().Ticks - $entry.CreationDate.ToUniversalTime().Ticks
            if ($ticks -lt 0 -or $ticks -ge 10) {
                Write-Output "PID $($entry.ProcessId) no longer matches the audit"
            } else {
                $process.Kill()
                if (-not $process.WaitForExit(5000)) { throw "process did not exit" }
                Write-Output "killed PID $($entry.ProcessId)"
            }
        } finally { $process.Dispose() }
    } catch {
        Write-Output "PID $($entry.ProcessId) cleanup: $_"
    }
}
foreach ($entry in @(Owned-Processes)) {
    Write-Output "still running PID $($entry.ProcessId): $($entry.CommandLine)"
}
"""
    argv = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command]
    try:
        audit = gdd_process.run(argv, env={**os.environ, "GDD_STRESS_TMP": str(tmp) + os.sep},
                                capture_output=True, text=True, timeout=AUDIT_TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        partial = (exc.stdout or b"").decode("utf-8", "replace")
        return f"process audit timed out after {AUDIT_TIMEOUT}s\n{partial}".rstrip()
    except OSError as exc:
        return f"process audit failed: {exc}"
    if audit.returncode or audit.stderr:
        return f"process audit failed (exit {audit.returncode}): {audit.stderr.strip()}\n{audit.stdout.strip()}"
    return audit.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("this stress job requires native Windows")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix="gdd-stress-run-", dir=out))
    print(f"Diagnostics: {out}", flush=True)
    guard_log = Path(os.environ.setdefault("NOWINDOW_GUARD_LOG", str(out / "guard.log")))
    env = dict(os.environ)
    guard = str(HERE / "nowindow")
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (env.get("PYTHONPATH"), guard)))
    deadline = time.monotonic() + RUN_TIMEOUT
    for iteration in range(1, ROUNDS + 1):
        started = time.monotonic()
        label = f"iteration-{iteration:02d}"
        print(f"{label}/{ROUNDS}", flush=True)
        tmp = out / (label + "-tmp")
        tmp.mkdir()
        # All Python entry points, including orphaned stubs, carry this round's
        # unique path in their command line even after their parent exits.
        source = tmp / "source"
        skills = HERE.parents[2]
        for skill in (skills / "gdd", *skills.glob("gdd-route-*")):
            shutil.copytree(skill, source / skill.name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        before = guard_log.stat().st_size if guard_log.exists() else 0
        log = out / (label + ".log")
        # Reserve enough time for both audit attempts, including on the last round.
        timeout = min(ROUND_TIMEOUT, int(deadline - time.monotonic() - 2 * AUDIT_TIMEOUT))
        code, outcome = 1, "stress budget exhausted"
        try:
            with log.open("wb") as stream:
                if timeout > 0:
                    # Windows has no SIGALRM; pytest-timeout's thread method exits the entire
                    # pytest child. Keep it as a stack dump, with the round bounded separately.
                    result = gdd_process.run(
                        [sys.executable, "-m", "pytest", "-vv", "-x", "--durations=0",
                         "-c", str(HERE.parents[3] / "pytest.ini"), *(str(source / case) for case in CASES)],
                        env={**env, "TEMP": str(tmp), "TMP": str(tmp), "PYTHONDONTWRITEBYTECODE": "1"},
                        stdout=stream, stderr=stream, timeout=timeout)
                    code, outcome = result.returncode, f"pytest exit {result.returncode}"
        except subprocess.TimeoutExpired:
            code, outcome = 1, f"pytest timed out after {timeout}s"
        except OSError as exc:
            code, outcome = 1, f"could not run pytest: {exc}"
        summary = f"{label}: {time.monotonic() - started:.2f}s ({outcome})"
        with log.open("a", encoding="utf-8") as stream:
            print(summary, file=stream)
        processes = leftovers_in(tmp)
        if processes.startswith("process audit "):
            retry = leftovers_in(tmp)
            processes += f"\ncleanup retry: {retry or '0 leftovers'}"
        paths = [path for path in tmp.iterdir() if path != source]
        details = f"leftover processes: {processes or '0'}\nleftover test paths: {paths or '0'}"
        refused = guard_log.exists() and guard_log.stat().st_size > before
        if refused:
            with guard_log.open("rb") as stream:
                stream.seek(before)
                (out / (label + "-guard.log")).write_bytes(stream.read())
        with log.open("a", encoding="utf-8") as stream:
            print(details, file=stream)
        print(f"{summary}\n{details}", flush=True)
        if code or paths or processes or refused:
            print(log.read_text(encoding="utf-8", errors="replace"), end="")
            return code or 1
        shutil.rmtree(source)
        tmp.rmdir()
    return 0


if __name__ == "__main__":
    sys.exit(main())
