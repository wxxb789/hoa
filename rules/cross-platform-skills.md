<!-- index: areas=software-development; targets=repo-only; summary="a skill runs unchanged on Windows, Linux and macOS: install the whole ../ closure, forward-slash relative paths, stdlib Python with explicit UTF-8, skill scripts run with uv run and a PEP 723 block"; summary_zh="技能在 Windows、Linux、macOS 上原样可跑：安装完整 ../ 依赖闭包、正斜杠相对路径、标准库 Python 显式 UTF-8、技能脚本用 uv run 且带 PEP 723 块" -->

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

- `npx skills` has no dependency concept and installs only the names it is given. The closure is
  delivered by the generated commands in `index.md` (`-s '*'`, or a skill's row naming its whole
  closure); `scripts/generate_index.py --check` keeps them current. One `npx skills add` puts every
  named skill in the same layout (one canonical copy per skill, linked into each agent's root, or
  copied with `--copy`), so a closure installed together satisfies both sides.
- Other copy installers (Codex's skill-installer `copytree`) copy one directory; the chain breaks
  unless the closure is copied into the same root too.
- On a machine, hoa-skill-set-audit's `inventory.py` diagnoses the installed set: its `closure-*`
  findings report a missing lexical or physical sibling, or two that differ.

## Link mechanics

- Link whole skill directories, never a single `SKILL.md`.
- Windows: a directory junction needs no privilege but takes an absolute local target; a directory
  symlink needs Developer Mode or admin.
- Never commit a symlink inside the repo tree: a Windows clone with `core.symlinks=false` checks it
  out as a text file.

## Paths

Paths in SKILL.md and `references/` use forward slashes and resolve relative to the file that holds
them, as Markdown links do; in SKILL.md that is the skill directory. A sibling link is therefore
`../<sibling>/` from SKILL.md and `../../<sibling>/` from `references/x.md`; the composition shape
"Read `../<child>/SKILL.md` (relative to this skill's directory)" belongs in SKILL.md only, where
both bases agree. `scripts/check_skill_links.py` and
hoa-skill-set-audit's `inventory.py` both resolve this way. No drive letters, no backslashes, no `~` or
`$HOME` expansion assumptions. `../` appears only in a sibling-skill link.

## Scripts

- Python stdlib and `pathlib`; no bash-only logic for core behavior.
- Explicit `encoding="utf-8"` on every text read, write and subprocess text stream; never the locale
  default (cp1252 or cp936 on Windows).
- Run through `uv run` (next section); never rely on an executable bit or shebang.
- Tolerate CRLF: the repo has no `.gitattributes`, so a Windows checkout may convert line endings;
  frontmatter parsers and file readers accept `\r\n`.

## Interpreter: `uv run`

A command in SKILL.md or `references/` that runs a skill's Python script spells **`uv run <path>`**
with the path and arguments it would otherwise take. Every entry point such a command runs starts
with a PEP 723 block, after the shebang:

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
```

`requires-python` is what the code needs; `dependencies` lists every third-party import and is `[]`
for stdlib-only code. Inline Python and stdlib modules run as `uv run --no-project python -c …` or
`uv run --no-project python -m …`, with `--with <package>` for a third-party import. There is no
`#!/usr/bin/env python3` exception: a script that tooling executes directly (a forwarder, a selftest)
goes through `uv run --script` too, and a child a script starts uses that script's own interpreter
(`sys.executable`).

uv is a prerequisite for skills with scripts. A missing uv is handled on demand, not in SKILL.md:
`scripts/shared/troubleshooting.md` is vendored by `scripts/vendor_shared.py` to
`references/troubleshooting.md` in every skill whose docs run its own scripts with `uv run`, and
SKILL.md carries one line: "Only if a script command fails (for example `uv` is not found), read
`[references/troubleshooting.md](references/troubleshooting.md)`." The reference asks the user before
installing uv and never auto-installs; if the user declines, the skill stops: uv is required, and a
bare `python3` is not a fallback because the system interpreter is often older than
`requires-python` (Ubuntu 24.04 ships 3.12, macOS `/usr/bin/python3` is 3.9).

Why: measured on 2026-11-17 (uv 0.13.9 on Windows, 0.13.8 on Linux) with the working directory
inside a user's project that has a `pyproject.toml` and the script inside that project, as a
project-scoped skill is:

| Command | Effect on the user's project |
|---|---|
| `uv run script.py`, no inline metadata | creates `.venv` in the project and installs the project's dependencies |
| `uv run script.py` with a PEP 723 block, even `dependencies = []` | none: runs in an isolated cached environment |
| `uv run --no-project …` | none |

A script outside the project was not affected. The block is therefore what keeps `uv run` from
mutating a user's environment, and `scripts/check_skill_links.py` fails on a `uv run <path>.py`
target without one, on `uv run python` without `--no-project`, and on a bare `python`/`python3`
command that runs a script under `skills/`.
`uv run` also ends the interpreter-name split: Linux distributions ship `python3` and leave `python`
to an optional package ([`python-is-python3`](https://packages.ubuntu.com/noble/python-is-python3));
macOS has had no `python` since 12.3 ([release notes](https://developer.apple.com/documentation/macos-release-notes/macos-12_3-release-notes));
on Windows `python3.exe` may be only the App Execution Alias that opens the Store. Repo tooling
(`scripts/`, `evals/`) carries the same shebang and block, so `uv run <script>` works there too; CI
installs `scripts/requirements.txt` and calls `python` directly.
