# Backing up / syncing the Hermes cockpit with chezmoi

Goal: a git-backed, restorable copy of the Hermes **setup** (config, identity, scripts, units, contract docs, local skills) on this host. Data and secrets never leave the machine.

## Source-tree mapping

chezmoi source lives at `~/.local/share/chezmoi` with `.chezmoiroot` = `home` (so `home/` maps to `~`).

| target | source entry |
|---|---|
| `~/.hermes/` | `home/private_dot_hermes/` |
| `~/.agents/` | `home/dot_agents/` |
| `~/.config/systemd/user/` | `home/dot_config/systemd/user/` |
| `~/claw/` | `home/claw/` |

Naming rules:

- `dot_<name>` targets `~/.<name>`. Use it **only** for dot targets — `dot_claw` targets `~/.claw`, not `~/claw`; a non-dot target keeps its bare name (`claw`). A wrong prefix silently manages a path nobody uses.
- `private_` sets 0600/0700, `executable_` sets the exec bit, and a file `symlink_<name>` whose **content is the target string** recreates a symlink.
- `private_` applies to the entry it names, **not** to children (see Permissions below).

## Permissions — the umask trap

`private_dot_hermes` makes the directory 0700, but every child file/dir renders at chezmoi's `umask` default. With the common `umask 002` that is 0664/0775, which contradicts Hermes' own 0600/0700 convention: `chezmoi status` then shows hundreds of `M` (mode-only) entries and `chezmoi apply` chmods the whole tree.

Fix:

1. Add `umask: 0o077` to `home/.chezmoi.yaml.tmpl` → files render 0600, dirs 0700.
2. That file is the **template for the host config** `~/.config/chezmoi/chezmoi.yaml`. Editing it alone has no effect — chezmoi warns `config file template has changed, run chezmoi init` and keeps the old values. Run `chezmoi init` to regenerate the host config, then `chezmoi apply`.
3. Expect one normalization pass that *tightens* live modes; afterwards `chezmoi status` must be empty. Never revert to `umask 002` — it re-introduces permanent mode churn.

## Plane selection (allowlist, not exclude)

Manage (config plane):
- `~/.hermes/config.yaml`, `SOUL.md`, `LOCAL_OVERRIDES.md`
- `~/.hermes/scripts/**` (drop `__pycache__`), `~/.hermes/plugins/**` (drop `.git`, `__pycache__`, `.install-metadata.json*`, `.hermes-catalog.json`)
- `~/.hermes/cron/jobs.json` (declarative job set only — see the `modify_` recipe below)
- `~/.hermes/profiles/<p>/{config.yaml,profile.yaml,SOUL.delta.md}` — **not** the generated `profiles/<p>/SOUL.md` (regenerated from root `SOUL.md` + the delta) and **not** profile `skills/` (derived symlinks; the daily reconciler rebuilds them)
- local/imported skills (see below) + `~/.agents/.skill-lock.json`
- systemd units: `hermes-gateway.service`, `hermes-auto-update.{service,timer}`, `ghc-proxy*`
- `~/claw/AGENTS.md` and `~/claw/growth-rails/**` (add `.chezmoiignore` rules so the rest of `~/claw` — research, tasks, finance — is never touched)

Never manage (data plane): `.env` and `.env.*`, `auth.json`, `.copilot_jwt.json`, `vault/`, `memories/**` (owner treats agent memory as personal data), `sessions/`, `logs/`, `*.db*`, `state/`, `state-snapshots/`, `checkpoints/`, `backups/`, `cache/`, `installs/`, `tools/`, `node/`, `bin/`, `environments/`, `lsp/`, `run/`, `runtime/`, `tmp/`, `sandboxes/`, `pairing/`, `pending*/`, `image_cache/`, `pastes/`, `telemetry/`, `gateway*/`, `whatsapp/`, `*.jsonl`, `*.lock`, `*_cache.json`, `*_cache.etag`, `channel_directory.json`, `gateway_state.json`, `install_id`, `.hermes_history`, `.skills_prompt_snapshot.json`, `kanban/**`, `cron/{output,runs,external-workers}/**` and `cron/*.db*`.

Provide a `~/.hermes/.env.example` listing only the **key names** (rendered from the real `.env`) so a restore knows what to set; values stay on the host.

## cron/jobs.json — declarative + runtime in one file

The file holds both declarative definitions and volatile runtime fields (`next_run_at`, `last_run_at`, `last_status`, `last_error`, `last_delivery_error`, `failure_streak`, `last_dispatch`, `last_failure`, `fire_claim`, `state`, `monitor_state`, `repeat.completed`, top-level `updated_at`). Committing it verbatim means the ticker rewrites counters every tick → `chezmoi status` drifts forever, and a naive `apply` rolls back counters and pause state.

Pattern that works:

1. Generator writes a **sanitized** definition set (drop the volatile keys and `repeat.completed`) to `home/.chezmoidata/cron-jobs.json` — the `.chezmoidata/` dir is chezmoi **data**, never applied to a target.
2. Generator also installs a `modify_` script as `home/private_dot_hermes/cron/modify_jobs.json` (kept in the repo as `tools/modify_jobs.py` so the logic is reviewable).
3. `modify_` semantics: chezmoi runs the script with the **current target content on stdin** and uses its **stdout as the new target content**.
4. Merge by starting from the **live job dict** and overriding only the declarative fields. That preserves live key ORDER; appending declarative keys to a repo-ordered dict instead makes `chezmoi status` permanently non-empty even though the JSON is semantically identical. Match the live trailing bytes too (the file has **no** trailing newline) — `chezmoi` compares bytes, not semantics.
5. **Union, don't drop**: keep live-only jobs so an apply never silently deletes a job added since the last sync. Deletions go through `hermes cron rm <id>` then re-sync.
6. Prove it before committing: run the script against the live file (`python3 tools/modify_jobs.py < ~/.hermes/cron/jobs.json | cmp - ~/.hermes/cron/jobs.json`) — it must be byte-identical, then `chezmoi status` empty.

## Skills: three classes, back up only one

`~/.hermes/skills` is a mix of real dirs and symlinks; `~/.agents/skills` holds the hub-installed real dirs, symlinked back into `~/.hermes/skills`. Classify each leaf skill (dir containing `SKILL.md`):

1. **builtin** — present in the Hermes source `~/.hermes/hermes-agent/skills/` (relative path or basename match); tracked by `~/.hermes/skills/.bundled_manifest`. Ships with Hermes → do **not** sync.
2. **hub-managed** — basename appears in `~/.agents/.skill-lock.json` (installed via `npx skills` / `hermes skills install`). Reinstallable from the lock → do **not** sync the content; keep the lock file.
3. **vendored** — the leaf is a **symlink** into another git repo (a public skills repo the owner publishes,
   mounted as `~/.hermes/skills/<category>/<name> -> <repo>/skills/<name>`). That repo is the single source
   of truth, so syncing the text here creates a second copy that `chezmoi apply` later writes **over the
   symlink**, silently dismantling the vendored layout; nothing complains until someone runs `apply` on a
   fresh host. Do **not** sync these, and make all three line up:
   - the generator skips them (a symlinked skill dir is already invisible to `os.walk`, which does not
     descend links — keep an explicit `os.path.islink()` skip anyway so a future `followlinks=True` cannot
     resurrect them);
   - `home/.chezmoiignore` carries a blanket `.hermes/skills/**`, which un-manages whatever the source
     tree still holds from an earlier sync;
   - the owner knows the trade: a blanket ignore also stops backing up **class-4 local** skills. Either
     accept it (the vendored repo is the durable home — port the rest) or narrow the ignore to the exact
     symlinked paths and maintain that list per port.
4. **local / imported** — everything else (e.g. `~/.hermes/skills/imports/**`, host-authored `devops/*` ops skills). These are the only ones to back up (text only: drop `.git`, `node_modules`, `__pycache__`, `.archive`, `.curator_*`, `.hub`, `.locks`).

Run `scripts/classify-skills.py` for the exact partition instead of re-deriving it. Do not try to reconstruct the hub/builtin split from `.bundled_manifest` alone — its names are the bundled *catalog*, not the installed leaf paths.

## Build the source from live

Do **not** `chezmoi add` a live tree: `add` follows/dereferences symlinks, chmods, and cannot express two real skill trees joined by symlinks. Instead write a generator under the repo (`tools/sync-from-live.py`) that copies the allowlisted planes and prefixes `executable_`/`private_`/`symlink_` as needed.

**Generate atomically.** A wipe-then-rebuild generator is a latent data-loss bug: a crash or a partial
read leaves a truncated source tree, and the next autosync commits the shortfall as a mass deletion.
Build the whole tree in `tempfile.mkdtemp(prefix=".build-", dir=REPO)`, run a sanity check on it
(`config.yaml` + `SOUL.md` present, ≥1 local skill, ≥1 systemd unit), and only then swap it in
(`shutil.rmtree` the target + `os.rename` from staging — same filesystem, so the rename is atomic;
`os.replace` for single data files). Add `.build-*/` to the repo `.gitignore`. On failure return
non-zero *without* touching the repo, so the caller's gate stops the commit. `--dry-run` must write
nothing **and skip the sanity check** (an unpopulated staging dir always fails it).

**Degrade, don't abort.** Optional inputs must not kill the sync: a missing/corrupt
`~/.agents/.skill-lock.json` means "no hub skills"; a missing builtin checkout falls back to
`.bundled_manifest` basenames (otherwise every builtin skill is silently reclassified as local and
bloat-synced); a malformed `jobs.json` skips the cron plane instead of raising.

Keep meta files minimal — each is surface area. `home/.chezmoi.yaml.tmpl` (data + `umask`) and
`home/.chezmoiremove` are needed; a per-host `.chezmoidata/<host>.yaml` "host contract" is dead
weight when nothing consumes it (the generator's allowlist *is* the contract, documented in `docs/`).
Keep `.chezmoiignore` to secrets/data only — it is functional (see below), so every extra line is a
chance to silently un-manage a managed file.

Validate with `--dry-run` before writing anything.

## Clearing a retired source (destructive, gated)

When the repo previously managed a different/retired platform, its old paths must leave the working tree or `chezmoi apply` will recreate that platform (`chezmoi status` showing `DA`/`DB` for targets that no longer exist is the tell). This is a destructive step and the approval gate treats a timeout as NO.

- Take a `git tag backup/pre-rebuild-<ts>` **and** a `tar czf` snapshot of the source dir before touching anything.
- Shell `rm`/`mv` on the repo tree are gated; `find … -exec rm -rf` can hit the hardline blocklist outright (it matches a generic recursive-delete pattern). Do not retry a blocked command.
- With explicit owner consent, the working path is a **path-asserted Python deletion** under `execute_code` (assert the repo `.git` exists, then `shutil.rmtree`/`os.remove` every top-level entry except `.git`). It is scoped, auditable, and leaves `.git` intact so history and the backup tag survive.
- Deleting the retired files and committing is enough — no force-push needed for a private repo.

### Gated writes: the repo `AGENTS.md`

Authoring the repo's own `AGENTS.md` through `write_file` hits a **protected agent-instruction
file** gate (any `AGENTS.md` path). A timeout on that prompt is a NO, and the gate re-prompts on
*every* attempt — do not loop on it. Take explicit owner consent first ("retry, I'll approve"), then
issue the write once while the owner is watching. Everything else in the repo (`README.md`,
`docs/**`, `tools/**`, `home/**`) writes normally; only the agent-instruction filename is gated.

## .chezmoiignore is functional, not documentation

`.chezmoiignore` filters the **source state** as well as `chezmoi add`. A pattern that matches a file you intend to manage silently un-manages it. Under any broad ignore (e.g. `claw/*`) you must negate every managed path (`!claw/AGENTS.md`, `!claw/growth-rails/**`). Patterns are target-relative (relative to `~`).

## Two `chezmoi add`/`apply` traps when realigning by hand

After a clean rebuild you sometimes only need to align a handful of files. Both commands refuse in a
non-TTY session, and the obvious workarounds are wrong:

- `chezmoi add <file>` asks `would remove private attribute, continue?` when the live file's mode is wider
  than the source entry's `private_` attribute (a 0664 profile `config.yaml` behind a `private_config.yaml`
  source). There is no `--private` flag to force it, and `--force` does not answer the prompt. Write the
  target bytes straight into `chezmoi source-path <file>` instead — attributes stay as they were and
  `chezmoi status` goes quiet.
- `chezmoi apply <path>` refuses with `has changed since chezmoi last wrote it` whenever the file moved
  after the last apply. When the only remaining diff is the **mode** (source carries `private_`, live is
  0664) and the content is already identical, `chmod 600` the live file: that is exactly what apply would
  have done, without letting chezmoi rewrite content you did not review.

Verify with `chezmoi diff` (0 lines) and `chezmoi status` (0 entries), not with exit codes.

## Runtime drift is normal

`~/.hermes/config.yaml` is rewritten by Hermes at runtime (observed: an `approvals.timeout` value persisted by an approval/clarify interaction). Expect 1-2 `M` entries between syncs; treat it as drift to re-sync, not breakage. The routine is: change live → `python3 tools/sync-from-live.py` → `tools/verify.sh` → commit.

## Verify before commit

1. `chezmoi status` — expected empty; any content diff means the generator diverged from live (a mode-only diff means the umask rule regressed).
2. Secret scan the staged tree: `grep -rInE '(sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|BEGIN (RSA|OPENSSH|EC) PRIVATE KEY)' home/` — treat only *real* values as hits (docs use `sk-xxx` placeholders).
3. Confirm no `.env` / `auth.json` / `*.db` / `*.jsonl` / `MEMORY.md` and no nested `.git` or `node_modules` landed in the source.
4. `chezmoi apply --dry-run -v` to confirm no unexpected create/delete on the host.
5. Commit locally; push only on explicit owner authorization.

Ship a `tools/verify.sh` that runs 2-4 and prints a single pass/fail line, so the check is one command instead of four.

## Automating the sync (systemd user timer, verify-gated)

Use a **systemd --user** timer + oneshot service, not Hermes cron (this is cockpit ops, and a
CLI-created cron job is local-only with no delivery). Script in `~/.hermes/scripts/`, units in
`~/.config/systemd/user/` — both are inside the synced plane, so the automation backs itself up.

Order inside the script matters:

1. `python3 tools/sync-from-live.py` (exit on failure).
2. `chezmoi apply` — **required**, not optional. Files created after the last sync land 0644/0755 in
   live while chezmoi renders 0600/0700 under `umask 0o077`, so without this step `verify.sh` reports
   permanent mode drift (observed: 3 entries for a new script + 2 units) and the repo never looks
   clean. The source was just rebuilt from live, so apply is a content no-op that only tightens perms.
3. `./tools/verify.sh` — the gate; non-zero means commit nothing.
4. Stage-guard: refuse to commit if `git diff --cached --name-only` matches
   `.env`/`auth.json`/`*.db`/`*.jsonl`/`MEMORY.md`, then `git reset`.
4b. Deletion guard: refuse if `git diff --cached --diff-filter=D --name-only | wc -l` exceeds a small
   bound (25 is generous — a normal sync adds/changes a few files). Defence in depth behind the
   generator's sanity check; a plane wipe must never reach the remote.
5. Commit **only if** `git diff --cached --quiet` is false; then `git push origin main`.

Idempotency proof: run the service twice — the second run must log `no changes` and leave HEAD
unchanged. A failed run is journal-only (`journalctl --user -u dotclaw-autosync.service`); it never
leaves a half-committed repo.

**The literal gate scans the whole tree: one personal/host identifier freezes every pending change.**
`verify.sh` refuses the commit with `<source-relpath>: line N: generalized file carries personal/host
identifier '<literal>'` and `RESULT: FAIL`, so the destination stays at the last good commit while the
log names a single file. Because this pipeline regenerates the source **from live**, the fix belongs in
the **live** file (the offender's real path under `~/.hermes/...`) — edit there and re-run the sync;
editing the repo tree is overwritten by the next regeneration. Read the failing stage from the journal,
not from the notification: the notify is deduped per reason per day, so a persistent failure pings once
and then goes silent while every 6h tick still logs its stage lines.

Credential pitfall: the helper is `!gh auth git-credential`, i.e. an **absolute** `/usr/bin/gh`, so it
resolves in systemd's minimal PATH. Verify before trusting the timer:
`env -i HOME="$HOME" PATH="/usr/bin:/bin" bash -c 'printf "protocol=https\nhost=github.com\n\n" | /usr/bin/gh auth git-credential get'`
must print `username=`/`password=`. (Note the `get` argument — without it gh errors
`accepts 1 arg(s), received 0`.) No `~/.git-credentials` is needed.

When adding the units, also add them to the generator's `SYSTEMD_UNITS` list or they stay unmanaged
and silently absent from the backup.

## Closing out after config work

A manual run of the sanctioned autosync script is the expected last step after config/provider/doc changes.
Verify the close-out on content, not on the diff:

1. `git -C <repo> status --short` empty **and** `git log origin/main..main --oneline` empty ⇒ committed and
   pushed.
2. `git show HEAD:<source path>` must contain each change. A file you edited can be **absent from the newest
   commit** because an earlier run already committed it — a missing diff is not evidence of a lost edit, and
   re-editing live to "make the diff appear" is wrong. Check content in HEAD, then conclude.
3. **Bundled/builtin skill content is never in the repo by design** (see the classifier rules).
   `git show HEAD:<that path>` failing there is expected — report it as a coverage gap, not a sync bug. Because
   those files are box-only, mirror any owner-specific fact that lives inside them into a synced plane
   (`LOCAL_OVERRIDES.md`) so a host rebuild does not lose it.
4. Commit subjects are generated boilerplate — read the file list, never the subject, as the description of
   what moved.

## Landing a merged repo change into the live host

The forward routine (change live → regenerate → commit) has a reverse: the repo already holds the change
(merged to `main`) and the host is behind. Same gates, opposite direction.

1. **Run git against the source repo through `chezmoi git -- <cmd>`** (`chezmoi git -- status -sb`,
   `-- log --oneline -3`, `-- merge --ff-only origin/main`). The chezmoi source tree is its own git repo;
   a plain `git` from `~/.hermes` is a different one.
2. **Classify the dirty worktree before fast-forwarding.** `chezmoi git -- status --porcelain` names the
   intentionally drifted files (runtime-written config, local overrides). The ff is safe **iff** the dirty
   set does not intersect `git diff --name-only <old>..<new>` from the incoming commit — check before
   running it, and never `checkout`/`stash` the drift to make the tree clean.
3. **Seed new template data before apply.** A commit that adds a `promptStringOnce` prompt
   (`.chezmoi.yaml.tmpl`) has no value until answered: `chezmoi init --promptString "<prompt text>=<value>"`
   (no `--apply`). The `--promptString` argument is the prompt's **text** (`git author name=<value>`), not
   its data key (`git.name=…`); the key form binds nothing and `chezmoi data` still lacks the value.
4. **Read `chezmoi data` narrowly.** It dumps the host facts **plus the full scheduled-job list** as one
   large JSON blob that floods the output; pipe it through a one-liner that prints only the key you asked
   for, e.g. `chezmoi data | python3 -c 'import sys,json; print(json.load(sys.stdin).get("git"))'`.
5. **Gate on the diff, then apply the narrow scope.** `chezmoi diff --include=scripts` must show only the
   expected script body (the rendered lines) — anything else is a stop. Then
   `chezmoi apply -v --include=scripts`. **Never a bare `chezmoi apply`** on a host carrying known drift: a
   full apply reconciles every managed plane and can churn files you were told not to touch; the
   script-only scope is the generator's narrow operation.
6. **Prove idempotency, then the effect.** Re-run the same narrow apply — a `run_onchange` script that
   already fired prints **no output** and exits 0. Read the effect back with the effective value
   (`git config --global --list`, `git -C <repo> var GIT_AUTHOR_IDENT`) and the file's `sha256sum` against
   a pre-change backup. A script that rewrites a value identical to the existing one moves the file's
   **mtime but not its bytes** — `sha256sum` equal to the backup is the proof content did not move, and a
   bare `ls -l` mtime looks like a change when it is not one.
