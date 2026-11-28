---
name: hermes-skill-generalization-gate
description: Use when a skill is nominated, renamed, or applied back.
---

# Skill generalization gate

## When to Use

Use when a skill is new, materially changed, renamed, or proposed for the shared catalog
(`~/repos/hoa`), or when a refactored skill must be applied back into the live Hermes install.

You are the **gatekeeper**, not the author. You decide *whether* and *what is missing*; the owning
line writes the rewrite, the builder lands the PR, a one-shot different-family model reviews it, the
owner merges. Never score your own draft.

## The rubric (single source)

`~/repos/hoa/rules/generalization-rubric.md` — read it before any verdict. Six gates
(topology neutral / no implicit host coupling / ≤3 required config keys with defaults /
anti-trigger / runnable by a stranger / failure modes), plus the hard-fail list.

Admission is layered, not mechanism-only: `entry` / `mechanism` are bounded protocols or judgment
rubrics; `controller` / `stage` are admitted when every repo-specific gate, path, launcher, review bot
and approval boundary is configuration or an ignored project profile, and the artifact contract is
declared in `metadata` for CI to check. A verdict that still demands "atomic primitives only"
contradicts the four-layer contract the repo's own CI enforces — fix the rule, do not fail the skill for
obeying the newer one.

Report **gaps**, not numbers. A "pass" is only valid with an empty-`$HOME` run log.

## Audit the plan before the first edit

For a cross-cutting catalog change (family rename, loop split, multi-skill port), the owner expects an
independent design audit *before* anything is edited. Gate it as: requirement verbatim, decisions marked
as already made, one verdict per open item with a counter-example that passes every check and is still
wrong, and a disposition table carried into the implementation. Prompt skeleton, lane setup and what such
an audit reliably catches: [`references/design-audit-before-execution.md`](references/design-audit-before-execution.md).

## Nomination triage (event-driven)

Trigger: new skill, material change, or explicit proposal. Do not rescore an unchanged catalog —
model noise manufactures refactor churn.

1. Read the skill's `SKILL.md` against the six gates; write the gap list to
   `~/claw/tasks/YYYY-MM-DD/skill-gate/<skill>.md` (one section per failed gate, evidence line each).
2. Decide one verdict: `keep-private` / `refactor` / `ready`.
3. For `refactor`, state the split: what stays a bounded primitive, what is environment scalar
   (config key + default), and what must remain a private workflow. A loop or a single phase is
   admissible when its repo-specific gates, launcher, review bot and approval boundary are
   configuration; a config key may still never change the step graph or the output contract — that is
   "split", not "parameterize".
4. Hand off: `refactor` → builder (`forge`) opens the PR; `ready` → owner merges after CI.

## Quarterly deterministic sweep (no model in the loop)

Shipped as one monthly `no_agent` cron (`[ops] hoa catalog sweep`, `0 4 1 * *`, stdout delivered
verbatim, silence when clean) running `~/.hermes/scripts/hoa-catalog-sweep.sh`:

```bash
PY=~/.hermes/hermes-agent/venv/bin/python          # a bare python3 may lack PyYAML
$PY ~/repos/hoa/scripts/generate_index.py --check  # index.md / index.zh-CN.md byte-fresh
$PY ~/.hermes/scripts/skill-applyback-guard.py schema
$PY ~/.hermes/scripts/skill-applyback-guard.py check
```

Report only findings. Silence means no drift — do not send an "all good" message. Two traps that made an
earlier version of this sweep useless: `skill-literals-ledger.py` has **no `--check`** (it takes `--list`
/ `--skill`, and it is a backlog ledger, not a pass/fail gate — do not wire it as one), and any helper
invoked with the wrong interpreter fails closed with `ModuleNotFoundError`, which looks like a finding.

**Catalog admission has its own paperwork.** A new file under `~/repos/hoa/rules/` must open with an
`<!-- index: areas=…; targets=…; summary="…"; summary_zh="…" -->` comment, `areas` drawn only from the
tuple inside `scripts/generate_index.py` (unknown area ⇒ hard failure), and both `index.md` /
`index.zh-CN.md` regenerated in the same commit — `--check` compares them byte-for-byte.

## Apply-back guard (the part that actually rots)

```bash
~/.hermes/hermes-agent/venv/bin/python ~/.hermes/scripts/skill-applyback-guard.py verify
~/.hermes/hermes-agent/venv/bin/python ~/.hermes/scripts/skill-applyback-guard.py check --home forge
```

`verify` = lock hash + source hash + read-only mode + tier conflicts + unmanaged entries + config
schema + declared `smoke.json` runs in an empty `$HOME`. Exit 0 clean, 1 violations.

Never hand-edit a materialized copy. To change a skill: edit the source → rematerialize
(`profile-skill-materialize.py --apply`) → `verify` → only then switch the lock. A drift is a hard
stop, not a warning.

**A guard that has never failed is unverified.** Prove it bites before trusting a clean run: copy one
home's `profile.yaml` + a single `skills.lock.json` entry + that skill dir into a throwaway
`HERMES_HOME=<tmp>/.hermes`, run `check` (expect rc=0), then `chmod -R u+w` one copy and append a byte —
expect rc=1 naming `live tree … != lock …`. Restore nothing; the sandbox is disposable.

## One job per cadence, not one job per check

The read-only half is wired into the existing daily health check
(`hermes_health.py --applyback-probe`, emitted as `skill_applyback` findings), so a drift surfaces with
the rest of the ops signal. The deterministic catalog sweep is the single monthly `no_agent` job above.
Do **not** add a third schedule covering either cadence: one invariant checked by two schedules doubles
the noise and halves the trust. Nomination triage stays event-driven — no schedule at all.

**When the layout these checks model changes, migrate the declarations in the same change.** A checker
left measuring the old world (symlink farms, delta files, one shared identity block) keeps reporting
drift that no longer exists; the findings get tuned out and the alarm is muted for days. Order:
rewrite declarations → back up and clear the finding state file → require the healthy run to print
**zero lines** → re-prove one negative test per finding class (make a copy writable, truncate a head
block by one byte) and restore it. A new finding key must be registered with the runner before it is
wired in: an unregistered `check`/`intent_ref` raises at emit time, the run exits non-zero, and the
violation hides inside "harness failure".

## Port gate — public mirrors get reviewed, not swept blindly

Anything headed for a public mirror (the <private-repo> chezmoi source, `hoa`, any published repo) passes this
gate first: **review, generalize, then port**. Unreviewed porting is forbidden even for a path that
already lives in the mirror — the live tree changes shape and the mirror silently follows.

**Sweep for the predictable classes before the first push.** Ported host content draws the same
findings round after round — each one a real defect, each one avoidable — so the sweep is what makes
review a confirmation instead of a discovery loop. Checklist with the greps and the fixes:
[`references/portability-sweep.md`](references/portability-sweep.md). The short version: selected install
root (`$HERMES_HOME`, not `~/.hermes`, expanded and checked before use), install-only scripts presented as
mandatory, account-specific policy lists shipped as upstream truth, fixed rosters, silent-empty fallbacks,
literal credentials in probes, variables inside quoted heredocs, and name-only snapshots that make a real
change look like no change.

**The privacy red line is repo-wide, and an edit is an arrival.** The catalog repo is public, so the scan
covers every path, not only `skills/`; and a **change to an already-curated skill re-opens the same question**
as a new candidate — an edit is the easiest way for a host path, an account id or a personal handle to slip
back into a file that was already clean. State the boundary in the verdict instead of implying coverage:
`check_unfettered.py` enforces this for the landing zone only, so for `skills/`, `prompts/`, `docs/` and
`rules/` the reviewer runs the literal scan by hand and puts the hit counts in the report. Invented fixture
identities (the reserved `example.*` domains, invented user names) are not leaks — sharpen the scan, never
rewrite the fixture.

1. Classify every pending path into `retired-by-design` / `renamed` / `generalize-then-port` /
   `local-only` / `unexplained`, with a one-line evidence note each. **`unexplained` must reach zero**
   before anything commits; open the live tree and the HEAD blob for each one.
2. `generalize-then-port`: host paths, bot/channel/account ids, personal data, model-specific defaults
   become config keys with defaults; the mirror receives the generalized file, never the literal one.
3. `local-only`: runtime state, session data, anything credential-shaped — excluded by manifest, not by
   remembering.
4. Encode the outcome as a manifest (path glob → `as-is | generalized | never`) plus a checker that runs
   inside the mirror's own `verify.sh`, listing the offending path and reason and stopping before commit.
5. **Moving a literal into config is half a change — the consumer environment must define the key in the
   same change.** `os.environ.get("CHANNEL_ID", "")` with no key and an empty default degrades silently:
   every run succeeds and nothing is delivered. Either keep a non-empty default for a value that must
   exist on this host, or add the key to the env file and assert it resolves at startup. Verify by
   printing the value's **length**, never the value — these keys sit next to credentials.
6. **Accept a dispatched classification as a draft, not a delivery.** A headless helper can die mid-run
   (host restart, dropped session) leaving half the rows classified and live files already edited. On
   return: read `git log` in the mirror (an auto-sync may have committed the partial work), diff every
   touched file against its backup byte-for-byte, and require `unexplained == 0` before committing.
   Finish the remainder yourself rather than re-dispatching the whole scope.

**A mass-deletion refusal is a finding, not a knob.** When an autosync refuses because "N deletions
staged (suspicious)", do not raise the threshold — decompose the batch: retired-by-design files
(`SOUL.delta`, dead homes) are expected, the rest is either a rename the differ could not follow or a
generator eating live files. Allow deletions only through an explicit reviewed allowlist file.

## Where a self-evolved skill lands (write path)

A self-evolved skill **never** goes into `skills/` directly and never forks a built-in. Settle three
things first — is it a Hermes built-in (then stop: use upstream, or file the change upstream), is it
coupled to Hermes (then `hermes-<topic>` in both tiers), what is its name — then land a candidate in the
destination's landing zone: `~/repos/hoa/unfettered-skills/<name>/SKILL.md`, preflight it with
`uv run --script scripts/check_unfettered.py --base origin/main`, and stop. Promotion into
`skills/<category>/<name>/` is the owner's PR — never a sync and never a copy.

On this host `~/.hermes/scripts/hoa-sync.sh` (wired into `[ops] repo auto-sync`) stages only the landing
zone, scans it, commits, runs the same `check_unfettered` preflight and pushes `main` — so writing the
candidate is the whole job. `hoa` is a **PUBLIC** repo: a landed candidate is world-visible
before review. Full brief, write rules and CI checks:
[`references/self-evolved-skill-handoff.md`](references/self-evolved-skill-handoff.md).

## Renaming or restructuring a skill family

A rename is a cross-cutting change: the ripple, not the rename, is the work. Full inventory:
[`references/renames.md`](references/renames.md). The two that bite hardest:

- **When the live install symlinks into the canonical repo, the rename is live before any merge.** The
  moment the working tree renames the directory, every runtime symlink into it dangles and the skill
  disappears from the loader while allow-lists still name the old string — neither name resolves. Do the
  rename and the host switch in one sitting (backup → remove old entries → re-link → update allow-lists
  → materialize → parity check), and never park a half-done rename.
- **Grep the whole repo, not just `skills/`.** Maintenance scripts that mirror shared files into a
  skill's `scripts/` dir keep a path map with the old name, and sibling-relative launcher paths resolve
  one directory up; both fail silently, and only their own tests prove them.

**Before naming the family, prove it should exist.** The prefix goes only to skills that *are* the loop,
and members are named after the phase verb — but run the necessity test first, because the usual answer
is that the family is a pseudo-family: accept / gates / recover / measure are phases of one protocol,
not separate capabilities, and their content is already written in the phase notes. The default decomposition for
a loop is **one entry skill plus `references/phases/*.md` playbooks**, addressed by stage name; a
per-phase skill must earn its own trigger, and "one phase of the loop" is not a trigger. A general
capability the loop merely calls keeps its own name, or the prefix stops meaning anything.

**Fold back only the net-new rules, and land each one on an executable mechanism.** When a phase skill
is retired into the phase notes, the temptation is to paste its body in; instead diff it against the
notes and keep only what is not already there. Before keeping a rule, name what it hooks into — a config
key with a default, a stage-template variable, a ledger column, a script check, a profile field. A rule
that lands as prose with nothing to act on it is unenforceable and gets skipped the first busy day: the
loop still passes every check and the rule is decoration. Either add the mechanism in the same change
or drop the rule — and count the ported rules in the PR body so the reviewer can see the diff is a fold,
not a copy.

## Landing a change in the catalog repo

Editing the catalog is a normal PR with a paperwork gate of its own:

- **Do it in a dedicated worktree, never in the live checkout.** The host's skills are symlinks into that
  checkout, so checking out a branch there swaps the skills the running agent is using, mid-task — the
  change is live before any merge. `git worktree add -b <type>/<slug> <task>/wt origin/main`.
- **Every PR bumps the patch version, and the bump is a wide diff by design.**
  `python scripts/version.py check-bump` is the guard; `python scripts/version.py bump` writes `VERSION` and
  mirrors it into every skill's `metadata.version` plus both generated indexes — a one-line skill edit
  arrives as dozens of changed files. That is the mirror, not scope creep: never hand-edit those scalars,
  and expect a concurrent PR to conflict on exactly those paths.
- **A version bump flips the changelog check on.** While `VERSION` is unchanged the check reports no entry
  required; the moment it moves, the same command demands one, so add `## [<version>] — <date>` with a
  `### Changed` bullet in the same commit.
- **Run the repo's whole PR gate set locally before pushing** — it is the workflow's own step list, and it
  is cheap (use an interpreter that has `scripts/requirements.txt`; see the interpreter note above):
  `vendor_shared.py --check`, `generate_index.py --check`, `check_frontmatter.py`,
  `check_contract_graph.py`, `version.py check`, `version.py check-bump`,
  `check_changelog.py --base origin/main`.
- **Read the CI config in *your* tree before running a command copied out of it.** A step can invoke a
  script that exists only on another branch (a discoverer landing in its own PR), so the file-not-found is
  your base, not a broken repo — run the steps that exist there and re-read the config after a fetch.
- A docs-only catalog PR still owes both inspection stages; the catalog's merge rule is not waived by a
  small diff.

## Hard rules

- Private line material never enters the public catalog; private is isolated by repo, not by a label.
- No skill audit may route work through `*-nrs` bots or their chains — the two lines share only skills.
- Follow-up actions that change live behaviour still obey the normal action gates.
