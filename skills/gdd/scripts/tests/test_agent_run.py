#!/usr/bin/env python3
"""Contract tests for agent_run.py: a stub agent stands in for each CLI (`<AGENT>_BIN`).

Opt-in smoke against real CLIs (costs tokens): GDD_SMOKE_AGENTS=omp,pi,codex,claude,opencode python -B test_agent_run.py SmokeTests
(GDD_SMOKE_<AGENT>_MODEL passes --model when an agent's default model does not work on the host.)
"""
import contextlib
import glob
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.join(os.path.dirname(HERE), "agent_run.py")
STUB = os.path.join(HERE, "stub_agent.py")
FIXTURES = os.path.join(HERE, "fixtures", "events")
RESULT_SCHEMA = os.path.join(os.path.dirname(os.path.dirname(HERE)), "references", "stage-result.schema.json")
STAGE_RESULT = {"stage": "implement", "verdict": "DONE", "summary": "done", "changed_files": [], "gates": [],
                "findings": [], "unmet_criteria": []}
IS_WINDOWS = os.name == "nt"
sys.path.insert(0, os.path.dirname(RUNNER))
import agent_run
import gdd_process
PROMPT = "Do the task.\nReply with the word done.\n"
EXPECTED = {
    "omp": {"answer": "done", "session_id": "00000000-0000-7000-8000-000000000001", "turns": 2, "tool_calls": 1,
            "usage": {"input_tokens": 6, "output_tokens": 54, "cache_read_tokens": 13420, "total_tokens": 26962},
            "cost_usd": 0.035599, "fail_error": "the last assistant message_end stopReason is 'error'"},
    "dsh": {"answer": "done", "session_id": "dsh-session-0001", "turns": 1, "tool_calls": 2,
            "usage": {"input_tokens": 250, "output_tokens": 40, "cache_read_tokens": 80, "total_tokens": 290},
            "cost_usd": None, "fail_error": "the last final.reason.kind is 'aborted'"},
    "codex": {"answer": json.dumps(STAGE_RESULT, separators=(",", ":")), "session_id": "00000000-0000-7000-8000-000000000002",
              "turns": 1, "tool_calls": 1, "cost_usd": None,
              "usage": {"input_tokens": 25409, "output_tokens": 72, "cache_read_tokens": 0, "total_tokens": 25481},
              "fail_error": "the last turn event is 'turn.failed': {\"error\":{\"message\":\"The selected model"},
    "claude": {"answer": json.dumps(STAGE_RESULT, separators=(",", ":")), "session_id": "00000000-0000-4000-8000-000000000004",
               "turns": 3, "tool_calls": 1, "cost_usd": 0.236953,
               "usage": {"input_tokens": 4, "output_tokens": 273, "cache_read_tokens": 44437, "total_tokens": 89232},
               "fail_error": "the result event outcome is 'api_error': API Error: 400 Model"},
    "pi": {"answer": "done", "session_id": "00000000-0000-7000-8000-000000000006", "turns": 2, "tool_calls": 1,
           "usage": {"input_tokens": 6, "output_tokens": 28, "cache_read_tokens": 14695, "total_tokens": 29460},
           "cost_usd": 0.0, "fail_error": "the last assistant message_end stopReason is 'error': ghc API error (400)"},
    "opencode": {"answer": "done", "session_id": "ses_000000000000000000000001", "turns": 2, "tool_calls": 1,
                 "usage": {"input_tokens": 6, "output_tokens": 23, "cache_read_tokens": 15605, "total_tokens": 31269},
                 "cost_usd": 0.040889, "fail_error": "the last step_finish reason is 'error': Model unavailable"},
}
CODEX = ["exec", "--json", "-c", "approval_policy=never", "-c", "sandbox_mode=workspace-write",
         "-c", "sandbox_workspace_write.network_access=true"]
OPENCODE = ["run", "--standalone", "--format", "json", "--auto", "--title"]
CLAUDE = ["-p", "--output-format", "stream-json", "--verbose", "--permission-mode", "bypassPermissions"]
ARGV = {  # (new session, resumed session S1); the prompt follows for argv-prompt agents
    "omp": (["-p", "--mode=json", "--approval-mode", "yolo"], ["-p", "--mode=json", "--approval-mode", "yolo", "-r", "S1"]),
    "dsh": (["--profile", "headless", "--json", "--permission-mode", "workspace-write", "--approval-policy", "never", "-"],
            ["--profile", "headless", "--json", "--session-id", "S1", "--permission-mode", "workspace-write",
             "--approval-policy", "never", "-"]),
    "codex": (CODEX + ["-"], CODEX[:1] + ["resume"] + CODEX[1:] + ["S1", "-"]),
    "claude": (CLAUDE + ["--session-id", "<uuid>"], CLAUDE + ["--resume", "S1"]),
    "pi": (["--mode", "json", "--no-approve"], ["--mode", "json", "--no-approve", "--session", "S1"]),
    "opencode": (OPENCODE + ["opencode-new"], OPENCODE + ["opencode-resume", "-s", "S1"]),
}
ARGV_PROMPT = ("omp", "opencode")


def uuid_masked(argv):
    """The claude route pre-assigns a fresh uuid4 session id: mask a valid one so goldens can compare."""
    index = argv.index("--session-id") + 1 if "--session-id" in argv else None
    try:
        fresh = index is not None and uuid.UUID(argv[index]).version == 4
    except ValueError:
        fresh = False
    return argv[:index] + ["<uuid>"] + argv[index + 1:] if fresh else argv


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


SCHEMA = json.loads(read(os.path.join(HERE, "state.schema.json")))
JSON_TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "object": dict, "array": list,
              "null": type(None)}


def schema_errors(state):
    errors = [f"missing {key}" for key in SCHEMA["required"] if key not in state]
    for key, value in state.items():
        rule = SCHEMA["properties"].get(key)
        if rule is None:
            errors.append(f"unexpected {key}")
            continue
        types = rule["type"] if isinstance(rule["type"], list) else [rule["type"]]
        if not any(isinstance(value, JSON_TYPES[t]) and not (t in ("integer", "number") and isinstance(value, bool))
                   for t in types) or ("enum" in rule and value not in rule["enum"]):
            errors.append(f"{key}={value!r} breaks {rule}")
    return errors


pid_alive = agent_run.pid_alive


def force_kill(pid, recorded):
    if not recorded or agent_run.identity(pid) != recorded:
        return
    if IS_WINDOWS:
        gdd_process.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
    else:
        os.kill(pid, signal.SIGKILL)


def wait_for(predicate, seconds=30.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return False


class RunnerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="agent-run-")
        self.root = os.path.join(self.tmp, "runs")
        self.work = os.path.join(self.tmp, "work")
        os.makedirs(self.work)
        self.record = os.path.join(self.tmp, "record.json")
        self.prompt = os.path.join(self.tmp, "prompt.md")
        write(self.prompt, PROMPT)
        drop = ("GDD_", "STUB_", "DSH_", "OMP_")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(drop)}
        self.env.update(GDD_RUN_ROOT=self.root, XDG_CONFIG_HOME=os.path.join(self.tmp, "config"),
                        GDD_RUN_DETACH="session",
                        **{f"{agent.upper()}_BIN": STUB for agent in EXPECTED}, STUB_RECORD=self.record,
                        PYTHONDONTWRITEBYTECODE="1")

    def tearDown(self):
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for path in glob.glob(os.path.join(self.root, "*", "*", "state.json")):
            run_dir = os.path.dirname(path)
            if not os.path.exists(os.path.join(run_dir, "finalized")):
                self.cli("kill", os.path.basename(run_dir), env={"GDD_RUN_STOP_WAIT_SECONDS": "1"})
            try:
                state = json.loads(read(path))
            except ValueError:
                continue
            for key in ("agent_pid", "pid"):
                pid, recorded = state.get(key), state.get(f"{key}_identity")
                force_kill(pid, recorded)
                if recorded:
                    self.assertTrue(wait_for(lambda: agent_run.identity(pid) != recorded, 10),
                                    f"live pid {pid} left by {run_dir}")

    def cli(self, *args, env=None):
        return gdd_process.run([sys.executable, "-B", RUNNER, *args], capture_output=True, text=True,
                              env={**self.env, **(env or {})}, cwd=self.work, timeout=90)

    def start(self, name, agent="omp", fixture="ok", *args, env=None, expect=0):
        env = {"STUB_FIXTURE": os.path.join(FIXTURES, f"{agent}.{fixture}.ndjson"), **(env or {})}
        proc = self.cli("start", "--name", name, "--prompt", self.prompt, "--cwd", self.work, "--agent", agent,
                        *args, env=env)
        self.assertEqual(proc.returncode, expect, proc.stdout + proc.stderr)
        return proc

    def run_dir(self, name):
        return glob.glob(os.path.join(self.root, "*", name))[0]

    def state(self, name):
        return json.loads(read(os.path.join(self.run_dir(name), "state.json")))

    def finished(self, name, seconds=30.0):
        marker = os.path.join(self.run_dir(name), "finalized")
        self.assertTrue(wait_for(lambda: os.path.exists(marker), seconds), f"{name} never finalized")
        return self.state(name)

    def recorded(self):
        self.assertTrue(wait_for(lambda: os.path.exists(self.record), 10))
        return json.loads(read(self.record))


class ContractTests(RunnerCase):
    def test_concurrent_starts_cannot_move_a_starting_run(self):
        wrapper = """
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv.pop(1)).parent))
import agent_run
write_json = agent_run.write_json
def paused_write(path, payload):
    if Path(path).name == "run.json":
        print("claimed", flush=True)
        sys.stdin.readline()
    write_json(path, payload)
agent_run.write_json = paused_write
sys.exit(agent_run.main())
"""
        argv = ("start", "--name", "race", "--prompt", self.prompt)
        fixture = {"STUB_FIXTURE": os.path.join(FIXTURES, "omp.ok.ndjson"), "STUB_HANG": "1"}
        with gdd_process.popen([sys.executable, "-B", "-c", wrapper, RUNNER, *argv],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, env={**self.env, **fixture}, cwd=self.work) as first:
            try:
                self.assertEqual(first.stdout.readline().strip(), "claimed")
                second = self.cli(*argv, env=fixture)
            finally:
                try:
                    stdout, stderr = first.communicate("\n", timeout=40)
                except subprocess.TimeoutExpired:
                    first.kill()
                    first.communicate()
                    raise
        self.assertEqual((first.returncode, second.returncode), (0, 1),
                         stdout + stderr + second.stdout + second.stderr)
        self.assertEqual(list(Path(self.root).glob("*/race.prev-*")), [])

    def test_t1_argv_golden_new_and_resume(self):
        for agent, (new, resumed) in ARGV.items():
            for label, extra, golden in (("new", (), new), ("resume", ("--resume", "S1"), resumed)):
                with self.subTest(agent=agent, session=label):
                    os.path.exists(self.record) and os.unlink(self.record)
                    self.start(f"{agent}-{label}", agent, "ok", "--max-time", "10m", *extra)
                    record = self.recorded()
                    prompt_in_argv = agent in ARGV_PROMPT
                    self.assertEqual(uuid_masked(record["argv"]), golden + ([PROMPT] if prompt_in_argv else []))
                    self.assertEqual(record["stdin"], "" if prompt_in_argv else PROMPT)
                    self.assertEqual(os.path.realpath(record["cwd"]), os.path.realpath(self.work))
                    self.finished(f"{agent}-{label}")

    def test_legacy_start_flags(self):
        self.start("omp-old-flags", "omp", "ok", "--backend", "tmux", "--profile", "with spaces")
        self.assertEqual(self.recorded()["argv"][-3:], ["--profile", "with spaces", PROMPT])
        self.finished("omp-old-flags")
        os.unlink(self.record)
        self.start("dsh-old-flags", "dsh", "ok", "--session-id", "S1")
        self.assertEqual(self.recorded()["argv"], ARGV["dsh"][1])
        self.finished("dsh-old-flags")

    def test_t1_model_thinking_and_extra_reach_the_agent(self):
        tails = {"omp": ["--model", "m1", "--thinking", "high", "--no-tools", "-x", PROMPT],
                 "codex": ["-m", "m1", "-c", "model_reasoning_effort=high", "--no-tools", "-x", "-"],
                 "claude": ["--model", "m1", "--effort", "high", "--no-tools", "-x"],
                 "pi": ["--model", "m1", "--thinking", "high", "--no-tools", "-x"],
                 "opencode": ["-m", "m1#high", "--no-tools", "-x", PROMPT]}
        for agent, tail in tails.items():
            with self.subTest(agent=agent):
                os.path.exists(self.record) and os.unlink(self.record)
                self.start(f"flags-{agent}", agent, "ok", "--model", "m1", "--thinking", "high", "--extra", "--no-tools -x")
                self.assertEqual(self.recorded()["argv"][-len(tail):], tail)
                self.finished(f"flags-{agent}")

    def test_t2_ok_fixture_is_done(self):
        for agent, want in EXPECTED.items():
            with self.subTest(agent=agent):
                self.start(f"ok-{agent}", agent)
                state = self.finished(f"ok-{agent}")
                self.assertEqual(schema_errors(state), [])
                self.assertEqual((state["state"], state["exit"]), ("done", 0), state)
                for key in ("session_id", "turns", "tool_calls", "usage", "cost_usd"):
                    self.assertEqual(state[key], want[key], key)
                run_dir = self.run_dir(f"ok-{agent}")
                self.assertEqual(read(os.path.join(run_dir, "answer.md")), want["answer"])
                self.assertEqual(read(os.path.join(run_dir, "exit.code")).strip(), "0")
                answer = self.cli("answer", f"ok-{agent}")
                self.assertEqual((answer.returncode, answer.stdout), (0, want["answer"]))

    def test_t3_exit_zero_without_success_marker_fails(self):
        for agent, want in EXPECTED.items():
            with self.subTest(agent=agent):
                self.start(f"fail-{agent}", agent, "fail")
                state = self.finished(f"fail-{agent}")
                self.assertEqual((state["state"], state["exit"]), ("failed", 0))
                self.assertIn(want["fail_error"], state["error"])
                self.assertEqual(state["errors"], [state["error"]])
                self.assertEqual(schema_errors(state), [])
        aborted = os.path.join(self.tmp, "pi-aborted.ndjson")  # pi documents exit 0 on an aborted run
        write(aborted, read(os.path.join(FIXTURES, "pi.ok.ndjson")).replace('"aborted": false', '"aborted": true'))
        self.start("aborted-pi", "pi", env={"STUB_FIXTURE": aborted})
        state = self.finished("aborted-pi")
        self.assertEqual((state["state"], state["exit"]), ("failed", 0))
        self.assertIn("agent_settled.aborted is true", state["error"])

    def test_t4_exit_codes(self):
        for code, verdict in ((3, "failed"), (130, "killed"), (143, "killed")):
            with self.subTest(code=code):
                self.start(f"exit-{code}", env={"STUB_EXIT": str(code)})
                state = self.finished(f"exit-{code}")
                self.assertEqual((state["state"], state["exit"]), (verdict, code))

    def test_t5_kill_a_hanging_run(self):
        self.start("hang", env={"STUB_HANG": "1"})
        agent_pid = self.state("hang")["agent_pid"]
        killed = self.cli("kill", "hang")
        self.assertEqual(killed.returncode, 0, killed.stderr)
        state = self.finished("hang")
        self.assertEqual((state["state"], state["exit"]), ("killed", 143))
        self.assertTrue(wait_for(lambda: not pid_alive(agent_pid), 10))
        again = self.cli("kill", "hang")
        self.assertEqual(again.returncode, 1)
        self.assertIn("already finished", again.stderr)

    def test_t6_stale_recovery_is_idempotent(self):
        self.start("stale", env={"STUB_HANG": "1"})
        before = self.state("stale")
        for key in ("pid", "agent_pid"):
            force_kill(before[key], before[f"{key}_identity"])
        self.assertTrue(wait_for(lambda: not pid_alive(before["pid"]) and not pid_alive(before["agent_pid"]), 10))
        first = self.cli("status", "stale")
        self.assertIn("stale_recovered: true", first.stdout)
        state = self.state("stale")
        self.assertEqual((state["state"], state["exit"], state["stale_recovered"]), ("failed", -1, True))
        second = self.cli("status", "stale")
        self.assertNotIn("stale_recovered: true", second.stdout)
        self.assertEqual(self.state("stale"), state)
        self.assertIn("failed(stale)", self.cli("list").stdout)

    def test_t6_kill_with_runner_gone_checks_agent_identity(self):
        fast = {"GDD_RUN_STOP_WAIT_SECONDS": "1"}
        for name, forged in (("orphan", False), ("reused", True)):
            with self.subTest(forged=forged):
                # The agent must survive the runner's pipe closing until kill checks its identity.
                self.start(name, env={"STUB_HANG": "1", "STUB_FIXTURE": ""})
                state = self.state(name)
                self.addCleanup(force_kill, state["agent_pid"], state["agent_pid_identity"])
                force_kill(state["pid"], state["pid_identity"])
                self.assertTrue(wait_for(lambda: not pid_alive(state["pid"]), 10))
                self.assertTrue(pid_alive(state["agent_pid"]))
                if forged:  # the recorded pid now names a different process
                    write(os.path.join(self.run_dir(name), "state.json"),
                          json.dumps({**state, "agent_pid_identity": "forged"}))
                killed = self.cli("kill", name, env=fast)
                if forged:
                    self.assertEqual(killed.returncode, 1, killed.stdout)
                    self.assertIn(f"agent_pid {state['agent_pid']} not signalled", killed.stderr)
                    self.assertTrue(pid_alive(state["agent_pid"]))
                    force_kill(state["agent_pid"], state["agent_pid_identity"])
                else:
                    self.assertEqual(killed.returncode, 0, killed.stderr)
                    final = self.state(name)
                    self.assertEqual((final["state"], final["exit"]), ("killed", 143))
                    self.assertTrue(wait_for(lambda: not pid_alive(state["agent_pid"]), 10))

    def craft(self, name, state=None, raw=None):
        run_dir = os.path.join(self.root, datetime.now().strftime("%Y-%m-%d"), name)
        os.makedirs(run_dir)
        write(os.path.join(run_dir, "prompt.md"), PROMPT)
        if state is not None or raw is not None:
            write(os.path.join(run_dir, "state.json"), raw if raw is not None else json.dumps(state))
        return run_dir

    def test_t7_starting_grace(self):
        base = {"name": "s", "agent": "omp", "state": "running", "exit": None, "pid": None, "agent_pid": None}
        self.craft("young", {**base, "started": datetime.now(timezone.utc).isoformat()})
        self.assertEqual(json.loads(self.cli("status", "young").stdout)["state"], "running")
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        self.craft("old", {**base, "started": old})
        out = self.cli("status", "old").stdout
        self.assertIn("stale_recovered: true", out)
        self.assertEqual((self.state("old")["state"], self.state("old")["exit"]), ("failed", -1))
        foreign = {"name": "s", "state": "running", "exit": None, "started": old}
        for name, state in (("paseo", {**base, **foreign, "backend": "paseo"}), ("custom", foreign)):
            with self.subTest(name=name):  # another launcher's run is never settled here
                run_dir = self.craft(name, state)
                self.cli("list")
                self.assertEqual(self.state(name)["state"], "running")
                self.assertFalse(os.path.exists(os.path.join(run_dir, "finalized")))

    def test_t8_missing_or_garbage_state_is_unknown(self):
        self.craft("missing")
        self.craft("garbage", raw="{not json")
        for name in ("missing", "garbage"):
            with self.subTest(name=name):
                status = self.cli("status", name)
                self.assertEqual(json.loads(status.stdout)["state"], "unknown")
                self.assertEqual(self.cli("answer", name).returncode, 1)

    def test_t9_start_refusals(self):
        cases = [
            ((), {"OMP_BIN": os.path.join(self.tmp, "nope")}, "agent binary not found: OMP_BIN="),
            (("--name", ".."), {}, "does not sanitize"),
            (("--agent", "dsh", "--model", "m"), {}, "--model is not supported on the DSH route"),
            (("--agent", "dsh", "--thinking", "high"), {}, "--thinking is not supported on the DSH route"),
            (("--agent", "dsh"), {"DSH_APPROVAL_POLICY": "on-request"}, "DSH_APPROVAL_POLICY='on-request' is refused"),
            (("--agent", "opencode", "--thinking", "high"), {}, "--thinking on the opencode route needs --model"),
            (("--agent", "nobody"), {}, "unknown agent 'nobody'"),
            (("--max-time", "soon"), {}, "--max-time must be"),
        ]
        if IS_WINDOWS:
            shim = os.path.join(self.tmp, "omp.cmd")
            write(shim, "@echo off\n")
            cases.append(((), {"OMP_BIN": shim}, "is a .cmd shim and argument 5 contains"))
        for args, env, message in cases:
            with self.subTest(message=message):
                argv = ["start", "--prompt", self.prompt, "--cwd", self.work]
                argv += [] if "--name" in args else ["--name", "refused"]
                proc = self.cli(*argv, *args, env=env)
                self.assertEqual(proc.returncode, 1, proc.stdout)
                self.assertIn(message, proc.stderr)
                self.assertFalse(glob.glob(os.path.join(self.root, "*", "*")), "a refusal created a run dir")

    def test_t9_bad_config_file_is_one_line_error(self):
        os.makedirs(os.path.join(self.tmp, "gdd"))
        write(os.path.join(self.tmp, "gdd", "config.yaml"), "not a mapping\n")
        for command in (("list",), ("status", "x"), ("kill", "x")):
            with self.subTest(command=command[0]):
                proc = self.cli(*command, env={"GDD_RUN_ROOT": "", "XDG_CONFIG_HOME": self.tmp})
                self.assertEqual(proc.returncode, 1, proc.stdout)
                self.assertIn("agent_run: GDD_RUN_ROOT: ", proc.stderr)
                self.assertNotIn("Traceback", proc.stderr)

    def test_t9_live_slug_needs_replace(self):
        self.start("busy", env={"STUB_HANG": "1"})
        refused = self.start("busy", env={"STUB_HANG": "1"}, expect=1)
        self.assertIn("still running", refused.stderr)
        self.start("busy", "omp", "ok", "--replace")
        self.assertEqual(self.finished("busy")["state"], "done")
        previous = glob.glob(os.path.join(self.root, "*", "busy.prev-*"))
        self.assertEqual(len(previous), 1)
        self.assertEqual(json.loads(read(os.path.join(previous[0], "state.json")))["state"], "killed")

    def test_t10_max_time(self):
        self.start("slow", "omp", "ok", "--max-time", "1", env={"STUB_HANG": "1"})
        state = self.finished("slow")
        self.assertEqual((state["state"], state["exit"]), ("failed", 124))
        self.assertIn("max_time exceeded", state["note"])

    def test_t11_event_bound_rotates_and_counters_stay_exact(self):
        self.start("bound", env={"GDD_RUN_EVENTS_MAX_BYTES": "1500"})
        state = self.finished("bound")
        run_dir = self.run_dir("bound")
        self.assertTrue(os.path.exists(os.path.join(run_dir, "events.1.ndjson")))
        first = json.loads(read(os.path.join(run_dir, "events.ndjson")).splitlines()[0])
        self.assertEqual(first["type"], "truncated")
        self.assertGreater(first["dropped_bytes"], 0)
        self.assertTrue(state["events_truncated"])
        self.assertEqual(state["events_dropped_bytes"], first["dropped_bytes"])
        self.assertEqual((state["turns"], state["tool_calls"], state["state"]), (2, 1, "done"))
        self.assertNotIn("tool_calls_partial", state)

    def test_t12_drain_timeout_marks_stream_incomplete(self):
        try:
            self.start("drain", env={"STUB_CHILD_HOLDS_STDOUT": "8", "GDD_RUN_DRAIN_TIMEOUT_SECONDS": "1"})
            state = self.finished("drain")
            self.assertTrue(state.get("stream_incomplete"), state)
            self.assertEqual(state["state"], "done")
        finally:
            child_path = Path(self.record + ".child")
            if child_path.exists():
                pid, recorded = json.loads(child_path.read_text(encoding="utf-8"))
                force_kill(pid, recorded)
                self.assertTrue(wait_for(lambda: agent_run.identity(pid) != recorded, 10))

    def test_t13_dsh_env_scrub(self):
        scrubbed = {"DSH_PROFILE": "caller", "DSH_PROFILE_DIR": "/caller", "DSH_SESSION_ID": "caller-session"}
        self.start("scrub", "dsh", env={**scrubbed, "DSH_KEEP": "1"})
        seen = set(self.recorded()["env"])
        self.assertIn("DSH_KEEP", seen)
        self.assertFalse(seen & set(scrubbed), seen)
        self.finished("scrub")

    def omp_fixture(self, answer):
        """omp.ok with every assistant message_end answering `answer`."""
        events = [json.loads(line) for line in read(os.path.join(FIXTURES, "omp.ok.ndjson")).splitlines()
                  if line.strip() and not line.startswith("#")]
        for event in events:
            if event["type"] == "message_end" and event["message"]["role"] == "assistant":
                event["message"]["content"] = [{"type": "text", "text": answer}]
        path = os.path.join(self.tmp, f"omp-{len(os.listdir(self.tmp))}.ndjson")
        write(path, "".join(json.dumps(event) + "\n" for event in events))
        return path

    def reported_fixture(self, agent, report):
        """<agent>.ok with an assistant `report` message before the structured result."""
        lines = read(os.path.join(FIXTURES, f"{agent}.ok.ndjson")).splitlines()
        events = [json.loads(line) for line in lines if line.strip() and not line.startswith("#")]
        message = ({"type": "item.completed", "item": {"id": "item_r", "type": "agent_message", "text": report}}
                   if agent == "codex" else
                   {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": report}]}})
        events.insert(len(events) - (2 if agent == "codex" else 3), message)
        path = os.path.join(self.tmp, f"{agent}-report.ndjson")
        write(path, "".join(json.dumps(event) + "\n" for event in events))
        return path

    def test_t14_structured_result(self):
        native = {"codex": ("--output-schema", RESULT_SCHEMA), "claude": ("--json-schema", None)}
        report = "## Findings\nnothing material"
        for agent, (flag, value) in native.items():
            with self.subTest(agent=agent):
                os.path.exists(self.record) and os.unlink(self.record)
                self.start(f"native-{agent}", agent, "ok", "--schema", RESULT_SCHEMA,
                           env={"STUB_FIXTURE": self.reported_fixture(agent, report)})
                argv = self.recorded()["argv"]
                carried = argv[argv.index(flag) + 1]
                self.assertEqual(carried if value else json.loads(carried), value or json.loads(read(RESULT_SCHEMA)))
                state = self.finished(f"native-{agent}")
                self.assertEqual((state["state"], state["result"]), ("done", "valid"), state)
                self.assertEqual(json.loads(read(os.path.join(self.run_dir(f"native-{agent}"), "result.json"))), STAGE_RESULT)
                self.assertEqual(read(os.path.join(self.run_dir(f"native-{agent}"), "answer.md")),
                                 f"{report}\n\n{EXPECTED[agent]['answer']}")
        bad = {**STAGE_RESULT, "gates": [{"command": "make test", "exit_code": "0", "counts": None}]}
        cases = (("fenced", f"Report.\n```json\n{json.dumps(STAGE_RESULT)}\n```\n", "valid", None),
                 ("invalid", f"```json\n{json.dumps(bad)}\n```", "invalid",
                  '$.gates[0].exit_code: expected integer, got "0"'),
                 ("missing", "done", "missing", None))
        for name, answer, verdict, error in cases:
            with self.subTest(case=name):
                self.start(name, "omp", "ok", "--schema", RESULT_SCHEMA, env={"STUB_FIXTURE": self.omp_fixture(answer)})
                state = self.finished(name)
                self.assertEqual((state["state"], state["result"], state.get("result_error")), ("done", verdict, error))
                self.assertEqual(os.path.exists(os.path.join(self.run_dir(name), "result.json")), verdict == "valid")
                self.assertEqual(schema_errors(state), [])
        refused = self.cli("start", "--name", "noschema", "--prompt", self.prompt, "--schema", os.path.join(self.tmp, "nope"))
        self.assertEqual(refused.returncode, 1)
        self.assertIn("is not a readable JSON object", refused.stderr)

    @unittest.skipIf(IS_WINDOWS or not shutil.which("bash"), "the gdd-route-omp forwarder is bash")
    def test_t15_omp_headless_forwarder_resolves_the_sibling_runner(self):
        forwarder = os.path.join(HERE, "..", "..", "..", "gdd-route-omp", "scripts", "omp-run.sh")
        env = {**self.env, "STUB_FIXTURE": os.path.join(FIXTURES, "omp.ok.ndjson"), "GDD_AGENT": "dsh"}
        proc = gdd_process.run(["bash", forwarder, "start", "--name", "fwd", "--prompt", self.prompt, "--cwd", self.work],
                              capture_output=True, text=True, env=env, timeout=90)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.finished("fwd")["agent"], "omp")  # the forwarder pins GDD_AGENT=omp
        listed = gdd_process.run(["bash", forwarder, "list"], capture_output=True, text=True, env=env, timeout=90)
        self.assertIn("fwd", listed.stdout)

    def test_t16_tail_renders_one_line_per_event(self):
        self.start("tail")
        self.finished("tail")
        events = read(os.path.join(self.run_dir("tail"), "events.ndjson")).splitlines()
        lines = self.cli("tail", "tail", "100").stdout.splitlines()
        self.assertEqual(len(lines), len(events))
        self.assertIn("message_end: done", lines)
        for line, raw in zip(lines, events):
            kind = json.loads(raw)["type"]
            self.assertTrue(line == kind or (line.startswith(f"{kind}: ") and len(line) <= len(kind) + 162), line)

    def test_t17_detachment_rule(self):
        self.start("detached", env={"STUB_HANG": "1"})
        state = self.state("detached")
        if IS_WINDOWS:
            self.assertEqual(state["detach"], "windows")
            self.assertIn(state["spawn"]["creationflags"], (0x08000200, 0x09000200))
        else:
            self.assertEqual(state["detach"], "session")
            self.assertEqual(os.getsid(state["pid"]), state["pid"])
            self.assertEqual(os.getsid(state["agent_pid"]), state["agent_pid"])


class RunnerMechanicsTests(unittest.TestCase):
    def test_detach_modes(self):
        for platform, available, response, expected in (
            ("linux", True, "running", "systemd"), ("linux", True, "degraded", "systemd"),
            ("linux", True, "offline", "session"), ("linux", False, "", "session"),
            ("darwin", True, "running", "session"), ("win32", True, "running", "windows"),
        ):
            with self.subTest(platform=platform, available=available, response=response), \
                    mock.patch.object(agent_run.sys, "platform", platform), \
                    mock.patch.object(agent_run, "IS_WINDOWS", platform == "win32"), \
                    mock.patch.object(agent_run.shutil, "which", side_effect=lambda name: name if available else None), \
                    mock.patch.object(agent_run.subprocess, "run",
                                      return_value=subprocess.CompletedProcess([], int(response != "running"), response)) as probe:
                plain = "windows" if platform == "win32" else "session"
                self.assertEqual(agent_run.select_detach("session"), (plain, None))
                probe.assert_not_called()
                self.assertEqual(agent_run.select_detach("auto"),
                                 (expected, "systemd-run" if expected == "systemd" else None))
                if expected == "systemd":
                    self.assertEqual(agent_run.select_detach("systemd"), ("systemd", "systemd-run"))
                else:
                    with self.assertRaises(ValueError):
                        agent_run.select_detach("systemd")
        with mock.patch.object(agent_run.sys, "platform", "linux"), \
                mock.patch.object(agent_run, "IS_WINDOWS", False), \
                mock.patch.object(agent_run.shutil, "which", side_effect=lambda name: name), \
                mock.patch.object(agent_run.subprocess, "run",
                                  side_effect=subprocess.TimeoutExpired("systemctl", 1)) as probe:
            self.assertEqual(agent_run.select_detach("auto"), ("session", None))
            self.assertEqual(probe.call_args.kwargs["timeout"], 1)

    def test_windows_detach_retries_without_breakaway_on_access_denied(self):
        error = PermissionError("job denies breakaway")
        error.winerror = 5
        process = object()
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(gdd_process, "IS_WINDOWS", True), \
                mock.patch.object(subprocess, "Popen", side_effect=[error, process]) as spawn:
            self.assertEqual(agent_run.spawn_detached(["python", "runner.py"], tmp, tmp, {}, "windows"),
                             (process, 0x08000200))
            self.assertEqual([call.kwargs["creationflags"] for call in spawn.call_args_list],
                             [0x09000200, 0x08000200])

    def test_systemd_argv_and_private_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            unit = agent_run.unit_name("demo.slug")
            self.assertRegex(unit, r"^gdd-demo\.slug-[0-9a-f]{12}$")
            self.assertNotEqual(unit, agent_run.unit_name("demo.slug"))

            def submit(argv, **kwargs):
                self.assertEqual(argv, [
                    "systemd-run", "--user", "--collect", "--quiet", "--unit", unit, "--service-type=exec",
                    "--no-ask-password", "--working-directory=/work/with spaces",
                    f"--property=StandardOutput=append:{run / 'runner.log'}", "--property=StandardError=inherit",
                    "--", "/python", "-B", "/runner.py", "_run", "--run-dir", "/runs/$$literal", "--restore-env",
                ])
                self.assertTrue(kwargs["check"])
                with mock.patch.dict(os.environ, {"MANAGER_ONLY": "unused"}, clear=True):
                    agent_run.restore_detached_env(run)
                    self.assertEqual(dict(os.environ), {"SECRET": "value with \n and $"})

            with mock.patch.object(agent_run.subprocess, "run", side_effect=submit):
                agent_run.spawn_detached(["/python", "-B", "/runner.py", "_run", "--run-dir", "/runs/$literal"],
                                         run, "/work/with spaces", {"SECRET": "value with \n and $"},
                                         "systemd", "systemd-run", unit)
            self.assertFalse((run / ".runner-env").exists())

    def test_winerror_5_falls_back_to_in_place_write(self):
        error = PermissionError("locked by a reader")
        error.winerror = 5
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            original = {"state": "running"}
            agent_run.write_json(path, original)
            with mock.patch.object(agent_run.os, "replace", side_effect=error) as replace, \
                    mock.patch.object(agent_run.time, "sleep"), contextlib.redirect_stderr(stderr):
                agent_run.write_json(path, {"state": "done"})
            self.assertEqual(replace.call_count, 40)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"state": "done"})
            self.assertEqual(list(Path(tmp).iterdir()), [path])
            self.assertEqual(len(stderr.getvalue().splitlines()), 1)


@unittest.skipUnless(os.environ.get("GDD_SMOKE_AGENTS"), "set GDD_SMOKE_AGENTS=omp,... to run real CLIs")
class SmokeTests(RunnerCase):
    def test_real_agents(self):
        """A new session, then a resume of it, per agent; each must end done with a valid stage result."""
        gdd_process.run(["git", "init", "-q", self.work], check=True)  # codex refuses a non-repo cwd
        write(self.prompt, f"Change nothing. Reply with one line saying done, then exactly this block:\n"
                           f"```json\n{json.dumps(STAGE_RESULT)}\n```\n")
        for agent in os.environ["GDD_SMOKE_AGENTS"].split(","):
            env, resume = {f"{agent.upper()}_BIN": os.environ.get(f"{agent.upper()}_BIN") or agent}, ()
            model = os.environ.get(f"GDD_SMOKE_{agent.upper()}_MODEL")
            for name in (f"smoke-{agent}", f"smoke-{agent}-resume"):
                with self.subTest(run=name):
                    proc = self.cli("start", "--name", name, "--prompt", self.prompt, "--agent", agent, "--cwd",
                                    self.work, "--schema", RESULT_SCHEMA, *resume,
                                    *(("--model", model) if model else ()), env=env)
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    state = self.finished(name, 300)
                    print(f"smoke {name}: state={state['state']} exit={state['exit']} turns={state['turns']} "
                          f"result={state.get('result')} session={state['session_id']}")
                    self.assertEqual((state["state"], state.get("result")), ("done", "valid"), state)
                    resume = ("--resume", state["session_id"])


if __name__ == "__main__":
    unittest.main()
