# Contributing a fix upstream (without touching the running install)

When the correct fix is in Hermes source rather than config/skill/profile, the change belongs in a
separate clone and a PR — never in `~/.hermes/hermes-agent`, which must stay byte-clean so the
unattended updater keeps working. That repo is the *runtime*; the clone is the *workbench*.

## When this applies

- A defect reproduces in a code path no config key can reach (delivery, cron status, provider
  resolution, CLI rendering).
- The owner says "PR 给上游" / "fix it upstream" — that authorises the public PR, but still confirm
  *which* behaviour to change before opening it.

If a config/env/profile workaround exists, prefer it (`upgrade-safe-local-ops.md`). Upstream is for
behaviour that every user hits.

## Procedure

1. **Clone beside the runtime, not over it.**
   ```bash
   git clone --depth=50 https://github.com/NousResearch/hermes-agent.git ~/repos/hermes-agent-upstream
   cd ~/repos/hermes-agent-upstream && git switch -c fix/<slug> main
   ```
   Note `git log -1 --format='%h %ad %s'` so the PR base is a commit you can name.
2. **Read the code before calling it a bug.** Grep the path and read the surrounding comments: a
   suspicious behaviour is often a deliberate decision with an issue reference ("treat as local
   rather than reporting an error"). A PR that reverses such a decision gets rejected — design the
   change as the *missing half* (keep the classification, add the status/reporting).
3. **Duplicate check before writing code** — the contribution guide requires it, and reviewers do it
   anyway:
   ```bash
   gh search issues --repo NousResearch/hermes-agent "<symptom>" --limit 10
   gh search issues --repo NousResearch/hermes-agent "<function or status name>" --limit 10
   ```
   Reference a related-but-different issue as "Related", never "Fixes", and say what distinguishes
   your case.
4. **Make the smallest change that fixes the class**, in the layer that owns it: record the state
   where the state lives, render it where the user reads it, and do not add a config key when an
   existing field can carry the signal.
5. **Run the tests in an isolated environment.** The installed runtime venv has no pytest:
   ```bash
   cd ~/repos/hermes-agent-upstream
   uv sync --group dev --no-install-project
   .venv/bin/python -m pytest tests/<area> -q
   .venv/bin/python -m pytest tests/<area>/<new_test>.py -q
   python scripts/check          # blocking lint + code-health; expect "14 checks, ok"
   ```
6. **Separate your failures from pre-existing ones.**
   ```bash
   git stash -u -q && .venv/bin/python -m pytest tests/<file>::<test> -q; git stash pop -q
   ```
   Report the pre-existing failure explicitly in the PR checklist instead of hiding it or "fixing"
   an unrelated test.
7. **Update tests that pinned the old behaviour.** A test asserting the buggy value is part of the
   bug: edit it with a comment saying why the expectation changed, and keep the non-failure
   invariants asserted alongside it.
8. **Ship it.**
   ```bash
   git add <files> && git commit -F -            # Conventional Commits: fix(scope): …
   git remote add fork https://github.com/<user>/hermes-agent.git
   git push -u fork fix/<slug>
   gh pr create --repo NousResearch/hermes-agent --base main \
     --head <user>:fix/<slug> --title '…' --body-file <body.md>
   ```
9. **Verify the public artifact, not the command output.**
   ```bash
   gh pr view <n> --json state,mergeable,files
   gh pr checks <n>
   ```
   Confirm the file list and line counts match what you meant to send; `no checks reported` means no
   CI ran (common for a first-time contributor), not that CI passed — say so.

## Pitfalls

- **Do not develop in the runtime checkout.** Even a temporary edit makes the unattended updater
  fail closed on a dirty tree and leaves upgrade debt.
- **`gh repo fork` output is not proof.** Verify with
  `gh repo view <user>/hermes-agent --json isFork,parent` before pushing; a failed fork still prints
  usage noise.
- **The PR body is a contract.** Run the checks the template names and state what you actually ran
  (tests, `~/repos/hermes-agent-upstream/scripts/check`, platform) plus anything that failed for reasons outside the change.
- **Scratch dirs: `mktemp -d`, never `rm -rf` + recreate.** A destructive command in a throwaway path
  can trip the consent gate and stall the turn for minutes; a fresh temp dir is free.
- **Read the PR back before reporting success.** `state`, `mergeable`, `files`, and check status are
  the evidence; a created URL alone is not.
