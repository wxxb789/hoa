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
import posixpath
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import tomllib
from datetime import datetime
from pathlib import Path, PurePosixPath

if __package__:
    from . import wsl_pi
else:
    import wsl_pi

EVALS = Path(__file__).resolve().parent
SKILLS = EVALS.parent / "skills"
NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
ARMS = ("none", "terse", "skill")
RUNTIMES = ("claude", "codex", "pi")
PI_PROVIDER = "tencent-litellm"
PI_DEFAULT_MODEL = f"{PI_PROVIDER}/deepseek-v4.1-flash-fast"
PI_TIMEOUT = 3000
PI_THINKING = ("off", "minimal", "low", "medium", "high", "xhigh", "max")
PI_ENV_REFERENCE = re.compile(r"\$\{([A-Za-z_]\w*)\}|\$([A-Za-z_]\w*)")
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
PI_PROFILE = {
    "PI_CODING_AGENT_DIR": "home/.pi/agent",
    "PI_CODING_AGENT_SESSION_DIR": "home/.pi/sessions",
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


def isolated_env(root, runtime, passthrough=()):
    allow = PASSTHROUGH.union(passthrough)
    env = {key: value for key, value in os.environ.items() if key.upper() in allow or key in allow}
    if os.name == "nt" and os.getenv("NOWINDOW_GUARD_LOG"):
        for key in ("NOWINDOW_GUARD_LOG", "PYTHONPATH"):
            env[key] = os.environ[key]
    profile = PROFILE | PI_PROFILE if runtime == "pi" else PROFILE
    for key, relative in profile.items():
        path = root / relative
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        env[key] = str(path)
    if os.name == "nt":
        env["HOMEDRIVE"], env["HOMEPATH"] = os.path.splitdrive(env["USERPROFILE"])
    if runtime == "pi":
        env["PI_TELEMETRY"] = "0"
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


def pi_provider(model=None):
    home = Path.home() / ".pi" / "agent"
    models = home / "models.json"
    provider = json.loads(models.read_text(encoding="utf-8")).get("providers", {}).get(PI_PROVIDER)
    if not provider:
        raise ValueError(f"{models.name}: missing providers.{PI_PROVIDER}")
    if model is not None:
        model_id = model.split("/", 1)[1]
        selected = [entry for entry in provider.get("models", ()) if entry["id"] == model_id]
        if len(selected) != 1:
            raise ValueError(f"{models.name}: expected one model entry for {model}")
        provider["models"] = selected
        if "modelOverrides" in provider:
            provider["modelOverrides"] = {key: value for key, value in provider["modelOverrides"].items()
                                          if key == model_id}
    files = {"models.json": {"providers": {PI_PROVIDER: provider}}}
    auth_file = home / "auth.json"
    auth = json.loads(auth_file.read_text(encoding="utf-8")).get(PI_PROVIDER) if auth_file.is_file() else None
    credentials, secrets = set(), set()
    if auth is not None:
        files["auth.json"] = {PI_PROVIDER: auth}
        secrets.update(argument_strings({key: value for key, value in auth.items() if key != "type"}))

    def credential(match):
        key = match[1] or match[2]
        credentials.add(key)
        return os.getenv(key, match[0])

    for config in (provider, *provider.get("models", ()), *provider.get("modelOverrides", {}).values(),
                   {"apiKey": (auth or {}).get("key")}):
        secrets.update(argument_strings(config.get("baseUrl")))
        for value in argument_strings([config.get("apiKey"), config.get("headers")]):
            if value.startswith("!"):
                raise ValueError(f"{PI_PROVIDER}: Pi credential commands are not supported in isolated trials")
            secrets.add(value)
            if value.startswith(("$$", "$!")):
                secrets.add(value[1:])
            else:
                secrets.add(PI_ENV_REFERENCE.sub(credential, value))
    return files, credentials, (*secrets, *map(os.getenv, credentials))


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
    if args.runtime == "pi":
        tools = ["read", "grep", "find", "ls"]
        if write:
            tools += ["write", "edit"]
        if shell:
            tools += ["bash", "powershell"] if os.name == "nt" and not getattr(args, "sandbox", None) else ["bash"]
        extra = ["--offline", "--no-session", "--no-extensions", "--no-mcp",
                 "--no-context-files", "--no-prompt-templates", "--no-themes", "--tools", ",".join(tools)]
        if arm != "skill" or args.mode == "forced":
            extra.append("--no-skills")
        if arm == "skill" and args.mode == "forced":
            extra += ["--skill", str(installed / task["skill"])]
        if arm == "terse":
            extra += ["--append-system-prompt", task["terse"]]
        return command + args.pi_route.argv(args, extra)
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


COMMAND_WORD = re.compile(r"""(["'])(.*?)\1|([;&|<>\r\n]+)|([^\s"'`;&|<>()]+)""", re.DOTALL)
SEARCH_TOOLS = {"glob", "grep", "ls", "dir", "find", "get-childitem"}
READ_COMMANDS = {"cat", "type", "get-content", "sed", "head"}
RG_LIST_OPTIONS = {"--files", "--files-with-matches", "--files-without-match", "-l", "--count", "-c",
                   "--count-matches"}
READ_VALUE_OPTIONS = {
    "rg": {"-g", "--glob", "--iglob", "--encoding", "--max-count", "-m", "-A", "-B", "-C"},
    "head": {"-n", "--lines", "-c", "--bytes"},
    "get-content": {"-totalcount", "-tail", "-readcount", "-encoding"},
}


def shell_commands(command):
    # Inspect literal commands, including quoted shell wrappers, not arbitrary shell behavior.
    words = []
    redirected = False
    for _, quoted, separator, bare in COMMAND_WORD.findall(command + "\n"):
        if separator and not set(separator) <= {"<", ">"}:
            if words:
                verb = words[0].replace("\\", "/").rsplit("/", 1)[-1].casefold().removesuffix(".exe")
                args = words[1:]
                if verb in {"bash", "sh", "zsh", "powershell", "pwsh", "cmd"}:
                    for flag, script in zip(args, args[1:]):
                        if flag.casefold() in {"-c", "-lc", "-cl", "-command", "/c"}:
                            yield from shell_commands(script)
                            break
                else:
                    yield verb, args
            words = []
            redirected = False
        elif separator:
            redirected = True
        elif not redirected:
            words.append(bare or quoted)


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
    if not isinstance(workspace, Path):
        if re.match(r"^[A-Za-z]:/", value):
            value = "/" + value
        target = PurePosixPath(posixpath.normpath(str(workspace / value)))
        return target, target
    try:
        # On Windows, realpath expands existing 8.3 aliases, including parent directories.
        target = workspace / value
        return Path(os.path.realpath(target)), Path(os.path.abspath(target))
    except (OSError, ValueError):
        return None, None


def skill_read(path, literal, workspace, skill_file):
    if path is None or path.is_relative_to(workspace):
        return None
    if any(p.is_relative_to(skill_file.parents[1]) for p in (path, literal)):
        return "installed-copy-read"
    if any(p.is_relative_to(catalog) and len(p.relative_to(catalog).parts) >= 2
           for p, catalog in ((path, SKILLS.resolve()), (literal, SKILLS))):
        return "catalog-read"
    for candidate in (path, literal):
        parts = tuple(part.casefold() for part in candidate.parts)
        if (parts[-1:] == ("skill.md",) or "skills" in parts[:-2]
                or (parts[-2:-1] == ("skills",) and (
                    parts[-3:-2] in {(".agents",), (".claude",), (".codex",)}
                    or candidate.is_relative_to(workspace.parent / "home")))):
            return "host-skill-read"
    return None


def skill_probe(values, workspace, skill_file, base=None):
    marker = re.compile(rf"(?<![\w-])(?:skills|skill\.md|{re.escape(skill_file.parent.name)})(?![\w-])", re.I)
    for value in values:
        if not marker.search(value):
            continue
        path, _ = trace_path(value, workspace)
        if path is not None and path.is_relative_to(workspace):
            if base is not None:
                # Structured search tools scope relative patterns to their explicit base.
                base_path, _ = trace_path(base, workspace)
                if base_path is not None and base_path.is_relative_to(workspace):
                    continue
            elif ((("/" in value or "\\" in value) and not value.startswith(("*", "?")))
                  or isinstance(path, Path) and path.exists()):
                continue
        return True
    return False


def shell_skill_operations(command, workspace):
    for verb, args in shell_commands(command):
        if verb in SEARCH_TOOLS or (verb == "rg" and RG_LIST_OPTIONS.intersection(args)):
            yield True, args
        elif verb in READ_COMMANDS or verb == "rg":
            # rg and sed take a pattern/script before files, unless supplied by option.
            files = []
            pattern_given = verb not in {"rg", "sed"}
            skip_value = False
            options = True
            for arg in args:
                if skip_value:
                    skip_value = False
                elif options and arg == "--":
                    options = False
                elif options and arg.startswith("-"):
                    option, equals, value = arg.partition("=")
                    if verb in {"rg", "sed"} and option in {"-e", "--regexp", "--expression"}:
                        pattern_given = True
                        skip_value = not equals
                    elif verb in {"rg", "sed"} and option in {"-f", "--file"}:
                        pattern_given = True
                        if equals:
                            files.append(value)
                    elif (option.casefold() if verb == "get-content" else option) in READ_VALUE_OPTIONS.get(verb, ()):
                        skip_value = not equals
                elif pattern_given:
                    files.append(arg)
                else:
                    pattern_given = True
            if verb == "rg":
                targets = [file for file in files if (path := trace_path(file, workspace)[0])
                           and not (isinstance(path, Path) and path.is_dir())]
                if not files or len(files) != len(targets):
                    yield True, args
                files = targets
            yield False, files


def skill_failed(content):
    return any(re.match(r"\s*(?:unknown skill\b|skill\b[^\r\n]*\bnot found\b)", value, re.I)
               for value in argument_strings(content))


def record_skill_reads(entry, values, workspace, skill_file):
    reasons = set(entry["contamination_reasons"])
    loaded = False
    for value in values:
        path, literal = trace_path(value, workspace)
        if reason := skill_read(path, literal, workspace, skill_file):
            reasons.add(reason)
            loaded |= path == skill_file
            if reason != "installed-copy-read":
                # Keep the offending path so a flagged trial can be audited after the workspace is gone.
                entry.setdefault("contamination_paths", []).append(str(literal))
    entry["contamination_reasons"] = sorted(reasons)
    return loaded


def claude_trace(events, skill_file, workspace):
    result, trace, pending = {}, [], {}
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
                entry = {"tool": name, "skill_probe": False, "skill_loaded": False, "contamination_reasons": []}
                trace.append(entry)
                reads = []
                if name.casefold() in SEARCH_TOOLS:
                    entry["skill_probe"] = skill_probe(argument_strings(arguments), workspace, skill_file,
                                                       arguments.get("path"))
                elif name == "Read":
                    reads = list(argument_strings(arguments.get("file_path")))
                elif name == "Bash":
                    for search, values in shell_skill_operations(arguments.get("command", ""), workspace):
                        if search:
                            entry["skill_probe"] |= skill_probe(values, workspace, skill_file)
                        else:
                            reads.extend(values)
                if name == "Skill" or reads:
                    pending[block["id"]] = entry, arguments.get("skill"), reads
            elif block.get("type") == "tool_result" and block.get("tool_use_id") in pending:
                entry, skill, reads = pending.pop(block["tool_use_id"])
                success = not block.get("is_error", False)
                if entry["tool"] == "Skill":
                    success = success and not skill_failed(block.get("content"))
                    entry["skill_probe"] = not success
                    if success:
                        entry["contamination_reasons"] = ["skill-load"]
                        entry["skill_loaded"] = skill == skill_file.parent.name
                elif success:
                    entry["skill_loaded"] = record_skill_reads(entry, reads, workspace, skill_file)
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
        entry = calls.setdefault(item["id"], {
            "tool": tool, "skill_probe": False, "skill_loaded": False, "contamination_reasons": [],
        })
        if tool == "command_execution":
            for search, values in shell_skill_operations(item.get("command", ""), workspace):
                if search:
                    entry["skill_probe"] |= skill_probe(values, workspace, skill_file)
                elif (kind == "item.completed" and item.get("status") == "completed"
                      and item.get("exit_code") == 0):
                    installed_read = record_skill_reads(entry, values, workspace, skill_file)
                    entry["skill_loaded"] |= (
                        installed_read and header in item.get("aggregated_output", "").replace("\r\n", "\n")
                    )
        elif tool == "mcp_tool_call":
            name, arguments = item.get("tool", "").casefold(), item.get("arguments")
            if name in SEARCH_TOOLS:
                entry["skill_probe"] |= skill_probe(argument_strings(arguments), workspace, skill_file)
            if kind == "item.completed":
                response = item.get("result")
                success = response is not None and not (
                    item.get("error") or item.get("status") == "failed"
                    or (isinstance(response, dict) and (response.get("isError") or response.get("is_error")))
                )
                if name == "skill":
                    entry["skill_probe"] = not success or skill_failed(response)
                    if not entry["skill_probe"]:
                        entry["contamination_reasons"] = ["skill-load"]
                        entry["skill_loaded"] = (isinstance(arguments, dict)
                                                 and arguments.get("skill") == skill_file.parent.name)
                elif name in {"read", "read_file"} and success:
                    record_skill_reads(entry, argument_strings(arguments), workspace, skill_file)
    return result, list(calls.values())


def pi_trace(route, acc, events, skill_file, workspace, skill_text):
    trace, pending = [], {}
    cache_write, has_usage, models = 0, False, set()
    header = "\n".join(skill_text.splitlines()[:3])
    for event in events:
        route.fold(acc, event)
        kind = event.get("type")
        if kind == "message_end" and event["message"].get("role") == "assistant":
            message = event["message"]
            if usage := message.get("usage"):
                has_usage = True
                cache_write += int(usage.get("cacheWrite") or 0)
            if model := message.get("model"):
                models.add(model)
        if kind == "tool_execution_start":
            tool, arguments = event["toolName"].casefold(), event.get("args", {})
            entry = {"tool": tool, "skill_probe": False, "skill_loaded": False, "contamination_reasons": []}
            trace.append(entry)
            reads = []
            if tool in SEARCH_TOOLS:
                entry["skill_probe"] = skill_probe(argument_strings(arguments), workspace, skill_file,
                                                   arguments.get("path"))
            elif tool == "read":
                reads = list(argument_strings(arguments.get("path")))
            elif tool in {"bash", "powershell"}:
                for search, values in shell_skill_operations(arguments.get("command", ""), workspace):
                    if search:
                        entry["skill_probe"] |= skill_probe(values, workspace, skill_file)
                    else:
                        reads.extend(values)
            if reads or tool == "skill":
                pending[event["toolCallId"]] = entry, arguments, reads
        elif kind == "tool_execution_end" and event["toolCallId"] in pending:
            entry, arguments, reads = pending.pop(event["toolCallId"])
            response = event.get("result")
            success = event.get("isError") is False and response is not None
            if entry["tool"] == "skill":
                entry["skill_probe"] = not success or skill_failed(response)
                if not entry["skill_probe"]:
                    entry["contamination_reasons"] = ["skill-load"]
                    entry["skill_loaded"] = arguments.get("skill") == skill_file.parent.name
            elif success:
                loaded = record_skill_reads(entry, reads, workspace, skill_file)
                entry["skill_loaded"] = loaded and (entry["tool"] == "read" or any(
                    header in value.replace("\r\n", "\n") for value in argument_strings(response)))
    usage = {**acc["usage"], "cache_write_tokens": cache_write} if has_usage else {}
    result = {"result": acc["answer"], "is_error": not route.succeeded(acc["success_marker"]),
              "usage": usage, "modelUsage": models, "num_turns": acc["turns"], "total_cost_usd": acc["cost_usd"]}
    return result, trace


def trial(args, task, fixture, root, arm, skill_text):
    runtime = args.runtime
    config, extra_env, secrets = args.provider
    env = isolated_env(root, runtime, CLAUDE_AUTH if runtime == "claude" else extra_env)
    workspace = root / "work"
    snapshot(fixture, workspace, fixture=True)
    sandbox = getattr(args, "wsl_pi", None)
    if runtime == "pi":
        home = Path(env["PI_CODING_AGENT_DIR"])
        for name, data in config.items():
            path = home / name
            path.touch(mode=0o600)
            path.write_text(json.dumps(data), encoding="utf-8")
    else:
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
            read_path = wsl_pi.TRIAL / skill_file.relative_to(root).as_posix() if sandbox else skill_file
            prompt += f'\n\nUse the {task["skill"]} skill. First read "{read_path.as_posix()}", then follow it.'
    started = time.monotonic()
    result, trace, error, exit_code = {}, [], None, None
    try:
        if sandbox:
            remote_skills = wsl_pi.TRIAL / installed.relative_to(root).as_posix()
            remote_work = wsl_pi.TRIAL / "work"
            outputs = {check["file"] for check in task["rubric"].values() if "file" in check}
            proc = sandbox.run(root, agent_command(args, task, remote_skills, arm), prompt, outputs, args.timeout)
            trace_skill = remote_skills / task["skill"] / "SKILL.md"
        else:
            proc = run_process(agent_command(args, task, installed, arm), input=prompt, cwd=workspace,
                               env=env, capture_output=True, timeout=args.timeout)
            remote_work, trace_skill = workspace, skill_file
        exit_code = proc.returncode
        events = [json.loads(line) for line in proc.stdout.split("\n") if line.strip()]
        if runtime == "claude":
            result, trace = claude_trace(events, skill_file, workspace)
            result["is_error"] = result.get("is_error") or result.get("subtype") != "success"
        elif runtime == "pi":
            result, trace = pi_trace(args.pi_route, args.pi_acc(), events, trace_skill, remote_work, skill_text)
        else:
            result, trace = codex_trace(events, skill_file, workspace, skill_text)
            result["is_error"] = result.get("subtype") != "turn.completed"
        if proc.returncode or result.get("is_error") or not isinstance(result.get("result"), str):
            error = f"agent failed (exit {proc.returncode})"
    except subprocess.TimeoutExpired:
        error = "agent timed out"
    except (ValueError, KeyError, TypeError, AttributeError):
        error = "invalid agent event stream"
    output = result.get("result", "") if error is None else ""
    loaded = any(event["skill_loaded"] for event in trace)
    reasons = sorted({reason for event in trace for reason in event["contamination_reasons"]}) if arm != "skill" else []
    invalid = ([error] if error else []) + (["control skill contamination"] if reasons else [])
    if arm == "skill" and args.mode == "forced" and not loaded:
        invalid.append("forced skill load not observed")
    answer, answer_format = extract_answer(output)
    scores, artifacts = judge(task["rubric"], answer, workspace)
    usage = result.get("usage", {})
    token_keys = ("input_tokens", "output_tokens")
    if runtime == "claude":
        token_keys += ("cache_creation_input_tokens", "cache_read_input_tokens")
    elif runtime == "pi":
        token_keys += ("cache_write_tokens", "cache_read_tokens")
    tokens = sum(usage.get(key, 0) for key in token_keys) if usage else None
    record = {"valid": not invalid, "invalid_reasons": invalid, "error": error,
              "contaminated": bool(reasons), "contamination_reasons": reasons, "skill_loaded": loaded,
              "skill_probe_count": sum(event["skill_probe"] for event in trace), "trace": trace,
              "output": output, "answer_format": answer_format, "artifacts": artifacts,
              "checks": scores, "score": sum(scores.values()) / len(scores),
              "passed": not invalid and all(scores.values()),
              "seconds": round(time.monotonic() - started, 3), "usage": usage, "tokens": tokens,
              "models": sorted(result.get("modelUsage", {})), "cost_usd": result.get("total_cost_usd"),
              "turns": result.get("num_turns")}
    if runtime == "pi":
        record["exit_code"] = exit_code
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
    sandbox = getattr(args, "wsl_pi", None)
    if args.runtime == "pi":
        if sandbox:
            _, _, secrets = pi_provider(args.model)
            args.provider = ({}, (), sorted({value for value in secrets if value}))
        else:
            args.provider = pi_provider()
        sys.path.insert(0, str(SKILLS / "gdd" / "scripts"))
        from agent_run import load_route, new_acc

        args.pi_route, args.pi_acc, args.resume = load_route("pi", SKILLS), new_acc, None
    else:
        args.provider = codex_provider() if args.runtime == "codex" else ("", (), ())
    args.host_skill_rules = codex_host_skill_rules() if args.runtime == "codex" else []
    if sandbox:
        preflight = sandbox.call("--check", payload=args.provider[2])
        version, model = redact(EVALS, [preflight["version"], args.model], secrets=args.provider[2])
    else:
        with tempfile.TemporaryDirectory(prefix="hoa-eval-version-") as temp:
            root = Path(temp)
            env = isolated_env(root, args.runtime)
            proc = run_process([str(args.executable), "--version"], cwd=root, env=env,
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
    record = {"schema_version": 3, "task": task["id"], "generated_at": stamp.isoformat(),
              "skill": task["skill"], "skill_revision": revision[1] if revision else None,
              "cli_version": version, "model": model, "repeats": args.repeats,
              "runtime": args.runtime, "mode": args.mode, "shell": args.shell, "order": order,
              "rubric": task["rubric"], "rubric_flags": rubric_flags, "thresholds": thresholds,
              "summary": summary, "mean_deltas_vs_skill": deltas, "runs": runs, "verdict": outcome,
              "limits": limits, "total_tokens": total_tokens, "skipped_trials": skipped_trials}
    if args.runtime == "pi":
        record["thinking"] = args.thinking
        if sandbox:
            record["sandbox"] = "wsl"
    args.results.mkdir(parents=True, exist_ok=True)
    with destination.with_suffix(".json").open("x", encoding="utf-8", newline="\n") as file:
        json.dump(record, file, indent=2, ensure_ascii=False)
        file.write("\n")
    markdown = [f"# {task['id']}", "", f"Verdict: **{outcome}** ({args.runtime}, {args.mode}, k={args.repeats}).",
                f"Model: `{model}`; CLI: `{version}`; skill: `{task['skill']}` rev {record['skill_revision']}.",
                "", f"Thresholds: `{json.dumps(thresholds, sort_keys=True)}`.", ""]
    if args.runtime == "pi":
        markdown.insert(4, f"Thinking: `{args.thinking}`.")
        if sandbox:
            markdown.insert(5, "Sandbox: `wsl`.")
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
    parser.add_argument("--runtime", choices=RUNTIMES, default="pi")
    parser.add_argument("--mode", choices=("forced", "natural"), default="forced")
    parser.add_argument("--claude", default="claude", help="native Claude Code executable")
    parser.add_argument("--codex", default="codex", help="native Codex executable")
    parser.add_argument("--pi", default="pi", help="native Pi executable")
    parser.add_argument("--sandbox", choices=("wsl",), help="Windows-only filesystem sandbox for Pi")
    parser.add_argument("--wsl-distro", default=wsl_pi.DISTRO)
    parser.add_argument("--model", help="required for Claude; defaults to gpt-6.2-sol for Codex "
                        f"or {PI_DEFAULT_MODEL} for Pi")
    parser.add_argument("--thinking", choices=PI_THINKING, help="Pi only; defaults to max")
    parser.add_argument("--results", type=Path, default=EVALS / "results")
    parser.add_argument("--thresholds", type=Path, default=EVALS / "necessity-thresholds.json")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--max-turns", type=int, default=12, help="Claude only")
    parser.add_argument("--max-budget-usd", type=float, default=1.0, help="Claude only")
    parser.add_argument("--max-total-tokens", type=int, help="stop starting trials at this CLI-reported token total")
    parser.add_argument("--timeout", type=int, help="seconds per trial; default 300, or 3000 for Pi")
    args = parser.parse_args()
    if not args.model:
        if args.runtime == "claude":
            parser.error("--model is required for Claude")
        args.model = PI_DEFAULT_MODEL if args.runtime == "pi" else "gpt-6.2-sol"
    if args.runtime == "pi":
        if "/" not in args.model:
            args.model = f"{PI_PROVIDER}/{args.model}"
        if args.model.partition("/")[0] != PI_PROVIDER or not args.model.partition("/")[2] or ":" in args.model:
            parser.error(f"Pi --model must use {PI_PROVIDER} without a thinking suffix; use --thinking")
        args.thinking = args.thinking or "max"
    elif args.thinking is not None:
        parser.error("--thinking is only supported with --runtime pi")
    # DeepSeek at max thinking spends about ten times the tokens and time of the other runtimes.
    if args.timeout is None:
        args.timeout = PI_TIMEOUT if args.runtime == "pi" else 300
    if (min(args.repeats, args.max_turns, args.max_budget_usd, args.timeout) <= 0
            or not math.isfinite(args.max_budget_usd)):
        parser.error("repeat, turn, budget and timeout limits must be positive")
    if args.max_total_tokens is not None and args.max_total_tokens <= 0:
        parser.error("--max-total-tokens must be positive")
    if args.sandbox:
        if args.runtime != "pi" or args.model != PI_DEFAULT_MODEL or args.pi != "pi":
            parser.error(f"--sandbox wsl requires Pi's installed executable and model {PI_DEFAULT_MODEL}")
        if os.name != "nt":
            print("necessity eval: skipped; --sandbox wsl is Windows-only", file=sys.stderr)
            return 0
        wsl = shutil.which("wsl.exe")
        if not wsl:
            parser.error("--sandbox wsl requires wsl.exe")
        args.wsl_pi = wsl_pi.WslPi(run_process, Path(wsl).absolute(), args.wsl_distro, EVALS)
        args.executable = wsl_pi.PI
    else:
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
