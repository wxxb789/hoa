# De-coupling checklist — five axes

Each row is a concrete transform. The left column is what a private runtime produces; the right is
what survives publication. Anything you cannot move to the right column stays local and the public
package points at a template instead.

## Resolution rule behind every row

One order, everywhere: **CLI flag → environment variable → operator config file → documented
default**. The config file is `$XDG_CONFIG_HOME/<skill>/config.yaml`, falling back to
`~/.config/<skill>/config.yaml`; a single env var overrides a single key. Reading that file to
customise the skill is the preferred shape, not a workaround. A value with no defensible default is
documented as "must be supplied", never silently invented.

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
| a hardcoded template dir inside another skill | script-relative sibling (`<script>/../references/<kind>/`) plus one override env var |
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
| a review-bot marker string compiled in | `--marker TEXT`; a repo without a bot must pass an explicit opt-in flag |
| model id / effort pairing in code | documented pairing guidance, values passed by the caller |
| internal bot handle in prose | "the repo's review bot", with the handle as a labelled example |
| an absolute wrapper path as default | default resolved from the package, overridable by env |
| a timeout or size cap as a literal | config key with a documented default (e.g. `24` hours, `20` MB) |
| a private host or port in an endpoint | `<proxy-base-url>` resolved from config |

## 5. Private data

| Private shape | Publishable shape |
|---|---|
| one profile per real repo | `references/profiles/_template.md` public; instances in `private/profiles/<repo>.md` |
| customer names, internal gate lists, API baselines | never published; profiles describe them locally only |
| personal notes inside a reference file | drop, or rewrite as a generic decision rule |
| a private repo named as "the example" | `<project>` placeholder, with the shape of the real thing kept |

Verify the ignore rule instead of assuming it:

```bash
git check-ignore -v <package>/private/profiles/*.md   # must print the rule that matches
```

A `**/private/` rule in the repo's `.gitignore` lets the private instances live *inside* the publishable
package — one directory, no second copy, and package consumers simply never see them.

## Release-blocking scan

Keep the patterns in one config-readable list (`PORTING_SCAN_PATTERNS` or the package's own scan
file) rather than retyping them per release. A workable default set:

```bash
grep -rniE '(/home/|~/(<private-root>|\.<runtime-dir>)|<username>|<private-repo>|sk-|ghp_|AKIA[0-9A-Z]{8}|@[a-z0-9.-]+\.(com|cn|io))' \
  <package> --include=*.md --include=*.py --include=*.sh | grep -v '/private/'
```

Expected hits: fixture emails at `example.com`, public product names. Anything else is a fix, not a
note. Run the scan before the port report, so the report's demotion table and the grep agree.
