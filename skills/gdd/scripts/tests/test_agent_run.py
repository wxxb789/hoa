#!/usr/bin/env python3
"""Contract tests for agent_run.py: a stub agent stands in for each CLI (`<AGENT>_BIN`).

Opt-in smoke against real CLIs (costs tokens): GDD_SMOKE_AGENTS=omp python -B test_agent_run.py SmokeTests
"""
import glob
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.join(os.path.dirname(HERE), "agent_run.py")
STUB = os.path.join(HERE, "stub_agent.py")
FIXTURES = os.path.join(HERE, "fixtures", "events")
IS_WINDOWS = os.name == "nt"
PROMPT = "Do the task.\nReply with the word done.\n"
EXPECTED = {
    "omp": {"answer": "done", "session_id": "00000000-0000-7000-8000-000000000001", "turns": 2, "tool_calls": 1,
            "usage": {"input_tokens": 6, "output_tokens": 54, "cache_read_tokens": 13420, "total_tokens": 26962},
            "cost_usd": 0.035599, "fail_error": "the last assistant message_end stopReason is 'error'"},
    "dsh": {"answer": "done", "session_id": "dsh-session-0001", "turns": 1, "tool_calls": 2,
            "usage": {"input_tokens": 250, "output_tokens": 40, "cache_read_tokens": 80, "total_tokens": 290},
            "cost_usd": None, "fail_error": "the last final.reason.kind is 'aborted'"},
}
ARGV = {  # (new session, resumed session S1); the prompt follows for argv-prompt agents
    "omp": (["-p", "--mode=json", "--approval-mode", "yolo"], ["-p", "--mode=json", "--approval-mode", "yolo", "-r", "S1"]),
    "dsh": (["--profile", "headless", "--json", "--permission-mode", "workspace-write", "--approval-policy", "never", "-"],
            ["--profile", "headless", "--json", "--session-id", "S1", "--permission-mode", "workspace-write",
             "--approval-policy", "never", "-"]),
}


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


def pid_alive(pid):
    if not pid:
        return False
    if IS_WINDOWS:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def force_kill(pid):
    if not pid_alive(pid):
        return
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
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
                        OMP_BIN=STUB, DSH_BIN=STUB, STUB_RECORD=self.record, PYTHONDONTWRITEBYTECODE="1")

    def tearDown(self):
        for path in glob.glob(os.path.join(self.root, "*", "*", "state.json")):
            run_dir = os.path.dirname(path)
            if not os.path.exists(os.path.join(run_dir, "finalized")):
                self.cli("kill", os.path.basename(run_dir), env={"GDD_RUN_STOP_WAIT_SECONDS": "1"})
            try:
                state = json.loads(read(path))
            except ValueError:
                continue
            for key in ("agent_pid", "pid"):
                force_kill(state.get(key))
            self.assertTrue(wait_for(lambda: not any(pid_alive(state.get(k)) for k in ("agent_pid", "pid")), 10),
                            f"live pids left by {run_dir}")
        shutil.rmtree(self.tmp, ignore_errors=True)

    def cli(self, *args, env=None):
        return subprocess.run([sys.executable, "-B", RUNNER, *args], capture_output=True, text=True,
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
    def test_t1_argv_golden_new_and_resume(self):
        for agent, (new, resumed) in ARGV.items():
            for label, extra, golden in (("new", (), new), ("resume", ("--resume", "S1"), resumed)):
                with self.subTest(agent=agent, session=label):
                    os.path.exists(self.record) and os.unlink(self.record)
                    self.start(f"{agent}-{label}", agent, "ok", "--max-time", "10m", *extra)
                    record = self.recorded()
                    prompt_in_argv = agent == "omp"
                    self.assertEqual(record["argv"], golden + ([PROMPT] if prompt_in_argv else []))
                    self.assertEqual(record["stdin"], "" if prompt_in_argv else PROMPT)
                    self.assertEqual(os.path.realpath(record["cwd"]), os.path.realpath(self.work))
                    self.finished(f"{agent}-{label}")

    def test_t1_model_thinking_and_extra_reach_omp(self):
        self.start("flags", "omp", "ok", "--model", "m1", "--thinking", "high", "--extra", "--no-tools -x")
        self.assertEqual(self.recorded()["argv"], ["-p", "--mode=json", "--approval-mode", "yolo", "--model", "m1",
                                                   "--thinking", "high", "--no-tools", "-x", PROMPT])

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
            force_kill(before[key])
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
                self.start(name, env={"STUB_HANG": "1"})
                state = self.state(name)
                force_kill(state["pid"])
                self.assertTrue(wait_for(lambda: not pid_alive(state["pid"]), 10))
                if forged:  # the recorded pid now names a different process
                    write(os.path.join(self.run_dir(name), "state.json"),
                          json.dumps({**state, "agent_pid_identity": "forged"}))
                killed = self.cli("kill", name, env=fast)
                if forged:
                    self.assertEqual(killed.returncode, 1, killed.stdout)
                    self.assertIn(f"agent_pid {state['agent_pid']} not signalled", killed.stderr)
                    self.assertTrue(pid_alive(state["agent_pid"]))
                    force_kill(state["agent_pid"])
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
        self.start("drain", env={"STUB_CHILD_HOLDS_STDOUT": "8", "GDD_RUN_DRAIN_TIMEOUT_SECONDS": "1"})
        state = self.finished("drain")
        self.assertTrue(state.get("stream_incomplete"), state)
        self.assertEqual(state["state"], "done")

    def test_t13_dsh_env_scrub(self):
        scrubbed = {"DSH_PROFILE": "caller", "DSH_PROFILE_DIR": "/caller", "DSH_SESSION_ID": "caller-session"}
        self.start("scrub", "dsh", env={**scrubbed, "DSH_KEEP": "1"})
        seen = set(self.recorded()["env"])
        self.assertIn("DSH_KEEP", seen)
        self.assertFalse(seen & set(scrubbed), seen)
        self.finished("scrub")

    @unittest.skipIf(IS_WINDOWS or not shutil.which("bash"), "the omp-headless-orchestration forwarder is bash")
    def test_t15_omp_headless_forwarder_resolves_the_sibling_runner(self):
        forwarder = os.path.join(HERE, "..", "..", "..", "omp-headless-orchestration", "scripts", "omp-run.sh")
        env = {**self.env, "STUB_FIXTURE": os.path.join(FIXTURES, "omp.ok.ndjson"), "GDD_AGENT": "dsh"}
        proc = subprocess.run(["bash", forwarder, "start", "--name", "fwd", "--prompt", self.prompt, "--cwd", self.work],
                              capture_output=True, text=True, env=env, timeout=90)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.finished("fwd")["agent"], "omp")  # the forwarder pins GDD_AGENT=omp
        listed = subprocess.run(["bash", forwarder, "list"], capture_output=True, text=True, env=env, timeout=90)
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
            self.assertEqual(state["spawn"]["creationflags"], 0x08000200)
        else:
            self.assertEqual(os.getsid(state["pid"]), state["pid"])
            self.assertEqual(os.getsid(state["agent_pid"]), state["agent_pid"])


@unittest.skipUnless(os.environ.get("GDD_SMOKE_AGENTS"), "set GDD_SMOKE_AGENTS=omp,... to run real CLIs")
class SmokeTests(RunnerCase):
    def test_real_agents(self):
        for agent in os.environ["GDD_SMOKE_AGENTS"].split(","):
            with self.subTest(agent=agent):
                env = {f"{agent.upper()}_BIN": os.environ.get(f"{agent.upper()}_BIN") or agent}
                proc = self.cli("start", "--name", f"smoke-{agent}", "--prompt", self.prompt, "--agent", agent,
                                "--cwd", self.work, env=env)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                state = self.finished(f"smoke-{agent}", 300)
                print(f"smoke {agent}: state={state['state']} exit={state['exit']} turns={state['turns']} "
                      f"answer={read(os.path.join(self.run_dir(f'smoke-{agent}'), 'answer.md'))!r}")
                self.assertEqual(state["state"], "done", state)


if __name__ == "__main__":
    unittest.main()
