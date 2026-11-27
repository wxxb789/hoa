#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
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

Run discovery: a run dir is <run_root>/<date>/<name>/ holding state.json. A run
whose state.json says `running` but whose runner and agent pids are both gone
(past the startup grace) is reported as `stale`, never as `running`.

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
import re
import sys
import time
from datetime import datetime, timezone
from functools import partial

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.dont_write_bytecode = True  # no __pycache__ inside an installed skill
import agent_run
import gdd_process
from repo_identity import normalize_repo as _normalize_repo

STAGES = [
    "setup",
    "contract",
    "implement",
    "verify",
    "simplify",
    "apply",
    "review",
    "fix",
    "commit",
    "gates",
    "pr",
    "babysit",
    "merge",
    "done",
    "blocked",
]

AGENT_STAGES = {"implement", "simplify", "apply", "review", "fix"}
RECORD_STAGES = {"setup", "commit"}

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
normalize_repo = partial(_normalize_repo, default_root=DEFAULT_REPO_ROOT)


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
        proc = gdd_process.run(cmd, cwd=cwd, capture_output=True, text=True)
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
    try:
        os.makedirs(os.path.dirname(os.path.abspath(args.state_file)), exist_ok=True)
        with open(args.state_file + ".lock", "a+b") as lock:
            deadline = time.monotonic() + 2
            while not gdd_process.try_file_lock(lock):
                if time.monotonic() >= deadline:
                    print(f"delivery-state: timed out locking ledger {args.state_file}", file=sys.stderr)
                    return 1
                time.sleep(0.05)
            with open(args.state_file, "a", encoding="utf-8") as handle:
                if not handle.tell():
                    handle.write("\t".join(COLUMNS) + "\n")
                handle.write("\t".join(clean(values[column]) for column in COLUMNS) + "\n")
    except OSError as exc:
        print(f"delivery-state: could not append to {args.state_file}: {exc}", file=sys.stderr)
        return 1
    print(f"appended: {args.state_file}")
    return 0


def unknown(reason):
    return f"unknown ({reason})"


def resolved_path(value):
    """realpath of one recorded path, or None when the value is unusable."""
    if not isinstance(value, str):
        return None
    try:
        return os.path.realpath(os.path.expanduser(value))
    except (OSError, ValueError):
        return None


def aware_start(value):
    """The UTC instant a run's `started` names, or None when it is not aware ISO-8601."""
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    if moment.tzinfo is None or moment.utcoffset() is None:
        return None
    return moment.astimezone(timezone.utc)


def attributable_lineage(run_dir, goal):
    """True when lineage.json names exactly this goal for an agent stage."""
    lineage = agent_run.read_json(os.path.join(run_dir, "lineage.json"), None)
    if not isinstance(lineage, dict):
        return False
    return lineage.get("goal") == goal and lineage.get("stage") in AGENT_STAGES


def live_facts(repo, goal, run_root, path_hint=None):
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
        ):
            facts.append(f"{key}: {unknown(reason)}")
        facts.append("last_run: unknown (repo path unavailable)")
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
        state_paths = glob.glob(os.path.join(run_root, "*", "*", "state.json"))
    except OSError as exc:
        facts.append(f"last_run: {unknown(exc)}")
    else:
        for state_path in state_paths:
            run_dir = os.path.dirname(state_path)
            name = os.path.basename(run_dir)
            date_dir = os.path.basename(os.path.dirname(run_dir))
            if ".prev-" in name or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", date_dir):
                continue
            state = agent_run.read_state(run_dir)
            if not state or state.get("name") != name:
                continue
            if resolved_path(state.get("cwd")) != path:
                continue
            if not attributable_lineage(run_dir, goal):
                continue
            started = aware_start(state.get("started"))
            if started is None:
                continue
            candidates.append((started, date_dir, name, state, run_dir))
        if not candidates:
            facts.append("last_run: none (no attributable runs for this repo and goal)")
        else:
            _, _, name, state, run_dir = max(candidates, key=lambda c: (c[0], c[1], c[2]))
            exit_code = state.get("exit")
            duration = state.get("duration_s")
            observed = agent_run.observed_state(run_dir, state)
            if observed not in agent_run.STATES + ("stale",):
                observed = "unknown"
            facts.append(
                "last_run: {} {} exit={} dur={}".format(
                    name,
                    observed,
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

    latest = matching[-1] if matching else None
    # A setup or commit row is a record, not work: an earlier actionable row keeps LATEST so the
    # operator still sees the stage and next action to resume.
    actionable = [row for row in matching if row["stage"] not in RECORD_STAGES]
    if actionable:
        latest = actionable[-1]

    # LIVE and the state snapshot path follow the row LATEST came from, so a later record
    # for another repo cannot mix a different repo's context into this view.
    if repo_filter:
        repo = repo_filter
    else:
        repo = latest["repo"] if latest else None

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
            live_facts(repo, args.goal, args.run_root, args.repo)
        )
    else:
        lines.append("repo: unknown (no rows and no --repo)")
        lines.append("last_run: unknown (repo path unavailable)")

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
        key = (row["repo"], row["goal"])
        current = newest.get(key)
        if current is None or row["stage"] not in RECORD_STAGES or current["stage"] in RECORD_STAGES:
            newest[key] = row
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

Run discovery covers <run_root>/<date>/<name>/. A `running` state.json whose
runner and agent pids are both gone prints `stale`.

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
