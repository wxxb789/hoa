# Fleet profile-layer drift cleanup

Ordered procedure for "the drift checker is red, clear it" on a multi-profile install: profiles, skill
whitelists, instruction files, generated NRS profiles, cron. Every step is reversible and every step has
its own verifier.

## 0. Ground truth before touching anything

```bash
python3 ~/.hermes/scripts/contract-drift-check.py >/tmp/drift.out 2>&1; echo "drift_rc=$?"; cat /tmp/drift.out
python3 ~/.hermes/scripts/profile-layer-reconcile.py --dry-run >/tmp/rec.out 2>&1; echo "rc=$?"; cat /tmp/rec.out
```

Both print **nothing** when healthy. Run them with the redirect + `echo $?` shape, never
`python3 … | tail`: the pipeline's exit code is `tail`'s, so a red install reads as green.

The reconcile wrapper only accepts `--dry-run`; to apply, run its underlying layers directly
(`sync-profile-soul.py --apply`, `sync-profile-skills.py --apply`, `sync-profile-skill-policy.py --apply`)
plus `core_invariants_compiler.compile_targets`. It does **not** run `materialize.py` — repo-materialized
`*-nrs` profiles are a separate layer.

## 1. Classify each finding

| Finding | Owner of the fix |
|---|---|
| `allowed_skills 含不存在于宿主的技能` (skill renamed/deleted) | repo bindings for `*-nrs`, `profile.yaml` for core bots |
| `skills.disabled 与 allowed_skills 不互补` (a new host skill is in no list) | derived state — run the policy sync, never hand-edit |
| `AGENTS.md 里 \<bot\> 的模型名 …` | instruction file (see 4) |
| `AGENTS.md 体积异常` | instruction file (see 5) |
| NRS 受管区 / `nrs-managed.yaml` mismatch | generated — rerun `materialize.py --apply` |
| `profile SOUL 与根不同步` quoting a reconcile ERROR | symptom of the layer that failed; fix that layer, the SOUL line clears |

## 2. Fix order (this is the part that costs a round when wrong)

1. **Instruction layer first** (`AGENTS.md` model declarations, size). `materialize.py --apply` runs
   `contract-drift-check.py` as its post-check and **rolls back the host control files when it fails**,
   leaving freshly rewritten `profile.yaml` files behind — the next `--check` then reports
   `profile.yaml allowed_skills != binding skills.allowed` for every bot, which looks like a new bug.
2. **Repo bindings** (`<repo>/bots/bindings/hermes/*.yaml`) — SSOT for `*-nrs`.
3. `python3 bots/bindings/hermes/materialize.py --apply` → expect `applied N change(s)`; then `--check`
   must be silent.
4. `python3 ~/.hermes/scripts/sync-profile-skill-policy.py --apply` → `[OK] positive skill whitelists
   aligned (… host skills, … known)`.
5. Re-run both verifiers from step 0; both silent, `rc=0`.

Back up first, one directory, one copy per touched file. **Enumerate from what each `--apply` writes, not
from what you remember editing:** `sync-profile-skill-policy.py --apply` rewrites every
`profiles/*/config.yaml` (the derived `skills.disabled` list), `materialize.py` rewrites the `*-nrs`
profiles, and the instruction file is `~/claw/AGENTS.md` — `~/.hermes/AGENTS.md` does not exist. A copy of
a nonexistent path is a **silent no-backup**: assert `os.path.exists(src)` (or `test -e`) per source and
fail loudly, and print the byte size of every copy so a zero-size or missing entry shows up in the log.
Commit + push the repo-side fix if the repo is git-as-sync.

Instruction-file edits are the one that gets forgotten: the backup helper usually names `AGENTS.md` under
`~/.hermes/` (where `SOUL.md` lives) and silently skips the real file. Confirm the backup dir contains a
non-trivial `AGENTS.md` before making the first edit.

## 3. Skill rename across the fleet

- `*-nrs`: rename the entry in each binding. Where a binding already lists the **new** name, delete the
  stale line instead of renaming (otherwise the list carries both).
- Core bots: `~/.hermes/profiles/<p>/profile.yaml` usually already lists the new name too — delete the
  stale line, do not rename it.
- Generated `profiles/<p>/profile.yaml` for `*-nrs` keep the stale name until `materialize.py --apply`
  rewrites them; do not hand-edit those.
- Verify with `grep -rn '<old-name>' ~/.hermes/profiles/*/profile.yaml <repo>/bots/bindings/hermes/*.yaml`
  → no hits.

## 4. Instruction-layer model declarations

`contract-drift-check.py` must only validate a **declaration** (``‘Name’（目录 `dir`，模型 `model`）``),
not any line that happens to contain the bot name. Substring matching on the profile name plus the first
model token on the line produces permanent false positives — a bot named `work` matches `worktree` /
`workspace`, and a routing paragraph that lists several bot names next to a provider's model flags them
all.

```python
DECL_RE = re.compile(r"目录\s*`?([\w.-]+)`?[^（）\n|]*?模型\s*`([^`]+)`")
```

Regress-test the checker itself both ways before trusting a green run. **Give the checker a `--self-test`
flag instead of relying on an ad-hoc snippet**, and point it at a pure parse function
(`declared_models(text) -> dict`) rather than at live profiles — a test that asserts a bot's *current* model
breaks the day the owner changes that model. Cases: mention-only line → `{}`; explicit declaration → one
entry; a line mentioning `workspace`/`worktree` → `{}`; two declarations on two lines → two entries. The
installed scripts tree has no `tests/` directory, so an argv-gated self-test is the cheapest repeatable
probe:

```python
def main() -> int:
    if "--self-test" in sys.argv[1:]:
        return self_test()
```

Also delete the regex the refactor orphaned (a `MODEL_RE` left defined-but-unused reads as live logic to
the next editor).

## 5. AGENTS.md size ceiling

The checker enforces a byte window (single-digit–25 KB) on `~/claw/AGENTS.md`. When it trips, **compress
prose, never drop rules**: owner policy sentences stay, historical backup paths / migration status /
restatements of what `config.yaml` already holds go. Measure bytes, not characters
(`len(text.encode())` — CJK is 3 bytes/char) and **leave headroom**: landing exactly on the ceiling turns
the next unrelated seven-byte edit into a red install, so trim until the file sits a couple of hundred
bytes under it.

Two more rules from doing it:

- **A literal that counts live state is the thing to delete, not to update.** `（正向白名单，Zoe 26 个）` was
already wrong (30); replacing 26 with 30 buys one week. Drop the number.
- **Gate the write on the post-condition.** A script that applies N replacements and persists when
  `not missing` will happily leave a 25 007-byte file on disk; assert `len(new.encode()) <= ceiling`
  *before* `open(..., "w")`, and treat a failed assert as "trim more", never as "write anyway, re-check later".
- Keep the rule set verifiable after the trim: `##` heading count, `- ` bullet count and code-fence count
  must be identical before and after (this session: 19 / 109 / 0 both sides). A drop means a rule left.

Write it as: full `read_file` of the instruction file once, then one anchored patch per region with
`t.count(old) == 1` asserted per replacement, then re-stat the file. Never blind-overwrite.

## 6. Cron duplicates found during cleanup

`cron-ledger.py` hints (`无前缀，无法归属`) only recognise `[ops]` / `[bot:]` prefixes; `[task] …` and
`[review] …` job names are legitimate and not drift — leave them.

A real duplicate shows up in `~/.hermes/cron/jobs.json`: same `name` + `schedule` in two homes, one of
them `enabled: false`, and a `deliver` pointing at a channel where the contract says DM. Copy
`jobs.json` to the backup dir, delete the disabled one with `cronjob_manage(action="remove")`, then
confirm the survivor (`grep '\[bot:<profile>\] <name>'` in `cron-ledger.py` output). Before deleting,
check no surviving job lists the id in `context_from`.

## 7. Audit your own batch before reporting it (and stop at the boundary)

The owner will ask "all six done?" — answer it with a per-item diff, not with the fact that the checker
is green:

- **Diff every touched file against its backup** and classify each as `identical` or `only intended
  lines`. A file whose diff contains an extra hunk is a second, unreported change.
- **Where a backup is missing, say so and give the compensated verification**, e.g. "`profiles/*/config.yaml`
  were not captured; the list is a deterministic derivation (`disabled == known_universe − allowed_skills`),
  `--check` passes, and the root diff is exactly `+ <new skill>`". Never present a green `--check` as if it
  were a line diff.
- **Write a `README.md` into the backup dir**: what was changed, one rollback command per artifact, and
  explicitly what was *not* captured. Reconstructed-from-memory copies are acceptable only when labelled
  with their byte delta against the original.
- **A cleanup restores green; it does not spend owner decisions.** When the sweep derives a new state
  (a newly installed skill becomes `disabled` in every home), that is a grant/revoke question — report one
  numbered line and leave it disabled. Same for roster shape, whitelist membership and cron naming: if the
  owner says another session will optimise profiles, the correct deliverable is "drift 0 + one open
  decision", not a redesigned fleet.
