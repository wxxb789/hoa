# De-coupling checklist (2026-11-21)

Each row is a concrete transform. The left column is what a private runtime produces; the right is
what survives publication. Anything you cannot move to the right column stays local and the public
package points at a template instead.

## Resolution rule behind every row

Every row applies the one resolution order defined in [configuration.md](configuration.md); this
checklist does not restate it. A value with no defensible default is documented as "must be
supplied", never silently invented.

Rule of thumb: every path and every vendor-specific value must be answerable from `--help` or the
skill's Configuration section. If a stranger cannot resolve it, it does not exist.

## 1. Identity

| Private shape | Publishable shape |
|---|---|
| "the owner's way", a named assistant, a personal pronoun | "the operator", "the author agent" — two roles that exist in any team |
| "<assistant> inspects", "<bot> runs the gates" | "The operator runs gates read-only, grades findings, decides to merge" |
| trigger phrases in one language only | one line of trigger phrases, multilingual, because routing matches surface text |
| the author's name in frontmatter | no author field; provenance belongs in the PR and the changelog |

Why it also improves the skill: a protocol written around roles states *what* must happen instead of
*who* happens to be standing there.

## 2. Paths

| Private shape | Publishable shape |
|---|---|
| `~/private-root/tools/x.py` | `<package>/scripts/x.py`, resolved from the script's own location |
| `~/private-root/tasks/...` for state | `${XDG_STATE_HOME:-$HOME/.local/state}/<tool>/...`, overridable by env |
| a hardcoded template dir inside another skill | package-relative asset plus an override only when the caller must supply another template |
| an absolute checkout path in a command | `<repo>` placeholder plus a documented `*_REPO` env var |
| tool silently defaults to the author's model | no default; pass a flag only when the caller supplies it |

## 3. Transport

| Private shape | Publishable shape |
|---|---|
| "always launch via this wrapper at this absolute path" | a launcher contract: `start --name --prompt --cwd [--model --thinking --max-time]`, plus `status`/`result`/`answer`/`kill` |
| knowledge tied to one CLI's flags | plus one reference adapter, with its adaptation points listed in its header |
| "no completion notification arrives" | "completion is polled; a missing state file means unknown, never success" |
| host-specific limits (cores, RAM, timers) baked into rules | "on a host sized for one heavy job", with the concrete numbers in the adapter or profile |
| one harness's tool names (`read_file`, `terminal`, `delegate_task`) | the capability: file read, shell, subagent dispatch — each mapped in the adapter |

Contract to require of an adapter: detached from the caller, `<run_root>/<date>/<slug>/state.json`
with `{name,state,exit,cwd,started,ended,duration_s}`, `answer.md` holding the final assistant text,
and a lock or session id that makes a dead run detectable.

## 4. Vendor constants

| Private shape | Publishable shape |
|---|---|
| a review-bot marker string compiled in | `--marker TEXT`; skipping a required check needs an explicit, authorized opt-out |
| model id / effort pairing in code | documented pairing guidance, values passed by the caller |
| internal bot handle in prose | "the repo's review bot", with no internal handle in the package |
| an absolute wrapper path as default | default resolved from the package, overridable by env |
| a timeout or size cap as a literal | config key with a documented default (e.g. `24` hours, `20` MB) |
| a private host or port in an endpoint | `<proxy-base-url>` resolved from config |

## 5. Private data

| Private shape | Publishable shape |
|---|---|
| one profile per real repo | publish a template; keep instances outside the distributable package |
| customer names, internal gate lists, API baselines | never published; profiles describe them locally only |
| personal notes inside a reference file | drop, or rewrite as a generic decision rule |
| a private repo named as "the example" | `<project>` placeholder, with the shape of the real thing kept |

Verify the ignore rule instead of assuming it:

```bash
git check-ignore -v <repo-relative-private-profile>   # must print the rule that matches
```

Check the tracked or staged files and the actual distribution file list too: an ignore rule
does not untrack a file and does not protect a private file copied by another packager.

## Release-blocking scan

Use one reviewed pattern list from the destination, or supply one for the port. Scan the
distribution inputs for absolute user paths, private identifiers, hostnames, model IDs,
mail addresses and credential prefixes. Review hits against a documented allowlist of
public names and synthetic fixtures. An unexpected hit blocks release; do not exempt a
directory merely because its name is `private`.
