# Hermes-evolved skills (`unfettered-skills/`)

`skills/` is the curated catalog; every rule in `AGENTS.md` binds what is promoted into it.
`unfettered-skills/` is its landing zone: Hermes, or a similar self-evolving system, checks
candidates in there automatically and unconstrained. It is a sibling of `skills/`, never an install
source or a manifest search path.

- **Only that writer lands candidates**, by automatic check-in. A candidate is
  `unfettered-skills/<name>/SKILL.md` (required) with any support files under
  `unfettered-skills/<name>/`; the landing root holds at most one `unfettered-skills/README.md`.
  Humans and regular agents only promote or delete them. A change set that adds or modifies
  anything there may touch no other path; a deletion there may ship beside an outside change,
  because promotion moves a skill out.
- **CI stays loose.** `scripts/check_unfettered.py` checks sensitive content (keys, tokens, e-mail
  addresses, home paths, private-range IPs), the candidate shape (`SKILL.md` under its own
  directory; non-empty `name` equal to that directory, and `description`), and name collisions with
  `skills/` or `scripts/retired_skills.toml` — nothing else, no line caps, links, revisions, index
  or tests.
- **Promote through the port review.** One PR moves a candidate into `skills/<category>/<name>/`,
  normalized to the full bar: every rule in `AGENTS.md`, the curated gates, and the raw copy gone.
  Raw renames and deletions never create retired entries; only previously curated names retire
  through the usual curated workflow. `hoa-skill-port` owns the procedure.
- **Never depend on the landing zone.** A curated skill must not require anything from
  `unfettered-skills/`; do not reference it from manifests, curated dependencies or install docs.
- **Discovery stays limited.** While standard locations yield valid skills, normal `npx skills`
  discovery does not list `unfettered-skills/`; an explicit path, recursive fallback,
  `--full-depth` or a specific-name retry can still reach it. Install commands point only at
  `skills/`.
- **Coupled skills carry `hermes-`** in both tiers: coupled means a dependency on Hermes runtime
  paths, config, tools, gateway or memory. Everything else stays portable and free of Hermes paths.
- **Never fork a Hermes built-in**, in either tier; they are tracked upstream. Propose the change
  upstream instead. `prompts/hermes-skill-naming.md` is the brief to hand Hermes.
