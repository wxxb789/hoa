# Skill family integrity — one protocol, several files

Use when a skill being evolved, or a family hoa-skill-set-audit's set pass flags (an umbrella plus
profiles, references or sibling skills), repeats the same protocol across several bodies. The
defect is rarely missing prose — it is the same protocol living in several files and drifting.
Probe before writing:

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
   headless). Report it as a factual error with both locations, not a design choice.
4. **Diff same-purpose scripts across skills**, whitespace-normalized
   (`diff <(sed 's/[[:space:]]*$//' a) <(sed 's/[[:space:]]*$//' b)`, or `git diff --no-index -w a b`
   on Windows). The weaker twin is dead weight: recommend keeping the stronger one and making the
   other a pointer.
5. **Check coverage against reality, not against intent.** For each repo/project the owner actually
   works in (look for the contract dir such as `docs/goals/`), ask whether a profile exists. An
   active repo with no profile is a bigger fluency gap than any wording fix.
6. **Check for durable state and telemetry.** Is there a per-increment state file (stage, base sha,
   next action) and a ledger with durations/rounds? If not, interruption recovery is the real
   bottleneck and more prose cannot fix it.

Deliver: what exists (with counts), where the protocol is duplicated, which claims are already
wrong, then 2–3 options sized by effort. Do not rewrite a methodology skill the owner depends on
before they pick an option — the audit is the deliverable.

- **A profile that declares itself authoritative over its umbrella is a drift machine.** Text like
  "where the two differ, this profile wins" puts owner-level protocol in a per-repo file, so the
  next protocol edit lands in the wrong place and the two silently disagree. Report it as
  structural; the profile should carry repo deltas only (contract location, gate commands, branch
  and bot conventions, frozen surfaces, resource limits).
- **Do not propose new machinery before checking what the existing failure cost.** Stage caps,
  extra checklists and dispatcher scripts are guesses until a ledger shows which stage burns the
  rounds; the mechanical part worth building first is the one that runs a gate the agent keeps
  skipping by hand.
