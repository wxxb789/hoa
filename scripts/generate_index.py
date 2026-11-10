#!/usr/bin/env python3
"""Generate index.md / index.zh-CN.md from per-skill metadata.

Custom-skill catalog fields live only in YAML frontmatter string scalars:
`metadata.areas`, `metadata.targets`, `metadata.version`, and the optional
bilingual notes `metadata.summary` / `metadata.summary_zh`. Legacy HTML
index annotations are rejected for skills; library files retain their
`<!-- index: ... -->` comments, which also carry `summary` / `summary_zh`.
There is no per-skill note table in this file: a missing English summary
falls back to the first sentence of the frontmatter description, and a
missing Chinese summary falls back to the English one. Missing or invalid
catalog metadata is a hard error.

Usage:
    python scripts/generate_index.py          # write both files
    python scripts/generate_index.py --check  # exit 1 on drift (CI)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Keep --check read-only, including helper/dependency import caches.
sys.dont_write_bytecode = True
import yaml
import skill_metadata as sm

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"

# Library folders indexed beside skills. Each artifact is a directory (or a
# single file) whose metadata comment lives in its main markdown file:
# <folder>/<name>.md or <folder>/<name>/README.md.
LIBRARY_FOLDERS = {
    "agents": "agent",
    "orchestration": "orchestration",
    "rules": "rule",
    "prompts": "prompt",
    "workflows": "workflow",
    "mcps": "mcp",
}

AREAS = ("software-development", "work-management", "self-management")
TARGETS = ("runtime-agnostic", "repo-only", "claude-code", "codex", "opencode",
           "hermes", "pi", "kimi-code")

INDEX_COMMENT = re.compile(
    r"^<!--\s*index:\s*(?P<kv>.*)\s*-->\s*$", re.MULTILINE
)


def _fallback_note(doc: Path) -> str:
    """First sentence of the frontmatter description; else the first
    non-empty Markdown line that is not a heading or comment."""
    text = doc.read_text(encoding="utf-8")
    description = ""
    if text.startswith("---"):
        lines = text.splitlines(keepends=True)
        for index in range(1, len(lines)):
            if lines[index].rstrip("\r\n") != "---":
                continue
            try:
                data = yaml.safe_load("".join(lines[1:index]))
            except yaml.YAMLError:
                data = None
            if isinstance(data, dict) and isinstance(data.get("description"), str):
                description = data["description"]
            break
    if description:
        desc = " ".join(description.split())
        return re.split(r"(?<=[.!?])\s", desc, maxsplit=1)[0]
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "<!--", "---")):
            continue
        return stripped
    return ""


def _unquote(value: str) -> str:
    """Strip one pair of matching surrounding quotes from a metadata value."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _comment_value(value: str, source: Path) -> str:
    """Decode one comment value: a double-quoted JSON/YAML string or a bare word."""
    if value.startswith('"'):
        try:
            return json.loads(value)
        except json.JSONDecodeError as error:
            raise ValueError(f"malformed quoted index value in {source}: {error}") from error
    return _unquote(value)


def _comment_fields(kv: str, source: Path) -> dict[str, str]:
    """Parse `key=value; ...`, keeping `;` inside a double-quoted value."""
    pairs: list[str] = []
    current: list[str] = []
    quoted = escaped = False
    for char in kv:
        if escaped:
            current.append(char)
            escaped = False
        elif quoted and char == "\\":
            current.append(char)
            escaped = True
        elif char == '"':
            quoted = not quoted
            current.append(char)
        elif char == ";" and not quoted:
            pairs.append("".join(current))
            current = []
        else:
            current.append(char)
    pairs.append("".join(current))
    if quoted:
        raise ValueError(f"unterminated quote in index comment in {source}")

    meta = {}
    for pair in pairs:
        if not pair.strip():
            continue
        key, separator, value = pair.partition("=")
        key = key.strip()
        if not separator or not re.fullmatch(r"\w+", key):
            raise ValueError(f"malformed index metadata {pair.strip()!r} in {source}")
        if key in meta:
            raise ValueError(f"duplicate index metadata {key!r} in {source}")
        meta[key] = _comment_value(value.strip(), source)
    return meta


def parse_metadata(skill_md: Path) -> dict[str, str]:
    text = skill_md.read_text(encoding="utf-8")
    m = INDEX_COMMENT.search(text)
    if not m:
        raise ValueError(f"no `<!-- index: ... -->` comment in {skill_md}")
    meta = _comment_fields(m.group("kv"), skill_md)
    for key in ("areas", "targets"):
        if key not in meta:
            raise ValueError(f"missing `{key}=` in {skill_md}")
    for a in meta["areas"].split(","):
        if a.strip() not in AREAS:
            raise ValueError(f"unknown area {a!r} in {skill_md}")
    for t in meta["targets"].split(","):
        if t.strip() not in TARGETS:
            raise ValueError(f"unknown target {t!r} in {skill_md}")
    return meta


def parse_skill_metadata(skill_md: Path) -> dict[str, str]:
    """Validate custom-skill YAML catalog strings and reject legacy annotations."""
    text = skill_md.read_bytes().decode("utf-8")
    if re.search(r"<!--\s*index\s*:", text, re.IGNORECASE):
        raise ValueError(f"legacy HTML index annotations are not allowed in {skill_md}; "
                         "use frontmatter metadata.areas, metadata.targets, and metadata.version")
    metadata = sm.catalog_metadata(text, skill_md)
    for area in metadata["areas"].split(","):
        if area.strip() not in AREAS:
            raise ValueError(f"unknown area {area!r} in {skill_md}")
    for target in metadata["targets"].split(","):
        if target.strip() not in TARGETS:
            raise ValueError(f"unknown target {target!r} in {skill_md}")
    return metadata


def _resolve_notes(meta: dict[str, str], doc: Path, kind: str, name: str) -> tuple[str, str]:
    """Bilingual note from the artifact's own metadata: summary / summary_zh,
    else the first sentence of the description. The Chinese note falls back to
    the English note, never to a translation of it."""
    fallback = _fallback_note(doc)
    note_en = meta.get("summary") or fallback
    note_zh = meta.get("summary_zh") or note_en
    if not note_en:
        raise ValueError(f"no note for {kind} {name!r}: no summary metadata "
                         f"and no usable description")
    return note_en, note_zh


def collect() -> list[dict]:
    rows = []
    skill_dirs = sorted(p for p in SKILLS.iterdir() if p.is_dir())
    for skill_dir in skill_dirs:
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            raise ValueError(f"skill directory without SKILL.md: {skill_dir}")
        name = skill_dir.name
        meta = parse_skill_metadata(skill_md)
        note_en, note_zh = _resolve_notes(meta, skill_md, "skill", name)
        for key in ("summary", "summary_zh"):
            meta.pop(key, None)
        rows.append({"name": name, "type": "skill", "path": f"skills/{name}/",
                     "note_en": note_en, "note_zh": note_zh, **meta})
    rows.extend(_collect_library())
    names: dict[str, str] = {}
    for row in rows:
        first = names.setdefault(row["name"], row["path"])
        if first != row["path"]:
            raise ValueError(f"duplicate artifact name {row['name']!r}: "
                             f"{first} and {row['path']}")
    if not rows:
        raise ValueError("no skills found")
    return rows


def _library_doc(entry: Path) -> Path | None:
    """Main markdown file of a library artifact: <name>.md or <name>/README.md."""
    if entry.is_file() and entry.suffix == ".md":
        return entry
    readme = entry / "README.md"
    if entry.is_dir() and readme.is_file():
        return readme
    return None


def _collect_library() -> list[dict]:
    rows = []
    for folder_name, artifact_type in sorted(LIBRARY_FOLDERS.items()):
        folder = ROOT / folder_name
        if not folder.is_dir():
            raise ValueError(f"configured library folder missing: {folder}")
        found = 0
        for entry in sorted(folder.iterdir()):
            if entry.name.startswith("."):
                continue
            doc = _library_doc(entry)
            if doc is None:
                raise ValueError(
                    f"library artifact without a main .md: {entry} "
                    f"(expected {entry.name}.md or {entry.name}/README.md)")
            is_file = entry.is_file()
            name = entry.stem if is_file else entry.name
            path = f"{folder_name}/{name}.md" if is_file else f"{folder_name}/{name}/"
            meta = parse_metadata(doc)
            note_en, note_zh = _resolve_notes(meta, doc, artifact_type, name)
            for key in ("summary", "summary_zh"):
                meta.pop(key, None)
            rows.append({"name": name, "type": artifact_type, "folder": folder_name,
                         "path": path, "note_en": note_en, "note_zh": note_zh, **meta})
            found += 1
        if not found:
            raise ValueError(f"library folder has no artifacts: {folder} "
                             f"(a bare .gitkeep is not an artifact)")
    return rows


HEADER_EN = """# Index — artifacts by area & target

> **English** · [简体中文](./index.zh-CN.md)

The repo is organized **by type** (the folders). Every logical artifact also
gets **one row here**, labeled by `areas` and `targets` — because one artifact
often serves several areas or runtimes, and folders can't express that.

> Generated by `python scripts/generate_index.py` — never edit the catalog
> table by hand. For skills, edit `metadata.areas` and `metadata.targets` in
> YAML frontmatter; for library files, edit the `<!-- index: ... -->` comment.

## Label vocabulary

```text
areas:    software-development | work-management | self-management
targets:  runtime-agnostic | repo-only |
          claude-code | codex | opencode | hermes | pi | kimi-code
```

- Both axes are **multi-valued** (comma-separated); skill values are YAML strings, not lists.
- **Type** is derived from the top-level folder — don't re-label it.
- `targets` = which `npx skills --agent` a skill installs to (`runtime-agnostic`
  = any; `repo-only` = never deployed, e.g. library/knowledge types).
- One row per **logical** artifact (not one per bilingual file).
- No `status` axis until experimental / deprecated states actually appear.

## Catalog

| Artifact | Type | Areas | Targets | Path | Notes |
|---|---|---|---|---|---|
"""

FOOTER_EN = """
> Reflections and eval results are prose/knowledge, not indexed here.
"""

HEADER_ZH = """# Index — 按 area 与 target 索引

> [English](./index.md) · **简体中文**

仓库**按类型**组织（就是那些目录）。每个逻辑 artifact 在这里也占**一行**，用
`areas` 和 `targets` 打标签——因为一个 artifact 常同时服务多个 area 或 runtime，
而目录表达不了这一点。

> 由 `python scripts/generate_index.py` 生成——目录表不要手改。skill 请修改 YAML
> frontmatter 中的 `metadata.areas`、`metadata.targets`；库文件仍修改
> `<!-- index: ... -->` 注释。

## 标签词表

```text
areas:    software-development | work-management | self-management
targets:  runtime-agnostic | repo-only |
          claude-code | codex | opencode | hermes | pi | kimi-code
```

- 两个轴都**可多值**（逗号分隔）；skill 中的值是 YAML 字符串，不是列表。
- **type** 从顶层目录推导——不要重复打标。
- 一行对应一个**逻辑** artifact（不为双语文件分别建行）。
- 暂不设 `status` 轴，等实验 / 废弃状态真的出现再加。

## 编目

| Artifact | Type | Areas | Targets | Path | Notes |
|---|---|---|---|---|---|
"""

FOOTER_ZH = """
> reflections 与 eval 结果属于文章 / 知识类，不在此索引。
"""

def render(rows: list[dict], lang: str) -> str:
    header, footer = (HEADER_EN, FOOTER_EN) if lang == "en" else (HEADER_ZH, FOOTER_ZH)
    out = [header]
    for r in rows:  # collect() already sorted by name
        note = r["note_en"] if lang == "en" else r["note_zh"]
        out.append(
            f"| {r['name']} | {r['type']} | {r['areas']} | {r['targets']} | "
            f"`{r['path']}` | {note} |\n"
        )
    out.append(footer)
    return "".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="verify generated files are up to date; exit 1 on drift")
    args = ap.parse_args(argv)

    try:
        rows = collect()
    except ValueError as e:
        print(f"generate_index: {e}", file=sys.stderr)
        return 1

    status = 0
    for lang, filename in (("en", "index.md"), ("zh", "index.zh-CN.md")):
        content = render(rows, lang)
        target = ROOT / filename
        if args.check:
            if target.read_text(encoding="utf-8") != content:
                print(f"generate_index: {filename} is stale; run "
                      f"python scripts/generate_index.py", file=sys.stderr)
                status = 1
        else:
            # Preserve the file's existing line-ending style: this repo stores the
            # catalog with CRLF, and writing LF here would leave every local generate
            # run looking like a whole-file edit (the --check comparison reads with
            # universal newlines, so both styles pass it).
            if target.exists() and b"\r\n" in target.read_bytes()[:2048]:
                content = content.replace("\n", "\r\n")
            target.write_bytes(content.encode("utf-8"))
            print(f"wrote {filename} ({len(rows)} artifacts)")
    return status


if __name__ == "__main__":
    sys.exit(main())
