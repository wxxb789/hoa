#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Run paired Claude Code trials against an outcome rubric, not a routing judge."""

import argparse
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

EVALS = Path(__file__).resolve().parent
SKILLS = EVALS.parent / "skills"
sys.path.insert(0, str(SKILLS / "gdd" / "scripts"))
import gdd_process  # noqa: E402

NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
PROFILE = {
    "HOME": "home", "USERPROFILE": "home", "CODEX_HOME": "home/.codex",
    "CLAUDE_CONFIG_DIR": "home/.claude", "APPDATA": "home/appdata/roaming",
    "LOCALAPPDATA": "home/appdata/local", "XDG_CONFIG_HOME": "home/xdg/config",
    "XDG_CACHE_HOME": "home/xdg/cache", "XDG_DATA_HOME": "home/xdg/data",
    "XDG_STATE_HOME": "home/xdg/state", "XDG_RUNTIME_DIR": "home/xdg/run",
    "XDG_CONFIG_DIRS": "home/xdg/system-config", "XDG_DATA_DIRS": "home/xdg/system-data",
    "TEMP": "tmp", "TMP": "tmp", "TMPDIR": "tmp",
}
PASSTHROUGH = {
    "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "LANG", "LC_ALL",
    "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "NODE_EXTRA_CA_CERTS", "SSL_CERT_FILE",
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
}
SKIP = {".git", "__pycache__", ".pytest_cache"}


def isolated_env(root):
    env = {key: value for key, value in os.environ.items() if key.upper() in PASSTHROUGH}
    if os.name == "nt" and os.getenv("NOWINDOW_GUARD_LOG"):
        for key in ("NOWINDOW_GUARD_LOG", "PYTHONPATH"):
            env[key] = os.environ[key]
    for key, relative in PROFILE.items():
        path = root / relative
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        env[key] = str(path)
    if os.name == "nt":
        env["HOMEDRIVE"], env["HOMEPATH"] = os.path.splitdrive(env["USERPROFILE"])
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1", CLAUDE_CODE_DISABLE_AUTO_MEMORY="1",
               CLAUDE_CODE_DISABLE_BACKGROUND_TASKS="1", CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN="1",
               DISABLE_AUTOUPDATER="1", DISABLE_TELEMETRY="1")
    return env


def snapshot(source, target, *, fixture=False):
    def ignored(directory, names):
        for name in set(names) - SKIP:
            path = Path(directory) / name
            if path.is_symlink() or path.is_junction():
                raise ValueError(f"links are not allowed in snapshots: {path}")
            if fixture and name.lower() in {".agents", ".claude", ".codex", "skill.md"}:
                raise ValueError(f"agent configuration is not allowed in fixtures: {path}")
        return SKIP.intersection(names)

    shutil.copytree(source, target, ignore=ignored)


def rubric_path(value):
    if not isinstance(value, str) or not re.fullmatch(r"[\w.-]+(?:/[\w.-]+)*", value, re.ASCII):
        raise ValueError(f"invalid rubric file path: {value!r}")
    if {".", ".."}.intersection(value.split("/")):
        raise ValueError(f"invalid rubric file path: {value!r}")
    return value


def load_task(path):
    task = json.loads(path.read_text(encoding="utf-8"))
    for key in ("id", "skill"):
        if not isinstance(task[key], str) or not NAME.fullmatch(task[key]):
            raise ValueError(f"{key} must be a kebab-case name")
    if not isinstance(task["prompt"], str) or not task["prompt"].strip():
        raise ValueError("prompt must be nonempty text")
    if not isinstance(task["rubric"], dict) or not task["rubric"]:
        raise ValueError("rubric must be a nonempty object")
    for label, check in task["rubric"].items():
        if not isinstance(check, dict) or set(check) not in ({"field", "equals"}, {"file", "contains"}):
            raise ValueError(f"{label}: expected field/equals or file/contains")
        if "file" in check:
            rubric_path(check["file"])
            if not isinstance(check["contains"], str) or not check["contains"]:
                raise ValueError(f"{label}: contains must be nonempty text")
        elif not isinstance(check["field"], str) or not check["field"]:
            raise ValueError(f"{label}: field must be nonempty text")
    fixture = path.parent / task["fixture"]
    if not fixture.is_dir() or fixture.is_symlink() or fixture.is_junction():
        raise ValueError(f"fixture must be a directory, not a link: {fixture}")
    fixture = fixture.resolve()
    if path.resolve().is_relative_to(fixture):
        raise ValueError(f"fixture would expose the task rubric to the agent: {fixture}")
    return task, fixture


def judge(rubric, output, workspace):
    try:
        answer = json.loads(output)
    except json.JSONDecodeError:
        answer = None
    artifacts = {}
    scores = {}
    for label, check in rubric.items():
        if "field" in check:
            field = check["field"]
            scores[label] = (isinstance(answer, dict) and field in answer
                             and json.dumps(answer[field], sort_keys=True)
                             == json.dumps(check["equals"], sort_keys=True))
        else:
            name = check["file"]
            path = workspace / name
            if (name not in artifacts and path.is_file() and path.resolve() == path
                    and path.stat().st_size <= 64 * 1024):
                artifacts[name] = path.read_text(encoding="utf-8", errors="replace")
            scores[label] = check["contains"] in artifacts.get(name, "")
    return scores, artifacts


def trial(args, task, fixture, root, with_skill):
    env = isolated_env(root)
    workspace = root / "work"
    snapshot(fixture, workspace, fixture=True)
    installed = Path(env["CLAUDE_CONFIG_DIR"]) / "skills"
    installed.mkdir()
    if with_skill:
        snapshot(SKILLS / task["skill"], installed / task["skill"])
    tools = "Read,Glob,Skill" + (",Write" if args.acceptance else "")
    command = [str(args.claude), "-p", "--output-format", "stream-json", "--verbose",
               "--restricted", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
               "--setting-sources", "user", "--no-session-persistence", "--no-chrome",
               "--tools", tools, "--permission-prompts", "none", "--permission-mode",
               "acceptEdits" if args.acceptance else "dontAsk", "--add-dir", str(installed),
               "--model", args.model, "--effort", "low", "--max-turns", str(args.max_turns),
               "--max-budget-usd", str(args.max_budget_usd)]
    started = time.monotonic()
    result, trace, calls, error = {}, [], {}, None
    try:
        proc = gdd_process.run(command, input=task["prompt"], cwd=workspace, env=env,
                               text=True, capture_output=True, timeout=args.timeout)
        for line in proc.stdout.splitlines():
            event = json.loads(line)
            if event.get("type") == "result":
                result = event
            if event.get("type") in {"assistant", "user"}:
                content = event.get("message", {}).get("content", [])
                for block in content if isinstance(content, list) else ():
                    if block.get("type") == "tool_use":
                        name, arguments = block["name"], block.get("input", {})
                        payload = json.dumps(arguments).lower()
                        skill_access = (name == "Skill" or "skill.md" in payload
                                        or any(p in payload for p in (".claude", ".codex", ".agents")))
                        entry = {"tool": name, "skill_access": skill_access, "skill_loaded": False}
                        trace.append(entry)
                        if ((name == "Skill" and arguments.get("skill") == task["skill"])
                                or (name == "Read" and task["skill"] in payload and "skill.md" in payload)):
                            calls[block["id"]] = entry
                    if block.get("type") == "tool_result" and block.get("tool_use_id") in calls:
                        calls[block["tool_use_id"]]["skill_loaded"] = not block.get("is_error", False)
        if proc.returncode or result.get("subtype") != "success" or result.get("is_error"):
            error = f"exit {proc.returncode}; result: {result.get('subtype', 'missing')}"
    except subprocess.TimeoutExpired:
        error = "agent timed out"
    except json.JSONDecodeError:
        error = "invalid Claude stream JSON"
    output = result.get("result", "") if error is None else ""
    contaminated = not with_skill and any(event["skill_access"] for event in trace)
    scores, artifacts = judge(task["rubric"], output, workspace)
    usage = result.get("usage", {})
    def redact(value):
        return value.replace(str(root), "<trial>").replace(root.as_posix(), "<trial>")

    return {"error": error, "contaminated": contaminated, "trace": trace, "output": redact(output),
            "artifacts": {name: redact(value) for name, value in artifacts.items()},
            "checks": scores, "score": sum(scores.values()) / len(scores),
            "passed": error is None and not contaminated and all(scores.values()),
            "seconds": round(time.monotonic() - started, 3), "usage": usage,
            "models": sorted(result.get("modelUsage", {})), "cost_usd": result.get("total_cost_usd"),
            "turns": result.get("num_turns")}


def run_eval(args):
    task, fixture = load_task(args.task)
    skill_file = SKILLS / task["skill"] / "SKILL.md"
    revision = re.search(r'^\s+revision:\s*["\']?(\d+)', skill_file.read_text(encoding="utf-8"), re.M)
    stamp = datetime.now().astimezone()
    destination = args.results / f"{stamp.date()}-{task['id']}"
    if any(destination.with_suffix(ext).exists() for ext in (".json", ".md")):
        raise ValueError(f"result already exists: {destination}.*")
    arms = ("skill",) if args.acceptance else ("skill", "baseline")
    runs = {arm: [] for arm in arms}
    order = []
    with tempfile.TemporaryDirectory(prefix="hoa-eval-version-") as temp:
        root = Path(temp)
        version = gdd_process.run([str(args.claude), "--version"], cwd=root, env=isolated_env(root),
                                  text=True, capture_output=True, check=True, timeout=args.timeout).stdout.strip()
    for repeat in range(args.repeats):
        for arm in (arms if repeat % 2 == 0 else arms[::-1]):
            with tempfile.TemporaryDirectory(prefix=f"hoa-eval-{arm}-") as temp:
                runs[arm].append(trial(args, task, fixture, Path(temp).resolve(), arm == "skill"))
            order.append(arm)
    summary = {}
    for arm, trials in runs.items():
        valid = all(not (run["error"] or run["contaminated"]) for run in trials)
        scores = [run["score"] for run in trials]
        summary[arm] = {"valid": valid, "passed": sum(run["passed"] for run in trials),
                        "pass^k": all(run["passed"] for run in trials) if valid else None,
                        "mean_score": statistics.mean(scores) if valid else None,
                        "sample_stddev": statistics.stdev(scores) if valid and len(scores) > 1 else None}
    treatment = all(any(event["skill_loaded"] for event in run["trace"]) for run in runs["skill"])
    outcome = "inconclusive"
    if treatment and all(row["valid"] for row in summary.values()):
        if args.acceptance:
            outcome = "pass" if summary["skill"]["pass^k"] else "fail"
        else:
            a, b = summary["skill"]["pass^k"], summary["baseline"]["pass^k"]
            if a != b:
                outcome = "skill wins" if a else "baseline wins"
    record = {"schema_version": 1, "task": task["id"], "generated_at": stamp.isoformat(),
              "skill": task["skill"], "skill_revision": revision[1] if revision else None,
              "cli_version": version, "model": args.model, "repeats": args.repeats,
              "mode": "acceptance" if args.acceptance else "necessity", "order": order,
              "rubric": task["rubric"], "summary": summary, "runs": runs, "outcome": outcome,
              "limits": {"turns_per_run": args.max_turns, "usd_per_run": args.max_budget_usd,
                         "seconds_per_run": args.timeout}}
    args.results.mkdir(parents=True, exist_ok=True)
    with destination.with_suffix(".json").open("x", encoding="utf-8", newline="\n") as file:
        json.dump(record, file, indent=2, ensure_ascii=False)
        file.write("\n")
    markdown = [f"# {task['id']}", "", f"Outcome: **{outcome}** ({args.model}, k={args.repeats}).", ""]
    for arm, row in summary.items():
        markdown.append(f"- {arm}: {row['passed']}/{args.repeats} passed; "
                        f"pass^k: {row['pass^k']}; mean score: {row['mean_score']}.")
    with destination.with_suffix(".md").open("x", encoding="utf-8", newline="\n") as file:
        file.write("\n".join(markdown) + "\n")
    print(f"{destination.name}: {outcome}")
    return 0 if all(row["valid"] for row in summary.values()) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", type=Path)
    parser.add_argument("--claude", default="claude", help="native Claude Code executable")
    parser.add_argument("--model", required=True)
    parser.add_argument("--results", type=Path, default=EVALS / "results")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--max-turns", type=int, default=12)
    parser.add_argument("--max-budget-usd", type=float, default=1.0)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--acceptance", action="store_true", help="run only the installed arm; enable Write")
    args = parser.parse_args()
    if (min(args.repeats, args.max_turns, args.max_budget_usd, args.timeout) <= 0
            or not math.isfinite(args.max_budget_usd)):
        parser.error("repeat, turn, budget and timeout limits must be positive")
    executable = shutil.which(args.claude)
    if not executable or (os.name == "nt" and Path(executable).suffix.lower() != ".exe"):
        parser.error("--claude must resolve to an executable, not a batch shim")
    args.claude = Path(executable).absolute()
    try:
        return run_eval(args)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(f"necessity eval: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
