# Dimension briefs

Each brief = subject path + this section + the lens in `panel.md` + prior ledger ids for the dimension
+ output path `find-<dim>.json`. Commands are starters, not a checklist; `SINCE` is the window start
(midnight-aligned `YYYY-MM-DD`), `B` the default branch, `O/R` the GitHub owner/repo when there is one.

## history-forensics (risk: recurring cost)
- `git log --since=SINCE --name-only --format= | awk -F/ '{print $1}' | sort | uniq -c | sort -rn`
- Fix-of-fix and reverts: `git log --since=SINCE --oneline | grep -Ei 'fix|revert|again|follow-?up'`,
  then group by touched path; three or more rounds on one surface is a design fault, not bad luck.
- Large commits for small subjects: `git log --since=SINCE --shortstat --format='%h %s'`.
- Direct pushes: `git log --first-parent B --since=SINCE --format='%h %s'` versus merged PRs
  (`gh pr list --state merged --search "merged:>=SINCE" --json number,mergeCommit`).

## ceremony (risk: recurring cost)
- Version/changelog/release gates and who consumes them (`git grep -n VERSION`, tags versus releases:
  `git tag | wc -l`, `gh release list`).
- Write-ups per increment (plans, evidence, ledgers, PR bodies) and their size; review rounds per PR
  (`gh pr view N --json reviews,comments`).

## enforcement (risk: irreversible state)
- `gh api repos/O/R/rulesets`, `gh api repos/O/R/branches/B/protection`, auto-merge setting
  (`gh api repos/O/R --jq .allow_auto_merge`). A CI gate with no required status is advisory.

## tests (risk: recurring cost)
- Test versus code LOC; tests whose subject is the test runner; imports of private names
  (`git grep -n 'import _\|\._[a-z]'` in tests); CI OS matrix versus OS-specific branches
  (`git grep -n -e win32 -e darwin -e CREATE_NO_WINDOW`).

## code-shape (risk: recurring cost)
- Copies: compare normalised lines (strip whitespace, sort -u, `comm -12`) between suspected twins;
  name matches alone prove nothing.
- Dead code: grep both `module.name` and `from module import name` before calling a symbol unused.
- Single-caller wrappers; helpers longer than one screen.

## reach (risk: recurring cost)
- Does each produced artifact reach a consumer? Installs versus the repo listing, deploy targets
  versus their source, docs versus behaviour. Decide from the installer's own lock or listing.

## boundary (risk: trust boundary)
- `git log --format='%an <%ae>' | sort | uniq -c`; secret-shaped strings; corporate hostnames or
  registry URLs in a public repo (`git grep -nE 'https?://[^ ]*(corp|internal|pkgs\.)'`); lockfile
  registries; generated files edited by hand (compare with their generator).

## external (risk: any; unknown unknowns only)
- Search the web for platform features, ecosystem tools and practices that would replace or obsolete
  what this repo builds by hand. Each finding: `kind: unknown`, a `sources` URL, and local evidence
  that it applies (the file or command it would replace).

## agent-stack (only for agent or harness repos)

| Layer | Question |
|---|---|
| Instructions | Is each always-loaded rule load-bearing, and loaded where it is needed? |
| Skills/tools | Does each one fire on its trigger and stay quiet otherwise? |
| Memory/state | Is durable state written once, read back, and pruned? |
| Delegation | Are worker outputs verified before acceptance? |
| Evals | Is there a measurement that would catch a regression in the agent's behaviour? |
| Cost | Context, tokens and wall time per run: measured or guessed? |
