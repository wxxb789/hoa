#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Park spin-breaker side quests and restart breadcrumbs; render static HTML maps.

Subcommands:
  park  Append a timestamped side quest or 4-line restart breadcrumb under
        <repo-root>/.tmp-artifacts/<parking-bundle>/parked-items.md, optionally
        forwarding the same text to a configured external adapter command.
  map   Render a self-contained static HTML decision/elimination board plus its
        backing JSON under <repo-root>/.tmp-artifacts/<bundle>/.
"""
from __future__ import annotations

import argparse
import html
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import skill_config as sc

SKILL = "spin-breaker"
KEY_REPO_ROOT = "repo_root"
KEY_PARKING_BUNDLE = "parking_bundle"
KEY_EXTERNAL_CMD = "external_cmd"
KEY_EXTERNAL_TIMEOUT = "external_timeout"
DEFAULT_PARKING_BUNDLE = "spin-breaker"
DEFAULT_EXTERNAL_TIMEOUT = "15"
ARTIFACT_DIR = ".tmp-artifacts"
PARKING_FILE = "parked-items.md"
GITIGNORE_FILE = ".gitignore"
GITIGNORE_CONTENT = "*\n"
PLACEHOLDER = "{text}"
EXIT_EXTERNAL_FAILED = 1
EXIT_USAGE = 2
HYPOTHESIS_STATUSES = ("live", "eliminated")
PROBE_KEYS = ("command", "pass", "fail")
BOARD_KEYS = ("outcome", "verified_facts", "hypotheses", "probe", "side_quests")
RESERVED_STEMS = frozenset({"con", "prn", "aux", "nul"}
                           | {f"com{number}" for number in range(1, 10)}
                           | {f"lpt{number}" for number in range(1, 10)})

PAGE_CSS = """
:root {
  color-scheme: light dark;
  --bg: #f4f6f8;
  --panel: #ffffff;
  --ink: #1b2430;
  --muted: #5b6b7c;
  --line: #d7dee6;
  --ok: #1f7a4d;
  --warn: #8a5a00;
  --bad: #a12f2f;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #10151a;
    --panel: #1a2129;
    --ink: #e7edf4;
    --muted: #97a6b5;
    --line: #2b3541;
    --ok: #71c493;
    --warn: #e2b45f;
    --bad: #e58f8f;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 1.5rem;
  background: var(--bg);
  color: var(--ink);
  font: 15px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}
header h1 { margin: 0 0 .2rem; font-size: 1.3rem; }
.meta { margin: 0; color: var(--muted); font-size: .85rem; }
.board {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1rem;
  align-items: start;
  margin-top: 1.1rem;
}
section {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 1rem;
  min-width: 0;
}
h2 {
  margin: 0 0 .7rem;
  font-size: .82rem;
  letter-spacing: .06em;
  text-transform: uppercase;
  color: var(--muted);
}
h3 { margin: .9rem 0 .35rem; font-size: .9rem; }
h3:first-of-type { margin-top: 0; }
ul { margin: .3rem 0 .6rem; padding-left: 1.1rem; }
li { margin: .25rem 0; overflow-wrap: anywhere; }
li.live::marker { color: var(--warn); }
li.dead { color: var(--muted); }
li.dead::marker { color: var(--bad); }
.outcome {
  border-left: 3px solid var(--ok);
  padding: .35rem .6rem;
  margin: .2rem 0 .8rem;
  overflow-wrap: anywhere;
}
.count { color: var(--muted); font-weight: normal; }
.note { color: var(--muted); font-size: .85rem; }
.empty { color: var(--muted); font-style: italic; margin: .3rem 0; }
.probe {
  border: 1px dashed var(--line);
  border-radius: 8px;
  padding: .6rem .7rem;
  margin: .4rem 0;
}
code { white-space: pre-wrap; overflow-wrap: anywhere; }
.actions { margin: .3rem 0 0; padding-left: 1.2rem; }
.actions li { margin: .3rem 0; }
@media (max-width: 900px) {
  .board { grid-template-columns: 1fr; }
}
"""


def _emit(stream, text: str) -> None:
    """Write text as UTF-8 bytes, bypassing the console codepage."""
    buffer = getattr(stream, "buffer", None)
    if buffer is None:
        stream.write(text)
        return
    buffer.write(text.encode("utf-8", "backslashreplace"))
    buffer.flush()


def _fail(message: str) -> int:
    """Name the offending value on stderr and return the usage exit code."""
    _emit(sys.stderr, f"spin_breaker: {message}\n")
    return EXIT_USAGE


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _has_surrogate(text: str) -> bool:
    return any(0xD800 <= ord(character) <= 0xDFFF for character in text)


def _field_value(value, flag: str) -> str:
    """Require one non-empty single-line field and keep its exact spacing."""
    text = value if isinstance(value, str) else ""
    if "\n" in text or "\r" in text:
        raise ValueError(f"{flag} must stay on one line")
    if not text.strip():
        raise ValueError(f"{flag} must not be empty")
    if _has_surrogate(text):
        raise ValueError(f"{flag} contains an unpaired UTF-16 surrogate")
    return text


def _optional_field(value, flag: str) -> str | None:
    return None if value is None else _field_value(value, flag)


def _safe_bundle(bundle: str) -> bool:
    if not bundle or bundle in (".", "..") or bundle != bundle.strip():
        return False
    if any(character in bundle for character in "/\\:") or ".." in bundle:
        return False
    if bundle.endswith("."):
        return False
    if any(ord(character) < 0x20 for character in bundle):
        return False
    return bundle.split(".", 1)[0].lower() not in RESERVED_STEMS


def _is_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction is not None and is_junction())


def _is_windows_script(executable: str) -> bool:
    candidates = [executable]
    if sys.platform == "win32":
        resolved = shutil.which(executable)
        if resolved:
            candidates.append(resolved)
    return any(Path(candidate).suffix.lower() in (".cmd", ".bat") for candidate in candidates)


def _ensure_gitignore(bundle_dir: Path) -> None:
    """Keep a bundle's contents out of the surrounding git repository."""
    marker = bundle_dir / GITIGNORE_FILE
    if _is_link(marker):
        raise ValueError(f"{marker} is a symlink; refusing to write through it")
    if marker.exists():
        if marker.lstat().st_nlink > 1:
            raise ValueError(f"{marker} has multiple hard links; refusing to modify it")
        text = marker.read_text(encoding="utf-8", errors="replace")
        if any(line.strip() == "*" for line in text.splitlines()):
            return
        separator = "\n" if text and not text.endswith("\n") else ""
        with marker.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(separator + GITIGNORE_CONTENT)
        return
    marker.write_text(GITIGNORE_CONTENT, encoding="utf-8", newline="\n")


def _resolve_bundle_dir(repo_root: Path, bundle: str) -> Path:
    """The bundle directory, refusing symlinked containers and path escapes."""
    artifacts = repo_root / ARTIFACT_DIR
    artifacts_root = artifacts.resolve(strict=False)
    target = artifacts / bundle
    if _is_link(artifacts) or _is_link(target):
        raise ValueError(f"{target} is a symlink or junction; refusing to write through it")
    resolved = target.resolve(strict=False)
    if resolved == artifacts_root or not resolved.is_relative_to(artifacts_root):
        raise ValueError(f"bundle {bundle!r} escapes {ARTIFACT_DIR}/; refusing to write")
    return target


def _side_quest_entry(timestamp: str, title: str, why_deferred, origin_outcome, locator) -> str:
    lines = [f"## Side quest — {title}", "", f"- when: {timestamp}"]
    optional = (("why deferred", why_deferred), ("origin outcome", origin_outcome),
                ("locator", locator))
    for label, value in optional:
        if value is not None:
            lines.append(f"- {label}: {value}")
    return "\n".join(lines) + "\n"


def _breadcrumb_entry(timestamp: str, outcome: str, last_fact: str, eliminated: str,
                      next_command: str) -> str:
    lines = [
        f"## Restart breadcrumb — {timestamp}",
        "",
        f"- outcome: {outcome}",
        f"- last fact: {last_fact}",
        f"- eliminated: {eliminated}",
        f"- next command: {next_command}",
    ]
    return "\n".join(lines) + "\n"


def _append_entry(path: Path, entry: str) -> None:
    separator = "\n" if path.is_file() and path.stat().st_size else ""
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(separator + entry)


def _split_command(command: str) -> list[str]:
    """Split one command template, preserving Windows and UNC backslashes.

    Tokens split on whitespace; one pair of outer quotes per token is removed
    (single or double), and inside double quotes only backslash-quote unescapes
    to a quote. Every other backslash stays verbatim, so `C:\\Tools\\app.exe`
    and `\\\\server\\share\\x.exe` survive unchanged. An unclosed quote raises
    ValueError.
    """
    tokens: list[str] = []
    token: list[str] = []
    quote = ""
    in_token = False
    index = 0
    while index < len(command):
        character = command[index]
        if quote:
            if character == quote:
                quote = ""
                index += 1
                continue
            if (quote == '"' and character == "\\"
                    and index + 1 < len(command) and command[index + 1] == '"'):
                token.append('"')
                index += 2
                continue
            token.append(character)
            index += 1
            continue
        if character in "'\"":
            quote = character
            in_token = True
            index += 1
            continue
        if character.isspace():
            if in_token:
                tokens.append("".join(token))
                token = []
                in_token = False
            index += 1
            continue
        token.append(character)
        in_token = True
        index += 1
    if quote:
        raise ValueError("unterminated quote")
    if in_token:
        tokens.append("".join(token))
    return tokens


def _run_external(tokens: list[str], timeout: int, payload: str) -> tuple[str, dict]:
    """Run the parsed adapter with the payload substituted into `{text}` or piped to stdin."""
    if any(PLACEHOLDER in token for token in tokens):
        tokens = [token.replace(PLACEHOLDER, payload) for token in tokens]
        stdin_bytes = None
    else:
        stdin_bytes = payload.encode("utf-8")
    options: dict = {}
    if sys.platform == "win32":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    if stdin_bytes is None:
        options["stdin"] = subprocess.DEVNULL
    else:
        options["input"] = stdin_bytes
    try:
        result = subprocess.run(tokens, capture_output=True, timeout=timeout,
                                check=False, **options)
    except subprocess.TimeoutExpired:
        return "failed", {"external_error": f"timed out after {timeout}s"}
    except OSError as error:
        return "failed", {"external_error": f"cannot run external_cmd: {error}"}
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", "replace").strip()
        return "failed", {"external_exit": result.returncode, "external_stderr": stderr[:1000]}
    return "ok", {}


def run_park(args: argparse.Namespace) -> int:
    repo_root = Path(str(sc.resolve(SKILL, KEY_REPO_ROOT, flag=args.repo_root, default=".")))
    bundle = str(sc.resolve(SKILL, KEY_PARKING_BUNDLE, flag=args.parking_bundle,
                            default=DEFAULT_PARKING_BUNDLE))
    if not _safe_bundle(bundle):
        return _fail(f"invalid parking bundle {bundle!r}: use one directory name without "
                     f"'/', '\\', ':', '..', trailing dots, or a reserved device name")
    try:
        store = _resolve_bundle_dir(repo_root, bundle)
    except ValueError as error:
        return _fail(str(error))
    try:
        if args.kind == "side-quest":
            entry = _side_quest_entry(_utc_stamp(), _field_value(args.title, "--title"),
                                      _optional_field(args.why_deferred, "--why-deferred"),
                                      _optional_field(args.origin_outcome, "--origin-outcome"),
                                      _optional_field(args.locator, "--locator"))
        else:
            entry = _breadcrumb_entry(_utc_stamp(),
                                      _field_value(args.outcome, "--outcome"),
                                      _field_value(args.last_fact, "--last-fact"),
                                      _field_value(args.eliminated, "--eliminated"),
                                      _field_value(args.next_command, "--next-command"))
    except ValueError as error:
        return _fail(str(error))
    external_cmd = str(sc.resolve(SKILL, KEY_EXTERNAL_CMD, flag=args.external_cmd,
                                  default="") or "")
    tokens: list[str] | None = None
    if external_cmd:
        if not external_cmd.strip():
            return _fail("external_cmd must not be blank")
        try:
            tokens = _split_command(external_cmd)
        except ValueError as error:
            return _fail(f"cannot parse external_cmd: {error}")
        if not tokens:
            return _fail("external_cmd is empty after parsing")
        if any(PLACEHOLDER in token for token in tokens) and _is_windows_script(tokens[0]):
            return _fail("Windows .cmd/.bat adapters cannot take {text} in argv; omit {text} "
                         "so the entry is piped via stdin")
    timeout = 0
    if tokens is not None and args.confirm_external:
        raw_timeout = sc.resolve(SKILL, KEY_EXTERNAL_TIMEOUT, flag=args.external_timeout,
                                 default=DEFAULT_EXTERNAL_TIMEOUT)
        try:
            timeout = int(str(raw_timeout))
        except ValueError:
            return _fail(f"external_timeout {raw_timeout!r} is not an integer number of seconds")
        if timeout <= 0:
            return _fail(f"external_timeout must be positive, got {timeout}")
    markdown_path = store / PARKING_FILE
    if _is_link(markdown_path):
        return _fail(f"{markdown_path} is a symlink; refusing to write through it")
    if markdown_path.exists() and markdown_path.lstat().st_nlink > 1:
        return _fail(f"{markdown_path} has multiple hard links; refusing to modify it")
    if markdown_path.exists() and not markdown_path.resolve(strict=False).is_relative_to(
            store.resolve(strict=False)):
        return _fail(f"{markdown_path} escapes {store}; refusing to write")
    store.mkdir(parents=True, exist_ok=True)
    try:
        _ensure_gitignore(store)
    except ValueError as error:
        return _fail(str(error))
    _append_entry(markdown_path, entry)
    receipt = {
        "status": "parked",
        "kind": args.kind,
        "local_path": str(markdown_path),
        "external_status": "not_configured",
    }
    if tokens is not None:
        if not args.confirm_external:
            receipt["external_status"] = "skipped_unconfirmed"
        else:
            status, detail = _run_external(tokens, timeout, entry)
            receipt["external_status"] = status
            receipt.update(detail)
    _emit(sys.stdout, json.dumps(receipt, ensure_ascii=False) + "\n")
    return EXIT_EXTERNAL_FAILED if receipt["external_status"] == "failed" else 0


def _require_text(value, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where} must be a non-empty string")
    if _has_surrogate(value):
        raise ValueError(f"{where} contains an unpaired UTF-16 surrogate")
    return value


def _string_list(value, where: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{where} must be a list of strings")
    return [_require_text(item, f"{where}[{index}]") for index, item in enumerate(value)]


def _validate_hypotheses(value) -> list[dict]:
    if not isinstance(value, list):
        raise ValueError("hypotheses must be a list")
    items = []
    for index, item in enumerate(value):
        where = f"hypotheses[{index}]"
        if isinstance(item, str):
            items.append({"text": _require_text(item, where), "status": "live", "note": ""})
            continue
        if not isinstance(item, dict):
            raise ValueError(f"{where} must be a string or an object with a text field")
        unknown = sorted(set(item) - {"text", "status", "note"})
        if unknown:
            raise ValueError(f"{where} has unknown keys: {', '.join(unknown)}")
        status = item.get("status", "live")
        if status not in HYPOTHESIS_STATUSES:
            raise ValueError(f"{where}.status must be one of {', '.join(HYPOTHESIS_STATUSES)}")
        note = item.get("note", "")
        items.append({"text": _require_text(item.get("text"), f"{where}.text"),
                      "status": status,
                      "note": _require_text(note, f"{where}.note") if note else ""})
    return items


def _validate_probe(value) -> dict | None:
    if value is None:
        return None
    if isinstance(value, str):
        return {"command": _require_text(value, "probe"), "pass": "", "fail": ""}
    if not isinstance(value, dict):
        raise ValueError("probe must be a string or an object")
    unknown = sorted(set(value) - set(PROBE_KEYS))
    if unknown:
        raise ValueError(f"probe has unknown keys: {', '.join(unknown)}")
    if "command" not in value:
        raise ValueError("probe object must include a command string")
    probe = {"command": _require_text(value["command"], "probe.command"), "pass": "", "fail": ""}
    for optional in ("pass", "fail"):
        if optional in value:
            probe[optional] = _require_text(value[optional], f"probe.{optional}")
    return probe


def _validate_side_quests(value) -> list[dict]:
    if not isinstance(value, list):
        raise ValueError("side_quests must be a list")
    items = []
    for index, item in enumerate(value):
        where = f"side_quests[{index}]"
        if isinstance(item, str):
            items.append({"title": _require_text(item, where), "note": ""})
            continue
        if not isinstance(item, dict):
            raise ValueError(f"{where} must be a string or an object with a title field")
        unknown = sorted(set(item) - {"title", "note"})
        if unknown:
            raise ValueError(f"{where} has unknown keys: {', '.join(unknown)}")
        note = item.get("note", "")
        items.append({"title": _require_text(item.get("title"), f"{where}.title"),
                      "note": _require_text(note, f"{where}.note") if note else ""})
    return items


def _validate_board(data) -> dict:
    if not isinstance(data, dict):
        raise ValueError("input must be a JSON object")
    unknown = sorted(set(data) - set(BOARD_KEYS))
    if unknown:
        raise ValueError(f"unknown input keys: {', '.join(unknown)}")
    return {
        "outcome": _require_text(data.get("outcome"), "outcome"),
        "verified_facts": _string_list(data.get("verified_facts", []), "verified_facts"),
        "hypotheses": _validate_hypotheses(data.get("hypotheses", [])),
        "probe": _validate_probe(data.get("probe")),
        "side_quests": _validate_side_quests(data.get("side_quests", [])),
    }


def _esc(value) -> str:
    return html.escape(str(value))


def _facts_column(board: dict) -> str:
    facts = board["verified_facts"]
    if facts:
        listing = "<ul>" + "".join(f"<li>{_esc(fact)}</li>" for fact in facts) + "</ul>"
    else:
        listing = '<p class="empty">No verified facts recorded.</p>'
    return ('<section><h2>Target outcome &amp; verified facts</h2>'
            f'<p class="outcome">{_esc(board["outcome"])}</p>{listing}</section>')


def _named_items(items: list[dict], key: str, text_key: str, item_class: str) -> str:
    if not items:
        return f'<p class="empty">No {text_key} recorded.</p>'
    attribute = f' class="{item_class}"' if item_class else ""
    entries = []
    for item in items:
        note = f' <span class="note">{_esc(item["note"])}</span>' if item["note"] else ""
        entries.append(f"<li{attribute}>{_esc(item[key])}{note}</li>")
    return "<ul>" + "".join(entries) + "</ul>"


def _live_column(board: dict) -> str:
    live = [item for item in board["hypotheses"] if item["status"] == "live"]
    listing = _named_items(live, "text", "live hypotheses", "live")
    probe = board["probe"]
    if probe is None:
        probe_html = '<p class="empty">No discriminating probe recorded.</p>'
    else:
        parts = [f'<p><code>{_esc(probe["command"])}</code></p>']
        if probe["pass"]:
            parts.append(f'<p class="note"><strong>Pass proves:</strong> {_esc(probe["pass"])}</p>')
        if probe["fail"]:
            parts.append(f'<p class="note"><strong>Fail proves:</strong> {_esc(probe["fail"])}</p>')
        probe_html = '<div class="probe">' + "".join(parts) + "</div>"
    return ('<section><h2>Active fork &mdash; live hypotheses '
            f'<span class="count">({len(live)})</span></h2>'
            f"{listing}"
            f"<h3>Single discriminating probe</h3>{probe_html}"
            '<h3>Decision &mdash; pick one</h3><ol class="actions">'
            "<li><strong>A. Run probe</strong> &mdash; execute only the read-only probe above.</li>"
            "<li><strong>B. Freeze &amp; park</strong> &mdash; write a 4-line restart breadcrumb "
            "with <code>park --kind breadcrumb</code> and stop cleanly.</li>"
            "<li><strong>C. Retire branch/approach</strong> &mdash; record the falsified lesson "
            "with <code>park</code> and await explicit rollback authorization before touching "
            "Git state.</li></ol></section>")


def _eliminated_column(board: dict) -> str:
    eliminated = [item for item in board["hypotheses"] if item["status"] == "eliminated"]
    eliminated_listing = _named_items(eliminated, "text", "eliminated hypotheses", "dead")
    quest_listing = _named_items(board["side_quests"], "title", "parked side quests", "")
    return ('<section><h2>Eliminated hypotheses &amp; parked side quests</h2>'
            f'<h3>Eliminated <span class="count">({len(eliminated)})</span></h3>'
            f"{eliminated_listing}"
            f'<h3>Parked side quests <span class="count">({len(board["side_quests"])})</span></h3>'
            f"{quest_listing}</section>")


def _render_html(bundle: str, generated: str, board: dict) -> str:
    columns = _facts_column(board) + _live_column(board) + _eliminated_column(board)
    return ("<!doctype html>\n"
            '<html lang="en">\n<head>\n'
            '<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f"<title>spin-breaker map &mdash; {_esc(bundle)}</title>\n"
            f"<style>{PAGE_CSS}</style>\n"
            "</head>\n<body>\n"
            '<header><h1>Decision &amp; elimination board</h1>'
            f'<p class="meta">bundle <code>{_esc(bundle)}</code> &middot; generated '
            f"{_esc(generated)}</p></header>\n"
            f'<main class="board">{columns}</main>\n'
            "</body>\n</html>\n")


def _dump_json(payload: dict) -> str:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    for character, escape in (("&", "\\u0026"), ("<", "\\u003c"), (">", "\\u003e")):
        text = text.replace(character, escape)
    return text + "\n"


def run_map(args: argparse.Namespace) -> int:
    repo_root = Path(str(sc.resolve(SKILL, KEY_REPO_ROOT, flag=args.repo_root, default=".")))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    if args.bundle is not None and not _safe_bundle(args.bundle):
        return _fail(f"invalid bundle {args.bundle!r}: use one directory name without "
                     f"'/', '\\', ':', '..', trailing dots, or a reserved device name")
    if args.input == "-":
        try:
            raw = sys.stdin.buffer.read().decode("utf-8-sig")
        except UnicodeDecodeError as error:
            return _fail(f"stdin is not valid UTF-8: {error}")
    else:
        try:
            raw = Path(args.input).read_bytes().decode("utf-8-sig")
        except OSError as error:
            return _fail(f"cannot read {args.input}: {error}")
        except UnicodeDecodeError as error:
            return _fail(f"{args.input} is not valid UTF-8: {error}")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        return _fail(f"{args.input}: invalid JSON: {error}")
    try:
        board = _validate_board(data)
    except ValueError as error:
        return _fail(f"{args.input}: {error}")
    artifacts = repo_root / ARTIFACT_DIR
    if _is_link(artifacts):
        return _fail(f"{artifacts} is a symlink or junction; refusing to write through it")
    artifacts.mkdir(parents=True, exist_ok=True)
    if args.bundle is not None:
        bundle = args.bundle
        try:
            target = _resolve_bundle_dir(repo_root, bundle)
        except ValueError as error:
            return _fail(str(error))
        try:
            target.mkdir(parents=False, exist_ok=False)
        except FileExistsError:
            return _fail(f"bundle {bundle!r} already exists; choose a new --bundle name")
    else:
        counter = 0
        while True:
            counter += 1
            bundle = f"spin-map-{stamp}" if counter == 1 else f"spin-map-{stamp}-{counter}"
            try:
                target = _resolve_bundle_dir(repo_root, bundle)
            except ValueError as error:
                return _fail(str(error))
            try:
                target.mkdir(parents=False, exist_ok=False)
            except FileExistsError:
                continue
            break
    generated = _utc_stamp()
    try:
        _ensure_gitignore(target)
    except ValueError as error:
        return _fail(str(error))
    html_path = target / f"{bundle}.html"
    data_path = target / "_map_data.json"
    if _is_link(html_path) or _is_link(data_path):
        return _fail(f"{target} holds a symlinked output file; refusing to write")
    html_path.write_text(_render_html(bundle, generated, board), encoding="utf-8", newline="\n")
    data_path.write_text(_dump_json({"bundle": bundle, "generated_at": generated, **board}),
                         encoding="utf-8", newline="\n")
    _emit(sys.stdout, json.dumps(
        {"html_path": str(html_path), "data_path": str(data_path), "bundle": bundle},
        ensure_ascii=False) + "\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False)
    subparsers = parser.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    common.add_argument("--repo-root",
                        help="repository root holding .tmp-artifacts/ (default: current directory)")
    park = subparsers.add_parser("park", parents=[common], allow_abbrev=False,
                                 help="append a side quest or 4-line restart breadcrumb")
    park.add_argument("--kind", choices=("side-quest", "breadcrumb"), required=True,
                      help="entry kind to append")
    park.add_argument("--title", help="side-quest title (required for --kind side-quest)")
    park.add_argument("--why-deferred", help="side-quest: why this item is deferred")
    park.add_argument("--origin-outcome", help="side-quest: the original user-visible outcome")
    park.add_argument("--locator", help="side-quest: file:line or target-surface locator")
    park.add_argument("--outcome", help="breadcrumb: the original user-visible outcome")
    park.add_argument("--last-fact", help="breadcrumb: last directly verified fact with locator")
    park.add_argument("--eliminated", help="breadcrumb: hypothesis eliminated by the last fact")
    park.add_argument("--next-command", help="breadcrumb: one minimal restart command")
    park.add_argument("--parking-bundle",
                      help="bundle directory under .tmp-artifacts/ (default: spin-breaker)")
    park.add_argument("--external-cmd", help="optional external adapter command template")
    park.add_argument("--external-timeout", help="external adapter timeout in seconds (default: 15)")
    park.add_argument("--confirm-external", action="store_true",
                      help="confirm running the configured external adapter (never implicit)")
    mapping = subparsers.add_parser("map", parents=[common], allow_abbrev=False,
                                    help="render a static HTML decision board from JSON")
    mapping.add_argument("--input", required=True, help="UTF-8 JSON file, or - for stdin")
    mapping.add_argument("--bundle",
                         help="bundle directory name (default: spin-map-<UTC timestamp>)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "park":
            return run_park(args)
        return run_map(args)
    except sc.ConfigError as error:
        return _fail(str(error))
    except OSError as error:
        return _fail(str(error))


if __name__ == "__main__":
    sys.exit(main())
