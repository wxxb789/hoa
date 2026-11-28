# Self-evolved skill hand-off (hoa landing zone)

Standing brief for this Hermes line. Read it **before** creating a skill or evolving an existing one.
Upstream source of truth: `~/repos/hoa/prompts/hermes-skill-naming.md` (hoa's Hermes-facing copy of
`AGENTS.md` → "Hermes-evolved skills" / "Portability") and `~/repos/hoa/unfettered-skills/README.md`.

## 1. Settle three things before writing any content

1. **Is this a Hermes built-in / bundled skill?** Check `hermes skills list` (the source column reads
   `builtin` / `official` / `hub`) and `~/.hermes/skills/.bundled_manifest`. If the skill you are about
   to write duplicates, forks or re-creates one → **stop**. Use the upstream skill as it is. If it is
   wrong or missing something, write the change up as an upstream contribution (issue or patch) and tell
   the owner; never keep a private copy under another name. Never fork a built-in, in either tier.
2. **Is it coupled to Hermes?** COUPLED if following it requires Hermes runtime paths, Hermes
   configuration, Hermes-only tools or commands, the gateway, or Hermes memory. PORTABLE if a coding
   agent in another runtime (Claude Code, Codex, OpenCode, pi) could follow it unchanged given ordinary
   shell, git and the files the skill ships. A mixed skill splits: the portable method stays, and a small
   `hermes-` skill holds the Hermes-specific steps.
3. **Name it.** Coupled → `hermes-<topic>` in both tiers (e.g. `hermes-updates`). Portable → never the
   prefix. The name is a global kebab-case identity, equal to its directory.

## 2. Land it in hoa — never in `skills/`

- The **only** landing point for a self-evolved skill is a candidate at
  `~/repos/hoa/unfettered-skills/<name>/SKILL.md` (required; `name` must equal the directory), with any
  support files under `unfettered-skills/<name>/`.
- `unfettered-skills/` is the landing zone — a sibling of the curated `skills/` catalog, and never an
  install source, never a manifest search path, never something a curated skill may depend on. Only an
  authorized self-evolving writer (this line) lands candidates, automatically, one folder-only change at
  a time. Humans and ordinary agents only promote or delete.
- **Never edit `~/repos/hoa/skills/` directly** and never fork a built-in: `skills/` is owner- and
  review-gated. To propose a change there, open a PR.
- The `~/repos/hoa` main worktree stays on `main` and clean — the host's `~/.hermes/skills/*` symlink
  into it, so a branch checked out there goes live immediately. Do any catalogue edit in a dedicated
  worktree (`git worktree add <dir> <branch>`), never in that checkout. Writing into
  `unfettered-skills/` is the exception: it is not a symlink target, so it does not move the live skills.
- Candidates are unconstrained (no literal demotion is required yet) but CI still screens them.

## 3. Preflight the committed candidate

```bash
cd ~/repos/hoa
uv run --script scripts/check_unfettered.py --base origin/main
```

`scripts/check_unfettered.py` runs exactly three checks:

1. **Path isolation** — a change that adds or modifies anything under `unfettered-skills/` may touch no
   other path. A deletion there may ship beside an outside change, because promotion moves a skill out.
2. **Sensitive content** — keys, tokens, e-mail addresses, personal home paths, private-range IPs,
   corporate package feeds.
3. **Shape and collisions** — `SKILL.md` under its own directory, non-empty `name` equal to that
   directory, plus `description`; no name collision with `skills/` or `scripts/retired_skills.toml`.

The candidate must be **committed** first — a staged or uncommitted candidate is invisible to the
checker, and `--base` compares `<rev>..HEAD`. CI (`.github/workflows/ci.yml`, `--event` mode) runs the
same scan only **after** the push, so the local preflight is the real gate.

## 4. Promotion is the owner's move

- One authorized PR moves the candidate into `skills/<category>/<name>/` and deletes the raw copy:
  a **review, not a sync and not a copy**.
- On promotion the package is normalized to the full bar: the port review plus every curated gate — no
  environment literals, each environment-specific value read from configuration (flag → env var → config
  file → documented default) with the default stated inside the skill.
- It starts at `metadata.revision: "1"`. A candidate-only name never gets a retired entry; only
  previously curated names retire, through `scripts/retired_skills.toml`.
- `hoa-skill-port` owns the procedure.

## 5. Automation on this host

`~/.hermes/scripts/hoa-sync.sh` (wired into `[ops] repo auto-sync` via `repo-sync.sh` → `REPOS`) does
the mechanical half: scope-strict staging of `unfettered-skills/**`, staged-secret scan, commit,
`check_unfettered.py --base <merge-base of origin/main and HEAD>`, then fetch + rebase + push to `main`.
It never stages a path outside the landing zone. A candidate therefore only has to be written; the push
is automatic. Pass the **merge base**, never `origin/main`: `--base` diffs its two endpoints, so an ahead
`origin/main` — the normal state after another machine pushes — inverts upstream's own commits into
outside-path changes and falsely reports "landing-zone write mixed with other paths" on a candidate that
is perfectly in scope. The wrapper's acceptance probe (throwaway clones; the real repo is only read)
lives with the task evidence under `~/claw/tasks/<date>/hoa-unfettered-autosync/`.

`hoa` is a **PUBLIC** repository: a landed candidate is world-visible immediately, before any
review. That is the landing zone's design; treat the sensitive-content check as the only gate standing
between a private note and a public commit.

Beyond the landing zone the rule is **repo-wide** (owner, 2026-11-25): no personal data anywhere in
`hoa`, and every skill that enters or is updated there is desensitized — host paths, personal
handles and IDs, model IDs, private repository names and channel snowflakes become configuration with a
stated default. The landing zone enforces this mechanically (`check_unfettered.py`); `skills/**` reaches
it only through the port review (`rules/generalization-rubric.md`, `hoa-skill-port`), so a port is not
finished until its literal scan is clean and says so in the report.
