# Which instruction file actually loads — probe, don't assume

This is the ground truth procedure for **which instruction file actually gets injected into the system
prompt**, and under what conditions. "Put the rule in the right layer" is necessary but NOT sufficient —
a correctly-layered rule in a file that the current cwd does not load is silently dead.

The scopes below are the common pattern across agent CLIs; the exact loader names and priority order
differ per runtime, so verify yours with the probes at the end. Never transfer a claim from one file type
to another by analogy: they are usually separate loader functions with separate scopes.

## The five context file types and their REAL discovery scope

| File type | Discovery scope | Global? | git needed? |
|------|-----------------|---------|-------------|
| **identity file** (e.g. `SOUL.md`) | **`<runtime-home>/` ONLY**. Never probes cwd. | ✅ YES — every turn, any cwd | no |
| **overlay file** (dot-prefixed variant) | cwd first, then **walk up parents to git root** and stop | ❌ no — bound to cwd→git-root chain | uses git root as the upper bound; no git → walks to filesystem root |
| **operating protocol** (e.g. `AGENTS.md` / `agents.md`) | **`cwd / name` — top-level only. NO recursive walk, NO parent walk, NO git.** | ❌ no — bound to **exact cwd** | **NO** |
| **legacy agent file** (e.g. `CLAUDE.md` / `claude.md`) | cwd only (one layer) | ❌ no | no |
| **editor rules** (`.cursorrules`, `.cursor/rules/*.mdc`) | cwd only | ❌ no | no |

## Mutual-exclusion rule (the slot)

Many runtimes load **exactly ONE project-context type per session, first match wins**, in a fixed order
(commonly: overlay file → operating protocol → legacy agent file → editor rules).

The identity file is loaded **independently** as identity (system-prompt slot #1) and does NOT compete for
this slot. When the identity file loads, a `skip_soul`-style guard prevents it appearing twice.

Implication: dropping an overlay file next to an existing operating protocol does NOT add context — it
**preempts** the protocol file, which then silently stops loading. Higher priority = it wins the single
slot, not "both load".

## Prompt-assembly tiers (where each file lands)

From the runtime's prompt builder, joined `stable → context → volatile`:

- **stable**: identity file (or a default-identity fallback), tool/model guidance, skills index, env/platform hints
- **context**: caller `system_message` + the ONE project-context file
- **volatile**: memory snapshot, user-profile snapshot, external memory block, timestamp/session/model/provider line

Because identity is `stable` and the protocol is `context`, **the same rule written into both is pure
per-turn token waste** — keep each canonical rule in one tier.

Memory + user-profile files are `volatile` snapshots re-injected every turn, so duplicated identity facts
across them = double tokens every single turn.

## Subagent / delegation blind spot

When `skip_context_files` is set (e.g. a delegation tool), **the identity file and the project-context file
are NOT loaded** — the child uses a hardcoded default identity. So subagents do NOT see the operating
contract. Pass any contract rules a child needs explicitly in the delegation `context=`.

## Globality decision (the practical takeaway)

> Want a rule that holds **regardless of cwd, every session** → it MUST live in the runtime's identity
> file. That is the only globally-loaded, cwd-independent slot. All project slots are cwd-bound and cannot
> be made global by relocating them into the runtime home — that is not their mechanism. A protocol file
> placed at `<runtime-home>/AGENTS.md` does NOT load globally; it only loads if the session cwd happens to
> sit in `<runtime-home>/` or below.

The operating protocol is the sharpest trap: it loads **only when session cwd === the exact directory
holding it**. Starting a session in a *subdirectory* of that dir does NOT pull in the top-level file at
startup (subdirectory files are appended later by a progressive-hints mechanism, and only the subdir's own
file). "Inside the project tree" is not enough; it must be that one directory.

## PITFALL — do not cross the wires (I made this exact error)

An overlay file's "walk up to git root" logic is NOT the operating protocol's logic. The protocol file does
**not** walk parents and does **not** touch git. Before asserting discovery behavior, check WHICH loader
function owns the file — they are separate functions with separate scopes. Reasoning by analogy from one to
another produces confidently-wrong answers.

Corollary: "Does the operating protocol require a git repo?" → **No.** Verified live: a cwd with no `.git`
anywhere up the tree still loads its protocol file fine. Only the overlay file even references git, and
only as a search *upper bound*, not a requirement.

## How to verify on any box (don't reason — probe)

```bash
# Is the project-context dir actually a git repo? (only matters for the overlay file)
cd <project-dir> && git rev-parse --show-toplevel 2>&1

# Which project-context file wins the single slot, given a cwd?
for f in <overlay-names> <protocol-names> <legacy-names> <editor-rules>; do
  [ -e "<cwd>/$f" ] && echo "PRESENT: $f"
done   # first match in the runtime's priority order wins; the identity file loads separately

# Then read the runtime's own prompt builder to confirm the priority order and the
# global-slot path. Fns to look for: identity loader, overlay finder, protocol loader,
# legacy loader, editor-rules loader, and the context-files assembler.
```

## When auditing/refactoring an agent's instruction files

Before deciding "this rule goes in the operating protocol", confirm the owner's actual sessions start with
cwd === that file's directory. If they routinely start elsewhere (or in subdirs), the protocol file is the
wrong home for must-always-hold rules — promote those to the identity file and let the protocol file carry
only genuinely-project-local conventions.
