# Skill library: updates, installs, provenance


## Hermes skill update lifecycle

When the user asks whether built-in skills update with Hermes or separately, answer from the bundled-vs-hub model:

- Bundled / built-in skills ship in the Hermes repo `skills/` and are synced into each profile with `hermes update` / startup bundled sync.
- Hub-installed skills update independently with `hermes skills check` / `hermes skills update`.
- Local / agent-created skills are not automatically overwritten by Hermes release sync.
- Bundled sync is guarded by `~/.hermes/skills/.bundled_manifest`: unmodified copies update, user-modified copies are skipped, and user-deleted bundled skills are respected.

Do not tell the owner to run `hermes skills update` for bundled skills unless the skill was installed through the Hub. For restoring or rejoining bundled updates, use `hermes skills list-modified`, `hermes skills diff <name>`, and `hermes skills reset <name> [--restore]`.

Session detail: `cases.md#bundled-vs-hub-skill-updates`.

### Full-library upgrade inventory and acceptance

1. Discover every update owner before writing: run `hermes skills check`, `hermes skills list-modified`, `hermes plugins check-updates --json`, and `hermes plugins list --plain --no-bundled`; inspect the global npx skill lock and nested skill Git checkouts separately. `hermes plugins update` refuses without `--yes` when stdin is not a TTY (`Not updating: no terminal to confirm`) while still printing the pending pin — re-run with `--yes` and confirm the `✓ updated <name> <old>..<new>` summary line. Do not equate Hermes's `local` source label with agent-created content — npx and Git imports can also appear as local.
2. Group installed npx lock entries by source and intersect their names with actual Hermes skill paths. Check `npx --yes skills@latest --help` for current named/global update options; scope updates to that intersection rather than blindly updating every agent sharing the global lock. Do not read protected Hub internals when public check/list commands provide provenance.
3. For each Git import, inspect `git status --short --branch` and its remote before fetching. Back up local modifications and preserve them by default; use non-destructive fast-forward updates only when safe. Report a conflicting import as blocked instead of treating “latest” as permission to reset or clean it.
4. Back up skill/plugin content and tracking locks before updating; a core quick state snapshot is not proof those directories are covered. Update managed sources without force, preserve local skills without verified provenance, and keep bundled plugins attached to the core updater. Preserve the owner's requested ordering of independent skill/plugin updates and the core upgrade.
5. Record each item's source, before/after revision or fingerprint, and status; aggregate updated/current/local-preserved/blocked/unresolved counts programmatically. Recheck all managed sources after execution and verify profile links within the authorized scope. A clean bundled-modification report does not prove npx or Git imports are current.

## Third-party GitHub skill / capability installs

When the user asks to install a skill or capability from a GitHub repo, treat it as a Hermes operations task plus an upstream package install, not just a file copy.

Workflow:

1. Load `hermes-agent` for current `hermes skills` syntax.
2. Pin and inspect upstream first: `git ls-remote <repo> HEAD`, then read the repo README/install docs and candidate `SKILL.md`.
3. Back up `~/.hermes/skills` before mutating it.
4. Prefer Hermes-native scan/install for raw skill URLs:
   - `hermes skills inspect <raw-SKILL.md-url>`
   - `hermes skills install <raw-SKILL.md-url> --category <category> --yes`
5. Verify with `skill_view(<name>)`, including `linked_files`.
6. If raw-URL install omitted upstream support files (`references/`, `templates/`, `scripts/`) and the installed skill is hub/community-protected, do **not** patch that protected skill in place. Use a proper source/tap that preserves files, or create a local wrapper/reference under an existing umbrella skill.
7. If the repo also ships a CLI/runtime, install and verify it separately with its version/doctor commands.
8. Save evidence under `~/claw/tasks/YYYY-MM-DD/<task>/evidence/` and clean temp source clones.

### Repo-based skill packages: the `npx skills` CLI

When the skill ships inside a git repo (`owner/repo` containing `skills/<name>/SKILL.md`) and its own SKILL.md references `npx skills`, install through that CLI — it fetches from the repo, tracks the install in `~/.agents/.skill-lock.json`, and lands files in the agent's skills dir. Keep `hermes skills install` for raw single-file SKILL.md URLs.

1. If a local checkout of the source repo exists, `git pull --ff-only` first — upstream may carry fixes newer than the checkout, and you want the installed copy current. **A repo whose `skills/` tree was reorganized is the exception**: that pull dangles every host link at once, so run the measurement in *Syncing the skill-source repo upstream* below first.
2. `npx skills add <owner>/<repo> -s <skill> -g -a hermes-agent -y --json`. The Hermes agent id is `hermes-agent` (global dir `~/.hermes/skills/`); the CLI `--help` does NOT list agent ids — the mapping table lives in the cached package README at `~/.npm/_npx/*/node_modules/skills/README.md`.
3. Read the JSON result before trusting it: `mode` may be `copy` (a real copy in the agent dir, no `~/.agents/skills` store entry) — confirm the actual landing path with `ls -la` instead of assuming the store path shown in the summary box.
4. Updates later: `npx skills update -g`; the lock entry (`source`, `skillPath`, `skillFolderHash`) is what the updater keys on. Never hand-edit the installed copy — patch upstream or the next update overwrites it.
5. After any new entry appears in `~/.hermes/skills`, run `python3 ~/.hermes/scripts/profile-layer-reconcile.py --apply` — expect one missing-symlink drift per served profile, or the profiles never see the skill.
6. Verify: `skill_view(<name>)` loads it, run the skill's own offline tests if it ships any, and confirm profile links with `ls ~/.hermes/profiles/*/skills/`.

Session detail: `cases.md#third-party-github-skill-install-agent-reach`.

## Bundled skill drift: de-fork instead of patching

A bundled skill that has been edited locally is a fork: it keeps working, but it stops receiving
upstream fixes and the drift is often invisible. Treat local knowledge as a layer **on top of** the
bundled skill, never as edits inside it.

**Detect**

- `diff -rq <repo>/skills/<cat>/<name> ~/.hermes/skills/<cat>/<name>` — the only direct comparison.
- `.bundled_manifest` holds one `name:md5` line per tracked skill. A bundled skill **missing** from
  it is silently untracked: `hermes skills list-modified` will not report it and `hermes update`
  will not refresh it. Count check: `find <repo>/skills -name SKILL.md | wc -l` vs
  `wc -l < ~/.hermes/skills/.bundled_manifest`.
- **Direction matters.** A diff does not mean "we added something": the installed copy is usually
  the *older* one, frozen at the snapshot taken when it stopped being tracked. Judge by content
  against the running code (e.g. `hermes status --full` vs `--all`), never by mtime — checkout
  mtimes are checkout time, not commit time.

**De-fork**

1. Back up the whole installed skill dir plus `.bundled_manifest` (`tar czf`) before touching it.
2. Re-home the local material **before** restoring: local-only files → the owning local skill's
   `references/`; local additions *inside* an official reference → lift that block into the local
   skill that covers the topic; a local `SKILL.md` section → the local skill's body.
3. Restore the bundled copy byte-for-byte from the checkout: `rm -rf <dest> && cp -a <repo>/skills/<cat>/<name> <dest>`.
   Never hand-merge — the point is hash equality.
4. Re-track: with the copy byte-identical, the next bundled sync baselines the manifest on its own
   (`_install_new_skill` records the hash only when `dir_hash(dest) == bundled_hash`). Force it now
   with `sync_skills(quiet=False)` from a Python that can import Hermes deps; otherwise wait for
   `hermes update`. **`hermes skills reset <name>` only CLEARS the manifest entry** — it does not
   rejoin updates. `--restore` reverts the copy to stock (destructive); plain reset makes tracking
   worse.
5. Verify: `hermes skills diff <name>` → `'<name>' matches the stock version`;
   `diff -rq` empty; `hermes skills list-modified` does not list it; the manifest line exists.
6. Fix pointers that named the old in-bundled paths (other skills, `LOCAL_OVERRIDES.md`, the
   chezmoi generator's `FORCE_SKILL_FILES`), then regenerate/reconcile the dependent layers.

**Tooling pitfall**: `tools/skills_sync` imports `ruamel` transitively, so the bare toolchain
`~/.hermes/tools/python-*` fails with `ModuleNotFoundError: ruamel`. Run it with a PM environment
interpreter (`~/.hermes/installs/*/environments/*/venv/bin/python`) and `sys.path` pointed at the
checkout — the same interpreter split that breaks cron workers.

## Bundled skills upstream later removed: cleaning local residue

`hermes update` respects local deletions, so a bundled skill upstream has since dropped keeps sitting in
the install, disabled and inert, until someone removes it. Clean it up only on owner request, and derive
the set from Hermes's own record — never from names or authors.

**Derive the set (authoritative):**

- The install's seeded-bundled list is `~/.hermes/skills/.bundled_manifest` (one `name:md5` line per
tracked skill) — the only record of what was *bundled here*, so it is the correct membership test.
- The current upstream bundle is the checkout tree: `git -C ~/.hermes/hermes-agent ls-tree -r --name-only
  HEAD -- skills | grep -c SKILL.md`.
- Set difference = official skills formerly bundled here but no longer shipped. Classify each against the
  checkout's `optional-skills/` tree: still listed there = **maintained as optional** (un-bundled only);
  absent from both = **dropped entirely**. Report the two classes separately — the owner usually means the
  dropped ones, and each optional one is one `hermes skills install official/<cat>/<name>` away.
- A skill that was *optional*-installed survives its upstream removal too; the manifest does not cover it,
  so check the plugin catalog / the deleted path in git for those separately.

**Why names and authors lie (both false-positived in practice):**

- The owner's own skills reuse the vendored frontmatter style (`author: Hermes Agent`,
  `metadata.hermes.tags`), so an author scan labels them official.
- A retired upstream skill and a live local skill can share a leaf name (`html-artifact`, `writing-plans`
  were both retired upstream *and* authored locally) — matching on name flags live skills for deletion.
- `disabled` is not a proxy for orphan: `config.yaml: skills.disabled` is a curated per-install list that
  holds the owner's own working skills right next to the dead ones.

**Execute (owner-approved list only):**

1. Confirm each target is a real directory, not a symlink into the skills-source repo
   (`[ -d … ] && [ ! -L … ]`) — deleting a symlink target would take out the repo package.
2. Tar the targets and write a `removed-list.txt` beside the archive for rollback.
3. `rm -rf` them, then `rmdir` the now-empty category dirs (`mlops/models`, `mlops/inference`).
4. Verify by count, not by eye: `hermes skills list | tail -1` enabled count must be **unchanged** (the
   removed skills were disabled) and `hermes skills list-modified` stays clean. Leave the stale
   `skills.disabled` entries in place — harmless, and removing them is a separate config edit.

## Retiring a skill across the fleet

Deleting the directory is the smallest part. A retired name survives in several layers, and two of them
are *regenerated* rather than derived from the packages on disk, so the deletion alone leaves the install
inconsistent.

1. Tar the package into the task dir before touching it: `tar czf <task>/backups/<name>-<ts>.tar.gz -C
   <skills root> <name>`. A retirement is reversible only while that archive exists.
2. Delete the directory.
3. Remove the name from `profile.yaml: allowed_skills` in every home that lists it. A whitelist entry
   naming a package that no longer exists fails the complement check permanently, and no rebuild fixes it.
4. **`skills.disabled` keeps dangling names.** `profile-layer-reconcile.py` recomputes the complement
   from the skills that exist but does not shrink a name whose package is gone, so the retired skill
   lingers in root and profile configs looking like an active policy. Grep every config after the run
   (`grep -rn '<name>' --include='*.yaml' ~/.hermes | grep -v '\.bak'`), back up each file, delete those
   lines, then reconcile once more. Do the same for `skills-reenable-exceptions.yaml` and
   `skills-reenable-exceptions.d/*.yaml`, which may name the skill for profiles that never had it.
5. Verify with three independent reads, not the reconcile output: the grep above returns nothing,
   `hermes skills list` no longer shows the name, and `contract-drift-check.py` gained no finding.
6. Retire only after the sessions that execute it finish. Deleting the package does not stop a run whose
   prompt is already loaded, but its next `skill_view` fails, so say which sessions are affected instead
   of assuming they are.

**A retiring skill is absorbed first.** Read it against the canonical skill's sections before deleting:
anything it knew that the canonical one does not (a prompt requirement, a triage rule, a transport
case) moves into the canonical skill's body or a topical reference first. Retiring a duplicate without
that diff is how a working rule disappears while everyone believes it was merged.

## Keeping a local skill family from rotting

Long-lived local skills fail in a predictable way: they are written as prose snapshots of the install
("the default model is X, providers are Y") and reality moves under them. Design against that.

1. **Split policy from state.** Hand-write the rules (what to do, why, in what order); *generate*
   anything that mirrors live config. A generated sheet (`~/.hermes/scripts/snapshot-install-facts.py` →
   `references/local-install.md`) carries providers/models/profiles/cron/channels with a "do not
   hand-edit; live wins" header. It cannot lie, and it costs one script.
2. **Assert the promises.** For every "must be true" rule add an assertion to a checker that reads live
   config (route resolves, per-profile providers defined, aux vision pinned, delivery routing,
   bundled skills stock, generated sheet fresh, enabled descriptions ≤60). Run it as a `no_agent` cron
   and **dedupe findings by hash** — silent unless the finding set changed, or it becomes noise and
   gets ignored. Scope each assertion to the population that matters (enabled skills, served profiles):
   a first run that reports dozens of legitimate-but-irrelevant items is muted within a week.
3. **When the checker fires, fix the install or the assertion — never the detector.** Deleting a check
   because it is noisy is how the family rots silently.
4. **No per-session reference files.** A dated case file is a log, not a skill: distill the durable
   rule into the topical reference and drop the narrative. If a procedure resists being stated as a
   rule, the rule is missing — not the log.

   **Merging existing cases into `references/cases.md`** (one per skill, `##` per case):

   - Verbose bodies are the safe default: concatenate them verbatim, because a case is usually kept
     for the exact commands and error strings that a summary would drop. **Compress only when the
     owner asks for it**, and then to a fixed shape — one bullet each for Signal / Cause / Fix /
     Prove / Pitfall, 5–8 lines per case. Keep command lines and verbatim error strings (paths,
     flags, `last_status` values); cut session narration, "answer shape" templates, and any catalog
     or unit file that already lives in SKILL.md or `templates/`. Re-check anchors after every
     retitle — compression rewrites headings, so every `cases.md#<slug>` pointer moves with them.
     Add one header stating that rules live in SKILL.md and the commands are leads to re-verify.
   - **Demote each case's internal headings by one level** (`##`→`###`) while merging. Split on the
     file boundary you control (one source file = one case), never on `\n## `: a case body with its
     own `##` sections turns every subsection into a sibling case and silently flattens the document.
   - Keep case headings free of `+`, `/`, `?`, quotes and backticks. Anchor slugs are mechanical, so
     a heading containing them yields `a--b` or a dropped character, and the pointer you typed by
     hand stops matching after the next retitle.
   - Rewrite every pointer in the skill tree from `references/<dated>.md` to `cases.md#<slug>`, where
     the slug is computed from the **rewritten** heading (dates stripped, backticks removed,
     punctuation dropped, spaces → hyphens). Compute the map in code; hand-typed slugs drift as soon
     as a heading is reworded.
   - Verify with `scripts/verify-skill-links.py <skill-dir>`: dangling anchors and stale dated links are
     invisible in `skill_view`, and a half-merged tree still loads.
   - If a merge already flattened the structure, rebuild from the pre-merge tar rather than editing the
     damaged file: check that the `##` count equals the case count first.
5. **Every SKILL.md answers four questions in this order**: trigger table (the exact phrases and
   error strings the owner uses, bilingual when they switch languages) → rules → proof commands with
   expected output → reference index with "load when". If a future session has to guess which file to
   open, the index is wrong.
6. **Keep descriptions honest.** The skill index truncates at ~57 chars, so a 300-char description loses
   its trigger. Audit only **enabled** local skills — `skills.disabled` entries cost no prompt space, so
   don't churn them — and fix the trigger-first sentence, not the prose that follows.
7. **Version the family together.** When one member's rule changes, grep the siblings for the same
   sentence (routing, protected files, restart safety): update the canonical home first, the pointers
   second.

## Syncing the skill-source repo upstream

When the local checkout of the shared skills repo is behind its remote, treat the sync as a migration, not a pull.

1. **Measure the real gap after a fetch.** `git fetch <remote> && git rev-list --count <branch>..origin/<branch>`.
   A stale remote-tracking ref makes `git status` report a fraction of the truth — a checkout that read
   `behind 10` was 91 commits behind.
2. **Diff the layout before pulling.** `git ls-tree -d --name-only <local-rev>:skills` vs
   `origin/<branch>:skills`. Curated skills are commonly reorganized into `skills/<category>/<name>/`; that one
   move relocates every package, so every host link pointing at the old path dangles at once.
3. **Read the repo's own rename/retire registry** (`scripts/retired_skills.toml`, the CHANGELOG, a naming-prompts
   doc) — it is the authoritative `old-name → replacement | none` map. Never infer a rename from name
   resemblance: a plausible-looking pair is a guess, and a wrong target silently wires a skill to the wrong body.
4. **Enumerate the host links that will dangle and classify each.** `find ~/.hermes/skills -maxdepth 2 -mindepth 2
   -type l` → resolve each target against the new tree: *repoint* (same name, new category), *rename* (registry
   replacement), *retire* (registry says `none`, or the package was absorbed into another skill). Count the three
   classes before touching anything. **Collapse many-to-one first**: a registry commonly maps several old names
   onto one successor, so repointing each leaves two host links to the same package and the index lists the skill
   twice — keep one link per successor, and dedupe the name where a whitelist gained both.
5. **The write side is owner-scope.** The fix lands in `profile.yaml: allowed_skills` and every home's derived
   `skills.disabled`; that is a derived-state change the owner decides, not a sweep.
6. **A host relink helper may assume the old flat layout.** A helper that finds the source at `<repo>/skills/<name>`
   (flat) locates nothing under a categorized upstream and reports no drift — a silent no-op. Verify its lookup
   against the actual tree before trusting its silence.
7. **Report before pulling when skills would retire.** Give the classification counts, the affected whitelists, and
   the skills that disappear from the fleet; a pull that removes capabilities the owner never agreed to lose is not
   a sync.
8. **Before archiving the directories a reorg leaves behind, rescue what git never tracked.** A retired or
   relocated package can hold host-local, gitignored content that is the only copy — a private project profile, a
   local config, a generated fixture. Sweep each leftover dir (`git status --ignored`, plus a `find` for files
   outside `.git`) and move that content to its new home first. Then **archive, do not delete**: `mv` the emptied
   shells into the task's backup dir so the whole migration is reversible from one place.
9. **Verify the migrated tree, not the migration.** Re-run the dangling sweep (`… -type l ! -exec test -e {} \;
   -print` → empty) and, for each renamed skill, compare the successor's frontmatter `name:` against the string you
   wrote into `allowed_skills` — an entry that differs from the package's own name resolves to nothing. Anchor the
   staleness grep (`^  - <old-name>$`) before trusting a zero: a successor whose name *contains* the old one
   (`ops-claim-verification` inside `hermes-ops-claim-verification`) makes an unanchored grep report every
   renamed entry as still stale.
