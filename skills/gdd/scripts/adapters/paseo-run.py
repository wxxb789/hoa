#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Native Paseo launcher: start|status|result|answer|kill|list (stdlib only)."""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager, suppress
from datetime import datetime
from pathlib import Path

ADAPTER = os.path.abspath(__file__)
sys.path.insert(0, os.path.dirname(os.path.dirname(ADAPTER)))
sys.dont_write_bytecode = True  # no __pycache__ inside an installed skill
import agent_run as support
import gdd_process
import stage_result

STATES = {"initializing": "running", "running": "running", "idle": "done",
          "error": "failed", "closed": "killed"}
EXITS = {"done": 0, "failed": 1, "killed": 143}
CLI_TIMEOUT_SECONDS = 60
CLAIM_WAIT_SECONDS = CLI_TIMEOUT_SECONDS / 2


class ClaimTimeout(RuntimeError):
    """The claim is unavailable, not evidence that the native run ended."""


def configured_command():
    value = os.environ.get("PASEO_BIN") or "paseo"
    if value.lstrip().startswith("["):
        try:
            prefix = json.loads(value)
        except ValueError:
            raise RuntimeError("PASEO_BIN must be an executable path or a JSON argv array")
        if not isinstance(prefix, list) or not prefix or any(
                not isinstance(part, str) or not part for part in prefix):
            raise RuntimeError("PASEO_BIN JSON argv must be a non-empty array of non-empty strings")
    else:
        prefix = [value]
    binary = os.path.expanduser(prefix[0])
    binary = binary if os.path.dirname(binary) else shutil.which(binary)
    if not binary or not os.path.isfile(binary):
        raise RuntimeError(f"PASEO_BIN is not an executable on PATH: {prefix[0]}")
    return [os.path.abspath(binary), *prefix[1:]]


def command_argv(prefix, argv):
    args = [*prefix[1:], *argv]
    if hazard := support.shim_hazard(prefix[0], args):
        raise RuntimeError(f"{hazard}; configure PASEO_BIN as a JSON argv array naming the real executable "
                           "and CLI entrypoint (no shell)")
    return [*support.command_prefix(prefix[0]), *args]


def text_file(run_dir, name, text):
    Path(run_dir, name).write_text(text, encoding="utf-8", newline="")


@contextmanager
def claim(path):
    """Keep the inode in place so every reader competes for the same kernel lock."""
    deadline = time.monotonic() + CLAIM_WAIT_SECONDS
    with open(path, "a+b") as handle:
        while not gdd_process.try_file_lock(handle):
            if time.monotonic() >= deadline:
                raise ClaimTimeout(f"cannot acquire claim: {path}")
            time.sleep(0.05)
        yield


def cli(state, argv):
    command = command_argv(state["paseo_argv"], argv)
    dispatch = argv[0] == "run"
    # These caller identities override --cwd in Paseo 0.15.4.
    scrub = ("PASEO_AGENT_ID", "PASEO_WORKSPACE_ID") if dispatch else ()
    environment = {key: value for key, value in os.environ.items() if key not in scrub}
    cwd, run_dir = state["cwd"], state["run_dir"]
    try:
        result = gdd_process.run(command, cwd=cwd if dispatch or os.path.isdir(cwd) else run_dir,
                                 capture_output=True, text=True, timeout=CLI_TIMEOUT_SECONDS, env=environment)
        code, stdout, stderr = result.returncode, result.stdout, result.stderr
    except (OSError, subprocess.TimeoutExpired) as exc:
        code, stdout, stderr = -1, "", str(exc)
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
        raise RuntimeError(f"paseo {' '.join(argv[:2])}: exit {code}: {stderr.strip() or stdout.strip()}")
    try:
        return json.loads(stdout)
    except ValueError:
        raise RuntimeError(f"paseo {argv[0]} returned invalid JSON (see cli.ndjson)")


def answer_argv(agent_id):
    return ["logs", agent_id, "--filter", "assistant_message", "--tail", "1"]


def fetch_answer(state, provisional=False):
    argv = answer_argv(state["agent_id"])
    code, stdout, _ = cli(state, argv)
    available = code == 0 and stdout.strip() not in ("", "No activity to display.")
    state["answer_available"] = available
    state["answer_argv"] = [*state["paseo_argv"], *argv]
    if available:
        text_file(state["run_dir"], "answer.partial.md" if provisional else "answer.md", stdout)


def publish(state):
    support.write_json(os.path.join(state["run_dir"], "state.json"), state)


def cwd_matches(actual, requested):
    return (isinstance(actual, str) and bool(actual.strip()) and
            os.path.normcase(os.path.realpath(actual)) == os.path.normcase(os.path.realpath(requested)))


def finalize(state):
    run_dir = state["run_dir"]
    if schema := state.get("result_schema"):
        text = ""
        with suppress(OSError):
            text = Path(run_dir, "answer.md").read_text(encoding="utf-8")
        state.update(stage_result.record(run_dir, text, None, schema))
    state.update(ended=support.now_iso(), duration_s=round(support.state_age_seconds(state), 1))
    exit_text = f"{state['exit']}\n"
    text_file(run_dir, "exit.code", exit_text)
    publish(state)
    text_file(run_dir, "finalized", exit_text)


def refresh_locked(run_dir):
    state = support.read_state(run_dir)
    if state.get("backend") != "paseo":
        return {"name": os.path.basename(run_dir), "state": "unknown", "exit": None,
                "error": "missing or non-Paseo state.json"}
    if os.path.exists(os.path.join(run_dir, "finalized")):
        return state
    previous = state.get("state"), state.get("paseo_status")
    try:
        agent = json_cli(state, ["inspect", state["agent_id"], "--json"])
        if not isinstance(agent, dict) or agent.get("Id") != state["agent_id"]:
            raise RuntimeError("missing or mismatched agent in inspect response")
        if not state.get("cwd_verified"):
            state["reported_cwd"] = agent.get("Cwd")
            if not cwd_matches(state["reported_cwd"], state["cwd"]):
                raise RuntimeError(state.get("cwd_error") or "inspect did not verify the requested cwd; dispatch provenance is unknown")
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
        state = refresh_locked(run_dir)
    if os.path.exists(os.path.join(run_dir, "finalized")):
        support.cleanup_supervisor(run_dir, state)
    return state


def find_run(name):
    if os.path.isdir(name):
        return os.path.abspath(name)
    slug = support.sanitize(name)
    if not slug:
        raise RuntimeError("empty run name")
    paths = sorted(glob.glob(os.path.join(support.run_root(), "*", glob.escape(slug))), reverse=True)
    if path := next(filter(os.path.isdir, paths), None):
        return path
    raise RuntimeError(f"no recorded run: {name}")


def start(args):
    if args.max_time:
        raise RuntimeError("--max-time is unsupported by paseo; --wait-timeout does not stop execution")
    slug = support.sanitize(args.name)
    if not slug:
        raise RuntimeError("empty run name after sanitizing")
    prefix = configured_command()
    cwd = os.path.abspath(os.path.expanduser(args.cwd))
    if not os.path.isdir(cwd):
        raise RuntimeError(f"not a working directory: {cwd}")
    with open(args.prompt, encoding="utf-8") as handle:
        prompt = handle.read()
    if not prompt.strip():
        raise RuntimeError("empty prompt")
    schema = args.schema and os.path.abspath(os.path.expanduser(args.schema))
    if schema and not isinstance(support.read_json(schema), dict):
        raise RuntimeError(f"--schema {schema} is not a readable JSON object")
    # Refuse unsafe shim input before making a claim or dispatching.
    command_argv(prefix, ["run", "--cwd", cwd, "--", prompt])
    root = support.run_root()
    run_dir = str(Path(root) / datetime.now().strftime("%Y-%m-%d") / slug)
    support.warn_wsl(prefix[0], run_dir)
    for arg in prefix[1:]:
        if Path(arg).suffix.lower() == ".exe":
            support.warn_wsl(arg, run_dir=None)
    mode, launcher = support.select_detach(support.detach_config())
    with support.slug_start_lock(root, slug):
        return start_locked(args, slug, prefix, cwd, prompt, schema, run_dir, mode, launcher)


def start_locked(args, slug, prefix, cwd, prompt, schema, run_dir, mode, launcher):
    os.makedirs(os.path.dirname(run_dir), exist_ok=True)
    try:
        os.mkdir(run_dir)  # the slug claim
    except FileExistsError:
        raise RuntimeError(f"run already recorded: {slug}; choose a fresh stage name")
    with claim(os.path.join(run_dir, "refresh")):
        state = {"name": slug, "state": "unknown", "exit": None, "cwd": cwd, "cwd_verified": False,
                 "started": support.now_iso(), "ended": None, "duration_s": None,
                 "backend": "paseo", "launcher": ADAPTER, "agent": prefix[0],
                 "paseo_argv": prefix, "run_dir": run_dir, "pid": None, "agent_id": None,
                 "session_id": "", "model": args.model, "thinking": args.thinking,
                 "result_schema": schema}
        for file, text in (("prompt.md", prompt), ("stderr.log", ""), ("events.ndjson", "")):
            text_file(run_dir, file, text)
        publish(state)
        argv = ["run", "--no-wait", "--title", slug, "--cwd", cwd,
                *support.flags(("--provider", args.model), ("--thinking", args.thinking)), "--json", "--", prompt]
        support.write_json(os.path.join(run_dir, "run.json"),
                           {"argv": command_argv(prefix, argv), "cwd": cwd,
                            "backend": "paseo", "launcher": ADAPTER})
        try:
            result = json_cli(state, argv)
            agent_id = result.get("agentId") if isinstance(result, dict) else None
            if not isinstance(agent_id, str) or not agent_id.strip():
                raise RuntimeError("run returned no agentId; dispatch is unknown (see cli.ndjson); do not retry blindly")
            state.update(agent_id=agent_id, session_id=agent_id, state="running")
            publish(state)
            state["reported_cwd"] = result.get("cwd")
            if not cwd_matches(state["reported_cwd"], cwd):
                state["cwd_error"] = ("run returned a different cwd; dispatch provenance is unknown "
                                      "(agent identity preserved; inspect before retrying)")
                raise RuntimeError(state["cwd_error"])
            state["cwd_verified"] = True
            runner = [support.interpreter(), "-B", ADAPTER, "_watch", "--run-dir", run_dir]
            pid, flags = support.spawn_detached(runner, run_dir, run_dir, dict(os.environ),
                                               state, mode, launcher)
            state["spawn"] = {"creationflags": flags, "platform": sys.platform}
            state.update(pid=pid, pid_identity=support.identity(pid))
            publish(state)
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
            state.update(state="unknown", error=str(exc))
            publish(state)
            raise
    print(f"started: {slug}\n  backend   : paseo\n  run dir   : {run_dir}\n  agent id  : {agent_id}")
    return 0


def watch(args):
    if not support.enter_detached(args):
        return 1
    run_dir, pid, recorded = args.run_dir, os.getpid(), False
    while True:
        try:
            if not recorded:
                with claim(os.path.join(run_dir, "refresh")):
                    state = support.read_state(run_dir)
                    if state.get("pid") != pid:
                        state.update(pid=pid, pid_identity=support.identity(pid))
                        publish(state)
                recorded = True
            state = refresh(run_dir)
        except ClaimTimeout:
            # Contention is not a lifecycle update.
            state = support.read_state(run_dir)
        if state.get("state") in EXITS or os.path.exists(os.path.join(run_dir, "finalized")):
            return 0
        time.sleep(1)


def kill(run_dir):
    with claim(os.path.join(run_dir, "refresh")):
        state = refresh_locked(run_dir)
        if state.get("agent_deleted"):
            return state
        if not state.get("agent_id"):
            raise RuntimeError("kill: no recorded agent identity")
        settled = os.path.exists(os.path.join(run_dir, "finalized"))
        partial = os.path.join(run_dir, "answer.partial.md")
        if not state.get("answer_available"):
            captured = dict(state)
            fetch_answer(captured, provisional=True)
            if not settled:
                state = captured
        try:
            result = json_cli(state, ["delete", state["agent_id"], "--json"])
            # delete can exit zero even when the underlying deletion failed.
            if (not isinstance(result, dict) or type(result.get("deletedCount")) is not int
                    or result["deletedCount"] != 1 or result.get("agentIds") != [state["agent_id"]]):
                raise RuntimeError("delete did not confirm termination; agent state is not killed")
        except BaseException:
            with suppress(OSError):
                os.remove(partial)
            raise
        state.update(agent_deleted=True, termination_verb="delete", terminated_at=support.now_iso())
        if settled:
            with suppress(OSError):
                os.remove(partial)
            publish(state)
        else:
            if os.path.exists(partial):
                os.replace(partial, os.path.join(run_dir, "answer.md"))
            state.update(state="killed", exit=143, answer_partial=bool(state.get("answer_available")))
            finalize(state)
        return state


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    launch = commands.add_parser("start")
    for flag in ("--name", "--prompt"):
        launch.add_argument(flag, required=True)
    launch.add_argument("--cwd", default=os.getcwd())
    for key in ("model", "thinking"):
        launch.add_argument(f"--{key}", default=os.environ.get(f"GDD_{key.upper()}") or None)
    launch.add_argument("--max-time")
    launch.add_argument("--schema", help="stage-result schema; the answer's ```json block is checked against it")
    monitor = commands.add_parser("_watch", help=argparse.SUPPRESS)
    monitor.add_argument("--run-dir", required=True)
    support.add_detach_arguments(monitor)
    for name in ("status", "result", "answer", "kill", "tail"):
        sub = commands.add_parser(name)
        sub.add_argument("name")
        if name == "tail":
            sub.add_argument("lines", nargs="?", type=int, default=20)
    commands.add_parser("list")
    args = parser.parse_args(support.normalize_argv(sys.argv[1:] if argv is None else argv))
    if args.command == "start":
        return start(args)
    if args.command == "_watch":
        return watch(args)
    if args.command == "list":
        found = False
        for path in sorted(glob.glob(os.path.join(support.run_root(), "*", "*")), reverse=True):
            if support.read_state(path).get("backend") == "paseo":
                state = refresh(path)
                print(f"{state['name']}  {state['state']}  agent={state.get('agent_id') or '-'}")
                found = True
        if not found:
            print("(no paseo runs recorded)")
        return 0
    run_dir = find_run(args.name)
    state = kill(run_dir) if args.command == "kill" else refresh(run_dir)
    if args.command == "kill" and (problem := support.cleanup_supervisor(run_dir, state)):
        raise RuntimeError(problem)
    if args.command == "tail":
        with open(os.path.join(run_dir, "events.ndjson"), encoding="utf-8") as handle:
            sys.stdout.write("".join(handle.readlines()[-max(1, args.lines):]))
        return 0
    if args.command == "answer":
        answer = Path(run_dir, "answer.md")
        cached = os.path.isfile(answer)
        if state.get("state") in EXITS and not cached:
            with claim(os.path.join(run_dir, "refresh")):
                state = support.read_state(run_dir)
                fetch_answer(state)
                publish(state)
            cached = os.path.isfile(answer)
        if state.get("state") not in EXITS or not cached:
            fallback = [*(state.get("paseo_argv") or ["paseo"]), *answer_argv(state.get("agent_id") or "<agent-id>")]
            raise RuntimeError(f"final assistant text unavailable ({state['state']}); logs argv: {json.dumps(fallback)}")
        sys.stdout.write(answer.read_text(encoding="utf-8"))
    else:
        print(json.dumps(state, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"paseo-run: {error}", file=sys.stderr)
        sys.exit(1)
