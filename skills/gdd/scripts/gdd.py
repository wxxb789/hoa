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

Environment or operator config file:
    GDD_STATE_FILE  ledger path passed to delivery-state.py
                    (default ${XDG_STATE_HOME:-$HOME/.local/state}/gdd/ledger.tsv)
    GDD_TASK_ROOT   prompt/state root
                    (default ${XDG_STATE_HOME:-$HOME/.local/state}/gdd/tasks)
    GDD_RUN_ROOT    run root exported to the launcher and used when it prints no
                    run dir (default ${XDG_STATE_HOME:-$HOME/.local/state}/gdd/runs)
    GDD_LAUNCHER    launcher command
                    (default <script dir>/adapters/omp-run.sh)
    GDD_TEMPLATES   template root
                    (default <script dir>/../references/stage-templates)
    GDD_GOAL_GLOB   goal-contract glob (default docs/goals/*<goal>*.md)
    GDD_MODEL, GDD_THINKING, GDD_MAX_TIME
                    passed to the launcher only when set; never defaulted here

The six path/command keys resolve through the shared resolver: flag, then environment,
then $XDG_CONFIG_HOME/gdd/config.yaml (fallback ~/.config/...),
then the default. The rule is owned by skill-porting-and-publishing.

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
import shlex
import subprocess
import sys
import time
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
import skill_config

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

SKILL = "gdd"
DEFAULT_GOAL_GLOB = "docs/goals/*<goal>*.md"
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


def config(key, *, flag=None, default=None):
    """Resolve one documented GDD key through the shared resolver."""
    return skill_config.resolve(SKILL, key, flag=flag, default=default)


def state_file():
    return config(
        "GDD_STATE_FILE", default=os.path.join(xdg_state_home(), "gdd", "ledger.tsv")
    )


def task_root():
    return os.path.expanduser(
        config("GDD_TASK_ROOT", default=os.path.join(xdg_state_home(), "gdd", "tasks"))
    )


def run_root():
    return os.path.expanduser(
        config("GDD_RUN_ROOT", default=os.path.join(xdg_state_home(), "gdd", "runs"))
    )


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


def resolve_ref(repo, value):
    """Full SHA for a supplied endpoint; the value unchanged when git cannot resolve it."""
    if not value:
        return value
    proc = subprocess.run(
        ["git", "-C", repo, "rev-parse", "--verify", "--quiet", str(value)],
        capture_output=True,
        text=True,
    )
    resolved = (proc.stdout or "").strip()
    return resolved if proc.returncode == 0 and resolved else value


def resolve_goal_file(repo, goal):
    """Contract file for a goal from GDD_GOAL_GLOB; '-' when nothing matches."""
    pattern = config("GDD_GOAL_GLOB", default=DEFAULT_GOAL_GLOB)
    expanded = os.path.expanduser(pattern.replace("<goal>", goal))
    matches = sorted(glob.glob(os.path.join(repo, expanded)))
    if not matches and pattern == DEFAULT_GOAL_GLOB:
        archive = os.path.join(
            "docs", "goals", "archive", os.path.basename(expanded)
        )
        matches = sorted(glob.glob(os.path.join(repo, archive)))
    return matches[0] if matches else "-"


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
        lock, has_lock = recorded_lock(state)
    if not has_lock:
        return recorded
    if not lock:
        return "stale lock"
    alive = pid_alive(lock.get("pid"))
    if alive is None:
        alive = tmux_alive(lock.get("tmux"))
    return "running" if alive else "stale lock"


def recorded_lock(state):
    """Launcher identity from state.json, for launchers that never write a lock file.

    omp-run.sh records `pid` (null under tmux) and `tmux` in state.json but writes no lock, so
    `read_lock` found nothing and a run that died kept reading as "running" until the 6h deadline.
    """
    text = state or {}
    pid, tmux = text.get("pid"), text.get("tmux")
    if not pid and not tmux:
        return None, False
    return {"pid": pid, "tmux": tmux}, True


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


NOT_READY_STATES = ("provisional", "superseded", "completed", "draft")
DIFF_STAGES = ("simplify", "apply", "review", "fix")


def goal_state_header(goal_file):
    """(state, status) words from the first 15 lines of a contract file."""
    try:
        with open(goal_file, encoding="utf-8", errors="replace") as handle:
            head_text = "".join(handle.readline() for _ in range(15))
    except OSError:
        return ""
    found = re.search(
        r"(?im)^[\s*#]*(?:state|status)[\s*]*:[*\s]*([a-z]+)", head_text
    )
    return found.group(1).lower() if found else ""


def dispatch_problems(stage, goal_file, dirty_paths, base, head, force=False):
    """Why this dispatch must not start. Pure: the caller supplies the facts."""
    if force:
        return []
    problems = []
    if stage == "implement":
        if goal_file in ("", "-"):
            problems.append(
                "no goal contract found — pass --goal that matches GDD_GOAL_GLOB, "
                "or write the contract first (phase 0)"
            )
        elif "/archive/" in goal_file.replace("\\", "/"):
            problems.append(
                f"contract {goal_file} is archived — an increment starts from an active goal"
            )
        else:
            state = goal_state_header(goal_file)
            if state in NOT_READY_STATES:
                problems.append(
                    f"contract {goal_file} declares state {state!r}; refine and activate it "
                    "in its own commit before implementing"
                )
        if dirty_paths:
            shown = ", ".join(dirty_paths[:5])
            problems.append(
                f"worktree is dirty before implement ({len(dirty_paths)} path(s): {shown}) — "
                "commit or stash it, so the increment stays attributable"
            )
    if stage in DIFF_STAGES and base and head and base == head:
        problems.append(
            f"base == head ({head[:7]}): there is no committed range to read — commit the "
            "stage output first (phase 4) or pass --base/--head explicitly"
        )
    return problems


AUTHORING_STAGES = ("implement", "apply", "fix")


def final_head_for(stage, head_supplied, head, post_head):
    """The SHA a finished-stage row should record.

    An authoring stage changed the tree, so the post-run HEAD is the increment. A report-only
    stage (review, simplify) reviewed the head it was given: when the operator supplied one, the
    checkout may have moved on and the supplied SHA is the fact worth keeping.
    """
    if head_supplied:
        return head
    if stage in AUTHORING_STAGES:
        return post_head
    return head


def ledger_append(repo, goal, stage, base, head, gates, next_stage=None, note=None, pr=None):
    cmd = [
        sys.executable,
        DELIVERY_STATE,
        "append",
        "--repo",
        repo,
    ]
    state = state_file()
    if state:
        cmd += ["--state-file", os.path.expanduser(state)]
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
    if pr:
        cmd += ["--pr", str(pr)]
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
    resolved_run_root = run_root()
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
    # The launcher resolves its run root from GDD_RUN_ROOT; export the value this
    # process resolved so a config-file run root lands where discovery looks.
    child_env = dict(os.environ)
    child_env["GDD_RUN_ROOT"] = resolved_run_root
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, env=child_env)
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
            resolved_run_root, datetime.now().strftime("%Y-%m-%d"), run_name
        )
    return run_name, run_dir, resolved_run_root


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
        config("GDD_TEMPLATES", flag=args.templates, default=DEFAULT_TEMPLATES)
    )
    launcher = os.path.expanduser(
        config("GDD_LAUNCHER", flag=args.launcher, default=DEFAULT_LAUNCHER)
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
    # Resolve supplied endpoints to commit SHAs: `--base <sha> --head HEAD` names one commit
    # twice, and a string compare would call that a non-empty range. A value git cannot resolve
    # is kept literally, so a caller may pass a SHA from another checkout.
    base = resolve_ref(repo, base)
    head = resolve_ref(repo, head)

    dirty = [
        line[3:]
        for line in git(repo, "status", "--porcelain").splitlines()
        if line.strip()
    ]
    # `GDD_DISPATCH_GUARDS=off` exists for harness fixtures that dispatch synthetic
    # goals on purpose; a real run leaves it unset.
    guard_off = os.environ.get("GDD_DISPATCH_GUARDS", "on").lower() in (
        "off",
        "0",
        "false",
        "no",
    )
    problems = [] if guard_off else dispatch_problems(
        args.stage, goal_file, dirty, base, head, force=args.force
    )
    if problems:
        for problem in problems:
            print(f"gdd: {problem}", file=sys.stderr)
        print("gdd: dispatch refused (use --force to override)", file=sys.stderr)
        return 3

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
        run_name, run_dir, launch_run_root = launch(
            launcher,
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
    print(f"poll: GDD_RUN_ROOT={shlex.quote(launch_run_root)} {launcher} status {run_name}")

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

        final_state = effective_state(run_dir, state)
        exit_code = state.get("exit")
        duration = state.get("duration_s")
        if final_state != "done":
            resume = state.get("session_id") or "?"
            fail(
                f"wait: run ended in {final_state} (exit={exit_code if exit_code is not None else '-'}) "
                f"instead of done — resume with: {launcher} start --name {run_name}-r2 "
                f"--prompt <same prompt> --resume {resume}",
                1,
            )
        post_head = git(repo, "rev-parse", "HEAD")
        final_head = final_head_for(args.stage, bool(args.head), head, post_head)
        note = (
            f"exit={exit_code if exit_code is not None else '-'} "
            f"dur={duration if duration is not None else '-'} "
            f"head={post_head[:7]}"
        )
        ledger_append(
            repo,
            args.goal,
            args.stage,
            base,
            final_head,
            gates,
            note=note,
        )
        print(f"finished: state={effective_state(run_dir, state)} {note}")
        print_answer_head(run_dir)
    return 0


def cmd_scope(args):
    """Print the resolved worktree-scope.py path (config file, not just env)."""
    resolved = os.path.expanduser(
        config(
            "GDD_WORKTREE_SCOPE",
            default="../delegated-work-acceptance/scripts/worktree-scope.py",
        )
    )
    if not os.path.isabs(resolved):
        resolved = os.path.normpath(os.path.join(os.path.dirname(SCRIPT_DIR), resolved))
    if not os.path.isfile(resolved):
        fail(f"GDD_WORKTREE_SCOPE does not resolve to a file: {resolved}", 2)
    print(resolved)
    return 0


def cmd_close(args):
    """Write the landing row: stage=done with the PR and the merged head.

    The operator used to record this by hand, and stopped: 36 ledger rows held zero
    `pr`/`done` entries, so a new session read every merged goal as still in `fix`.
    """
    if not os.path.isdir(args.repo):
        fail(f"--repo is not a directory: {args.repo}")
    repo = os.path.realpath(git(args.repo, "rev-parse", "--show-toplevel"))
    base = args.base or git(repo, "merge-base", "origin/main", "HEAD")
    head = args.head or git(repo, "rev-parse", "HEAD")
    pr = args.pr or "-"
    note = args.note or f"pr={pr} head={head[:7]}"
    ledger_append(repo, args.goal, "done", base, head, args.gates or "-", note=note, pr=pr)
    print(
        f"closed: {os.path.basename(repo)} {args.goal} pr={pr} head={head[:7]}"
    )
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
        "--state-file",
        os.path.expanduser(state_file()),
        "--task-root",
        task_root(),
        "--run-root",
        run_root(),
    ]
    return subprocess.run(cmd).returncode


EPILOG = """\
Environment or operator config file:
  GDD_STATE_FILE  ledger path passed to delivery-state.py
                  (default ${XDG_STATE_HOME:-$HOME/.local/state}/gdd/ledger.tsv)
  GDD_TASK_ROOT   prompt/state root
                  (default ${XDG_STATE_HOME:-$HOME/.local/state}/gdd/tasks)
  GDD_RUN_ROOT    run root exported to the launcher, and the fallback when it
                  prints no run dir
                  (default ${XDG_STATE_HOME:-$HOME/.local/state}/gdd/runs)
  GDD_LAUNCHER    launcher command (default <script dir>/adapters/omp-run.sh)
  GDD_TEMPLATES   template root (default <script dir>/../references/stage-templates)
  GDD_GOAL_GLOB   goal-contract glob (default docs/goals/*<goal>*.md)
  GDD_MODEL, GDD_THINKING, GDD_MAX_TIME
                  passed to the launcher only when set; never defaulted here

The six path/command keys above also resolve from
$XDG_CONFIG_HOME/gdd/config.yaml (fallback ~/.config/...).
Order: CLI flag, then environment variable, then that file, then the default.
The shared rule is documented in skill-porting-and-publishing.

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
        default=None,
        help="launcher command (default: $GDD_LAUNCHER, config file, or the bundled adapter)",
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

    scope = sub.add_parser(
        "scope", help="print the resolved worktree-scope.py path (GDD_WORKTREE_SCOPE)"
    )
    scope.set_defaults(func=cmd_scope)

    close = sub.add_parser(
        "close", help="record the landing row for a goal (stage=done, pr, merged head)"
    )
    close.add_argument("--repo", required=True)
    close.add_argument("--goal", required=True)
    close.add_argument("--pr", default=None, help="PR number")
    close.add_argument("--base", default=None, help="base sha (default merge-base)")
    close.add_argument("--head", default=None, help="merged head sha (default HEAD)")
    close.add_argument("--gates", default=None, help="gate summary")
    close.add_argument("--note", default=None, help="free-form note")
    close.set_defaults(func=cmd_close)

    status = sub.add_parser("status", help="delegate to delivery-state.py show")
    status.add_argument("--repo", required=True)
    status.add_argument("--goal", required=True)
    status.set_defaults(func=cmd_status)
    return parser


def main():
    args = build_parser().parse_args()
    try:
        return args.func(args)
    except skill_config.ConfigError as error:
        fail(str(error))


if __name__ == "__main__":
    sys.exit(main())
