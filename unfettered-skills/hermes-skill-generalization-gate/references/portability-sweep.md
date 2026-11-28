# Portability sweep before the first push

Host-authored skill content entering the shared catalog draws review findings in a handful of recurring
classes. Sweep them yourself first: each round of review that *discovers* one of these costs a commit, a
re-review and a re-resolve, and a large port can absorb six rounds finding exactly the items below one at
a time.

Run this on the diff, before opening the PR. Every item is a rule plus the fix.

## 1. Host paths, private names, ids

`grep -rInE '/home/<user>/claw|~/repos/<private-repo>|[0-9]{18,19}|sk-[A-Za-z0-9_-]{12,}' <skill>`

A workspace path becomes a named variable with a default (`CLAW_HOME=${CLAW_HOME:-$HOME/claw}`), a private
repo name becomes its role ("the roster repo"), and an id is a config key. Keep the grep in the checklist,
not just in your head: the sweep is the evidence.

**A personal handle is its own class, and its blast radius is the whole mirror.** The <private-repo> gate
(`tools/check-port.py`) matches the install's account/machine names (`REAL_NAME_RE`) and `/home/<user>`
(`HOME_PATH_RE`) inside *every* file the manifest marks `generalized`. Read the exact token set from those
two regexes rather than copying it — that file is the single source, and a copy of the tokens inside a
generalized doc is itself a finding. The scan is repo-wide and pre-commit, so a single literal anywhere
fails the gate and the **entire autosync halts**: nothing commits, every unrelated pending change is stuck
behind it, and the failure notice is sent at most once per day, so the mirror can sit stale and silent for a
day or more before anyone sees it. Run those two patterns over the whole diff before pushing, not just the
file you meant to edit. Generalize a measured example to a placeholder (`owner/wt-prep-toprule`) and keep
the lesson; never add an allowlist entry for the token — exempting it ships the handle into the mirror.

**Documents are swept too, and they carry a second class of literal.** A plan, design note or README drafted
in the private workspace ships the paths of whatever produced its numbers — the scan script under the
workspace, the throwaway worktree the audit ran in. Replace the path with the method a reader can re-run
from the repo, or the document asks a stranger to open a directory they do not have. Then apply the target
repo's own document policy before committing: the mirror states its language rule in its README ("English
is the source of truth", with the other language as a pointer), so a document written for the owner in
another language is a finding, not a style preference. The repo decides the language of what lands in it,
and the drafting session does not.

## 2. Install-only tooling presented as mandatory

Any step naming a script under the host's own workspace, another skill's directory, or a test harness that
does not ship with this skill. A stranger following the step gets `command not found` and the procedure
reads as broken.

Fix in two parts: state the **contract** (what must be true afterwards — the subcommands, the exit-code
semantics, the observable outcome) as the requirement, and resolve the **command** through the skill
config chain (flag → env → `$XDG_CONFIG_HOME/<skill>/config.yaml` → an adapter the install ships). "Do it
by hand and satisfy the contract" must be a legitimate answer.

## 3. The selected install root

Sweep for `~/.hermes` where the operator can relocate or select (`$HERMES_HOME`, `$HERMES_ROOT`) and for
`Path.home()` used to build a default argument.

The one that bites: a backup step that copies the *default* home while the following commands write to the
*selected* home — the backup succeeds and the change is unprotected. Rule: back up the home you are about
to change. Same for a default CLI argument: resolve the env var before falling back to `~/.hermes`.

Two more from the same sweep:

- **Precedence, not either/or.** `HERMES_ROOT` is the installation root, `HERMES_HOME` is the home in use:
  read `HERMES_HOME or HERMES_ROOT or ~/.hermes`. The reverse order audits the root while the operator has
  a profile selected, and the diff it prints still looks plausible.
- **Expand before you check, and refuse a target that is not there.** `Path("~/.hermes").is_dir()` is
  False, so a literal tilde reads as a missing install; and a checker handed a home that does not exist
  must stop naming the path rather than emit an empty inventory for a tree it never opened.

## 4. Account-specific policy shipped as shared truth

Ban lists, "unavailable on this account", retired-id tiers, "this install's hard policy". The method is
portable; the list is not, and importing it tells another operator their working route is dead.

Fix: keep the **method** (probe the endpoint, call each candidate, derive the live set), push the list to
the install's own overlay, and label example provider keys as the reference install's so nobody edits
their config to match a stranger's.

## 5. Fixed rosters

"The five homes", a named bot list, a hardcoded profile loop (`for p in ('a-nrs','b-nrs')`). On a different
fleet this turns one request into edits to homes that do not exist, and a probe fails on the first missing
name.

Fix: enumerate what exists (`$HERMES_HOME/profiles/*/config.yaml`, the roster repo's bindings, a glob) and
require the report to state what was enumerated — a home you could not enumerate is *not covered*, never
silently assumed.

The same rule covers fetched evidence: a catalog read from one provider's endpoint cannot judge another
provider's models. Scope the comparison to the (provider, endpoint) pair the data came from, print which
scope was used, and label the rest `not consulted` — reporting them as absent turns "never queried" into a
finding, and that false FAIL costs as much as a silent pass.

## 6. Silent-empty fallbacks

`except Exception: return {}`, `if not path.exists(): continue`, `try: import yaml / except: return {}`.
An unreadable config then reads as an empty fleet: the audit exits 0, the findings are the opposite of the
truth, and a before/after comparison says "no change".

Fix: fail loudly with the **path and the reason** (non-zero exit / `SystemExit`), and add a fixture whose
malformed input proves it stops. A helper that swallows its own read error is worse than no helper.

## 7. Snapshots that record names but not values

An inventory of alias names, of provider keys, of catalog entries. Repointing an alias or moving an
endpoint between two runs leaves the output byte-identical, so the snapshot certifies a change it never
saw.

Fix: record the routing values (model, endpoint/`base_url`, transport/`api_mode`, `context_length`) and add
a fixture that changes one value and asserts the before/after differ.

## 8. Shell snippets in prose

Undefined variables, unquoted expansions, a copy with no `mkdir -p` in front of it, no fail-fast on a
missing input. These read as correct and fail only on the operator's machine.

Fix: `${VAR:-default}` plus an existence check that aborts with a message, every expansion quoted, the
destination created before the copy, `set -euo pipefail` at the top of a multi-step block.

Two that survive that pass and still fail on a stranger's machine:

- **A quoted heredoc expands nothing.** `python3 - <<'PY'` hands the block to Python verbatim, so
  `$HERMES_HOME` stays a literal string and the snippet addresses a path called `$HERMES_HOME`. Inside such
  a block read the environment yourself (`os.path.expanduser(os.environ.get("HERMES_HOME", "~/.hermes"))`);
  keep the quoted form — unquoting reintroduces shell expansion into the payload.
- **A credential in a probe must be a variable.** A literal token, or a `***` left behind by a redaction
  pass, makes the documented curl send a dead credential: an authenticated relay answers 401 and the
  transport evidence is worthless. Use `$RELAY_KEY`, say where to read it from the install, and normalize
  the base before the operation path (`RELAY=${RELAY%/v1}`) — a provider entry often already stores the API
  prefix, so `$RELAY/v1/responses` becomes `/v1/v1/responses` and a working route looks dead.

## 9. Format ownership

When the host copy has drifted from the catalog, the merge direction is per concern: the catalog owns the
frontmatter schema (its checker enforces it), the host owns the body it has been editing daily. Keep the
catalog frontmatter, take the host body, then diff the supporting files both ways and port the host-only
ones — a new `references/` file or script on the host side is the signal that the host is ahead at all.

## 10. Verification, in the same change

Run the catalog's own gates (frontmatter, index `--check`, contract graph, vendor `--check`, version and
changelog rules) and add a fixture test per fixed failure class, then wire the new test into CI — otherwise
it is a local habit. A fixture named for the class it prevents is also the reply you post when the reviewer
raises that class.

## 11. Bound the loop

The mechanics that decide whether the loop converges at all:

- **List every open thread before claiming clean, with pagination.** A `reviewThreads(first:20)` query on a
  review with 45 threads reports zero unresolved while two sit on page 2 — the truncation
  `mechanical-gate-design` forbids in a gate applies to your own check.
- **Reply with the fix commit and the evidence, then resolve it.** Fixture names and probe output in the
  reply; the bot re-raises an already-fixed finding as a new thread on the next round, which is answered
  once, not fixed twice.
- **A push does not re-trigger the bot.** Post the explicit review request and wait for the marker's
  `commit_sha` to equal the new head; a marker for an older SHA says nothing about what you just pushed.
- **The summary marker is a round snapshot.** After you fix and resolve that round, `has_any_findings`
  still reads true. The signals that matter are unresolved threads == 0 and a marker naming the current
  head.
- **Bound it explicitly.** When each round adds one small completeness item, fix what is concrete, record
  the residue in the PR body (found / landed / left, and why it is not blocking), and merge. A long tail of
  one-item rounds means the sweep was skipped: go back to section 1 for the next port, and do not spend a
  twentieth round discovering class eleven.

## 12. Shell (or PowerShell) carrying the logic

A skill that ships its implementation as `.sh`/`.ps1` works on the author's machine only: the operator
moves between Windows, macOS and Linux, so a PowerShell one-liner is as unusable on Linux as a bash one is
on Windows. Skill scripts must run on all three. Check with `grep -rIn '\.sh\b\|\.ps1\b' <skill>` — the
only acceptable hits are illustrative examples that the skill does not depend on.

Port by what the script *is*, not by taste:

- **Flexible or short → keep it a script**, that is where the flexibility belongs: Python through
  `uv`/`uvx` (dependencies inline via PEP 723 `# /// script`, never installed into the system python), F#
  through `dotnet fsi` (`.fsx`), TypeScript through `bun`/`bunx`.
- **Never JavaScript.** A `.js` in a skill is a portability finding too — convert to `.ts`. (Exception: the
  agent's own Code Mode scratch, which never ships.)
- **Larger, well-specified, highly repetitive tool → a Go CLI**, one static cross-compiled binary. Only
  then; a Go program for a ten-line helper is a maintenance tax, and Go is also the worst of the three for
  iteration speed while the requirement is still moving.
- **`.sh` survives only as host-specific runtime glue that never enters the catalog** — and new glue is
  written In one of the three, not in shell.
