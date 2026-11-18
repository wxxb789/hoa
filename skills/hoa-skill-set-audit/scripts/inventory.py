#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.7"
# dependencies = []
# ///
"""Inventory one or more skill roots as JSON for a set-level skill audit.

Walks each root for skill directories (a directory holding SKILL.md; the walk
stops there and skips node_modules, .git and __pycache__) and prints one JSON
document to stdout:

  roots       every scanned root: path, label, host, exists, host depth
  skills      per copy: name, dir (as found), realpath, root, depth, link kind,
              frontmatter keys, description/when_to_use length, hidden flags
              (frontmatter + agents/openai.yaml), ../ sibling links (relative to
              the file holding them) with lexical and physical status, broken
              intra-skill links, bundled files the body never names, body
              lines, content hash
  duplicates  by_name (same name, distinct realpaths, same_content flag),
              by_hash (different names, identical content), aliases (one
              realpath reached through several roots); compares only the roots
              of one run, so pass every host in play together
  overlap     description pairs ranked by token Jaccard similarity; with
              --offered, offered-only entries join by their listing text
  offered     with --offered: the session's skill listing diffed against disk
              (count, without_description, not_on_disk, hidden_but_offered,
              visible_not_offered, offered_twice); a namespaced `plugin:name`
              entry never matches a disk copy of `name`
  totals      copies, unique names, model-visible count and description chars
  findings    severity error|warn|info, kind, skill, detail

Roots come from --root (repeatable), --host presets (repeatable, resolved
against the home directory and --project), or SKILL_SET_AUDIT_ROOTS (os.pathsep
separated) when neither flag is given. Content hashes normalize CRLF to LF so a
Windows checkout does not read as drift. Host-specific description caps
apply only when that host is in --host or a root carries no host.

Exit codes: 0 inventory printed, no error/warn findings; 1 inventory printed
with at least one error/warn finding; 2 usage error (no roots, no root exists,
unreadable --offered file).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from itertools import combinations
from pathlib import Path

SKIP_DIRS = {"node_modules", ".git", "__pycache__"}
RESOURCE_DIRS = ("references", "scripts", "assets")
DESCRIPTION_CAPS = (  # (label, chars, severity, host; None = every host) -- sources in references/hosts.md
    ("agentskills-spec", 1024, "warn", None),
    ("dsh-catalog", 500, "info", "dsh"),
)
CLAUDE_ENTRY_CAP = 1536  # description + when_to_use, truncated in the listing
BODY_LINE_LIMIT = 500
STOPWORDS = set("""
the and for not use when with this that from into your you are any all its it's
one two via per but its than then them they their what which who how why can
only also more most must should would will out off own same each other such
skill skills agent agents user users asked request requests work task tasks
""".split())

# A `../` run that starts a path token (not `x/../`), then a name segment and the rest.
SIBLING_LINK = re.compile(r"(?<![\w./-])((?:\.\./)+)([A-Za-z0-9_][A-Za-z0-9._-]*)(/[^\s)\]`'\"<>|]*)?")
SKILL_LAYOUT = re.compile(r"^/(SKILL\.md$|references/|scripts/|assets/)")
MD_LINK = re.compile(r"\]\(([^)\s]+)\)")
MD_LINK_SPAN = re.compile(r"\[[^\]\n]*\]\([^)\s]+\)")
BACKTICK_NAME = re.compile(r"`([A-Za-z0-9][A-Za-z0-9._-]*)`")
OTHER_SKILL_WINDOW = 200  # chars before a code path searched for another skill's `name`
CODE_REF = re.compile(r"`((?:references|scripts|assets|agents)/[^`\s]+)`")
OFFERED_LINE = re.compile(r"^\s*-\s+(\S+?):?(?:\s+(.*))?$")


def _home_roots(env: str, default: str) -> Path:
    value = os.environ.get(env)
    return Path(value).expanduser() if value else Path.home() / default


def host_presets(project: Path) -> dict[str, list[tuple[str, Path, int | None]]]:
    """Documented default roots per host, highest precedence first where known.

    Each entry is (label, path, host_depth); host_depth is how many levels below
    the root the host discovers a SKILL.md (None: deeper or unknown).
    """
    home = Path.home()
    claude = _home_roots("CLAUDE_CONFIG_DIR", ".claude")
    codex = _home_roots("CODEX_HOME", ".codex")
    return {
        "claude": [("claude-user", claude / "skills", 1),
                   ("claude-project", project / ".claude" / "skills", 1)],
        "codex": [("codex-project", project / ".agents" / "skills", None),
                  ("codex-user", codex / "skills", None),
                  ("agents-user", home / ".agents" / "skills", None)],
        "pi": [("pi-project", project / ".pi" / "skills", None),
               ("pi-user", home / ".pi" / "agent" / "skills", None)],
        # ~/.claude/skills only with skills.enableClaudeUser (default false): add it with --root.
        "omp": [("omp-project", project / ".omp" / "skills", 1),
                ("omp-user", home / ".omp" / "agent" / "skills", 1),
                ("agents-user", home / ".agents" / "skills", 1)],
        "opencode": [("opencode-project", project / ".opencode" / "skills", None),
                     ("opencode-user", home / ".config" / "opencode" / "skills", None),
                     ("claude-project", project / ".claude" / "skills", None),
                     ("claude-user", claude / "skills", None),
                     ("agents-project", project / ".agents" / "skills", None),
                     ("agents-user", home / ".agents" / "skills", None)],
        "dsh": [("dsh-project", project / ".dsh" / "skills", None),
                ("agents-project", project / ".agents" / "skills", None),
                ("dsh-user", home / ".dsh" / "skills", None),
                ("agents-user", home / ".agents" / "skills", None)],
    }


# --- minimal YAML subset: top-level scalars, block scalars, one nested mapping --

def _scalar(raw: str):
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        return raw[1:-1]
    if raw in ("true", "True", "TRUE"):
        return True
    if raw in ("false", "False", "FALSE"):
        return False
    return raw


def _block(lines: list[str], style: str) -> str:
    body = [line.strip() for line in lines]
    if style.startswith("|"):
        text = "\n".join(body)
    else:
        text, gap = "", False
        for line in body:
            if not line:
                gap = True
                continue
            text += ("\n" if gap else " ") + line if text else line
            gap = False
    return text.strip()


def parse_yaml_subset(lines: list[str]) -> dict:
    """Parse the frontmatter shapes skills use; raise ValueError on anything else."""
    data: dict = {}
    index = 0
    key_line = re.compile(r"^([A-Za-z0-9_./-]+):(?:\s+(.*?))?\s*$")
    while index < len(lines):
        line = lines[index]
        if not line.strip() or line.lstrip().startswith("#"):
            index += 1
            continue
        if line[0] in " \t":
            raise ValueError(f"unexpected indentation at line {index + 1}: {line.strip()!r}")
        match = key_line.match(line)
        if not match:
            raise ValueError(f"not a 'key: value' line {index + 1}: {line.strip()!r}")
        key, value = match.group(1), (match.group(2) or "")
        if key in data:
            raise ValueError(f"duplicate key {key!r}")
        index += 1
        children = []
        while index < len(lines) and (not lines[index].strip() or lines[index][0] in " \t"):
            children.append(lines[index])
            index += 1
        while children and not children[-1].strip():
            children.pop()
        if value[:1] in (">", "|"):
            data[key] = _block(children, value)
        elif value:
            data[key] = _scalar(" ".join([value] + [c.strip() for c in children]))
        elif children and children[0].strip().startswith("- "):
            data[key] = [_scalar(c.strip()[2:]) for c in children if c.strip()]
        elif children:
            data[key] = parse_yaml_subset(_dedent(children))
        else:
            data[key] = None
    return data


def _dedent(lines: list[str]) -> list[str]:
    width = min(len(l) - len(l.lstrip()) for l in lines if l.strip())
    return [l[width:] for l in lines]


def read_frontmatter(skill_md: Path) -> tuple[dict, str | None, str]:
    """Return (frontmatter, error, body); tolerant of a BOM and CRLF."""
    text = skill_md.read_text(encoding="utf-8", errors="replace").lstrip("\ufeff")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, "missing frontmatter opening ---", text
    for end in range(1, len(lines)):
        if lines[end].strip() == "---":
            break
    else:
        return {}, "missing frontmatter closing ---", text
    body = "\n".join(lines[end + 1:])
    try:
        return parse_yaml_subset(lines[1:end]), None, body
    except ValueError as error:
        return {}, str(error), body


# --- filesystem ------------------------------------------------------------

def _files(directory: Path):
    for path in sorted(directory.rglob("*")):
        if path.is_file() and not SKIP_DIRS.intersection(path.relative_to(directory).parts):
            yield path


def content_hash(target: Path) -> str | None:
    """sha256 over relative paths and CRLF-normalized bytes; None when absent."""
    digest = hashlib.sha256()
    if target.is_file():
        digest.update(target.read_bytes().replace(b"\r\n", b"\n"))
    elif target.is_dir():
        for path in _files(target):
            digest.update(path.relative_to(target).as_posix().encode("utf-8") + b"\0")
            digest.update(path.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    else:
        return None
    return digest.hexdigest()[:16]


def link_kind(path: Path) -> str | None:
    if path.is_symlink():
        return "symlink"
    is_junction = getattr(path, "is_junction", None)
    return "junction" if is_junction and is_junction() else None


def discover(root: Path, max_depth: int):
    """Yield (skill_dir, depth); stop at a SKILL.md, follow links, avoid cycles."""
    seen: set[str] = set()

    def walk(directory: Path, depth: int):
        real = os.path.realpath(directory)
        if real in seen:
            return
        seen.add(real)
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            return
        for entry in entries:
            if entry.name in SKIP_DIRS or not entry.is_dir():
                continue
            if (entry / "SKILL.md").is_file():
                yield entry, depth
            elif depth < max_depth:
                yield from walk(entry, depth + 1)

    yield from walk(root, 1)


def sibling_links(skill_dir: Path, texts: dict[str, str], skill_names: set[str]) -> list[dict]:
    """Check every ../<sibling>/ reference lexically and physically.

    A path resolves relative to the file that holds it (for SKILL.md, the skill
    directory), so in `references/x.md` a sibling is `../../<sibling>/`; fewer
    `../` stay inside the skill, more leave the host root. A sibling counts only
    when it is a scanned skill name or the path continues into a skill layout
    (SKILL.md, references/, scripts/, assets/).
    """
    lexical_base = os.path.abspath(skill_dir)
    physical_base = os.path.realpath(skill_dir)
    links, seen = [], set()
    for source, text in texts.items():
        depth = len(source.split("/")) - 1
        for match in SIBLING_LINK.finditer(text):
            ups = match.group(1).count("../")
            sibling, rest = match.group(2), (match.group(3) or "").split("#", 1)[0].rstrip(".,;:")
            if ups != depth + 1 or "<" in rest or "*" in rest or (source, sibling, rest) in seen:
                continue
            if sibling not in skill_names and not SKILL_LAYOUT.match(rest):
                continue
            seen.add((source, sibling, rest))
            relative = f"../{sibling}{rest}"  # from the skill directory
            lexical = Path(os.path.normpath(os.path.join(lexical_base, relative)))
            physical = Path(os.path.normpath(os.path.join(physical_base, relative)))
            links.append({"source": source, "ref": match.group(1) + sibling + rest,
                          "lexical": str(lexical), "physical": str(physical),
                          "status": closure_status(lexical, physical,
                                                   Path(lexical_base).parent / sibling,
                                                   Path(physical_base).parent / sibling)})
    return links


def closure_status(lexical: Path, physical: Path, lexical_skill: Path, physical_skill: Path) -> str:
    lexical_ok, physical_ok = lexical.exists(), physical.exists()
    if lexical_ok and physical_ok:
        if os.path.realpath(lexical) == os.path.realpath(physical):
            return "ok"
        same = content_hash(lexical_skill) == content_hash(physical_skill)
        return "ok-identical" if same else "diverged"
    if lexical_ok:
        return "lexical-only"
    return "physical-only" if physical_ok else "missing"


def intra_links(skill_dir: Path, body: str, other_skills: set[str]) -> list[str]:
    """Markdown link targets and backticked resource paths that do not exist.

    A backticked path inside link text defers to the link target. One that
    follows another skill's backticked name in the same paragraph (within
    OTHER_SKILL_WINDOW chars, e.g. "skill `gdd` -> `references/x.md`") is that
    skill's path and is skipped.
    """
    targets = [m.group(1) for m in MD_LINK.finditer(body)]
    prose = MD_LINK_SPAN.sub(lambda m: " " * len(m.group(0)), body)
    for match in CODE_REF.finditer(prose):
        window = prose[max(0, match.start() - OTHER_SKILL_WINDOW):match.start()].rsplit("\n\n", 1)[-1]
        if not other_skills.intersection(BACKTICK_NAME.findall(window)):
            targets.append(match.group(1))
    broken = []
    for target in targets:
        target = target.split("#", 1)[0]
        if (not target or "://" in target or target.startswith(("mailto:", "../", "/", "~", "$"))
                or any(ch in target for ch in "<>*{}") or not any(ch in target for ch in "./")
                or SKIP_DIRS.intersection(target.split("/"))):
            continue
        path_part = target.split(":", 1)[0]  # scripts/x.py:function
        if not (skill_dir / path_part).exists() and target not in broken:
            broken.append(target)
    return broken


def unreferenced(skill_dir: Path, body: str) -> list[str]:
    missing = []
    for folder in RESOURCE_DIRS:
        base = skill_dir / folder
        if not base.is_dir():
            continue
        for entry in sorted(base.iterdir()):
            name = entry.name
            if name in SKIP_DIRS or name == "tests" or name.startswith(("test_", "test-", ".")):
                continue
            relative = f"{folder}/{name}"
            # A directory needs its path named; a file may be named alone.
            if relative not in body and (entry.is_dir() or name not in body):
                missing.append(relative)
    return missing


def openai_policy(skill_dir: Path) -> bool | None:
    path = skill_dir / "agents" / "openai.yaml"
    if not path.is_file():
        return None
    try:
        data = parse_yaml_subset(path.read_text(encoding="utf-8").splitlines())
    except ValueError:
        return None
    policy = data.get("policy")
    value = policy.get("allow_implicit_invocation") if isinstance(policy, dict) else None
    return value if isinstance(value, bool) else None


def inspect_skill(skill_dir: Path, root: dict, depth: int, skill_names: set[str],
                  hosts: set[str | None]) -> tuple[dict, list[dict]]:
    skill_md = skill_dir / "SKILL.md"
    frontmatter, error, body = read_frontmatter(skill_md)
    name = frontmatter.get("name") if isinstance(frontmatter.get("name"), str) else skill_dir.name
    description = frontmatter.get("description")
    description = description if isinstance(description, str) else ""
    when = frontmatter.get("when_to_use") if isinstance(frontmatter.get("when_to_use"), str) else ""
    metadata = frontmatter.get("metadata") if isinstance(frontmatter.get("metadata"), dict) else {}
    hidden_key = frontmatter.get("disable-model-invocation")
    texts = {"SKILL.md": body}
    for folder in ("references",):
        for path in _files(skill_dir / folder) if (skill_dir / folder).is_dir() else ():
            if path.suffix == ".md":
                texts[path.relative_to(skill_dir).as_posix()] = path.read_text(encoding="utf-8", errors="replace")
    record = {
        "name": name,
        "dir": str(skill_dir),
        "realpath": os.path.realpath(skill_dir),
        "root": root["path"],
        "root_label": root["label"],
        "depth": depth,
        "link": link_kind(skill_dir),
        "frontmatter_keys": sorted(frontmatter),
        "frontmatter_error": error,
        "kind": metadata.get("kind"),
        "description": description,
        "description_chars": len(description),
        "when_to_use_chars": len(when),
        "hidden": {
            "disable_model_invocation": hidden_key is True,
            "codex_allow_implicit": openai_policy(skill_dir),
            "opencode_autoinvoke": metadata.get("opencode/autoinvoke"),
        },
        "sibling_links": sibling_links(skill_dir, texts, skill_names),
        "broken_links": intra_links(skill_dir, body, skill_names - {name, skill_dir.name}),
        "unreferenced_files": unreferenced(skill_dir, body),
        "body_lines": len(body.splitlines()),
        "hash": content_hash(skill_dir),
    }
    return record, skill_findings(record, frontmatter, skill_dir, root, hosts)


def skill_findings(record: dict, frontmatter: dict, skill_dir: Path, root: dict,
                   hosts: set[str | None]) -> list[dict]:
    out = []

    def add(severity, kind, detail):
        out.append({"severity": severity, "kind": kind, "skill": record["name"],
                    "dir": record["dir"], "detail": detail})

    if record["frontmatter_error"]:
        add("error", "frontmatter-invalid", record["frontmatter_error"])
    else:
        if not record["description"].strip():
            add("error", "description-missing", "description must be a non-empty string")
        if record["name"] != skill_dir.name:
            add("warn", "name-mismatch", f"name {record['name']!r} != directory {skill_dir.name!r}")
    for label, cap, severity, host in DESCRIPTION_CAPS:
        if (host is None or host in hosts or None in hosts) and record["description_chars"] > cap:
            add(severity, "description-over-cap", f"{record['description_chars']} chars > {label} {cap}")
    combined = record["description_chars"] + record["when_to_use_chars"]
    if combined > CLAUDE_ENTRY_CAP:
        add("warn", "listing-entry-over-cap", f"description+when_to_use {combined} > claude {CLAUDE_ENTRY_CAP}")
    if "disableModelInvocation" in frontmatter:
        add("warn", "hidden-key-camelcase", "use kebab-case disable-model-invocation; DSH drops camelCase")
    hidden_key = frontmatter.get("disable-model-invocation")
    if hidden_key is not None and not isinstance(hidden_key, bool):
        add("warn", "hidden-not-boolean", f"disable-model-invocation is {hidden_key!r}, not a YAML boolean")
    if frontmatter.get("user-invocable") is False:
        add("warn", "user-invocable-false", "removes the skill from the user's / menu")
    hidden = record["hidden"]
    if hidden["disable_model_invocation"] and hidden["codex_allow_implicit"] is not False:
        add("warn", "codex-policy-missing", "hidden skill lacks agents/openai.yaml policy.allow_implicit_invocation: false")
    if hidden["codex_allow_implicit"] is False and not hidden["disable_model_invocation"]:
        add("warn", "hidden-codex-only", "openai.yaml hides it from Codex but frontmatter leaves it visible elsewhere")
    for link in record["sibling_links"]:
        if link["status"] not in ("ok", "ok-identical"):
            add("error", f"closure-{link['status']}", f"{link['source']}: {link['ref']}")
    for target in record["broken_links"]:
        add("warn", "broken-link", target)
    for relative in record["unreferenced_files"]:
        add("info", "unreferenced-file", f"{relative} not named in SKILL.md")
    if record["body_lines"] > BODY_LINE_LIMIT:
        add("info", "body-over-limit", f"{record['body_lines']} lines > {BODY_LINE_LIMIT}")
    if root["host_depth"] is not None and record["depth"] > root["host_depth"]:
        add("warn", "beyond-host-depth",
            f"depth {record['depth']} > {root['host_depth']}: {root['label']} does not discover it")
    return out


# --- set level ---------------------------------------------------------------

def tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z0-9-]{2,}", text.lower()) if w not in STOPWORDS}


def overlap_pairs(skills: list[dict], threshold: float, limit: int) -> list[dict]:
    first: dict[str, dict] = {}
    for skill in skills:
        first.setdefault(skill["name"], skill)
    # Name parts count; other skills' full names (cross-references in anti-triggers) do not.
    bags = {name: tokens(s["description"] + " " + name.replace("-", " ")) - set(first)
            for name, s in first.items()}
    pairs = []
    for a, b in combinations(sorted(bags), 2):
        union = bags[a] | bags[b]
        if not union:
            continue
        score = len(bags[a] & bags[b]) / len(union)
        if score >= threshold:
            pairs.append({"a": a, "b": b, "score": round(score, 3),
                          "shared": sorted(bags[a] & bags[b])[:12],
                          "hidden": [n for n in (a, b) if first[n]["hidden"]["disable_model_invocation"]]})
    pairs.sort(key=lambda p: (-p["score"], p["a"], p["b"]))
    return pairs[:limit]


def duplicates(skills: list[dict]) -> tuple[dict, list[dict]]:
    by_name: dict[str, list[dict]] = {}
    by_real: dict[str, list[dict]] = {}
    by_hash: dict[str, list[dict]] = {}
    for skill in skills:
        by_name.setdefault(skill["name"], []).append(skill)
        by_real.setdefault(skill["realpath"], []).append(skill)
        by_hash.setdefault(skill["hash"], []).append(skill)
    result = {"by_name": [], "by_hash": [], "aliases": []}
    findings = []
    for name, copies in sorted(by_name.items()):
        reals = sorted({c["realpath"] for c in copies})
        if len(reals) < 2:
            continue
        same = len({c["hash"] for c in copies}) == 1
        entry = {"name": name, "same_content": same,
                 "copies": [{"root_label": c["root_label"], "dir": c["dir"], "realpath": c["realpath"],
                             "hash": c["hash"]} for c in copies]}
        result["by_name"].append(entry)
        if not same:
            findings.append({"severity": "warn", "kind": "same-name-diverged", "skill": name, "dir": copies[0]["dir"],
                             "detail": "; ".join(f"{c['root_label']}={c['hash']}" for c in copies)})
    for digest, copies in sorted(by_hash.items()):
        names = sorted({c["name"] for c in copies})
        if len(names) > 1:
            result["by_hash"].append({"hash": digest, "names": names})
            findings.append({"severity": "warn", "kind": "same-content-different-names", "skill": names[0],
                             "dir": copies[0]["dir"], "detail": ", ".join(names)})
    for real, copies in sorted(by_real.items()):
        if len(copies) > 1:
            result["aliases"].append({"realpath": real, "dirs": [c["dir"] for c in copies]})
    return result, findings


def offered_entries(text: str) -> list[tuple[str, str]]:
    entries = []
    for line in text.splitlines():
        match = OFFERED_LINE.match(line)
        if match:
            entries.append((match.group(1).rstrip(":"), (match.group(2) or "").strip()))
    return entries


def offered_diff(entries: list[tuple[str, str]], skills: list[dict]) -> tuple[dict, list[dict]]:
    """Diff the listing against disk. A namespaced `plugin:name` entry is a plugin
    skill, never the disk copy of `name`; entries sharing a bare name are each
    offered to the model."""
    on_disk = {}
    for skill in skills:
        on_disk.setdefault(skill["name"], skill)
    not_on_disk, hidden_offered, by_bare = [], [], {}
    for name, _ in entries:
        by_bare.setdefault(name.rsplit(":", 1)[-1], []).append(name)
        skill = on_disk.get(name)
        if skill is None:
            not_on_disk.append(name)
        elif skill["hidden"]["disable_model_invocation"]:
            hidden_offered.append(name)
    offered_names = {name for name, _ in entries}
    visible_not_offered = sorted(n for n, s in on_disk.items()
                                 if n not in offered_names and not s["hidden"]["disable_model_invocation"])
    without = [name for name, desc in entries if not desc]
    twice = {bare: names for bare, names in sorted(by_bare.items()) if len(names) > 1}
    result = {"count": len(entries), "with_description": len(entries) - len(without),
              "without_description": without, "not_on_disk": not_on_disk,
              "hidden_but_offered": hidden_offered, "visible_not_offered": visible_not_offered,
              "offered_twice": twice}
    findings = [{"severity": "warn", "kind": "hidden-but-offered", "skill": n, "dir": None,
                 "detail": "disable-model-invocation on disk, yet in the session listing"} for n in hidden_offered]
    findings += [{"severity": "warn", "kind": "offered-twice", "skill": bare, "dir": None,
                  "detail": ", ".join(names)} for bare, names in twice.items()]
    if without:
        findings.append({"severity": "warn", "kind": "listing-truncated", "skill": None, "dir": None,
                         "detail": f"{len(without)} of {len(entries)} offered skills have no description"})
    return result, findings


# --- cli -------------------------------------------------------------------------

def resolve_roots(args) -> list[dict]:
    roots = []
    for path in args.root or []:
        roots.append({"label": "root", "path": Path(path).expanduser(), "host_depth": None, "host": None})
    presets = host_presets(Path(args.project).expanduser().absolute())
    for host in args.host or []:
        for label, path, depth in presets[host]:
            roots.append({"label": label, "path": path, "host_depth": depth, "host": host})
    if not roots and os.environ.get("SKILL_SET_AUDIT_ROOTS"):
        for path in os.environ["SKILL_SET_AUDIT_ROOTS"].split(os.pathsep):
            if path:
                roots.append({"label": "env", "path": Path(path).expanduser(), "host_depth": None, "host": None})
    unique, seen = [], set()
    for root in roots:
        key = os.path.abspath(root["path"])
        if key not in seen:
            seen.add(key)
            root["path"] = key
            root["exists"] = os.path.isdir(key)
            unique.append(root)
    return unique


def build(roots: list[dict], max_depth: int, offered: str | None, threshold: float, limit: int,
          hosts: set[str | None]) -> dict:
    """`hosts` selects host-specific caps; None in it (an unlabeled root) applies every cap."""
    skills, findings, discovered = [], [], []
    for root in roots:
        if not root["exists"]:
            continue
        discovered.extend((root, d, depth) for d, depth in discover(Path(root["path"]), max_depth))
    skill_names = {skill_dir.name for _, skill_dir, _ in discovered}
    for root, skill_dir, depth in discovered:
        record, found = inspect_skill(skill_dir, root, depth, skill_names, hosts)
        skills.append(record)
        findings.extend(found)
    dupes, dupe_findings = duplicates(skills)
    findings.extend(dupe_findings)
    report = {"roots": roots, "skills": skills, "duplicates": dupes}
    candidates = skills
    if offered is not None:
        entries = offered_entries(offered)
        report["offered"], offered_findings = offered_diff(entries, skills)
        findings.extend(offered_findings)
        # Offered-only entries (plugin, built-in) join the overlap pass with their listing text.
        not_on_disk = set(report["offered"]["not_on_disk"])
        candidates = skills + [{"name": name, "description": desc, "hidden": {"disable_model_invocation": False}}
                               for name, desc in entries if name in not_on_disk]
    report["overlap"] = overlap_pairs(candidates, threshold, limit)
    visible = {s["name"]: s for s in skills if not s["hidden"]["disable_model_invocation"]}
    report["totals"] = {"copies": len(skills), "unique_names": len({s["name"] for s in skills}),
                        "visible_names": len(visible),
                        "visible_description_chars": sum(s["description_chars"] for s in visible.values())}
    order = {"error": 0, "warn": 1, "info": 2}
    report["findings"] = sorted(findings, key=lambda f: (order[f["severity"]], f["kind"], f["skill"] or ""))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Hosts: " + ", ".join(sorted(host_presets(Path.cwd()))) + ".")
    parser.add_argument("--root", action="append", metavar="DIR", help="skill root to scan (repeatable)")
    parser.add_argument("--host", action="append", choices=sorted(host_presets(Path.cwd())),
                        help="add a host's documented default roots (repeatable)")
    parser.add_argument("--project", default=".", metavar="DIR",
                        help="project directory for project-level host roots (default: cwd)")
    parser.add_argument("--max-depth", type=int, default=3, metavar="N",
                        help="directory levels below a root to search for SKILL.md (default: 3)")
    parser.add_argument("--offered", metavar="FILE",
                        help="session skill listing copied verbatim ('- name: description' lines; '-' = stdin)")
    parser.add_argument("--min-similarity", type=float, default=0.1, metavar="X",
                        help="lowest description Jaccard score reported in overlap (default: 0.1)")
    parser.add_argument("--max-pairs", type=int, default=50, metavar="N",
                        help="overlap pairs reported (default: 50)")
    args = parser.parse_args(argv)

    roots = resolve_roots(args)
    if not roots:
        print("inventory: no roots; pass --root DIR, --host NAME, or set SKILL_SET_AUDIT_ROOTS", file=sys.stderr)
        return 2
    if not any(root["exists"] for root in roots):
        print("inventory: no root exists: " + ", ".join(r["path"] for r in roots), file=sys.stderr)
        return 2
    offered = None
    if args.offered:
        try:
            offered = sys.stdin.read() if args.offered == "-" else Path(args.offered).read_text(encoding="utf-8")
        except OSError as error:
            print(f"inventory: cannot read --offered {args.offered}: {error}", file=sys.stderr)
            return 2
    hosts = {root["host"] for root in roots}
    report = build(roots, args.max_depth, offered, args.min_similarity, args.max_pairs, hosts)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    json.dump(report, sys.stdout, indent=1, ensure_ascii=False)
    sys.stdout.write("\n")
    return 1 if any(f["severity"] != "info" for f in report["findings"]) else 0


if __name__ == "__main__":
    sys.exit(main())
