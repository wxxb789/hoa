#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Compare no skill, frozen terse guidance, and a full skill on an outcome rubric."""

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
import tomllib
from datetime import datetime
from pathlib import Path

EVALS = Path(__file__).resolve().parent
SKILLS = EVALS.parent / "skills"
NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
ARMS = ("none", "terse", "skill")
RUNTIMES = ("claude", "codex")
CODEX_DISABLED = (
    "computer_use", "browser_use", "browser_use_external", "in_app_browser", "remote_plugin",
    "image_generation", "skill_search", "plugins", "apps", "memories",
    "multi_agent", "multi_agent_v2", "skill_mcp_dependency_install", "shell_snapshot",
)
THRESHOLD_KEYS = {"min_mean_gain", "max_terse_gap", "min_pass_rate", "min_natural_load_rate"}
CLAUDE_AUTH = {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"}
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
}
SKIP = {".git", "__pycache__", ".pytest_cache"}
WINDOWS_SEPARATOR = r"(?:\\+|/)"
WINDOWS_ROOT = rf"(?:[a-zA-Z]:{WINDOWS_SEPARATOR}|(?:\\{{2,}}|//)(?=[\w?.]))"
ABSOLUTE_PATH = re.compile(
    rf"(?<![\w:/\\>])(?:"
    rf"(?<=[\"'`])(?:{WINDOWS_ROOT}|/(?!/))[^\"'`\r\n]*"
    rf"|{WINDOWS_ROOT}[^\s\"'`<>|,;)]*"
    r"|/(?!/)[\w.~%-][^\s\"'`<>|,;)]*)"
)


def path_forms(path):
    forms = {os.fspath(path), os.path.realpath(path)}
    if os.name == "nt":
        from ctypes import create_unicode_buffer, windll

        # A volume may disable 8.3 aliases; in that case this adds no new form.
        short_path = windll.kernel32.GetShortPathNameW
        size = short_path(str(path), None, 0)
        if size:
            buffer = create_unicode_buffer(size)
            if 0 < short_path(str(path), buffer, size) < size:
                forms.add(buffer.value)
    return forms


def redact(root, value, *, windows=os.name == "nt", secrets=()):
    forms = sorted(path_forms(root), key=len, reverse=True)
    if windows:
        # Backslashes can already be escaped in an answer containing nested JSON.
        trials = [WINDOWS_SEPARATOR.join(map(re.escape, re.split(r"[/\\]", form)))
                  for form in forms]
        prefix = rf"(?:{WINDOWS_SEPARATOR}{{2}}\?{WINDOWS_SEPARATOR})?"
    else:
        trials, prefix = list(map(re.escape, forms)), ""
    trial = re.compile(prefix + "(?:" + "|".join(trials) + r")(?![\w.-])",
                       re.IGNORECASE if windows else 0)
    identities = [re.escape(os.environ[key]) for key in ("USERNAME", "LOGNAME", "USER")
                  if os.environ.get(key)]
    identity = re.compile(r"(?<!\w)(?:" + "|".join(identities) + r")(?!\w)", re.IGNORECASE)
    credentials = sorted({value for value in (*secrets, *(os.getenv(key) for key in CLAUDE_AUTH))
                          if value}, key=len, reverse=True)

    def clean(item):
        if isinstance(item, str):
            for secret in credentials:
                item = item.replace(secret, "<redacted>").replace(toml_string(secret)[1:-1], "<redacted>")
            item = ABSOLUTE_PATH.sub("<path>", trial.sub("<trial>", item))
            return identity.sub("<redacted>", item) if identities else item
        if isinstance(item, dict):
            return {clean(key): clean(entry) for key, entry in item.items()}
        if isinstance(item, list):
            return [clean(entry) for entry in item]
        return item

    return clean(value)


def run_process(command, **kwargs):
    if os.name == "nt":
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        kwargs.update(creationflags=subprocess.CREATE_NO_WINDOW, startupinfo=startup)
    return subprocess.run(command, encoding="utf-8", errors="replace", **kwargs)


def isolated_env(root, passthrough=()):
    allow = PASSTHROUGH.union(passthrough)
    env = {key: value for key, value in os.environ.items() if key.upper() in allow or key in allow}
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
            if fixture and name.lower() in {".agents", ".claude", ".codex", "skill.md",
                                            "claude.md", "claude.local.md", ".mcp.json"}:
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
    for key in ("prompt", "terse"):
        if not isinstance(task[key], str) or not task[key].strip():
            raise ValueError(f"{key} must be nonempty text")
    shell = task.get("shell", False)
    if type(shell) is not bool and (not isinstance(shell, list) or not all(item in RUNTIMES for item in shell)):
        raise ValueError("shell must be a boolean or a list of runtimes")
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


JSON_FENCE = re.compile(r"^[ \t]*```json[ \t]*\r?\n(.*?)^[ \t]*```[ \t]*(?=\r?$)",
                        re.IGNORECASE | re.MULTILINE | re.DOTALL)
JSON_CONTAINER = re.compile(r"[\[{]")


def extract_answer(output):
    try:
        answer = json.loads(output)
    except json.JSONDecodeError:
        pass
    else:
        return answer, "bare"
    fences = JSON_FENCE.findall(output)
    if fences:
        try:
            answer = json.loads(fences[-1])
        except json.JSONDecodeError:
            pass
        else:
            return answer, "fenced"
    decoder = json.JSONDecoder()
    answer, end = None, 0
    while start := JSON_CONTAINER.search(output, end):
        try:
            value, end = decoder.raw_decode(output, start.start())
        except json.JSONDecodeError as error:
            # Resume at the error instead of reinterpreting already parsed nested values.
            end = max(start.end(), error.pos)
        else:
            if isinstance(value, dict):
                answer = value
    return answer, "extracted" if answer is not None else "none"


def judge(rubric, answer, workspace):
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


def toml_string(value):
    return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")


def toml_value(value):
    if isinstance(value, str):
        return toml_string(value)
    if type(value) in (bool, int, float):
        return json.dumps(value)
    if isinstance(value, dict):
        return "{" + ", ".join(f"{toml_string(key)} = {toml_value(item)}"
                               for key, item in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ", ".join(map(toml_value, value)) + "]"
    raise ValueError("unsupported TOML value in Codex provider configuration")


def codex_provider():
    home = Path(os.environ["CODEX_HOME"]) if os.getenv("CODEX_HOME") else Path.home() / ".codex"
    path = home / "config.toml"
    config = tomllib.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    name = config.get("model_provider")
    if not name:
        return "", (), ()
    providers = config.get("model_providers", {})
    provider = providers.get(name, {})
    if provider.get("auth"):
        raise ValueError("Codex provider auth commands are not supported in isolated trials")
    credentials = set(provider.get("env_http_headers", {}).values())
    if provider.get("env_key"):
        credentials.add(provider["env_key"])
    secrets = (*map(os.getenv, credentials), *provider.get("http_headers", {}).values(),
               provider.get("experimental_bearer_token"), provider.get("base_url"))
    text = f"model_provider = {toml_string(name)}\n"
    if name in providers:
        text += f"[model_providers]\n{toml_string(name)} = {toml_value(provider)}\n"
    return text, credentials, secrets


def codex_host_skill_rules():
    if os.name != "nt":
        return []
    from ctypes import create_unicode_buffer, windll

    # dirs::home_dir in Codex 0.171 uses the Windows Known Folder, not USERPROFILE.
    profile = create_unicode_buffer(260)
    if windll.shell32.SHGetFolderPathW(None, 0x28, None, 0, profile):
        raise ValueError("cannot locate the Windows profile to exclude host skills")
    discovered = set()
    visited = set()
    for path, dirs, names in (Path(profile.value) / ".agents" / "skills").walk(follow_symlinks=True):
        resolved = path.resolve()
        if resolved in visited:
            dirs.clear()
        visited.add(resolved)
        if any(name.lower() == "skill.md" for name in names):
            discovered.add((resolved / "SKILL.md").as_posix())
    if not discovered:
        return []
    rules = [{"path": path, "enabled": False} for path in sorted(discovered)]
    return ["-c", f"skills.config={toml_value(rules)}"]


def agent_command(args, task, installed, arm):
    command = [str(args.executable)]
    shell = args.shell
    write = any("file" in check for check in task["rubric"].values())
    if args.runtime == "claude":
        tools = ["Read", "Glob", "Skill"] + (["Write"] if write else []) + (["Bash"] if shell else [])
        command += ["-p", "--output-format", "stream-json", "--verbose", "--restricted",
                    "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--setting-sources", "user",
                    "--no-session-persistence", "--no-chrome", "--tools", ",".join(tools),
                    "--permission-prompts", "none", "--permission-mode", "acceptEdits" if write else "dontAsk",
                    "--add-dir", str(installed), "--model", args.model, "--effort", "low",
                    "--max-turns", str(args.max_turns), "--max-budget-usd", str(args.max_budget_usd)]
        if shell:
            command += ["--allowedTools", "Bash"]
        if arm == "terse":
            command += ["--append-system-prompt", task["terse"]]
        return command
    command += ["exec", "--json", "--ephemeral", "--skip-git-repo-check",
                "--dangerously-bypass-approvals-and-sandbox", "--model", args.model,
                "-c", 'model_reasoning_effort="medium"', "-c", 'web_search="disabled"',
                "-c", "skills.bundled.enabled=false", "-c", "project_root_markers=[]",
                "-c", "allow_login_shell=false", "-c", "mcp_servers={}", *args.host_skill_rules]
    for feature in CODEX_DISABLED + (() if shell else ("shell_tool",)):
        command += ["--disable", feature]
    if arm == "terse":
        command += ["-c", f"developer_instructions={toml_string(task['terse'])}"]
    return command + ["-"]


COMMAND_WORD = re.compile(r"""(["'])(.*?)\1|([^\s"'`;&|<>()=,]+)""", re.DOTALL)


def command_paths(command):
    # Shell syntax is only a trace hint. Inspect literal operands, not command output.
    previous = ""
    for word in COMMAND_WORD.finditer(command):
        quoted, bare = word.group(2, 3)
        value = quoted if bare is None else bare
        if quoted and previous in {"-c", "-lc", "-cl", "-command", "/c"}:
            yield from command_paths(quoted)
        elif "/" in value or "\\" in value:
            yield value
        previous = value.casefold()


def argument_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, (dict, list)):
        for item in value.values() if isinstance(value, dict) else value:
            yield from argument_strings(item)


def trace_path(value, workspace):
    value = value.replace("\\", "/")
    if value.startswith("~/"):
        value = str(workspace.parent / "home" / value[2:])
    try:
        # On Windows, realpath expands existing 8.3 aliases, including parent directories.
        return Path(os.path.realpath(workspace / value))
    except (OSError, ValueError):
        return None


def skill_access(paths, workspace, skill_file):
    catalog = (SKILLS / skill_file.parent.name).resolve()
    home = workspace.parent / "home"
    for path in paths:
        if path is None or path.is_relative_to(workspace):
            continue
        if path.is_relative_to(catalog) or path.is_relative_to(skill_file.parent):
            return True
        if path.is_relative_to(home):
            parts = path.relative_to(home).parts
            if "skills" in (part.casefold() if os.name == "nt" else part for part in parts):
                return True
    return False


def claude_trace(events, skill_file, workspace):
    result, trace, reads = {}, [], {}
    for event in events:
        kind = event.get("type")
        if kind == "result":
            result = event
        if kind not in {"assistant", "user"}:
            continue
        content = event.get("message", {}).get("content", [])
        for block in content if isinstance(content, list) else ():
            if block.get("type") == "tool_use":
                name, arguments = block["name"], block.get("input", {})
                read_path, paths = None, ()
                if name == "Read" and "file_path" in arguments:
                    read_path = trace_path(arguments["file_path"], workspace)
                    paths = (read_path,)
                elif name == "Glob":
                    base = arguments.get("path") or "."
                    pattern = arguments.get("pattern", "")
                    paths = (trace_path(base, workspace), trace_path(str(Path(base) / pattern), workspace))
                elif name == "Bash":
                    paths = (trace_path(value, workspace) for value in command_paths(arguments.get("command", "")))
                access = name == "Skill" or skill_access(paths, workspace, skill_file)
                entry = {"tool": name, "skill_access": access, "skill_loaded": False}
                trace.append(entry)
                if ((name == "Skill" and arguments.get("skill") == skill_file.parent.name)
                        or read_path == skill_file):
                    reads[block["id"]] = entry
            if block.get("type") == "tool_result" and block.get("tool_use_id") in reads:
                reads[block["tool_use_id"]]["skill_loaded"] = not block.get("is_error", False)
    return result, trace


def codex_trace(events, skill_file, workspace, skill_text):
    result, calls = {}, {}
    # Require returned document text, not just an exit-zero command that mentions SKILL.md.
    header = "\n".join(skill_text.splitlines()[:3])
    for event in events:
        kind = event.get("type")
        if kind in {"turn.completed", "turn.failed"}:
            result.update(subtype=kind, usage=event.get("usage", {}))
        if kind not in {"item.started", "item.updated", "item.completed"}:
            continue
        item = event["item"]
        tool = item["type"]
        if tool == "agent_message" and kind == "item.completed":
            result["result"] = item["text"]
        if tool not in {"command_execution", "mcp_tool_call", "file_change"}:
            continue
        entry = calls.setdefault(item["id"], {"tool": tool, "skill_access": False, "skill_loaded": False})
        payload = (command_paths(item.get("command", "")) if tool == "command_execution"
                   else argument_strings(item.get("arguments")) if tool == "mcp_tool_call" else ())
        paths = {trace_path(value, workspace) for value in payload}
        entry["skill_access"] |= (
            (tool == "mcp_tool_call" and item.get("tool", "").casefold() == "skill")
            or skill_access(paths, workspace, skill_file)
        )
        if (kind == "item.completed" and tool == "command_execution"
                and item.get("status") == "completed" and item.get("exit_code") == 0
                and skill_file in paths and header in item.get("aggregated_output", "").replace("\r\n", "\n")):
            entry["skill_loaded"] = True
    return result, list(calls.values())


def trial(args, task, fixture, root, arm, skill_text):
    runtime = args.runtime
    config, extra_env, secrets = args.provider
    env = isolated_env(root, CLAUDE_AUTH if runtime == "claude" else extra_env)
    workspace = root / "work"
    snapshot(fixture, workspace, fixture=True)
    home = Path(env["CLAUDE_CONFIG_DIR" if runtime == "claude" else "CODEX_HOME"])
    if config:
        (home / "config.toml").write_text(config, encoding="utf-8")
    installed = home / "skills"
    installed.mkdir()
    skill_file = installed / task["skill"] / "SKILL.md"
    prompt = task["prompt"]
    if arm == "skill":
        snapshot(SKILLS / task["skill"], skill_file.parent)
        if args.mode == "forced":
            prompt += f'\n\nUse the {task["skill"]} skill. First read "{skill_file.as_posix()}", then follow it.'
    started = time.monotonic()
    result, trace, error = {}, [], None
    try:
        proc = run_process(agent_command(args, task, installed, arm), input=prompt, cwd=workspace,
                           env=env, capture_output=True, timeout=args.timeout)
        events = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
        if runtime == "claude":
            result, trace = claude_trace(events, skill_file, workspace)
        else:
            result, trace = codex_trace(events, skill_file, workspace, skill_text)
        if (proc.returncode or result.get("subtype") != ("success" if runtime == "claude" else "turn.completed")
                or result.get("is_error") or not isinstance(result.get("result"), str)):
            error = f"agent failed (exit {proc.returncode})"
    except subprocess.TimeoutExpired:
        error = "agent timed out"
    except (ValueError, KeyError, TypeError, AttributeError):
        error = "invalid agent event stream"
    output = result.get("result", "") if error is None else ""
    loaded = any(event["skill_loaded"] for event in trace)
    contaminated = arm != "skill" and any(event["skill_access"] for event in trace)
    invalid = ([error] if error else []) + (["control skill access"] if contaminated else [])
    if arm == "skill" and args.mode == "forced" and not loaded:
        invalid.append("forced skill load not observed")
    answer, answer_format = extract_answer(output)
    scores, artifacts = judge(task["rubric"], answer, workspace)
    usage = result.get("usage", {})
    token_keys = ("input_tokens", "output_tokens")
    if runtime == "claude":
        token_keys += ("cache_creation_input_tokens", "cache_read_input_tokens")
    tokens = sum(usage.get(key, 0) for key in token_keys) if usage else None
    record = {"valid": not invalid, "invalid_reasons": invalid, "error": error,
              "contaminated": contaminated, "skill_loaded": loaded, "trace": trace,
              "output": output, "answer_format": answer_format, "artifacts": artifacts,
              "checks": scores, "score": sum(scores.values()) / len(scores),
              "passed": not invalid and all(scores.values()),
              "seconds": round(time.monotonic() - started, 3), "usage": usage, "tokens": tokens,
              "models": sorted(result.get("modelUsage", {})), "cost_usd": result.get("total_cost_usd"),
              "turns": result.get("num_turns")}
    return redact(root, record, secrets=secrets)


def verdict(summary, thresholds):
    if not all(row["valid"] for row in summary.values()):
        return "inconclusive"
    none, terse, skill = (summary[arm] for arm in ARMS)
    if not skill["loaded"] or skill["load_rate"] < thresholds["min_natural_load_rate"]:
        return "inconclusive"
    gain = thresholds["min_mean_gain"]
    if (skill["pass_rate"] >= thresholds["min_pass_rate"]
            and all(skill["mean_score"] - control["mean_score"] >= gain for control in (none, terse))):
        return "skill-wins"
    if (terse["pass_rate"] >= thresholds["min_pass_rate"]
            and terse["mean_score"] - none["mean_score"] >= gain
            and skill["mean_score"] - terse["mean_score"] <= thresholds["max_terse_gap"]):
        return "terse-suffices"
    return "no-difference"


def run_eval(args):
    task, fixture = load_task(args.task)
    shell = task.get("shell", False)
    args.shell = shell if type(shell) is bool else args.runtime in shell
    thresholds = json.loads(args.thresholds.read_text(encoding="utf-8"))
    if (not isinstance(thresholds, dict) or set(thresholds) != THRESHOLD_KEYS
            or any(type(value) not in (int, float) or not 0 <= value <= 1 for value in thresholds.values())
            or thresholds["min_mean_gain"] == 0):
        raise ValueError(f"{args.thresholds.name}: expected {sorted(THRESHOLD_KEYS)} in [0, 1], with positive min_mean_gain")
    skill_text = (SKILLS / task["skill"] / "SKILL.md").read_text(encoding="utf-8")
    revision = re.search(r'^\s+revision:\s*["\']?(\d+)', skill_text, re.M)
    stamp = datetime.now().astimezone()
    destination = args.results / f"{stamp.date()}-{task['id']}-{args.runtime}-{args.mode}"
    if any(destination.with_suffix(ext).exists() for ext in (".json", ".md")):
        raise ValueError(f"result already exists: {destination}.*")
    runs = {arm: [] for arm in ARMS}
    order, skipped_trials = [], []
    total_tokens = 0
    args.provider = codex_provider() if args.runtime == "codex" else ("", (), ())
    args.host_skill_rules = codex_host_skill_rules() if args.runtime == "codex" else []
    with tempfile.TemporaryDirectory(prefix="hoa-eval-version-") as temp:
        root = Path(temp)
        proc = run_process([str(args.executable), "--version"], cwd=root, env=isolated_env(root),
                           capture_output=True, timeout=args.timeout)
        if proc.returncode:
            raise ValueError(f"{args.runtime} --version failed (exit {proc.returncode})")
        version, model = redact(root, [proc.stdout.strip(), args.model], secrets=args.provider[2])
    for repeat in range(args.repeats):
        for arm in (ARMS if repeat % 2 == 0 else ARMS[::-1]):
            if args.max_total_tokens is not None and total_tokens >= args.max_total_tokens:
                skipped_trials.append({"arm": arm, "repeat": repeat + 1})
                continue
            with tempfile.TemporaryDirectory(prefix=f"hoa-eval-{arm}-") as temp:
                run = trial(args, task, fixture, Path(temp).resolve(), arm, skill_text)
            runs[arm].append(run)
            total_tokens += run["tokens"] or 0
            order.append(arm)
    summary = {}
    for arm, trials in runs.items():
        valid = len(trials) == args.repeats and all(run["valid"] for run in trials)
        scores = [run["score"] for run in trials]
        passed = sum(run["passed"] for run in trials)
        loaded = sum(run["skill_loaded"] for run in trials)
        summary[arm] = {"valid": valid, "passed": passed, "loaded": loaded,
                        "load_rate": loaded / len(trials) if trials else None,
                        "pass_rate": passed / len(trials) if valid else None,
                        "pass^k": all(run["passed"] for run in trials) if valid else None,
                        "mean_score": statistics.mean(scores) if valid else None,
                        "sample_stddev": statistics.stdev(scores) if valid and len(scores) > 1 else None}
    outcome = verdict(summary, thresholds)
    rubric_flags = {}
    for label in task["rubric"]:
        by_arm = [{run["checks"][label] for run in trials if run["valid"]} for trials in runs.values()]
        if all(by_arm) and len(set.union(*by_arm)) == 1:
            rubric_flags[label] = "non-discriminating"
        elif any(len(values) > 1 for values in by_arm):
            rubric_flags[label] = "flaky"
    deltas = {arm: summary["skill"]["mean_score"] - summary[arm]["mean_score"]
              for arm in ("none", "terse")
              if summary["skill"]["valid"] and summary[arm]["valid"]}
    limits = {"seconds_per_run": args.timeout, "total_tokens": args.max_total_tokens}
    if args.runtime == "claude":
        limits.update(turns_per_run=args.max_turns, usd_per_run=args.max_budget_usd)
    record = {"schema_version": 2, "task": task["id"], "generated_at": stamp.isoformat(),
              "skill": task["skill"], "skill_revision": revision[1] if revision else None,
              "cli_version": version, "model": model, "repeats": args.repeats,
              "runtime": args.runtime, "mode": args.mode, "shell": args.shell, "order": order,
              "rubric": task["rubric"], "rubric_flags": rubric_flags, "thresholds": thresholds,
              "summary": summary, "mean_deltas_vs_skill": deltas, "runs": runs, "verdict": outcome,
              "limits": limits, "total_tokens": total_tokens, "skipped_trials": skipped_trials}
    args.results.mkdir(parents=True, exist_ok=True)
    with destination.with_suffix(".json").open("x", encoding="utf-8", newline="\n") as file:
        json.dump(record, file, indent=2, ensure_ascii=False)
        file.write("\n")
    markdown = [f"# {task['id']}", "", f"Verdict: **{outcome}** ({args.runtime}, {args.mode}, k={args.repeats}).",
                f"Model: `{model}`; CLI: `{version}`; skill: `{task['skill']}` rev {record['skill_revision']}.",
                "", f"Thresholds: `{json.dumps(thresholds, sort_keys=True)}`.", ""]
    for arm, row in summary.items():
        markdown.append(f"- {arm}: {row['passed']}/{args.repeats} passed; "
                        f"loaded {row['loaded']}; pass^k: {row['pass^k']}; mean score: {row['mean_score']}; "
                        f"sample stddev: {row['sample_stddev']}.")
    markdown += ["", f"CLI-reported tokens: {total_tokens}."]
    if skipped_trials:
        skipped = ", ".join(f"{row['arm']} (repeat {row['repeat']})" for row in skipped_trials)
        markdown.append(f"Skipped at token cap {args.max_total_tokens}: {skipped}.")
    markdown += ["", "| Arm | Trial | Validity | Answer format | Tokens | Seconds |",
                 "|---|---:|---|---|---:|---:|"]
    for arm, trials in runs.items():
        for i, run in enumerate(trials, 1):
            validity = "valid" if run["valid"] else "; ".join(run["invalid_reasons"])
            markdown.append(f"| {arm} | {i} | {validity} | {run['answer_format']} | {run['tokens']} | {run['seconds']} |")
    with destination.with_suffix(".md").open("x", encoding="utf-8", newline="\n") as file:
        file.write("\n".join(markdown) + "\n")
    print(f"{destination.name}: {outcome}")
    return 0 if all(row["valid"] for row in summary.values()) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", type=Path)
    parser.add_argument("--runtime", choices=RUNTIMES, default="claude")
    parser.add_argument("--mode", choices=("forced", "natural"), default="forced")
    parser.add_argument("--claude", default="claude", help="native Claude Code executable")
    parser.add_argument("--codex", default="codex", help="native Codex executable")
    parser.add_argument("--model", help="required for Claude; defaults to gpt-6.2-sol for Codex")
    parser.add_argument("--results", type=Path, default=EVALS / "results")
    parser.add_argument("--thresholds", type=Path, default=EVALS / "necessity-thresholds.json")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--max-turns", type=int, default=12, help="Claude only")
    parser.add_argument("--max-budget-usd", type=float, default=1.0, help="Claude only")
    parser.add_argument("--max-total-tokens", type=int, help="stop starting trials at this CLI-reported token total")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    if not args.model:
        if args.runtime == "claude":
            parser.error("--model is required for Claude")
        args.model = "gpt-6.2-sol"
    if (min(args.repeats, args.max_turns, args.max_budget_usd, args.timeout) <= 0
            or not math.isfinite(args.max_budget_usd)):
        parser.error("repeat, turn, budget and timeout limits must be positive")
    if args.max_total_tokens is not None and args.max_total_tokens <= 0:
        parser.error("--max-total-tokens must be positive")
    executable = shutil.which(getattr(args, args.runtime))
    if not executable or (os.name == "nt" and Path(executable).suffix.lower() != ".exe"):
        parser.error(f"--{args.runtime} must resolve to a native executable, not a batch shim")
    args.executable = Path(executable).absolute()
    try:
        return run_eval(args)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        secrets = getattr(args, "provider", ("", (), ()))[2]
        print(f"necessity eval: {redact(EVALS, str(error), secrets=secrets)}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
