<!-- index: areas=software-development; targets=repo-only; summary="a skill runs unchanged on Windows, Linux and macOS: install the whole ../ closure, forward-slash relative paths, stdlib Python with explicit UTF-8, python3 in commands"; summary_zh="技能在 Windows、Linux、macOS 上原样可跑：安装完整 ../ 依赖闭包、正斜杠相对路径、标准库 Python 显式 UTF-8、命令写 python3" -->

# Cross-platform skills

A standing constraint: every skill runs unchanged on Windows, Linux and macOS, from any host skills
root, whether installed by link or by copy. Chaining rules live in
[skill-composition.md](skill-composition.md).

## The `..` trap

The same `../<child>/SKILL.md` string reaches different directories depending on OS and tool.
Measured on 2026-11-17 (Windows 11, WSL Ubuntu 24.04) for
`<host-root>/<parent-link>/../<child>/SKILL.md`, where `<parent-link>` points at the repo's
`skills/<parent>`:

| Platform | Link type | OS open (Python `open`, Node `fs`, `cat`) | Normalize-first (`os.path.normpath`, Node `path.resolve`, many harness Read tools) |
|---|---|---|---|
| Windows | directory junction | lexical | lexical |
| Windows | directory symlink | lexical | lexical |
| Linux | symlink | physical | lexical |
| macOS | symlink | physical (POSIX kernel; not measured here) | lexical |

**Lexical** = `<host-root>/<child>`; **physical** = next to the link target, `<repo>/skills/<child>`.
On POSIX one string can therefore hit two directories. Harnesses also differ in the base directory
they show the model (link path or realpath; OMP dedups by realpath).

## Install-closure invariant

For every `../<sibling>/` reference in an installed skill, **both** the lexical sibling
`<host-root>/<sibling>` and the physical sibling `realpath(<host-root>/<parent>)/../<sibling>` exist
and are the same skill (same realpath, or byte-identical). Installing a parent means installing its
whole `../` dependency closure into the same host root. On a categorized host (`<root>/<category>/<name>`)
the host root is the parent's category directory, so the closure shares the parent's category.

- Linking every skill from one checkout into one host root satisfies both sides.
- `install_host_skills.py --link` links every skill flat at `<root>/<name>`, or under one
  `--category`, so a parent and its closure share a directory; `--check` lists every
  `missing closure` left by entries placed some other way.
- Copy installers (`npx skills --copy`, Codex's skill-installer `copytree`) copy one directory; the
  chain breaks unless the closure is copied into the same root too.

## Link mechanics

- Link whole skill directories, never a single `SKILL.md`.
- Windows: a directory junction needs no privilege but takes an absolute local target; a directory
  symlink needs Developer Mode or admin. `scripts/install_host_skills.py --link` creates directory
  symlinks with an absolute target.
- Never commit a symlink inside the repo tree: a Windows clone with `core.symlinks=false` checks it
  out as a text file.

## Paths

Paths in SKILL.md and `references/` use forward slashes and resolve relative to the file that holds
them, as Markdown links do; in SKILL.md that is the skill directory. A sibling link is therefore
`../<sibling>/` from SKILL.md and `../../<sibling>/` from `references/x.md`; the composition shape
"Read `../<child>/SKILL.md` (relative to this skill's directory)" belongs in SKILL.md only, where
both bases agree. `scripts/check_skill_links.py`, `install_host_skills.py --check` and
hoa-skill-set-audit's `inventory.py` all resolve this way. No drive letters, no backslashes, no `~` or
`$HOME` expansion assumptions. `../` appears only in a sibling-skill link.

## Scripts

- Python stdlib and `pathlib`; no bash-only logic for core behavior.
- Explicit `encoding="utf-8"` on every text read, write and subprocess text stream; never the locale
  default (cp1252 or cp936 on Windows).
- Invoke through the interpreter (`python3 scripts/x.py`); never rely on an executable bit or shebang.
- Tolerate CRLF: the repo has no `.gitattributes`, so a Windows checkout may convert line endings;
  frontmatter parsers and file readers accept `\r\n`.

## Interpreter name

Commands in SKILL.md and `references/` spell **`python3`**. A skill that ships such commands states
once, before its first one: "On Windows, run `python` where this says `python3`."

Why: Linux distributions ship `python3` and leave `python` to an optional package
([`python-is-python3`](https://packages.ubuntu.com/noble/python-is-python3)); macOS has had no
`python` since 12.3 ([release notes](https://developer.apple.com/documentation/macos-release-notes/macos-12_3-release-notes)).
On Windows the python.org and Store installs provide `python.exe`, and `python3.exe` may be only the
App Execution Alias that opens the Store. `py -3` is Windows-only and absent with some installers.
One spelling plus one stated exception beats a per-command menu. Repo tooling (`scripts/`, CI,
README commands) runs in a venv where `python` exists and is out of scope.

## Follow-up

Existing skills predate this rule and are not edited here. List the commands that still spell
`python` (SKILL.md and other Markdown under `skills/`) with:

```bash
grep -rnoE --include='*.md' '(^|[`[:space:](;&|])python[[:space:]]+(-|[^[:space:]]*\.py\b|[^[:space:]]*scripts/)' skills/
```

Convert those files and add the Windows line to every skill with Python commands in one change,
with the rerun output as evidence.
