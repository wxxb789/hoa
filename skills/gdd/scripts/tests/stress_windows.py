"""Repeat a focused lifecycle suite in fresh guarded Windows interpreters."""

import argparse
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import gdd_process

CASES = (
    "test_agent_run.py::ContractTests::test_concurrent_starts_cannot_move_a_starting_run",
    "test_agent_run.py::ContractTests::test_t5_kill_a_hanging_run",
    "test_agent_run.py::ContractTests::test_t12_drain_timeout_marks_stream_incomplete",
    "test_agent_run.py::ContractTests::test_t13_dsh_env_scrub",
    "test_agent_run.py::ContractTests::test_t17_detachment_rule",
    "test_agent_run.py::RunnerMechanicsTests::test_progress_tick_waits_out_windows_reader_before_replacing",
    "test_agent_run.py::RunnerMechanicsTests::test_runner_retries_progress_when_replace_and_in_place_write_fail",
    "test_gdd.py::LaunchTests::test_live_run_blocks_and_stale_run_does_not",
    "test_paseo_run_python.py::PaseoLauncherTests::test_monitor_finalizes_without_status_and_answer_is_last_assistant",
    "test_paseo_run_python.py::PaseoLauncherTests::test_missing_state_file_is_unknown_even_with_an_agent_lock",
)


def leftovers_in(tmp):
    command = """
$paths = $env:GDD_STRESS_TMP, $env:GDD_STRESS_STUB
Get-CimInstance Win32_Process | Where-Object {
    $line = $_.CommandLine
    $line -and ($paths | Where-Object { $line.IndexOf($_, [StringComparison]::OrdinalIgnoreCase) -ge 0 })
} | Select-Object ProcessId, Name, CommandLine | Format-List
"""
    audit = gdd_process.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                            env={**os.environ, "GDD_STRESS_TMP": str(tmp),
                                 "GDD_STRESS_STUB": str(HERE / "stub_agent.py")},
                            capture_output=True, text=True, timeout=15)
    if audit.returncode or audit.stderr:
        return f"process audit failed (exit {audit.returncode}): {audit.stderr.strip()}"
    return audit.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("this stress job requires native Windows")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    guard = str(HERE / "nowindow")
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (env.get("PYTHONPATH"), guard)))
    guard_log = Path(env.setdefault("NOWINDOW_GUARD_LOG", str(out / "guard.log")))
    for iteration in range(1, 11):
        started = time.monotonic()
        label = f"iteration-{iteration:02d}"
        print(f"{label}/10", flush=True)
        tmp = out / (label + "-tmp")
        tmp.mkdir()
        before = guard_log.stat().st_size if guard_log.exists() else 0
        log = out / (label + ".log")
        with log.open("wb") as stream:
            result = gdd_process.run(
                [sys.executable, "-m", "pytest", "-vv", "-x", "--durations=0",
                 *(str(HERE / case) for case in CASES)],
                env={**env, "TEMP": str(tmp), "TMP": str(tmp)}, stdout=stream, stderr=stream)
        summary = f"{label}: {time.monotonic() - started:.2f}s (pytest exit {result.returncode})"
        paths = list(tmp.iterdir())
        processes = leftovers_in(tmp)
        summary += f"\nleftover processes: {processes or '0'}\nleftover test paths: {paths or '0'}"
        refused = guard_log.exists() and guard_log.stat().st_size > before
        if refused:
            with guard_log.open("rb") as stream:
                stream.seek(before)
                (out / (label + "-guard.log")).write_bytes(stream.read())
        with log.open("a", encoding="utf-8") as stream:
            print(summary, file=stream)
        print(summary, flush=True)
        if result.returncode or paths or processes or refused:
            print(log.read_text(encoding="utf-8", errors="replace"), end="")
            return result.returncode or 1
        tmp.rmdir()
    return 0


if __name__ == "__main__":
    sys.exit(main())
