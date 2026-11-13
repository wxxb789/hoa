# Auditing & De-duplicating Instruction Files — Workflow

A repeatable surgical procedure for cleaning the four owner-level instruction files
(`SOUL.md`, `AGENTS.md`, `MEMORY.md`, `USER.md`) without breaking voice or losing meaning.
Distilled from a real audit→de-dup session. Pairs with the mechanics in the parent `SKILL.md`.

## When to run this

Owner asks to "audit / clean / optimize / de-dup / fix conflicts in" the instruction files,
or asks to make a rule "global", or asks why a file did/didn't take effect.

## The procedure

### 0. Resolve filenames against reality FIRST (don't audit ghosts)
- The owner may name a file that doesn't exist (e.g. "hermes.md"). Before auditing, confirm
  what actually exists: the real owner-editable layers are `~/.hermes/SOUL.md`,
  `the workspace `AGENTS.md` (`$CLAW_HOME/AGENTS.md`)` (or wherever cwd points), `~/.hermes/memories/{MEMORY,USER}.md`.
- A "hermes.md" the owner mentions is almost always the **injected system prompt** (framework-
  owned, not an editable file) OR a misremembered `.hermes.md`/`HERMES.md` (project slot).
  Clarify which before touching anything.

### 1. Read all four, then VERIFY every path/claim before calling it a problem
- **Pitfall (happened): do not flag a referenced path as a "ghost" without checking it.**
  In the source session, `growth-rails/*` and `team/*` paths were accused of being phantom
  references — a quick `ls` proved them all real. Verification beats inference. Retract any
  accusation the evidence kills.
- Run a real existence check on every path the files cite (artifact dirs, team docs, growth-rails).

### 2. Classify findings into a fact table (verified status, not vibes)
Columns: finding | what the evidence showed | TRUE problem / RETRACTED / ALREADY-FIXED.
Only TRUE-problem rows get touched.

### 3. Get owner decisions on the BRANCHES, act on the rest
Three recurring decision points that are NOT yours to decide unilaterally:
- **Global vs project contract** — should owner-level rules be cwd-independent? If yes, they
  MUST go in `SOUL.md` (only global file). If "good enough", keep them in `AGENTS.md` (cwd-bound).
- **Metaphor / persona wording** — e.g. a level mismatch like "staff engineer helping you reach
  Senior" sets the agent a rung ABOVE the user. Align it (here: "cofounder + senior/staff-level
  engineer, shoulder to shoulder", dropping the rung-above implication).
- **Surgical vs structural rewrite** — default to **surgical** when the files are well-written.
  Their voice (question-style headers, dry humor, Green/Yellow/Red gates) is deliberate design;
  don't bulldoze it to fix local redundancy. Structural rewrite is over-engineering for de-dup.

### 4. Backup before editing (Yellow gate)
```bash
BK=$CLAW_HOME/tasks/$(date +%F)/contract-audit/backup; mkdir -p "$BK"
cp ~/.hermes/SOUL.md "$BK/SOUL.md.bak"
cp $CLAW_HOME/AGENTS.md "$BK/AGENTS.md.bak"
cp ~/.hermes/memories/USER.md "$BK/USER.md.bak"
cp ~/.hermes/memories/MEMORY.md "$BK/MEMORY.md.bak"
sha256sum "$BK"/*.bak   # proof trail
```

### 5. De-dup along the canonical-owner principle
- **SOUL = who / AGENTS = how.** Any layering table, persistence-routing list, or self-evolution
  ordering that appears in BOTH belongs canonically in `AGENTS.md`. In `SOUL.md`, collapse the
  duplicate to a short stance + a pointer: "full detail is authoritative in AGENTS.md, not
  re-copied here." Keeps the voice, kills the drift source.
- **Pitfall (happened): duplicated ordered lists drift into CONFLICT.** SOUL's evolution order
  ranked SOUL #2 / AGENTS #3; AGENTS's ranked AGENTS #1 / SOUL #2 — a real contradiction, not just
  redundancy. Collapsing one side to a pointer removes the conflict, not only the bytes.
- **De-dup volatile tier first** (`MEMORY.md` + `USER.md`): they re-inject every turn, so
  duplicated identity facts (company/level/goal/gap) cost tokens on every call. Keep identity in
  `USER.md` (who-the-user-is), delete the copies from `MEMORY.md`.

### 6. Edit MEMORY/USER via the memory TOOL, not by hand-patching the file
- `MEMORY.md` / `USER.md` are managed by the memory tool with a hard char cap and entry framing.
  Patching the raw file desyncs tool state. Use `memory(action=remove/replace/add)`.
- **Pitfall (happened): the memory store hits its char cap and rejects adds.** When it does:
  (a) delete genuinely stale entries first (e.g. a model-context line naming a now-superseded
  default), (b) merge overlapping rules into one shorter entry, (c) shorten the new entry — the
  skill name itself is the pointer, mechanics live in the skill, so the memory line can be one
  sentence. Do NOT retry the same oversized add unchanged (tool-loop warning fires).
- Give bare entries (no `[P0]/[P1]` prefix, no date) the format prefix while you're in there.

### 7. Verify (Yellow close-out) and report proof
```bash
# confirm the removed/duplicated content is actually gone
grep -n "OLD METAPHOR\|DUP TABLE FIRST LINE\|CONFLICTING ORDERED LIST LINE" ~/.hermes/SOUL.md \
  || echo "✓ removed"
wc -l -c ~/.hermes/SOUL.md $CLAW_HOME/AGENTS.md   # sanity: not truncated/corrupted
```
Report: per-file what changed, backup path, and one line of "what behavior should differ next
session." Note that instruction-file edits only take effect in a NEW session (system prompt is
rebuilt per session, not mid-turn).

## One-line summary of the lessons
Verify paths before accusing • collapse duplicates to a pointer in SOUL (AGENTS is canonical) •
duplicated ordered lists become conflicts • de-dup volatile (MEMORY/USER) first • edit memory via
the tool and consolidate when the cap bites • surgical beats rewrite for well-voiced files.
