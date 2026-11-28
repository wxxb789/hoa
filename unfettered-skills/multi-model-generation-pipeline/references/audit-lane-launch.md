# Launching read-only audit lanes

Concrete recipe for running two or more models against one proposal so the reports arrive comparable and a
misbehaving lane cannot touch the real tree. Substitute the ids/providers your catalog carries.

## 0. Compose the prompt by script, not by heredoc

```bash
/usr/bin/python3 - <<'PY'
from pathlib import Path
p = Path("audit-prompt.md").read_text()
extra = "\n补充：工作目录 /tmp/<lane>（只读工作树副本）；正本在 <real-repo>。报告写标准输出。\n"
Path("/tmp/audit-inst.md").write_text(p + extra)
print("bytes:", len(p + extra))
PY
```

A quoted heredoc (`cat > f <<'EOF'`) performs no expansion: `$(cat prompt.md)` becomes literal text in the
file and the lane then audits the instruction to read a file instead of the proposal. Check the byte count
and the first lines after composing.

## 1. One detached worktree per lane

```bash
git -C <repo> worktree add -q --detach /tmp/<lane-a> HEAD
git -C <repo> worktree add -q --detach /tmp/<lane-b> HEAD
```

A worktree is the sandbox that makes "read-only" more than a request. `git worktree remove /tmp/<lane> --force`
when the report lands.

## 2. Prompt shape (the part that makes two reports diffable)

- Header line written by you: `# <model> 独立审计（lane <x>）／只读` — makes a 0-byte file unambiguous.
- Absolute paths to the proposal, the raw measured-facts file, and the repo.
- The same **numbered** question list for every lane.
- Output contract per finding: `[P0|P1|P2] conclusion / evidence (file:line) / impact / minimal fix`, then a
  verdict line, "the one thing to change", "where I disagree with the plan", and "what I could not verify".
- Hard boundary block: no writes, no `git checkout|reset|clean|commit|push|stash`, no reading credential
  files; say "exists" rather than quoting sensitive content.

## 3. Launch detached, one unit per lane

```bash
systemd-run --user --collect --unit=<lane>-$(date +%H%M%S) -p WorkingDirectory=/tmp/<lane> \
  /bin/bash -lc '<cli> … >> /home/<user>/audit-<lane>.md 2>&1; echo "EXIT=$?" >> /home/<user>/audit-<lane>.md'
```

Redirect *inside* the `bash -lc` string, and append the exit code — a lane that dies at argument parsing
otherwise looks like a lane that answered nothing.

Decide liveness by the unit, never by file size: `systemctl --user is-active <unit>`. These CLIs buffer the
whole answer and write once at exit, so `active + 0 bytes` is healthy.

**The unit's environment is not your shell's.** A transient `--user` unit reads no rc files and inherits no
shim directory, so a CLI that sits on `PATH` interactively dies at spawn with
`FileNotFoundError: [Errno 2] No such file or directory: '<cli>'` and leaves the report holding nothing but
your header line. Pass the absolute path (a mise shim such as `~/.local/share/mise/shims/<cli>`). When a
report is 0 bytes, read `journalctl --user -u <unit> -n 20` before assuming the lane is still thinking: a
lane that failed at spawn and a lane that is thinking look identical from the file alone.

## 4. CLI shapes that work

- **`pi`** (chat or responses, per the provider entry):
  `pi --print --provider <provider> --model <id> "$(cat /tmp/audit-inst.md)"`.
  `--print`/`-p` is non-interactive; pick the provider whose `api` matches the model id (see SKILL.md).
- **`codex exec`**: feed the prompt on stdin and ask for a sandbox mode:
  `codex exec -s read-only -m <model> - < /tmp/audit-inst.md`.
  Read `codex exec --help` for the current sandbox/approval flags and `-c key=value` overrides (they let you
  point a provider at a URL without editing `~/.codex/config.toml`) — flag names move between releases, so
  a remembered flag like `--full-auto` fails at argument parsing and shows up as an empty report.
- **Auth failure on one harness** (`Failed to refresh token … sign in again`) is the harness's credential
  state, not the model: reroute the same model through the harness that is authed, and give the owner the
  login command for the other one.

## 5. After the reports land

1. Open two or three `path:line` claims per report — an auditor reads code and does not verify its own
   citations.
2. **Re-derive every headline number yourself before it reaches a document.** Two harnesses count the same
   tree differently by design — one counts a directory existing, another counts a test a CI step actually
   runs — so a gap between their totals is information about the counting rule, not an error to average
   away. Publish the method beside the number, and take the stricter rule as the plan's own.
3. **A number you publish must be re-derivable by the rule you published.** State the basis explicitly —
   file lines or body lines after the frontmatter, headings counted outside fenced code blocks, which
   directories are excluded — and then check that the queue the rule selects is exactly the list printed:
   a rule that selects 13 while the text lists 15 fails the first reproduction, and the fix is the stated
   basis, not a footnote. Reviewers' arithmetic is as unverified as their citations — in one round an
   orphan count, a "over 600 lines" claim and a registry item count were each off by one or more — so
   re-derive in both directions: the findings you adopt, and the numbers you ship.
3. Print the two reports against the same numbered list; list per item: adopt / adapt / reject + why.
4. A merged "both agreed" summary loses exactly the items where they disagreed, and those are the ones the
   owner needs to decide.
