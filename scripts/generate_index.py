#!/usr/bin/env python3
"""Generate index.md / index.zh-CN.md from per-skill metadata.

Single source of truth: the `<!-- index: ... -->` HTML comment in each
skills/<name>/SKILL.md, plus a short description from a table in this script
(bilingual). Skills without an index comment are a hard error — an unindexed
skill is invisible to the catalog.

Usage:
    python scripts/generate_index.py          # write both files
    python scripts/generate_index.py --check  # exit 1 on drift (CI)
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

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

# Optional bilingual note overrides per skill: (en, zh). A skill absent here
# falls back to the first sentence of its SKILL.md frontmatter description,
# so a new skill generates without touching this file. Overrides exist to
# keep the Chinese note from rendering the English description verbatim.
NOTES = {
    "ghc-search": (
        "web and X/Twitter search via a local ghc-proxy Responses API; answer plus deduped sources",
        "经本机 `ghc-proxy` Responses API 做 web 与 X/Twitter 搜索；返回答案加去重来源",
    ),
    "define-goal": (
        "define one cohesive, verifiable goal or the smallest sufficient goal set without planning implementation",
        "把意图定义为一个完整、可验证的目标或最小充分目标集，不制定实现方案",
    ),
    "git-worktree-workflow": (
        "run several agent CLIs in parallel on one repo via isolated worktrees; ships the `gitwt` helper",
        "用隔离的 worktree 在同一仓库并行运行多个 agent CLI；随附 `gitwt` 助手",
    ),
    "hoa-agent-retrieve": (
        "cross-agent history → coverage-manifested, deduped Retrieval Bundle",
        "跨 agent 历史 → 带 coverage manifest、已去重的 Retrieval Bundle",
    ),
    "hoa-introspect": (
        "layered self-report: deterministic usage facets (L1) + evidence-cited blind-spot audit (L2)",
        "分层自省报告：确定性使用 facets（L1）+ 带证据的盲点审计（L2）",
    ),
    "hoa-introspect-distill": (
        "distill approved repeatable work into a skill (or opt-in rule/config) via the runtime-native skill-creator or inline",
        "把已批准的可复用工作提炼成 skill（或 opt-in 的 rule/config），经 runtime 原生 skill-creator 或内联产出",
    ),
    "my-ado-cppr": (
        "commit → push → create/update PR on Azure DevOps or GitHub; probe/plan/apply with resumable state",
        "commit → push → 在 Azure DevOps 或 GitHub 创建/更新 PR；probe/plan/apply 三段式，状态可 resume",
    ),
    "skill-scout": (
        "search local/marketplace/upstream for an existing skill before authoring a new one; report, never author",
        "写新 skill 前先在本地/marketplace/上游搜索已有实现；只报告，不代写",
    ),
    "typed-verification-gates": (
        "every loop iteration ends at a gate typed programmatic / judge / human, declared before the work",
        "循环每次迭代止于一道事先定型的验证门：programmatic / judge / human",
    ),
    "generated-means-generated": (
        "generated files are never hand-edited; regeneration rides the same commit and drift fails CI",
        "生成文件绝不手改；再生成随同一提交，漂移即 CI 失败",
    ),
    "fresh-context-grader": (
        "one-shot judge prompt: grade a response against a rubric written before it existed",
        "一次性评审 prompt：用先于回答写好的 rubric 在全新上下文里评分",
    ),
    "adopt-a-pattern": (
        "finite recipe turning a ref-map what-to-steal note into a landed, classified, attributed artifact",
        "把 ref 地图里的 what-to-steal 笔记变成落地、归类、带署名 artifact 的有限步骤",
    ),
    "ghc-proxy": (
        "portable definition of the local ghc-proxy search service; registration stays in chezmoi",
        "本地 ghc-proxy 搜索服务的可移植定义；注册留在 chezmoi",
    ),
}

KV = re.compile(r"(\w+)\s*=\s*([^;]+)")

INDEX_COMMENT = re.compile(
    r"^<!--\s*index:\s*(?P<kv>.*)\s*-->\s*$", re.MULTILINE
)

FRONTMATTER_DESC = re.compile(
    r"^---\s*\n.*?^description:\s*(?P<desc>.*?)(?=\n\w|\n---)", re.MULTILINE | re.DOTALL
)


def _fallback_note(skill_md: Path) -> str:
    """First sentence of the SKILL.md frontmatter description."""
    text = skill_md.read_text(encoding="utf-8")
    m = FRONTMATTER_DESC.search(text)
    if not m:
        return ""
    desc = " ".join(m.group("desc").split())
    first_sentence = re.split(r"(?<=[.!?])\s", desc, maxsplit=1)[0]
    return first_sentence


def _unquote(value: str) -> str:
    """Strip one pair of matching surrounding quotes from a metadata value."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parse_metadata(skill_md: Path) -> dict[str, str]:
    text = skill_md.read_text(encoding="utf-8")
    m = INDEX_COMMENT.search(text)
    if not m:
        raise ValueError(f"no `<!-- index: ... -->` comment in {skill_md}")
    meta = {k: _unquote(v.strip()) for k, v in KV.findall(m.group("kv"))}
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


def _resolve_notes(name: str, doc: Path, kind: str) -> tuple[str, str]:
    """Bilingual note for an artifact: NOTES override, else the doc's
    frontmatter description. Raises when neither yields a note."""
    fallback = _fallback_note(doc)
    en, zh = NOTES.get(name, (fallback, fallback))
    note_en, note_zh = en or fallback, zh or fallback
    if not note_en:
        raise ValueError(f"no note for {kind} {name!r}: no NOTES override "
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
        meta = parse_metadata(skill_md)
        note_en, note_zh = _resolve_notes(name, skill_md, "skill")
        rows.append({"name": name, "type": "skill", "path": f"skills/{name}/",
                     "note_en": note_en, "note_zh": note_zh, **meta})
    rows.extend(_collect_library())
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
            continue
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
            note_en, note_zh = _resolve_notes(name, doc, artifact_type)
            rows.append({"name": name, "type": artifact_type, "folder": folder_name,
                         "path": path, "note_en": note_en, "note_zh": note_zh, **meta})
    return rows


HEADER_EN = """# Index — artifacts by area & target

> **English** · [简体中文](./index.zh-CN.md)

The repo is organized **by type** (the folders). Every logical artifact also
gets **one row here**, labeled by `areas` and `targets` — because one artifact
often serves several areas or runtimes, and folders can't express that.

> Generated by `python scripts/generate_index.py` — never edit the catalog
> table by hand; edit each skill's `<!-- index: ... -->` comment instead.

## Label vocabulary

```text
areas:    software-development | work-management | self-management
targets:  runtime-agnostic | repo-only |
          claude-code | codex | opencode | hermes | pi | kimi-code
```

- Both axes are **multi-valued** (comma-separated).
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

> 由 `python scripts/generate_index.py` 生成——目录表不要手改；改每个 skill 里的
> `<!-- index: ... -->` 注释即可。

## 标签词表

```text
areas:    software-development | work-management | self-management
targets:  runtime-agnostic | repo-only |
          claude-code | codex | opencode | hermes | pi | kimi-code
```

- 两个轴都**可多值**（逗号分隔）。
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
            target.write_text(content, encoding="utf-8")
            print(f"wrote {filename} ({len(rows)} artifacts)")
    return status


if __name__ == "__main__":
    sys.exit(main())
