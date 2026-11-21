# unfettered-skills

Landing zone for skills that Hermes or a similar self-evolving system evolved on its own. Skills here usually work
but are not engineered: they have not passed hoa's port review or curated gates. Use them as raw material.

## Who writes here

- Only an authorized self-evolving writer, such as Hermes, checks candidates in. It does so automatically, one
  folder-only change at a time.
- Humans and regular agents do not add or edit candidates. They either promote a candidate into `skills/` or
  delete it.

## Layout

- `<name>/SKILL.md` is required. Its frontmatter needs `name` and `description`, and `name` must equal the
  directory name.
- Support files may sit under `<name>/`. Only one `SKILL.md` per candidate.
- `<name>` must not match a skill in `skills/` or a retired name in `scripts/retired_skills.toml`.

## What CI checks here

`scripts/check_unfettered.py` runs three checks and nothing else:
1. A change that adds or modifies anything here touches nothing outside this folder. Deletions here may be mixed
   with outside changes, because promotion moves a skill out.
2. No sensitive-signature hits (keys, tokens, e-mail, personal home paths, private IPs, corporate feeds) in any
   path or file.
3. The minimal shape and name rules above.

Before pushing, the writer commits locally and runs
`uv run --script scripts/check_unfettered.py --base <publication base>`.

## Promotion

`hoa-skill-port` describes the full procedure. In short:
- One PR moves a candidate into `skills/<name>/` and deletes it from here.
- The promoted skill is normalized to the full bar: the port review and every curated gate.
- It starts at `metadata.revision: "1"`. A candidate-only name never gets a retired entry.
- Curated skills never depend on anything in this folder.

## Discovery

`npx skills add wxxb789/hoa` does not list these skills in normal discovery while `skills/` holds valid skills. An
explicit path, `--full-depth`, a name retry or the recursive fallback can still reach them. Install from here only
on purpose.
