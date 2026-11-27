"""Runtime commands and normalized skill-use traces for the necessity eval."""

import json
import os
import posixpath
import re
import tomllib
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import NamedTuple

SKILLS = Path(__file__).resolve().parent.parent / "skills"


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


def claude_command(args, task, installed, arm):
    command = [str(args.executable)]
    shell = args.shell
    write = any("file" in check for check in task["rubric"].values())
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


def claude_trace(_args, events, skill_file, workspace, _skill_text):
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
    result["is_error"] = result.get("is_error") or result.get("subtype") != "success"
    return result, trace


CODEX_DISABLED = (
    "computer_use", "browser_use", "browser_use_external", "in_app_browser", "remote_plugin",
    "image_generation", "skill_search", "plugins", "apps", "memories",
    "multi_agent", "multi_agent_v2", "skill_mcp_dependency_install", "shell_snapshot",
)


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


def codex_command(args, task, _installed, arm):
    command = [str(args.executable)]
    shell = args.shell
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


def codex_trace(_args, events, skill_file, workspace, skill_text):
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
    result["is_error"] = result.get("subtype") != "turn.completed"
    return result, list(calls.values())


PI_PROVIDER = "tencent-litellm"
PI_DEFAULT_MODEL = f"{PI_PROVIDER}/deepseek-v4.1-flash-fast"
PI_ENV_REFERENCE = re.compile(r"\$\{([A-Za-z_]\w*)\}|\$([A-Za-z_]\w*)")


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


def pi_command(args, task, installed, arm):
    command = [str(args.executable)]
    shell = args.shell
    write = any("file" in check for check in task["rubric"].values())
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


def pi_trace(args, events, skill_file, workspace, skill_text):
    route, acc = args.pi_route, args.pi_acc()
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


class RuntimeAdapter(NamedTuple):
    command: Callable
    trace: Callable


ADAPTERS = {
    "claude": RuntimeAdapter(claude_command, claude_trace),
    "codex": RuntimeAdapter(codex_command, codex_trace),
    "pi": RuntimeAdapter(pi_command, pi_trace),
}
