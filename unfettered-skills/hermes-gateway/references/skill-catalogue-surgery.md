# Skill catalogue surgery (per-profile trimming)

Use when a fleet review says "too many skills / the bots load the whole library" or when a bot's
catalogue must be narrowed to its job.

> **Mechanism changed.** A home's skill surface is now `profile.yaml: allowed_skills` rendered as
> **real per-home copies** by `profile-skill-materialize.py`. `skills.disabled` and the
> `skills-reenable-exceptions.yaml` complement are retired and carry no authority — anything
> below that still mentions them is history, not procedure. Regenerate a surface with:
> `python3 ~/.hermes/scripts/profile-skill-materialize.py --apply --profile <p>`, then `--check`.

## Why it matters

Every enabled skill costs a name + description in the system prompt of *every* turn. A fleet of
research bots each loading the full library pays that tax N times while using two of the skills.

| role | enabled skills |
|---|---|
| front door / router | ~15–20 |
| builder | ~25–30 |
| vertical specialist (finance, career, research) | ~10–20 |
| narrow verifier / control-plane role | 5–10 |

## Procedure

1. Edit the home's `allowed_skills` (Zoe-line homes) or the repo binding's `skills.allowed`
   (`*-nrs` homes — `materialize.py` writes the profile and materializes the copies).
2. Choose by capability, not alphabet: intake/search/extract, evidence + citation, writing/artifact,
   coordination (kanban), self-maintenance (hermes-*, curation). A research bot that loses
   `grounded-citations` has been made smaller, not better.
3. `python3 ~/.hermes/scripts/profile-skill-materialize.py --apply --profile <p>`.
4. Verify three ways: `--check` (exit 0), the file-level invariant
   (`find profiles/<p>/skills -maxdepth 1 -type l | wc -l` → 0, entry count == `|allowed_skills|`),
   and a functional probe (`hermes -p <p> -z "reply with exactly: <TOKEN>"`). For a builder add one
   probe that must call a tool — a bot with no shell access is a chatbot with a job title.
5. Record before/after counts; the number is the only proof the prompt tax fell.

## Pitfalls

- **Read names from disk or from the lock, never from `hermes skills list`** — its table truncates
  long names with `…`, and a truncated name resolves to nothing.
- **Do not disable the identity-critical skills of a role because they look generic.** Every bot keeps
  `hermes-agent` + `hermes-context-file-loading` unless it is deliberately sandboxed from its own
  instructions.
- **Plugin-provided skills are not in the skills directory.** `dreaming` and friends load from the
  plugin, appear in cron jobs as `agent-plugin-<name>-<hash>:<skill>`, and never show up in `find`
  output — do not try to "restore" them by adding names anywhere.
- **A trimmed surface is not live until the session/adapter restarts**; new sessions read disk, so say
  which of the two you verified.
- **Removing a name deletes that home's copy.** Anything the bot edited inside it must first be forked
  (`evolvable_skills`), or the edit disappears with the directory.
