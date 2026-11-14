#!/usr/bin/env python3
"""Append-only ledger for goal-driven delivery increments.

Records where each increment is (stage, shas, rounds, next action) so a fresh
session can resume without archaeology in prompt files.

Usage:
    delivery-state.py append --repo PATH --goal 0041 --stage implement \\
        --base abc1234 --head def5678 --next review
    delivery-state.py show --repo PATH --goal 0041
    delivery-state.py list

`show` also rewrites <task_root>/<date>/<repo>-<goal>/state.md with the printed
block. Facts in LIVE are measured (git/gh/run state), never inferred; a failing
command prints `unknown (<reason>)`.

Environment:
    GDD_STATE_FILE  ledger path       (default ${XDG_STATE_HOME:-$HOME/.local/state}/gdd/ledger.tsv)
    GDD_TASK_ROOT   task/state root   (default ${XDG_STATE_HOME:-$HOME/.local/state}/gdd/tasks)
    GDD_RUN_ROOT    launcher run root (default ${XDG_STATE_HOME:-$HOME/.local/state}/gdd/runs)
    GDD_REPO_ROOT   optional root used to resolve a bare repo name

Run discovery: a run dir is any directory holding state.json under
<run_root>/<date>/<name>/, <task_root>/<date>/runs/<name>/,
<task_root>/<date>/omp-runs/<name>/ or the legacy
<task_root>/<date>/<repo>-<goal>/... layout. A run whose state.json says
`running` but whose lock file names a dead process is reported as `stale lock`,
never as `running`.

Launcher contract (read side only; this tool never starts a run):
    <launcher> start --name SLUG --prompt FILE [--cwd DIR] [--model M] [--thinking L] [--max-time D]
    <launcher> status SLUG | result SLUG | answer SLUG | kill SLUG
Each run dir holds state.json with at least
{"name","state","exit","cwd","started","ended","duration_s"} (state in
running|done|killed|failed) and answer.md with the final assistant text.
"""

import argparse
import glob
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

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

COLUMNS = [
    "ts",
    "repo",
    "goal",
    "stage",
    "base_sha",
    "head_sha",
    "pr",
    "gates",
    "rounds_simplify",
    "rounds_review",
    "findings",
    "next_action",
    "note",
]


def xdg_state_home():
    return os.environ.get("XDG_STATE_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "state"
    )


def env_path(name, *fallback):
    value = os.environ.get(name)
    if value:
        return os.path.expanduser(value)
    return os.path.join(xdg_state_home(), *fallback)


DEFAULT_STATE = env_path("GDD_STATE_FILE", "gdd", "ledger.tsv")
DEFAULT_TASK_ROOT = env_path("GDD_TASK_ROOT", "gdd", "tasks")
DEFAULT_RUN_ROOT = env_path("GDD_RUN_ROOT", "gdd", "runs")
DEFAULT_REPO_ROOT = os.environ.get("GDD_REPO_ROOT") or ""


def clean(value):
    """TSV-safe cell; empty/None becomes '-'."""
    if value is None:
        return "-"
    text = str(value).replace("\t", " ").replace("\r", " ").replace("\n", " ").strip()
    return text or "-"


def stage_type(value):
    if value not in STAGES:
        raise argparse.ArgumentTypeError(
            f"invalid stage {value!r}; expected one of: {', '.join(STAGES)}"
        )
    return value


def normalize_repo(value):
    """PATH_OR_NAME -> short repo name (git toplevel basename when possible)."""
    path = os.path.expanduser(value)
    if os.path.isdir(path):
        try:
            out = subprocess.run(
                ["git", "-C", path, "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
            )
            if out.returncode == 0 and out.stdout.strip():
                return os.path.basename(out.stdout.strip())
        except OSError:
            pass
        return os.path.basename(os.path.abspath(path))
    if DEFAULT_REPO_ROOT:
        candidate = os.path.join(os.path.expanduser(DEFAULT_REPO_ROOT), value)
        if os.path.isdir(candidate):
            return os.path.basename(os.path.abspath(candidate))
    return value


def resolve_repo_path(repo):
    """Repo path or name -> directory, or None with a reason."""
    path = os.path.expanduser(repo)
    if os.path.isdir(path):
        return os.path.realpath(path), None
    if DEFAULT_REPO_ROOT:
        candidate = os.path.join(os.path.expanduser(DEFAULT_REPO_ROOT), repo)
        if os.path.isdir(candidate):
            return os.path.realpath(candidate), None
    return None, f"repo not found: {repo}"


def run(cmd, cwd=None):
    """(ok, stdout, reason)."""
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    except OSError as exc:
        return False, "", str(exc)
    if proc.returncode != 0:
        reason = (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()
        return False, "", reason.splitlines()[0] if reason else f"exit {proc.returncode}"
    return True, proc.stdout.strip(), None


def read_rows(state_file):
    if not os.path.exists(state_file):
        return []
    rows = []
    with open(state_file, encoding="utf-8") as handle:
        for index, line in enumerate(handle):
            line = line.rstrip("\n")
            if not line:
                continue
            if index == 0 and line.split("\t") == COLUMNS:
                continue
            cells = line.split("\t")
            cells += ["-"] * (len(COLUMNS) - len(cells))
            rows.append(dict(zip(COLUMNS, cells[: len(COLUMNS)])))
    return rows


def write_header_if_missing(state_file):
    if os.path.exists(state_file) and os.path.getsize(state_file) > 0:
        return
    parent = os.path.dirname(os.path.abspath(state_file))
    os.makedirs(parent, exist_ok=True)
    with open(state_file, "a", encoding="utf-8") as handle:
        handle.write("\t".join(COLUMNS) + "\n")


def cmd_append(args):
    values = {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "repo": normalize_repo(args.repo),
        "goal": args.goal,
        "stage": args.stage,
        "base_sha": args.base,
        "head_sha": args.head,
        "pr": args.pr,
        "gates": args.gates,
        "rounds_simplify": args.rounds_simplify,
        "rounds_review": args.rounds_review,
        "findings": args.findings,
        "next_action": args.next,
        "note": args.note,
    }
    write_header_if_missing(args.state_file)
    with open(args.state_file, "a", encoding="utf-8") as handle:
        handle.write("\t".join(clean(values[column]) for column in COLUMNS) + "\n")
    print(f"appended: {args.state_file}")
    return 0


def unknown(reason):
    return f"unknown ({reason})"


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
                return (
                    {
                        "pid": data.get("pid"),
                        "agent_pid": data.get("agent_pid"),
                        "tmux": data.get("tmux"),
                    },
                    True,
                )
            return None, True
        try:
            return {"pid": int(raw.split()[0]), "agent_pid": None, "tmux": None}, True
        except (ValueError, IndexError):
            return None, True
    return None, False


def pid_alive(pid):
    """True/False, or None when the pid is unusable.

    Windows needs a process query rather than os.kill(pid, 0): measured on Windows 11,
    os.kill on a live console process raises (a live run read as `stale lock`) and on
    an exited one whose handle is still open it succeeds (a dead run read as live).
    Keep in step with gdd.py and adapters/omp-run.py.
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    if os.name == "nt":
        import ctypes

        SYNCHRONIZE = 0x00100000
        QUERY_LIMITED = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(SYNCHRONIZE | QUERY_LIMITED, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return None
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
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


def recorded_lock(state):
    """Launcher identity from state.json, for launchers that never write a lock file.

    omp-run.sh records `pid` (null under tmux) and `tmux` in state.json but writes no lock, so
    `read_lock` found nothing and a run that died kept reading as "running" until the 6h deadline.
    Both adapters also record the agent's own pid, and the agent can outlive its runner.
    """
    text = state or {}
    pid, agent_pid, tmux = text.get("pid"), text.get("agent_pid"), text.get("tmux")
    if not pid and not agent_pid and not tmux:
        return None, False
    return {"pid": pid, "agent_pid": agent_pid, "tmux": tmux}, True


def effective_state(run_dir, state):
    """Recorded run state, with `stale lock` for a lock whose processes are gone.

    Same rule as gdd.py: live while either the runner or the agent is alive, and
    "starting" rather than stale while a pidless run is inside the grace window.
    """
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
    verdicts = [pid_alive(lock.get("pid")), pid_alive(lock.get("agent_pid"))]
    if any(verdict is True for verdict in verdicts):
        return "running"
    if all(verdict is None for verdict in verdicts):
        alive = tmux_alive(lock.get("tmux"))
        if alive is None:
            return "running" if run_is_young(state) else "stale lock"
        return "running" if alive else "stale lock"
    return "stale lock"


def startup_grace_seconds():
    """The launcher's OMP_RUN_START_GRACE_SECONDS, so both sides agree on "starting"."""
    try:
        value = float((os.environ.get("OMP_RUN_START_GRACE_SECONDS") or "").strip())
    except ValueError:
        return 60.0
    return value if value > 0 else 60.0


def run_is_young(state):
    """Was this run started inside the grace window (so it may still be claiming a pid)?"""
    started = (state or {}).get("started")
    if not started:
        return False
    try:
        age = (
            datetime.now(timezone.utc) - datetime.fromisoformat(str(started))
        ).total_seconds()
    except ValueError:
        return False
    return age < startup_grace_seconds()


def run_state_paths(task_root, run_root):
    """state.json candidates across the canonical and legacy run layouts."""
    patterns = [
        os.path.join(run_root, "*", "*", "state.json"),
        os.path.join(task_root, "*", "*", "state.json"),
        os.path.join(task_root, "*", "runs", "*", "state.json"),
        os.path.join(task_root, "*", "omp-runs", "*", "state.json"),
        os.path.join(task_root, "*", "*-*", "*", "state.json"),
        os.path.join(task_root, "*", "*-*", "*", "*", "state.json"),
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


def live_facts(repo, goal, task_root, run_root, path_hint=None):
    facts = []
    path = None
    reason = None
    if path_hint:
        candidate = os.path.expanduser(path_hint)
        if os.path.isdir(candidate):
            path = os.path.realpath(candidate)
    if path is None:
        path, reason = resolve_repo_path(repo)
    if path is None:
        for key in (
            "branch",
            "head",
            "ahead_of_origin_main",
            "behind_origin_main",
            "base_is_origin_main",
            "dirty_files",
            "open_pr",
            "last_run",
        ):
            facts.append(f"{key}: {unknown(reason)}")
        return facts

    ok, branch, why = run(["git", "-C", path, "rev-parse", "--abbrev-ref", "HEAD"])
    if not ok:
        branch = unknown(why)
    facts.append(f"branch: {branch}")

    ok, head, why = run(["git", "-C", path, "rev-parse", "--short=7", "HEAD"])
    facts.append(f"head: {head if ok else unknown(why)}")

    ok, ahead, why = run(
        ["git", "-C", path, "rev-list", "--count", "origin/main..HEAD"]
    )
    facts.append(f"ahead_of_origin_main: {ahead if ok else unknown(why)}")

    ok, behind, why = run(
        ["git", "-C", path, "rev-list", "--count", "HEAD..origin/main"]
    )
    facts.append(f"behind_origin_main: {behind if ok else unknown(why)}")

    ok, merge_base, why = run(["git", "-C", path, "merge-base", "HEAD", "origin/main"])
    if not ok:
        facts.append(f"base_is_origin_main: {unknown(why)}")
    else:
        ok, origin_main, why = run(["git", "-C", path, "rev-parse", "origin/main"])
        if not ok:
            facts.append(f"base_is_origin_main: {unknown(why)}")
        else:
            facts.append(
                f"base_is_origin_main: {'yes' if merge_base == origin_main else 'no'}"
            )

    ok, status, why = run(["git", "-C", path, "status", "--porcelain"])
    if ok:
        dirty = len([line for line in status.splitlines() if line.strip()])
        facts.append(f"dirty_files: {dirty}")
    else:
        facts.append(f"dirty_files: {unknown(why)}")

    if branch.startswith("unknown (") or branch == "HEAD":
        facts.append(f"open_pr: {unknown('detached HEAD')}")
    else:
        ok, out, why = run(
            [
                "gh",
                "pr",
                "list",
                "--head",
                branch,
                "--json",
                "number,state",
            ],
            cwd=path,
        )
        if not ok:
            facts.append(f"open_pr: {unknown(why)}")
        else:
            try:
                prs = json.loads(out or "[]")
                facts.append(
                    "open_pr: "
                    + (
                        ", ".join(f"#{pr['number']} {pr.get('state', '?')}" for pr in prs)
                        if prs
                        else "none"
                    )
                )
            except (ValueError, KeyError, TypeError) as exc:
                facts.append(f"open_pr: {unknown(f'unparsable gh output: {exc}')}")

    candidates = []
    try:
        for state_path in run_state_paths(task_root, run_root):
            try:
                with open(state_path, encoding="utf-8") as handle:
                    state = json.load(handle)
            except (OSError, ValueError):
                continue
            cwd = state.get("cwd")
            if not cwd:
                continue
            if os.path.realpath(os.path.expanduser(cwd)) != path:
                continue
            run_dir = os.path.dirname(state_path)
            name = str(state.get("name") or os.path.basename(run_dir))
            try:
                mtime = os.path.getmtime(state_path)
            except OSError:
                mtime = 0
            candidates.append((mtime, name, state, run_dir))
    except OSError as exc:
        facts.append(f"last_run: {unknown(exc)}")
    else:
        if not candidates:
            facts.append("last_run: none (no runs for this repo)")
        else:
            goal_matches = [c for c in candidates if goal.lower() in c[1].lower()]
            _, name, state, run_dir = max(goal_matches or candidates, key=lambda c: c[0])
            exit_code = state.get("exit")
            duration = state.get("duration_s")
            facts.append(
                "last_run: {} {} exit={} dur={}".format(
                    name,
                    effective_state(run_dir, state),
                    "-" if exit_code is None else exit_code,
                    "-" if duration is None else duration,
                )
            )
    return facts


def cmd_show(args):
    rows = read_rows(args.state_file)
    repo_filter = normalize_repo(args.repo) if args.repo else None

    matching = []
    for row in rows:
        if row["goal"] != args.goal:
            continue
        if repo_filter and row["repo"] != repo_filter:
            continue
        matching.append(row)

    if repo_filter:
        repo = repo_filter
    elif matching:
        repo = matching[-1]["repo"]
    else:
        repo = None

    latest = matching[-1] if matching else None
    lines = ["LATEST"]
    if latest:
        for column in COLUMNS:
            lines.append(f"{column}: {latest[column] or '-'}")
    else:
        lines.append("no rows")

    lines.append("")
    lines.append("HISTORY")
    for row in matching:
        sha = row["head_sha"] if row["head_sha"] != "-" else row["base_sha"]
        sha7 = sha[:7] if sha != "-" else "-"
        lines.append(
            f"{row['ts']} {row['stage']} {sha7} {row['next_action']} {row['note']}"
        )

    lines.append("")
    lines.append("LIVE")
    if repo:
        lines.extend(
            live_facts(repo, args.goal, args.task_root, args.run_root, args.repo)
        )
    else:
        lines.append("repo: unknown (no rows and no --repo)")

    block = "\n".join(lines)
    print(block)

    if not repo:
        print("state_md: -")
        return 0

    state_md = os.path.join(
        args.task_root,
        datetime.now().strftime("%Y-%m-%d"),
        f"{repo}-{args.goal}",
        "state.md",
    )
    try:
        os.makedirs(os.path.dirname(state_md), exist_ok=True)
        with open(state_md, "w", encoding="utf-8") as handle:
            handle.write(block + "\n")
    except OSError as exc:
        print(f"state_md: error: {exc}", file=sys.stderr)
        return 1
    print(f"state_md: {state_md}")
    return 0


def human_age(ts):
    try:
        moment = datetime.fromisoformat(ts)
    except ValueError:
        return "?"
    if moment.tzinfo is None:
        moment = moment.astimezone()
    seconds = (datetime.now(moment.tzinfo) - moment).total_seconds()
    if seconds < 0:
        seconds = 0
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    if seconds < 86400:
        return f"{seconds / 3600:.1f}h"
    return f"{seconds / 86400:.1f}d"


def cmd_list(args):
    rows = read_rows(args.state_file)
    newest = {}
    for row in rows:
        newest[(row["repo"], row["goal"])] = row
    for (repo, goal), row in sorted(newest.items()):
        print(
            f"{repo} {goal} {row['stage']} {human_age(row['ts'])} {row['next_action']}"
        )
    return 0


EPILOG = """\
Environment:
  GDD_STATE_FILE  ledger path        (default ${XDG_STATE_HOME:-$HOME/.local/state}/gdd/ledger.tsv)
  GDD_TASK_ROOT   task/state root    (default ${XDG_STATE_HOME:-$HOME/.local/state}/gdd/tasks)
  GDD_RUN_ROOT    launcher run root  (default ${XDG_STATE_HOME:-$HOME/.local/state}/gdd/runs)
  GDD_REPO_ROOT   optional root used to resolve a bare repo name

Run discovery covers <run_root>/<date>/<name>/, <task_root>/<date>/runs/<name>/,
<task_root>/<date>/omp-runs/<name>/ and <task_root>/<date>/<repo>-<goal>/... .
A `running` state.json whose lock file names a dead process prints `stale lock`.

Launcher contract (read side only; this tool never starts a run):
  <launcher> start --name SLUG --prompt FILE [--cwd DIR] [--model M] [--thinking L] [--max-time D]
  <launcher> status SLUG | result SLUG | answer SLUG | kill SLUG
Each run dir holds state.json ({"name","state","exit","cwd","started","ended",
"duration_s"}) and answer.md with the final assistant text.
"""


def build_parser():
    parser = argparse.ArgumentParser(
        description="Append-only ledger for goal-driven delivery increments.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    append = sub.add_parser("append", help="append one ledger row")
    append.add_argument("--repo", required=True, help="repo path or name")
    append.add_argument("--goal", required=True, help="goal / increment id")
    append.add_argument("--stage", required=True, type=stage_type)
    append.add_argument("--base", default=None, help="base sha")
    append.add_argument("--head", default=None, help="head sha")
    append.add_argument("--pr", default=None, help="PR number")
    append.add_argument("--gates", default=None, help="gate summary")
    append.add_argument("--rounds-simplify", default=None, help="simplify rounds")
    append.add_argument("--rounds-review", default=None, help="review rounds")
    append.add_argument("--findings", default=None, help="findings file/summary")
    append.add_argument("--next", default=None, help="next action")
    append.add_argument("--note", default=None, help="free-form note")
    append.add_argument("--state-file", default=DEFAULT_STATE)
    append.set_defaults(func=cmd_append)

    show = sub.add_parser("show", help="print latest/history/live for one goal")
    show.add_argument("--goal", required=True)
    show.add_argument("--repo", default=None, help="filter by repo path or name")
    show.add_argument("--state-file", default=DEFAULT_STATE)
    show.add_argument("--task-root", default=DEFAULT_TASK_ROOT)
    show.add_argument("--run-root", default=DEFAULT_RUN_ROOT)
    show.set_defaults(func=cmd_show)

    listing = sub.add_parser("list", help="one line per (repo, goal)")
    listing.add_argument("--state-file", default=DEFAULT_STATE)
    listing.set_defaults(func=cmd_list)
    return parser


def main():
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
