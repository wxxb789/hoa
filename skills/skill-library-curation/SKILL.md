---
name: skill-library-curation
description: >-
  Review a reusable skill library: inventory, overlap groups, pruning and consolidation proposals,
  installer provenance, and upstream freshness. Use when asked to audit, prune, or recommend skills,
  or to answer where an installed skill came from and whether it is current. Not for creating or
  editing a skill, and not for porting one into a shared repo — review and execution are separate
  modes, and execution needs its own confirmed scope.
metadata:
  version: "0.1.30"
  areas: "software-development,self-management"
  targets: "runtime-agnostic"
  summary: "review a skill library by evidence: inventory, overlap groups, installer provenance, upstream freshness; recommendations never change state"
  summary_zh: "按证据审查技能库：清点、重叠分组、安装来源、上游新鲜度；建议不改动状态"
  kind: "entry"
---

# Skill Library Curation

Use this for library review, pruning/overlap/consolidation proposals, or usage-based skill discovery.
Review and recommendation are distinct modes; execution requires its own explicitly confirmed scope.
For recurring discovery, follow `references/usage-based-recommendations.md`, not a whole-library sweep.
Moving a skill *out* of the runtime into a shared/public repo is a different job — porting and
publishing (de-coupling axes, generated catalogs, canonical-source swap), not this skill.

## Core rules

- Be active: a meaningful library review should produce a reusable inventory, classification, or skill-library improvement; do not turn “no deletion yet” into “no work done.”
- Be conservative: zero usage is evidence, not proof of low value. If the owner's scenario is unclear, classify `needs confirmation` and do not guess.
- Keep skills class-level: prefer one reusable workflow skill with a small topical reference set over many narrow incident skills or one umbrella with a reference file per session.
- Report overlap explicitly. Do not silently merge or delete a skill because another one looks similar.
- For usage-based discovery, ground recommendations in the owner's actual preceding-week activity, not
  agent-generated maintenance or cumulative counters. Return at most three concise Simplified Chinese
  bullet recommendations: actual trigger, practical benefit, next use, installed/enabled/disabled/external
  status and verified source. Do not auto-install or change state; stay silent without worthwhile evidence
  and do not repeat a prior recommendation without a new reason.

## Auditing one workflow skill for protocol integrity

When the owner says a working skill "should be general, let's improve it", the defect is rarely
missing prose — it is the same protocol living in several files and drifting. Probe before writing:

1. **Inventory the family, not the file.** `wc -l` the umbrella `SKILL.md` plus every `references/`
   and `profiles/` file, then read the headings of the related skills it names. A stage order or
   gate that appears in three bodies is already a liability; 500-line profile copies of a 180-line
   protocol mean every future edit must land in two places.
2. **Count copies by distinctive token.** Grep a protocol-specific string across the skill tree
   (a role marker name, the transport wrapper command, the gate script name): one hit per file =
   one more source of truth. No judgement needed, and it is faster than reading.
3. **Hunt claims that contradict current defaults.** The highest-value defect is a stale
   transport/command sentence in a reference file that the umbrella already superseded (e.g. a
   prompt template still telling you to paste into an interactive pane after the default moved to
   headless). Fix that in place immediately — it is a factual error, not a design choice.
4. **Diff same-purpose scripts across skills**
   (`diff <(sed 's/[[:space:]]*$//' a) <(sed 's/[[:space:]]*$//' b)`). The weaker twin is dead
   weight: keep the stronger one and make the other a pointer.
5. **Check coverage against reality, not against intent.** For each repo/project the owner actually
   works in (`ls -d <workspace>/*/`, look for the contract dir such as `docs/goals/`), ask whether a
   profile exists. An active repo with no profile is a bigger fluency gap than any wording fix.
6. **Check for durable state and telemetry.** Is there a per-increment state file (stage, base sha,
   next action) and a ledger with durations/rounds? If not, interruption recovery is the real
   bottleneck and more prose cannot fix it.

Deliver: what exists (with counts), where the protocol is duplicated, which claims are already
wrong, then 2–3 options sized by effort. Do not rewrite a methodology skill the owner depends on
before they pick an option — the audit is the deliverable.

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

1. **Provenance is a lookup.** Shared-store installs (`~/.agents/skills/<name>`) record their
   origin in `~/.agents/.skill-lock.json` under `skills.<name>` (`source`, `sourceType`,
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
- Run `scripts/upstream-freshness-check.py` (reads the optional disabled list + the installer
  lock, threads the fetches, prints only DIFF/ERR rows plus a SAME/DIFF/ERR tally; exits non-zero
  on any DIFF so it can gate). `--enabled` limits the sweep to non-disabled skills; `--lock`,
  `--skills-root`, and `--config` override the XDG-based defaults.

## Review procedure

1. **Define the review scope.** Include enabled, disabled, filesystem-only, loader-only, and archived entries. Record the source/path and current runtime status for every entry.
2. **Establish runtime truth.** Query the actual runtime loader/registry, then reconcile it with the filesystem inventory. Report loader-only and filesystem-only mismatches instead of dropping them or trusting a stale snapshot.
3. **Collect usage evidence.** Read the available usage metadata and record use count, last-used time, and whether the evidence is recent, historical, or absent. Never invent frequency from the skill name.
4. **Read enough content to judge quality.** Inspect each skill's description and, for candidates, its `SKILL.md`; flag empty/malformed metadata, stale instructions, dangerous permissions, unclear scope, or obsolete dependencies.
5. **Assess every skill on four axes:**
   - usage frequency: recent, historical, or unobserved;
   - overlap: unique, complementary, or a concrete replacement candidate;
   - core value: directly supports the owner's main workflows, useful on demand, or non-core;
   - quality: clear and maintained, bulky/ambiguous, stale, risky, or malformed.
6. **Assign exactly one recommendation:** `retain`, `merge`, `suggest delete`, or `needs confirmation`. Use `needs confirmation` whenever a personal integration, domain interest, or future workflow cannot be inferred safely.
7. **Produce the recommendation before changing state.** For every skill, output its name, recommendation, one-sentence reason, and the four evidence dimensions. Use a CSV/JSON artifact for the full set when chat formatting is constrained; on a channel that renders tables poorly use bullets or labeled rows rather than a raw Markdown table.
8. **Stop at the decision gate.** Do not delete files, disable skills, rewrite routing, or merge content during the review. Wait for an explicit owner confirmation that names the action scope. A vague request to “review” is not deletion approval.

## Execution procedure after explicit confirmation

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
- **Do not use an old inventory as runtime truth.** Skill installs, platform gates, and malformed metadata can make loader and filesystem counts differ; reconcile both before declaring totals.
- **`node_modules` phantom skills.** A vendored npm package under a skill's `scripts/node_modules/` can ship its own `SKILL.md` (e.g. `dotenv/skills/dotenvx/SKILL.md`). A recursive filesystem scan counts it as a top-level skill, but the runtime loader skips `node_modules`, so it is NOT injected and costs no prompt. Do not add it to the disabled list (creates a phantom entry) or delete it (breaks the vendored dep) — exclude `node_modules` from the inventory and note it once. Confirm the real injected count from the live assembled prompt, not the filesystem count.
- **Do not equate “never used” with “useless.”** Integrations and specialist skills are often intentionally dormant; keep them in `needs confirmation` unless the owner context rules them out.
- **Do not make a deletion proposal without a replacement or scope reason.** A skill can be non-core without being safe to remove; state the replacement, overlap, or explicit irrelevance.
- **Do not patch a user-owned, bundled, hub-installed, external, or pinned skill during autonomous curation.** Report the protection boundary and recommend adoption or foreground-owner action instead.
- **A profile that declares itself authoritative over its umbrella is a drift machine.** Text like
  "where the two differ, this profile wins" puts owner-level protocol in a per-repo file, so the
  next protocol edit lands in the wrong place and the two silently disagree. Report it as
  structural; the profile should carry repo deltas only (contract location, gate commands, branch
  and bot conventions, frozen surfaces, resource limits).
- **Do not propose new machinery before checking what the existing failure cost.** Stage caps,
  extra checklists and dispatcher scripts are guesses until a ledger shows which stage burns the
  rounds; the mechanical part worth building first is the one that runs a gate the agent keeps
  skipping by hand.
- **Do not make a raw Markdown table the only deliverable on a channel that renders tables poorly.** Attach a CSV/JSON artifact and provide readable bullet rows.
- **Do not let a large inventory hide the decision.** Lead with counts and the high-confidence take, then link the complete per-skill evidence.

## Completion output

Report:

- total entries and runtime/archived split;
- counts for retain/merge/suggest-delete/needs-confirmation;
- high-confidence recommendations and the main overlap groups;
- at most three genuinely justified new-skill candidates;
- artifact paths for the complete review;
- an explicit statement that no changes were made when still at the review gate.
