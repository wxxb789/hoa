#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Check every `../<name>/` reference that leaves a skill directory.

A parent chains to a sibling skill with a path relative to its own file, e.g.
`Read ../<child>/SKILL.md`. Each such reference in a skill's `SKILL.md` or
`references/**/*.md` is resolved lexically against the file that holds it:

- a path that stays inside the skill is ignored, unless it lands on a missing
  `<name>/` while `skills/<name>` is a skill: that sibling link was written
  with too few `../` for its own file's depth (`../../<name>/` from
  `references/`, `../../../<name>/` from `references/phases/`) -- an error;
- a path that lands in `skills/<name>/` must name an existing sibling skill and,
  unless it carries a `<placeholder>` or glob, an existing file or directory
  there (`#anchor` stripped) — otherwise an error;
- a path that climbs above `skills/` is not a sibling link and is ignored.

It also checks how skill Markdown runs a skill's own Python scripts, in fenced
code blocks and inline code:

- a `uv run <path>.py` target must resolve to a file under `skills/` that
  carries a PEP 723 `# /// script` block; without one, `uv run` inside a user's
  project installs that project's environment instead of an isolated one;
- `uv run python`/`python3` must carry `--no-project` (or name its own
  `--project`), or it syncs the user's project environment too;
- a bare `python`/`python3` command (not `uv run ... python`) must not run a
  file under `skills/` (write `uv run <path>`); a `test_*`/`test-*` file is
  exempt, since dated evidence quotes how a suite was run;
- a skill's `.py` file outside `tests/` that starts with a shebang must use
  `#!/usr/bin/env -S uv run --script`, so running it directly also honours its
  `requires-python` (a bare `python3` is often older; test files are exempt).
- a skill's `.sh`/`.bash`/`.ps1` launcher outside `tests/` must not call a bare
  `python`/`python3`: it goes through `uv run` too.

Script paths resolve against the skill directory, the file holding them,
`skills/` and the repository root, after dropping a leading `$VAR/`, `${...}/`,
`<placeholder>/` or `~/`.

Usage:
    uv run scripts/check_skill_links.py

Exit codes: 0 every sibling reference and script command is valid, 1 at least one error.
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"

# `../` runs that start a path token (not `x/../`, not the tail of `...`), then a
# name segment and its trailing slash. The rest stops at Markdown/quote delimiters.
REFERENCE = re.compile(
    r"(?<![\w./-])((?:\.\./)+)([A-Za-z0-9][A-Za-z0-9._-]*)/([^\s)\]`'\"#]*)")
PLACEHOLDER = re.compile(r"[<>*]|\.\.\.")
FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
INLINE = re.compile(r"(`+)(.+?)\1", re.S)
# Every `uv run`, including one nested in `$(...)` or chained after `&&`; its arguments stop at
# the next shell separator.
UV_RUN = re.compile(r"(?<![\w-])uv\s+run\s+(?=([^|;&)`]*))")
PYTHON = re.compile(r"(?<![\w./$<-])python3?(?:\.exe)?((?:\s+-[A-Za-z]+)*)\s+([^\s;|&)`]+)")
UV_PREFIX = re.compile(r"(?<![\w-])uv\s+run\b[^|;&]*$")
TEST_FILE = re.compile(r"test[_-]")
UV_VALUE_OPTIONS = {"--with", "--with-requirements", "--with-editable", "--project", "--directory",
                    "--python", "-p", "--env-file", "--extra", "--group", "--index", "--package"}
LEADING_VARIABLE = re.compile(r"^(?:\$\{[^}]*\}|\$\w+|<[^>]*>|~)/")
UV_SHEBANG = "#!/usr/bin/env -S uv run --script"
SCRIPT_SUFFIXES = {".py", ".sh", ".bash", ".ps1"}
SHELL_PYTHON = re.compile(r"(?<![\w./$<'\"-])python3?(?:\.exe)?(?=\s|$)")
PEP_723 = re.compile(r"^# /// script\s*$", re.M)


@dataclass(frozen=True)
class Reference:
    source: Path   # file holding the reference
    line: int
    text: str      # the reference as written
    scope: str     # "sibling" or "skill-relative" (sibling written from the skill dir)
    name: str      # sibling skill name
    rest: str      # path inside the sibling, anchor stripped


def skill_files(skill_dir: Path) -> list[Path]:
    """The files whose `../` references count: SKILL.md and references/**/*.md."""
    files = [skill_dir / "SKILL.md"] if (skill_dir / "SKILL.md").is_file() else []
    references = skill_dir / "references"
    if references.is_dir():
        files.extend(sorted(path for path in references.rglob("*.md") if path.is_file()))
    return files


def references(skill_dir: Path) -> list[Reference]:
    """Every `../` reference that leaves `skill_dir`, resolved lexically."""
    found = []
    for path in skill_files(skill_dir):
        depth = len(path.relative_to(skill_dir).parts) - 1
        text = path.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            for match in REFERENCE.finditer(line):
                ups = match.group(1).count("../")
                name = match.group(2)
                if ups <= depth:
                    if (not (path.parents[ups] / name).exists()
                            and (skill_dir.parent / name / "SKILL.md").is_file()):
                        found.append(Reference(
                            source=path, line=number, text=match.group(0).rstrip(".,;:"),
                            scope="skill-relative", name=name, rest=match.group(3).rstrip(".,;:")))
                    continue
                if ups == depth + 1:
                    found.append(Reference(
                        source=path, line=number, text=match.group(0).rstrip(".,;:"),
                        scope="sibling", name=name, rest=match.group(3).rstrip(".,;:")))
    return found


def siblings(skill_dir: Path) -> set[str]:
    """Names of the sibling skills `skill_dir` references through `../`."""
    return {ref.name for ref in references(skill_dir) if ref.scope == "sibling"}


def code_spans(path: Path) -> list[tuple[int, str]]:
    """(line, text) of every fenced-code line and inline code span in a Markdown file.

    An inline span may wrap inside its paragraph; it is reported at its first line.
    """
    spans, fence, paragraph = [], None, []

    def inline(paragraph):
        text = "\n".join(line for _, line in paragraph)
        for match in INLINE.finditer(text):
            number = paragraph[0][0] + text.count("\n", 0, match.start())
            spans.append((number, match.group(2).replace("\n", " ")))

    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        marker = FENCE.match(line)
        if fence:
            if marker and marker.group(1)[0] == fence[0] and len(marker.group(1)) >= len(fence):
                fence = None
            else:
                spans.append((number, line))
        elif marker or not line.strip():
            inline(paragraph)
            paragraph = []
            fence = marker.group(1) if marker else None
        else:
            paragraph.append((number, line))
    inline(paragraph)
    return sorted(spans)


def resolve_script(token: str, source: Path, skill_dir: Path, skills_root: Path) -> Path | None:
    """The file under skills_root a command's script token names, or None."""
    rest = token.strip("\"'")
    while LEADING_VARIABLE.match(rest):
        rest = LEADING_VARIABLE.sub("", rest, count=1)
    if not rest or "$" in rest or "<" in rest:
        return None
    root = skills_root.resolve()
    for base in (skill_dir, source.parent, skills_root, skills_root.parent):
        candidate = Path(os.path.normpath(base / rest)).resolve()
        if candidate.is_file() and candidate.is_relative_to(root):
            return candidate
    return None


def uv_run_target(command: str) -> tuple[str | None, list[str]]:
    """The first positional argument of `uv run` and the uv options before it."""
    tokens = command.split()
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if not token.startswith("-"):
            return token, tokens[:index]
        index += 2 if token in UV_VALUE_OPTIONS else 1
    return None, tokens


def script_errors(skill_dir: Path, skills_root: Path) -> list[str]:
    """Errors for `uv run` and bare-python commands that run scripts in skill Markdown."""
    errors = []
    repo = skills_root.resolve().parent
    for path in skill_files(skill_dir):
        where_file = path.relative_to(skills_root.parent).as_posix()
        for number, code in code_spans(path):
            where = f"{where_file}:{number}"
            for match in UV_RUN.finditer(code):
                target, options = uv_run_target(match.group(1))
                if (target in ("python", "python3")
                        and not {"--no-project", "--project"}.intersection(options)):
                    errors.append(f"{where}: uv run {target} without --no-project syncs the user's "
                                  f"project; write uv run --no-project {target}")
                    continue
                if target is None or not target.strip("\"'").endswith(".py"):
                    continue
                script = resolve_script(target, path, skill_dir, skills_root)
                if script is None:
                    errors.append(f"{where}: uv run target {target} does not resolve to a file "
                                  f"under skills/")
                elif not PEP_723.search(script.read_text(encoding="utf-8")):
                    errors.append(f"{where}: uv run target {script.relative_to(repo).as_posix()} "
                                  f"has no PEP 723 '# /// script' block")
            for match in PYTHON.finditer(code):
                target = match.group(2)
                if (not target.strip("\"'").endswith(".py")
                        or UV_PREFIX.search(code, 0, match.start())):
                    continue
                script = resolve_script(target, path, skill_dir, skills_root)
                if script is not None and not TEST_FILE.match(script.name):
                    errors.append(f"{where}: bare python runs {script.relative_to(repo).as_posix()}; "
                                  f"write uv run {target}")
    return errors


def shebang_errors(skill_dir: Path, skills_root: Path) -> list[str]:
    """Errors for a non-test skill script whose shebang or shell launcher bypasses uv."""
    errors = []
    for path in sorted(p for p in skill_dir.rglob("*") if p.suffix in SCRIPT_SUFFIXES):
        relative = path.relative_to(skill_dir)
        if "tests" in relative.parts or TEST_FILE.match(path.name):
            continue
        where = path.relative_to(skills_root.parent).as_posix()
        lines = path.read_text(encoding="utf-8").splitlines()
        if path.suffix == ".py":
            if lines and lines[0].startswith("#!") and lines[0].rstrip() != UV_SHEBANG:
                errors.append(f"{where}:1: shebang {lines[0].rstrip()!r} bypasses uv; "
                              f"write {UV_SHEBANG}")
            continue
        for number, line in enumerate(lines, 1):
            code = line.split("#", 1)[0] if path.suffix != ".ps1" else line
            if SHELL_PYTHON.search(code) and not UV_PREFIX.search(code):
                errors.append(f"{where}:{number}: bare python in a launcher; write "
                              f"uv run <script> or uv run --no-project python")
    return errors


def check(skills_root: Path) -> list[str]:
    """Return the errors for every skill under skills_root."""
    errors = []
    for skill_dir in sorted(path for path in skills_root.iterdir()
                            if path.is_dir() and not path.name.startswith(".")):
        errors.extend(script_errors(skill_dir, skills_root))
        errors.extend(shebang_errors(skill_dir, skills_root))
        for ref in references(skill_dir):
            where = f"{ref.source.relative_to(skills_root.parent).as_posix()}:{ref.line}"
            if ref.scope == "skill-relative":
                errors.append(f"{where}: {ref.text} resolves inside the skill; paths are relative "
                              f"to the file holding them, so the sibling is "
                              f"{'../' * (len(ref.source.relative_to(skill_dir).parts))}{ref.name}/")
                continue
            sibling = skills_root / ref.name
            if not (sibling / "SKILL.md").is_file():
                errors.append(f"{where}: {ref.text} names no sibling skill "
                              f"(expected skills/{ref.name}/SKILL.md)")
                continue
            if ref.rest and not PLACEHOLDER.search(ref.rest):
                target = sibling.joinpath(*PurePosixPath(ref.rest).parts)
                if not target.exists():
                    errors.append(f"{where}: {ref.text} does not exist in skills/{ref.name}/ "
                                  f"(got {ref.rest!r})")
    return errors


def main(argv=None) -> int:
    if not SKILLS.is_dir():
        print(f"check_skill_links: no skills directory at {SKILLS}", file=sys.stderr)
        return 1
    errors = check(SKILLS)
    for error in errors:
        print(error)
    if errors:
        print(f"check_skill_links: {len(errors)} error(s)", file=sys.stderr)
        return 1
    print("check_skill_links: sibling references OK; script commands OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
