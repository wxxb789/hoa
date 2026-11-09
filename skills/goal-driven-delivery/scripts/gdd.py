#!/usr/bin/env python3
"""Goal-driven delivery stage dispatcher.

Renders one stage prompt from a template, guards against two writers in one
worktree, records the increment in the delivery ledger, and launches a headless
agent run through a launcher adapter.

Usage:
    gdd.py stage --repo PATH --goal 0041 --stage implement
    gdd.py stage --repo PATH --goal 0041 --stage simplify --dry-run
    gdd.py stage --repo PATH --goal 0041 --stage apply --findings FILE --wait
    gdd.py status --repo PATH --goal 0041

Agent stages: implement, simplify, apply, review, fix. Every other stage is
mechanical and belongs to the orchestrator.

Environment:
    GDD_STATE_FILE  ledger path passed to delivery-state.py
                    (default ${XDG_STATE_HOME:-$HOME/.local/state}/gdd/ledger.tsv)
    GDD_TASK_ROOT   prompt/state root
                    (default ${XDG_STATE_HOME:-$HOME/.local/state}/gdd/tasks)
    GDD_RUN_ROOT    fallback run root when the launcher prints no run dir
                    (default ${XDG_STATE_HOME:-$HOME/.local/state}/gdd/runs)
    GDD_LAUNCHER    launcher command
                    (default <script dir>/adapters/omp-run.sh)
    GDD_TEMPLATES   template root
                    (default <script dir>/../references/stage-templates)
    GDD_MODEL, GDD_THINKING, GDD_MAX_TIME
                    passed to the launcher only when set; never defaulted here

Launcher contract (adapters/omp-run.sh is the reference implementation):
    <launcher> start --name SLUG --prompt FILE [--cwd DIR] [--model M] [--thinking L] [--max-time D]
    <launcher> status SLUG | result SLUG | answer SLUG | kill SLUG

The launcher owns <run_root>/<date>/<SLUG>/state.json with at least
{"name","state","exit","cwd","started","ended","duration_s"} (state is one of
running|done|killed|failed) and answer.md holding the final assistant text.
This tool polls that file and treats a missing file as unknown, never success.
"""

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime

STAGES = [
    "contract",
    "implement",
    "verify",
    "simplify",
    "apply",
    "review",
    "fix",
    "gates",
    "pr",
    "babysit",
    "merge",
    "done",
    "blocked",
]
AGENT_STAGES = {"implement", "simplify", "apply", "review", "fix"}
NEEDS_FINDINGS = {"apply", "fix"}

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DELIVERY_STATE = os.path.join(SCRIPT_DIR, "delivery-state.py")
DEFAULT_LAUNCHER = os.path.join(SCRIPT_DIR, "adapters", "omp-run.sh")
DEFAULT_TEMPLATES = os.path.normpath(
    os.path.join(SCRIPT_DIR, "..", "references", "stage-templates")
)


def fail(message, code=2):
    print(f"gdd: {message}", file=sys.stderr)
    sys.exit(code)


class LaunchError(Exception):
    """The launcher could not start the run; the ledger must not claim otherwise."""


def xdg_state_home():
    return os.environ.get("XDG_STATE_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "state"
    )


def env_path(name, *fallback):
    value = os.environ.get(name)
    if value:
        return os.path.expanduser(value)
    return os.path.join(xdg_state_home(), *fallback)


def task_root():
    return env_path("GDD_TASK_ROOT", "gdd", "tasks")


def run_root():
    return env_path("GDD_RUN_ROOT", "gdd", "runs")


def git(repo, *args):
    proc = subprocess.run(
        ["git", "-C", repo, *args], capture_output=True, text=True
    )
    if proc.returncode != 0:
        reason = (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()
        fail(f"git {' '.join(args)} failed: {reason.splitlines()[0]}")
    return proc.stdout.strip()


def validate_stage(stage):
    if stage not in STAGES:
        fail(f"invalid stage {stage!r}; expected one of: {', '.join(STAGES)}")
    if stage not in AGENT_STAGES:
        fail(
            f"stage {stage!r} is mechanical and belongs to the orchestrator, "
            f"not the agent (agent stages: {', '.join(sorted(AGENT_STAGES))})"
        )


def render(template_text, variables):
    text = template_text
    for key, value in variables.items():
        text = text.replace("${" + key + "}", str(value))
    unresolved = sorted(set(re.findall(r"\$\{([^}]+)\}", text)))
    if unresolved:
        fail("unresolved placeholders: " + ", ".join(unresolved))
    return text


def resolve_goal_file(repo, goal):
    """Contract file for a goal: active tree first, then archive, else '-'."""
    for directory in ("docs/goals", "docs/goals/archive"):
        matches = sorted(
            glob.glob(os.path.join(repo, directory, f"*{goal}*.md"))
        )
        if matches:
            return matches[0]
    return "-"


def read_lock(run_dir):
    """(lock dict or None, lock file exists). Accepts JSON or a bare pid file."""
    for name in ("lock", ".lock"):
        path = os.path.join(run_dir, name)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                raw = handle.read().strip()
        except OSError:
            return None, True
        if not raw:
            return None, True
        if raw.startswith("{"):
            try:
                data = json.loads(raw)
            except ValueError:
                return None, True
            if isinstance(data, dict):
                return {"pid": data.get("pid"), "tmux": data.get("tmux")}, True
            return None, True
        try:
            return {"pid": int(raw.split()[0]), "tmux": None}, True
        except (ValueError, IndexError):
            return None, True
    return None, False


def pid_alive(pid):
    """True/False, or None when the pid is unusable."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None
    return True


def tmux_alive(session):
    if not session:
        return None
    try:
        proc = subprocess.run(
            ["tmux", "has-session", "-t", str(session)],
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    return proc.returncode == 0


def effective_state(run_dir, state):
    """Recorded run state, with `stale lock` for a lock whose process is gone."""
    recorded = str((state or {}).get("state") or "?")
    if recorded != "running":
        return recorded
    lock, has_lock = read_lock(run_dir)
    if not has_lock:
        return recorded
    if not lock:
        return "stale lock"
    alive = pid_alive(lock.get("pid"))
    if alive is None:
        alive = tmux_alive(lock.get("tmux"))
    return "running" if alive else "stale lock"


def run_state_paths(task_root_dir, run_root_dir):
    """state.json candidates across the canonical and legacy run layouts."""
    patterns = [
        os.path.join(run_root_dir, "*", "*", "state.json"),
        os.path.join(task_root_dir, "*", "*", "state.json"),
        os.path.join(task_root_dir, "*", "runs", "*", "state.json"),
        os.path.join(task_root_dir, "*", "omp-runs", "*", "state.json"),
        os.path.join(task_root_dir, "*", "*-*", "*", "state.json"),
        os.path.join(task_root_dir, "*", "*-*", "*", "*", "state.json"),
    ]
    seen = set()
    paths = []
    for pattern in patterns:
        for path in glob.glob(pattern):
            real = os.path.realpath(path)
            if real in seen:
                continue
            seen.add(real)
            paths.append(path)
    return paths


def active_runs(repo_path):
    """(name, run_dir) for runs still alive whose cwd is repo_path."""
    active = []
    for state_path in run_state_paths(task_root(), run_root()):
        try:
            with open(state_path, encoding="utf-8") as handle:
                state = json.load(handle)
        except (OSError, ValueError):
            continue
        run_dir = os.path.dirname(state_path)
        if effective_state(run_dir, state) != "running":
            continue
        cwd = state.get("cwd")
        if not cwd:
            continue
        if os.path.realpath(os.path.expanduser(cwd)) != repo_path:
            continue
        name = state.get("name") or os.path.basename(run_dir)
        active.append((name, run_dir))
    return active


def ledger_append(repo, goal, stage, base, head, gates, next_stage=None, note=None):
    cmd = [
        sys.executable,
        DELIVERY_STATE,
        "append",
        "--repo",
        repo,
    ]
    state_file = os.environ.get("GDD_STATE_FILE")
    if state_file:
        cmd += ["--state-file", os.path.expanduser(state_file)]
    cmd += [
        "--goal",
        goal,
        "--stage",
        stage,
        "--base",
        base,
        "--head",
        head,
    ]
    if gates and gates != "-":
        cmd += ["--gates", gates]
    if next_stage:
        cmd += ["--next", next_stage]
    if note:
        cmd += ["--note", note]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        reason = (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()
        fail(f"ledger append failed: {reason}", 1)


def launch(launcher, prompt_path, repo, goal, stage, model, thinking, max_time):
    name = f"{os.path.basename(repo)}-{goal}-{stage}"
    cmd = [
        launcher,
        "start",
        "--name",
        name,
        "--prompt",
        prompt_path,
        "--cwd",
        repo,
    ]
    for flag, value in (
        ("--model", model),
        ("--thinking", thinking),
        ("--max-time", max_time),
    ):
        if value:
            cmd += [flag, str(value)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except OSError as exc:
        raise LaunchError(str(exc)) from exc
    if proc.returncode != 0:
        reason = (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()
        raise LaunchError(reason or f"exit {proc.returncode}")
    run_name = name
    run_dir = None
    for line in proc.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("started:"):
            run_name = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("run dir"):
            run_dir = stripped.split(":", 1)[1].strip()
    if not run_dir:
        run_dir = os.path.join(
            run_root(), datetime.now().strftime("%Y-%m-%d"), run_name
        )
    return run_name, run_dir


def read_state(run_dir):
    path = os.path.join(run_dir, "state.json")
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def print_answer_head(run_dir, limit=40):
    path = os.path.join(run_dir, "answer.md")
    print(f"answer: {path}")
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for index, line in enumerate(handle):
                if index >= limit:
                    break
                print(line.rstrip("\n"))
    except OSError as exc:
        print(f"answer: unknown ({exc})")


def cmd_stage(args):
    validate_stage(args.stage)
    if args.stage in NEEDS_FINDINGS:
        if not args.findings:
            fail("--findings is required for stage " + args.stage)
        if not os.path.isfile(args.findings):
            fail(f"--findings file does not exist: {args.findings}")
    elif args.findings and not os.path.isfile(args.findings):
        fail(f"--findings file does not exist: {args.findings}")

    if not os.path.isdir(args.repo):
        fail(f"--repo is not a directory: {args.repo}")
    repo = os.path.realpath(git(args.repo, "rev-parse", "--show-toplevel"))
    repo_name = os.path.basename(repo)

    templates = os.path.expanduser(
        args.templates or os.environ.get("GDD_TEMPLATES") or DEFAULT_TEMPLATES
    )
    template_path = os.path.join(templates, args.stage + ".md")
    if not os.path.isfile(template_path):
        fail(f"template not found: {template_path}")
    with open(template_path, encoding="utf-8") as handle:
        template_text = handle.read()

    goal_file = resolve_goal_file(repo, args.goal)

    if args.base:
        base = args.base
    else:
        base = git(repo, "merge-base", "origin/main", "HEAD")

    if args.head:
        head = args.head
    else:
        head = git(repo, "rev-parse", "HEAD")

    gates = args.gates or os.environ.get("GDD_GATES") or "-"
    findings = os.path.abspath(os.path.expanduser(args.findings)) if args.findings else "-"

    variables = {
        "REPO_PATH": repo,
        "REPO_NAME": repo_name,
        "GOAL": args.goal,
        "GOAL_FILE": goal_file,
        "BASE_SHA": base,
        "HEAD_SHA": head,
        "GATES": gates,
        "FINDINGS_FILE": findings,
        "DATE": datetime.now().strftime("%Y-%m-%d"),
    }
    rendered = render(template_text, variables)

    stamp = datetime.now().strftime("%H%M%S")
    prompt_dir = os.path.join(
        task_root(),
        datetime.now().strftime("%Y-%m-%d"),
        f"{repo_name}-{args.goal}",
        "prompts",
    )
    prompt_path = os.path.join(prompt_dir, f"{args.stage}-{stamp}.md")
    counter = 2
    while os.path.exists(prompt_path):
        prompt_path = os.path.join(prompt_dir, f"{args.stage}-{stamp}-{counter}.md")
        counter += 1
    os.makedirs(prompt_dir, exist_ok=True)
    with open(prompt_path, "w", encoding="utf-8") as handle:
        handle.write(rendered)
    print(f"prompt: {prompt_path}")

    if args.dry_run:
        print("----- first 5 lines -----")
        with open(prompt_path, encoding="utf-8") as handle:
            for index, line in enumerate(handle):
                if index >= 5:
                    break
                print(line.rstrip("\n"))
        return 0

    running = active_runs(repo)
    if running and not args.force:
        names = ", ".join(name for name, _ in running)
        fail(
            f"refusing to start: run(s) still active in {repo}: {names} "
            f"(use --force to override)",
            3,
        )

    try:
        run_name, run_dir = launch(
            args.launcher,
            prompt_path,
            repo,
            args.goal,
            args.stage,
            args.model,
            args.thinking,
            args.max_time,
        )
    except (LaunchError, OSError) as exc:
        message = str(exc).strip() or exc.__class__.__name__
        first_line = message.splitlines()[0]
        print(f"gdd: launch failed: {first_line}", file=sys.stderr)
        ledger_append(
            repo,
            args.goal,
            "blocked",
            base,
            head,
            gates,
            note=f"launch-failed: {first_line}",
        )
        return 3

    ledger_append(repo, args.goal, args.stage, base, head, gates, next_stage=args.stage)
    print(f"run: {run_name}")
    print(f"run_dir: {run_dir}")
    print(f"poll: {args.launcher} status {run_name}")

    if args.wait:
        deadline = time.time() + 6 * 3600
        state = None
        while True:
            state = read_state(run_dir)
            if state and effective_state(run_dir, state) != "running":
                break
            if time.time() > deadline:
                fail(f"wait: run still not finished after 6h: {run_name}", 1)
            time.sleep(30)

        exit_code = state.get("exit")
        duration = state.get("duration_s")
        note = f"exit={exit_code if exit_code is not None else '-'} dur={duration if duration is not None else '-'}"
        ledger_append(
            repo,
            args.goal,
            args.stage,
            base,
            head,
            gates,
            note=note,
        )
        print(f"finished: state={effective_state(run_dir, state)} {note}")
        print_answer_head(run_dir)
    return 0


def cmd_status(args):
    cmd = [
        sys.executable,
        DELIVERY_STATE,
        "show",
        "--repo",
        args.repo,
        "--goal",
        args.goal,
    ]
    state_file = os.environ.get("GDD_STATE_FILE")
    if state_file:
        cmd += ["--state-file", os.path.expanduser(state_file)]
    return subprocess.run(cmd).returncode


EPILOG = """\
Environment:
  GDD_STATE_FILE  ledger path passed to delivery-state.py
                  (default ${XDG_STATE_HOME:-$HOME/.local/state}/gdd/ledger.tsv)
  GDD_TASK_ROOT   prompt/state root
                  (default ${XDG_STATE_HOME:-$HOME/.local/state}/gdd/tasks)
  GDD_RUN_ROOT    fallback run root when the launcher prints no run dir
                  (default ${XDG_STATE_HOME:-$HOME/.local/state}/gdd/runs)
  GDD_LAUNCHER    launcher command (default <script dir>/adapters/omp-run.sh)
  GDD_TEMPLATES   template root (default <script dir>/../references/stage-templates)
  GDD_MODEL, GDD_THINKING, GDD_MAX_TIME
                  passed to the launcher only when set; never defaulted here

Launcher contract:
  <launcher> start --name SLUG --prompt FILE [--cwd DIR] [--model M] [--thinking L] [--max-time D]
  <launcher> status SLUG | result SLUG | answer SLUG | kill SLUG

The launcher writes <run_root>/<date>/<SLUG>/state.json with at least
{"name","state","exit","cwd","started","ended","duration_s"} and answer.md.
A missing state.json is unknown, never success.

Agent stages: implement, simplify, apply, review, fix
"""


def build_parser():
    parser = argparse.ArgumentParser(
        description="Render a stage prompt and launch one headless agent run.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    stage = sub.add_parser("stage", help="render a prompt and launch a run")
    stage.add_argument("--repo", required=True, help="repo path")
    stage.add_argument("--goal", required=True, help="goal / increment id")
    stage.add_argument("--stage", required=True)
    stage.add_argument("--base", default=None, help="base sha (default merge-base)")
    stage.add_argument("--head", default=None, help="head sha (default HEAD)")
    stage.add_argument("--findings", default=None, help="findings file (apply/fix)")
    stage.add_argument("--gates", default=None, help="gate command text")
    stage.add_argument(
        "--launcher",
        default=os.environ.get("GDD_LAUNCHER") or DEFAULT_LAUNCHER,
        help="launcher command (default: $GDD_LAUNCHER or the bundled adapter)",
    )
    stage.add_argument(
        "--model", default=os.environ.get("GDD_MODEL") or None, help="passed through only when set"
    )
    stage.add_argument(
        "--thinking", default=os.environ.get("GDD_THINKING") or None, help="passed through only when set"
    )
    stage.add_argument(
        "--max-time", default=os.environ.get("GDD_MAX_TIME") or None, help="passed through only when set"
    )
    stage.add_argument("--templates", default=None, help="template directory")
    stage.add_argument("--dry-run", action="store_true", help="render only")
    stage.add_argument("--wait", action="store_true", help="poll until the run ends")
    stage.add_argument("--force", action="store_true", help="ignore active-run guard")
    stage.set_defaults(func=cmd_stage)

    status = sub.add_parser("status", help="delegate to delivery-state.py show")
    status.add_argument("--repo", required=True)
    status.add_argument("--goal", required=True)
    status.set_defaults(func=cmd_status)
    return parser


def main():
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
