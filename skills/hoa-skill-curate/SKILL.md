---
name: hoa-skill-curate
description: >-
  Use when asked where a skill came from, why an installer warns, whether skills match upstream,
  which imported skills have abandoned upstreams, or which skills recent work suggests; or to
  execute an owner-confirmed retirement, merge or deletion. Not for loaded-set overlap or pruning
  (hoa-skill-set-audit), or creating, editing or porting a skill.
metadata:
  revision: "3"
  areas: "software-development,self-management"
  targets: "runtime-agnostic"
  summary: "trace installed skills' provenance and upstream freshness, apply the upstream-retirement rule, and execute only owner-confirmed library changes"
  summary_zh: "追溯已安装技能的来源与上游新鲜度，执行上游退役规则，仅在所有者确认后变更技能库"
  kind: "entry"
---

# hoa-skill-curate

## Configuration

| Variable | Resolves | Default |
|---|---|---|
| `SKILLS_HUB` | shared skill store (hub installs + `.skill-lock.json`) | `~/.agents` |
| `SKILLS_ROOT` | directory the runtime loads skills from | `<hub>/skills` |
| `SKILL_RUNTIME_CONFIG` | operator config file used for the `skills.disabled` label | `${XDG_CONFIG_HOME:-~/.config}/agent/config.yaml` |

Resolution order and the config-file path are defined in
[references/configuration.md](references/configuration.md).
Nothing above has a machine-specific default: point `SKILLS_HUB` at the store and the rest follows.

Use this for installer provenance, upstream freshness, the retirement sweep, usage-based skill
discovery, and executing a confirmed library change. Recommendation and execution are distinct
modes; execution requires its own explicitly confirmed scope.
For recurring discovery, follow `references/usage-based-recommendations.md`, not a whole-library sweep.
Overlap, shadowing, contradiction and pruning analysis of the whole loaded set is the user-run
`hoa-skill-set-audit` command (hidden; e.g. `/hoa-skill-set-audit` in Claude Code, `$hoa-skill-set-audit` in Codex).
Moving a skill *out* of the runtime into a shared/public repo is a different job — porting and
publishing (de-coupling axes, generated catalogs, canonical-source swap), not this skill.

## Core rules

- Be conservative: zero usage is evidence, not proof of low value. If the owner's scenario is unclear, classify `needs confirmation` and do not guess.
- Keep skills class-level: prefer one reusable workflow skill with a small topical reference set over many narrow incident skills or one umbrella with a reference file per session.
- For usage-based discovery, ground recommendations in the owner's actual preceding-week activity, not
  agent-generated maintenance or cumulative counters. Return at most three concise Simplified Chinese
  bullet recommendations: actual trigger, practical benefit, next use, installed/enabled/disabled/external
  status and verified source. Do not auto-install or change state; stay silent without worthwhile evidence
  and do not repeat a prior recommendation without a new reason.

## Upstream-maintenance retirement rule

Standing owner policy (pre-authorized deletion class): delete imported skills whose **upstream author** has been inactive longer than 3 months. The author's activity is the criterion, not local usage — a zero-use skill with an active upstream author stays; an unused skill with an abandoned upstream is a delete candidate without further conservative gating.

Sweep procedure:

1. Build the provenance map before judging activity: hub installs from the runtime's hub lock file (`source`), shared-store installs from the shared installer lock (`skills.<name>.source` / `sourceUrl`), the rest from repo links inside `SKILL.md`. Locally-authored skills with no upstream are owned by the owner — judge those by usage count and edit staleness instead, and treat them as `needs confirmation` unless the owner stated a local-staleness rule.

**Owner's stated local-staleness rule**: a skill 180 days unloaded or never loaded is a delete candidate — but keep it when a plausible near-future use exists (judge from the owner's projects and current direction). Always produce the deletion list and get owner confirmation before deleting; never prune this class autonomously.
2. Probe each upstream repo once: `curl -s https://api.github.com/repos/<owner>/<repo>` → read `pushed_at` and `archived`. An archived repo or a `pushed_at` older than the cutoff is the delete signal.
3. Cross-reference before deleting: scheduled-job prompts, live docs (identity file, operating contract, fact store, shared rails, team docs), and other skills' bodies. A mention inside another skill as a historical case study is not a live dependency — update the example, proceed with the deletion.
4. Back up the confirmed set into one tarball before deleting. Category-level profile symlinks propagate the removal automatically, so verify with a profile-side skill count, not the category-entry count the reconciler reports.
5. Do not trust `SKILL.md` mtimes after editing anything in the tree — your own sed/patch refreshes them. Use the runtime's usage ledger plus directory mtimes for staleness evidence.

## Installer provenance and warning triage

Answer "where did this skill come from", "is it actually installed", "why is the installer
warning" from recorded state and source, never from guessing:

1. **Provenance is a lookup.** Shared-store installs (`${SKILLS_HUB:-~/.agents}/skills/<name>`) record their
   origin in `${SKILLS_HUB:-~/.agents}/.skill-lock.json` under `skills.<name>` (`source`, `sourceType`,
   `sourceUrl`, `skillPath`, `skillFolderHash`, `installedAt`, `updatedAt`; the file also holds
   `dismissed` and `lastSelectedAgents`). Hub installs use the runtime's own hub lock file.
   Per-source counts from this file answer "how many skills came from repo X" exactly.
2. **Attribute a repo-relative path without cloning.** `gh search code "<path>" --limit 10`
   names the owning repo; `gh api repos/<owner>/<repo>/contents/<path> --jq '.content' |
   base64 -d` reads a single file. Prefer `gh` over browser/HTTP fetching for anything on
   GitHub — it is authenticated, prints clean JSON, and needs no scraping.
3. **Locate the emitting code before explaining a warning.** `grep -rl "<warning text>"
   <runtime-home> ~/.npm` finds the CLI bundle; read the surrounding function. The warning's own
   path prefix identifies the phase — a path under the tool's `mkdtemp(TMPDIR/<tool>-*)`
   directory means it scanned a throwaway git clone, not an install target.
4. **Scan warnings that point inside `tests/`/fixtures are noise, but verify it.** Installers
   walk every `SKILL.md` in the cloned tree and validate frontmatter (`name` + `description`),
   so upstream test fixtures trip the gate. Confirm with two reads: the fixture file carries
   only `name:` (deliberately incomplete), and the warned names are absent from the lock file
   (nothing was installed, nothing was silently dropped).
5. **Report mechanism + impact + provenance.** "Cosmetic, here is why, zero entries affected,
   here is the file that proves it" — never a bare "it's fine". A genuine defect found this way
   belongs upstream (e.g. the scanner should skip test trees); do not patch the local install
   to silence someone else's tool.

This applies to the `skills` CLI install model and its lock layout in detail — see
`references/skills-cli-installs.md`.

## Upstream freshness — verify by HEAD diff, not the lock timestamp

"Are all my skills up to date?" is a different question from "is the upstream author active?"
(the retirement rule above). Answer it by content, not timestamps:

- An old `updatedAt` in the installer lock is NOT staleness. The installer only rewrites files
  whose content changed, so an unchanged skill keeps its original install timestamp for months.
  A repo `pushed_at` is also a weak signal — a monorepo push rarely touches your specific skill.
- The truth is a byte-for-byte diff of each github-backed skill's local `SKILL.md` against
  upstream HEAD: resolve `sourceUrl` + `skillPath` from the lock, build
  `https://raw.githubusercontent.com/<owner>/<repo>/HEAD/<skillPath>`, and compare with CRLF
  normalized. (Prefer this over `gh api .../contents` here — raw HEAD is one fetch per skill.)
- Cover DISABLED skills too — they still sit on disk and can be re-enabled; a stale one is a
  latent surprise.
- Run `uv run scripts/upstream-freshness-check.py` (requires uv: it declares PyYAML; reads the optional disabled list + the installer
  lock, threads the fetches, prints only DIFF/ERR rows plus a SAME/DIFF/ERR tally; exits non-zero
  on any DIFF so it can gate). `--enabled` limits the sweep to non-disabled skills; `--lock`,
  `--skills-root`, and `--config` override the XDG-based defaults.
- Only if a script command fails (for example `uv` is not found), read [references/troubleshooting.md](references/troubleshooting.md).

## Execution procedure after explicit confirmation

Input: a retirement-sweep list or a hoa-skill-set-audit report, plus an owner confirmation that names
the action scope. A vague request to "review" is not deletion approval.

1. Freeze the confirmed set; do not expand it from inference.
2. Back up every skill directory and affected config before destructive edits. Preserve an audit trail of the selected set and the backup path.
3. For a merge, choose one canonical class-level skill, move reusable rules into its `SKILL.md`, extend an existing topical reference before creating a new one, and update active routing references precisely.
4. For deletion, remove only the confirmed skills; leave archived history untouched unless the owner explicitly includes it.
5. Reload or rebuild the runtime only after the filesystem/config edit succeeds.
6. Verify the exact post-change state: loader list, disabled list, active references to removed names, skill loading, and config validity. Report proof and rollback path.

## Pitfalls

- **Do not explain a tool warning from its message text alone.** Locate the emitting code and
  the provenance/lock record first; the message often names a temp path or a fixture, and the
  plausible reading of it is wrong more often than not.
- **Do not recurse a grep over the whole runtime tree.** A `grep -rn` across the runtime home
  walks the installer's hub index cache — a single-line, multi-megabyte JSON index — and buries
  the hits in tens of megabytes of one JSON line. Target the skill directory or exclude
  `index-cache`.
- **Do not patch a user-owned, bundled, hub-installed, external, or pinned skill during autonomous curation.** Report the protection boundary and recommend adoption or foreground-owner action instead.

## Completion output

Report:

- provenance answers with the lock record or file that proves them;
- freshness tally (SAME/DIFF/ERR) and the DIFF rows;
- retirement candidates with upstream evidence (`pushed_at`, `archived`) and live-dependency checks;
- for an execution: the frozen set, backup path, post-change verification and rollback path;
- an explicit statement that no changes were made when still at a decision gate.
