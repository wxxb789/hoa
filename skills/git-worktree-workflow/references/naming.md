# Why the name is `gitwt`

Not `wt`, and not `git-wt` — both collide, and both failures are quiet:

- **`wt`** is Windows Terminal's App Execution Alias
  (`%LOCALAPPDATA%\Microsoft\WindowsApps\wt.exe`), registered system-wide. A helper
  named `wt` only wins by PATH order and loses the moment its directory drops out,
  at which point a `command -v wt` guard passes on Windows Terminal and
  `wt --shell` pops a **modal error dialog** on every shell start. Because git-bash
  starts as a login shell, that is one dialog per shell — unbounded.
- **`git-wt`** would be reachable as `git wt …` (git dispatches `git <verb>` to
  `git-<verb>` on PATH), but it is the binary name of
  [k1LoW/git-wt](https://github.com/k1LoW/git-wt), whose CLI has **no subcommands** —
  `git wt list` there creates a worktree named `list`. Sharing the name means a
  later `brew install k1LoW/tap/git-wt` silently shadows this script with one whose
  verbs mean something else.

`gitwt` collides with neither, at the cost of not being a `git <verb>` subcommand.

# Windows `bash` trap

On Windows there are usually **two** `bash` executables on PATH:

- Git Bash: `C:\Program Files\Git\bin\bash.exe` (what `gitwt` needs)
- WSL: `C:\Windows\System32\bash.exe` (a Linux shell — it cannot see Git-for-Windows
  paths the same way, and on machines without a WSL distro it fails with
  `execvpe(/bin/bash) failed`)

If bare `bash` resolves to the WSL one, `gitwt` and its tests break. Check with
`where bash` (first hit wins) and invoke Git Bash explicitly when needed:

```bash
"C:/Program Files/Git/bin/bash.exe" gitwt ...
```
