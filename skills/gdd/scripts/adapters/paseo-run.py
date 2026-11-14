#!/usr/bin/env python3
"""Native Paseo launcher: start|status|result|answer|kill|list (stdlib only).

Explicitly opt in with GDD_LAUNCHER; daemon failure never selects another
launcher. PASEO_BIN is an executable path or JSON argv array (default paseo on
PATH). Windows batch shims refuse newlines/shell metacharacters; configure the
native executable and CLI entrypoint argv for multiline stages, without a shell.
--model / GDD_MODEL selects
Paseo's --provider, --thinking / GDD_THINKING selects --thinking. GDD_RUN_ROOT
defaults to ${XDG_STATE_HOME:-$HOME/.local/state}/gdd/runs on every OS.

start records the real `run --no-wait --json` agentId before returning. A
detached local monitor keeps state.json current for gdd.py's file-only polling.
The daemon, not that monitor, owns execution. Its disappearance is unknown,
never proof of success or permission to launch a substitute. Lifecycle mapping
(Paseo 0.15.4): initializing/running -> running, idle -> done, error -> failed,
closed -> killed. kill hard-deletes exactly the recorded agent, not merely its
current turn. A confirmed deletion finalizes an active stage as killed; deleting
an already-finalized agent preserves its historical stage outcome.
An unverified dispatch cwd stays unknown until inspect explicitly confirms the
requested directory, regardless of the agent's lifecycle state.

inspect --json exposes Id/Status, not an answer field. Verified CLI 0.15.4
`logs ID --filter assistant_message --tail 1` returns the last assistant text;
even logs --json renders text, so this adapter deliberately does not parse it
as JSON. Empty/unavailable output is explicitly unavailable, with the logs
argv recorded, never a fabricated assistant response.

Run artifacts include prompt.md, run.json (exact argv), state.json, lock
(monitor pid and agent_id), events.ndjson (observed lifecycle transitions),
stderr.log, cli.ndjson (raw command evidence), answer.md when addressable,
exit.code and finalized. Claims use the existing adapter's cross-platform OS
locks; a finalized marker is immutable and ledger rows are serialized per run.
An existing slug is refused rather than silently reused or replaced. Unsupported
--max-time is refused: Paseo's --wait-timeout is not an execution deadline.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time
import types
from contextlib import contextmanager
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ADAPTER = os.path.abspath(__file__)
# Reuse the shipped OS-lock, atomic-write and detachment rules without changing
# the headless adapter or leaving bytecode in an installed skill directory.
support = types.ModuleType("gdd_headless_support")
support.__file__ = os.path.join(HERE, "omp-run.py")
with open(support.__file__, encoding="utf-8") as source:
    exec(compile(source.read(), support.__file__, "exec"), support.__dict__)

STATES = {"initializing": "running", "running": "running", "idle": "done",
          "error": "failed", "closed": "killed"}
EXITS = {"done": 0, "failed": 1, "killed": 143}
CMD_UNSAFE = re.compile(r'[\r\n"&|<>^()%!]')
# Foreground claim attempts wait half of one CLI call's 60-second budget.
# A holder may make several calls, so no finite claim wait resolves a run:
# the detached monitor retries every timeout until terminal evidence exists.
CLI_TIMEOUT_SECONDS = 60
CLAIM_WAIT_SECONDS = CLI_TIMEOUT_SECONDS / 2


class ClaimTimeout(RuntimeError):
    """The claim is unavailable, not evidence that the native run ended."""


def fail(message):
    raise RuntimeError(message)


def configured_command():
    value = os.environ.get("PASEO_BIN") or "paseo"
    if value.lstrip().startswith("["):
        try:
            prefix = json.loads(value)
        except ValueError:
            fail("PASEO_BIN must be an executable path or a JSON argv array")
        if not isinstance(prefix, list) or not prefix or any(
                not isinstance(part, str) or not part for part in prefix):
            fail("PASEO_BIN JSON argv must be a non-empty array of non-empty strings")
    else:
        prefix = [value]
    binary = support.resolve_agent(prefix[0])
    if not binary:
        fail("PASEO_BIN is not an executable on PATH")
    return [binary, *prefix[1:]]


def command_argv(state, argv):
    prefix = state["paseo_argv"]
    if support.IS_WINDOWS and os.path.splitext(prefix[0])[1].lower() in (".cmd", ".bat"):
        if any(CMD_UNSAFE.search(part) for part in [*prefix[1:], *argv]):
            fail("Windows .cmd/.bat transport refuses newlines or shell metacharacters; "
                 "configure PASEO_BIN as a JSON argv array naming the real executable "
                 "and CLI entrypoint (no shell)")
    return support.agent_command(prefix[0], [*prefix[1:], *argv])


def run_root():
    return os.path.abspath(os.path.expanduser(os.environ.get("GDD_RUN_ROOT") or
                           os.path.join(support.state_home(), "gdd", "runs")))


def text_file(run_dir, name, text):
    with open(os.path.join(run_dir, name), "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


@contextmanager
def claim(path):
    deadline = time.monotonic() + CLAIM_WAIT_SECONDS
    while True:
        with support.slug_start_claim(path) as held:
            if held:
                yield
                return
        if time.monotonic() >= deadline:
            raise ClaimTimeout(f"cannot acquire claim: {path}")
        time.sleep(0.05)


def cli(state, argv):
    command = command_argv(state, argv)
    environment = dict(os.environ)
    if argv[0] == "run":
        # CLI 0.15.4 utils/caller-agent.js reads PASEO_AGENT_ID; agent/run.js
        # reads PASEO_WORKSPACE_ID. Both override --cwd. These are the complete
        # caller/session readers found in that CLI; preserve unrelated config.
        for key in ("PASEO_AGENT_ID", "PASEO_WORKSPACE_ID"):
            environment.pop(key, None)
    try:
        result = subprocess.run(command, cwd=state["cwd"], capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=CLI_TIMEOUT_SECONDS,
                                creationflags=support.hidden_flags(), env=environment)
        code, stdout, stderr = result.returncode, result.stdout, result.stderr
    except (OSError, subprocess.TimeoutExpired) as exc:
        code, stdout, stderr = -1, "", str(exc)
    run_dir = state["run_dir"]
    with open(os.path.join(run_dir, "cli.ndjson"), "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"at": support.now_iso(), "argv": command, "exit": code,
                                 "stdout": stdout, "stderr": stderr}, ensure_ascii=False) + "\n")
    if stderr:
        with open(os.path.join(run_dir, "stderr.log"), "a", encoding="utf-8") as handle:
            handle.write(stderr + ("" if stderr.endswith("\n") else "\n"))
    return code, stdout, stderr


def json_cli(state, argv):
    code, stdout, stderr = cli(state, argv)
    if code:
        fail(f"paseo {' '.join(argv[:2])}: exit {code}: {stderr.strip() or stdout.strip()}")
    try:
        return json.loads(stdout)
    except ValueError:
        fail(f"paseo {argv[0]} returned invalid JSON (see cli.ndjson)")


def answer_argv(state):
    return ["logs", state["agent_id"], "--filter", "assistant_message", "--tail", "1"]


def fetch_answer(state):
    code, stdout, _ = cli(state, answer_argv(state))
    available = code == 0 and bool(stdout.strip()) and stdout.strip() != "No activity to display."
    state["answer_available"] = available
    state["answer_argv"] = [*state["paseo_argv"], *answer_argv(state)]
    if available:
        text_file(state["run_dir"], "answer.md", stdout)


def publish(state):
    support.write_json(os.path.join(state["run_dir"], "state.json"), state)


def cwd_matches(actual, requested):
    return (isinstance(actual, str) and bool(actual.strip()) and
            os.path.normcase(os.path.realpath(actual)) == os.path.normcase(os.path.realpath(requested)))


def finalize(state):
    run_dir = state["run_dir"]
    state["ended"] = support.now_iso()
    state["duration_s"] = round(support.state_age_seconds(state), 1)
    text_file(run_dir, "exit.code", str(state["exit"]) + "\n")
    publish(state)
    support.ledger_append(run_dir, state, state["exit"])
    text_file(run_dir, "finalized", str(state["exit"]) + "\n")


def refresh_locked(run_dir):
    state = support.read_state_file(run_dir)
    if not state or state.get("backend") != "paseo":
        return {"name": os.path.basename(run_dir), "state": "unknown", "exit": None,
                "error": "missing or non-Paseo state.json"}
    if os.path.exists(os.path.join(run_dir, "finalized")):
        return state
    previous = state.get("state"), state.get("paseo_status")
    try:
        agent = json_cli(state, ["inspect", state["agent_id"], "--json"])
        if not isinstance(agent, dict) or agent.get("Id") != state["agent_id"]:
            fail("missing or mismatched agent in inspect response")
        if not state.get("cwd_verified"):
            state["reported_cwd"] = agent.get("Cwd")
            if not cwd_matches(state["reported_cwd"], state["cwd"]):
                fail(state.get("cwd_error") or "inspect did not verify the requested cwd; dispatch provenance is unknown")
            state["cwd_verified"] = True
            state.pop("cwd_error", None)
        native = agent.get("Status")
        word = STATES.get(native, "unknown")
        if native == "idle" and agent.get("PendingPermissions"):
            word = "running"
        state.update(state=word, paseo_status=native, exit=EXITS.get(word))
        state.pop("error", None)
        if word == "unknown":
            state["error"] = "unrecognized Paseo lifecycle state"
    except (RuntimeError, KeyError) as exc:
        state.update(state="unknown", exit=None, paseo_status=None, error=str(exc))
    state["observed_at"] = support.now_iso()
    if previous != (state["state"], state.get("paseo_status")):
        with open(os.path.join(run_dir, "events.ndjson"), "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"type": "paseo_status", "at": state["observed_at"],
                                     "state": state["state"], "status": state.get("paseo_status")}) + "\n")
    if state["state"] in EXITS:
        fetch_answer(state)
        finalize(state)
    else:
        publish(state)
    return state


def refresh(run_dir):
    with claim(os.path.join(run_dir, "refresh")):
        return refresh_locked(run_dir)


def find_run(name):
    if os.path.isdir(name):
        return os.path.abspath(name)
    slug = support.sanitize(name)
    if not slug:
        fail("empty run name")
    paths = sorted(glob.glob(os.path.join(run_root(), "*", glob.escape(slug))), reverse=True)
    for path in paths:
        if os.path.isdir(path):
            return path
    fail(f"no recorded run: {name}")


def start(args):
    if args.max_time:
        fail("--max-time is unsupported by paseo; --wait-timeout does not stop execution")
    slug = support.sanitize(args.name)
    if not slug:
        fail("empty run name after sanitizing")
    prefix = configured_command()
    binary = prefix[0]
    cwd = os.path.abspath(os.path.expanduser(args.cwd))
    if not os.path.isdir(cwd):
        fail(f"not a working directory: {cwd}")
    with open(args.prompt, encoding="utf-8") as handle:
        prompt = handle.read()
    if not prompt.strip():
        fail("empty prompt")
    # Validate before creating a run directory or dispatching anything. Batch
    # shims cannot carry arbitrary prompts; never send a silently shortened one.
    command_argv({"paseo_argv": prefix}, ["run", "--cwd", cwd, "--", prompt])
    warning = support.interop_warning(binary)
    if warning:
        print(warning.replace("OMP_BIN", "PASEO_BIN"), file=sys.stderr)
    run_dir = os.path.join(run_root(), datetime.now().strftime("%Y-%m-%d"), slug)
    with support.slug_start_claim(run_dir) as held:
        if not held:
            fail(f"another start owns {slug}")
        if os.path.exists(run_dir):
            fail(f"run already recorded: {slug}; choose a fresh stage name")
        os.makedirs(run_dir)
        with claim(os.path.join(run_dir, "refresh")):
            state = {"name": slug, "state": "unknown", "exit": None, "cwd": cwd,
                     "cwd_verified": False,
                     "started": support.now_iso(), "ended": None, "duration_s": None,
                     "backend": "paseo", "launcher": ADAPTER, "agent": binary,
                     "paseo_argv": prefix,
                     "run_dir": run_dir, "pid": None, "agent_id": None,
                     "session_id": "", "model": args.model, "thinking": args.thinking,
                     "ledger": os.path.join(run_root(), "ledger.tsv")}
            text_file(run_dir, "prompt.md", prompt)
            text_file(run_dir, "stderr.log", "")
            text_file(run_dir, "events.ndjson", "")
            publish(state)
            support.write_json(os.path.join(run_dir, "start.lock"), {"pid": os.getpid()})
            argv = ["run", "--no-wait", "--title", slug, "--cwd", cwd]
            if args.model:
                argv.extend(["--provider", args.model])
            if args.thinking:
                argv.extend(["--thinking", args.thinking])
            argv.extend(["--json", "--", prompt])
            support.write_json(os.path.join(run_dir, "run.json"),
                               {"argv": command_argv(state, argv), "cwd": cwd,
                                "backend": "paseo", "launcher": ADAPTER})
            try:
                result = json_cli(state, argv)
                agent_id = result.get("agentId") if isinstance(result, dict) else None
                if not isinstance(agent_id, str) or not agent_id.strip():
                    fail("run returned no agentId; dispatch is unknown (see cli.ndjson); do not retry blindly")
                state.update(agent_id=agent_id, session_id=agent_id, state="running")
                publish(state)
                support.write_json(os.path.join(run_dir, "lock"),
                                   {"pid": None, "agent_id": agent_id, "backend": "paseo",
                                    "started_at": state["started"]})
                state["reported_cwd"] = result.get("cwd")
                if not cwd_matches(state["reported_cwd"], cwd):
                    state["cwd_error"] = ("run returned a different cwd; dispatch provenance is unknown "
                                          "(agent identity preserved; inspect before retrying)")
                    fail(state["cwd_error"])
                state["cwd_verified"] = True
                with open(os.path.join(run_dir, "runner.log"), "ab", buffering=0) as log:
                    options = {"cwd": cwd, "stdin": subprocess.DEVNULL, "stdout": log,
                               "stderr": subprocess.STDOUT}
                    if support.IS_WINDOWS:
                        options["creationflags"] = support.detach_flags()
                    else:
                        options["start_new_session"] = True
                    process = subprocess.Popen([sys.executable, "-B", ADAPTER, "_watch",
                                                "--run-dir", run_dir], **options)
                state["pid"] = process.pid
                publish(state)
                support.update_lock(run_dir, pid=process.pid)
            except (RuntimeError, OSError) as exc:
                state.update(state="unknown", error=str(exc))
                publish(state)
                raise
            finally:
                support.remove_quietly(os.path.join(run_dir, "start.lock"))
    print(f"started: {slug}\n  backend   : paseo\n  run dir   : {run_dir}\n  agent id  : {agent_id}")
    return 0


def watch(args):
    while True:
        try:
            state = refresh(args.run_dir)
        except ClaimTimeout:
            # Another reader may still be inside a permitted CLI call. Preserve
            # its published observation; contention is not a lifecycle update.
            state = support.read_state_file(args.run_dir)
        if state.get("state") in EXITS or os.path.exists(os.path.join(args.run_dir, "finalized")):
            return 0
        time.sleep(1)


def kill(run_dir):
    with claim(os.path.join(run_dir, "refresh")):
        state = refresh_locked(run_dir)
        if state.get("agent_deleted"):
            return state
        if not state.get("agent_id"):
            fail("kill: no recorded agent identity")
        settled = os.path.exists(os.path.join(run_dir, "finalized"))
        if not state.get("answer_available"):
            captured = dict(state)
            fetch_answer(captured)
            if not settled:
                state = captured
        result = json_cli(state, ["delete", state["agent_id"], "--json"])
        # delete can exit zero even when the underlying deletion failed.
        if (not isinstance(result, dict) or type(result.get("deletedCount")) is not int
                or result["deletedCount"] != 1 or result.get("agentIds") != [state["agent_id"]]):
            fail("delete did not confirm termination; agent state is not killed")
        state.update(agent_deleted=True, termination_verb="delete", terminated_at=support.now_iso())
        if settled:
            publish(state)
        else:
            state.update(state="killed", exit=143, answer_partial=bool(state.get("answer_available")))
            finalize(state)
        return state


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    launch = commands.add_parser("start")
    launch.add_argument("--name", required=True)
    launch.add_argument("--prompt", required=True)
    launch.add_argument("--cwd", default=os.getcwd())
    launch.add_argument("--model", default=os.environ.get("GDD_MODEL") or None)
    launch.add_argument("--thinking", default=os.environ.get("GDD_THINKING") or None)
    launch.add_argument("--max-time")
    monitor = commands.add_parser("_watch", help=argparse.SUPPRESS)
    monitor.add_argument("--run-dir", required=True)
    for name in ("status", "result", "answer", "kill"):
        sub = commands.add_parser(name)
        sub.add_argument("name")
    tail = commands.add_parser("tail")
    tail.add_argument("name")
    tail.add_argument("lines", nargs="?", type=int, default=20)
    commands.add_parser("list")
    args = parser.parse_args(support.normalize_argv(sys.argv[1:] if argv is None else argv))
    if args.command == "start":
        return start(args)
    if args.command == "_watch":
        return watch(args)
    if args.command == "list":
        found = False
        for path in sorted(glob.glob(os.path.join(run_root(), "*", "*")), reverse=True):
            if support.read_state_file(path).get("backend") == "paseo":
                state = refresh(path)
                print(f"{state['name']}  {state['state']}  agent={state.get('agent_id') or '-'}")
                found = True
        if not found:
            print("(no paseo runs recorded)")
        return 0
    run_dir = find_run(args.name)
    state = kill(run_dir) if args.command == "kill" else refresh(run_dir)
    if args.command == "tail":
        with open(os.path.join(run_dir, "events.ndjson"), encoding="utf-8") as handle:
            sys.stdout.write("".join(handle.readlines()[-max(1, args.lines):]))
        return 0
    if args.command == "answer":
        cached = os.path.isfile(os.path.join(run_dir, "answer.md"))
        if state.get("state") in EXITS and not cached:
            with claim(os.path.join(run_dir, "refresh")):
                state = support.read_state_file(run_dir)
                fetch_answer(state)
                publish(state)
            cached = os.path.isfile(os.path.join(run_dir, "answer.md"))
        if state.get("state") not in EXITS or not cached:
            fallback = [*(state.get("paseo_argv") or ["paseo"]), "logs", state.get("agent_id") or "<agent-id>",
                        "--filter", "assistant_message", "--tail", "1"]
            fail(f"final assistant text unavailable ({state['state']}); logs argv: {json.dumps(fallback)}")
        with open(os.path.join(run_dir, "answer.md"), encoding="utf-8") as handle:
            sys.stdout.write(handle.read())
    else:
        print(json.dumps(state, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, OSError) as error:
        print(f"paseo-run: {error}", file=sys.stderr)
        sys.exit(1)
