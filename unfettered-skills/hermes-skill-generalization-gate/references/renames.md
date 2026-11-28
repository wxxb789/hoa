# Renaming a skill family — ripple inventory

The rename is the easy part. Work the list, then verify with a grep that returns zero hits and with every
path-bearing test the repo owns.

## Identity

- Directory name == frontmatter `name`. CI enforces the pair; a loader also keys on it, so rename both
  in one commit or the catalog and the runtime disagree.
- Copy the shape of the repo you join. A private-lineage `author:` / `license:` block is a literal, not
  a convention, and a public catalog drops it.
- Redefine `metadata.kind` on anything ported: only `controller` / `stage` / `mechanism` / `entry` are
  valid, `mechanism` is never a routing target, and a stage is a phase its controller invokes — a
  "procedure" is not a kind.

## Generated artifacts

- Regenerate the catalog; a hand-edited index loses to `--check` on the next run.
- If a repo-wide version file mirrors into every skill's `metadata.version`, run the repo's own bump.
  Never hand-set a version: the generator owns it and the release job rewrites the tree under you.
- Counts in prose ("N skills", "M artifacts", "K courses") rot on every addition. Delete the number
  rather than update it; a repo with a generated-means-generated rule will fail the review for it.

## Composition contract

- Close the graph with **real producers**: before registering an artifact as `external`, grep for a skill
  that already produces it. A goal/contract/spec artifact usually has a producer nobody credited.
- `consumes` must name an artifact some skill produces or one registered external; duplicate producers
  are errors; a produced artifact is either consumed or declared terminal with a one-line reason.
- **An exemption table is not a fix.** Registering every input as `external` and every output as
  `terminal` passes CI and leaves each node an isolated stub — a graph that proves nothing.
- Controllers have a line cap. Moving prose into `references/` and dropping duplicated samples from the
  entry file is the standard way to buy room for the section the rename exists to add (a family map).

## Cross-references

- Grep the whole repo, not `skills/`: skill bodies, reference files, maintenance scripts holding a
  vendored-copy path map, launcher forwarders that resolve a sibling skill by relative path, README
  prose, eval case files.
- Protect exactly one string: an upstream project's own name in a provenance line is not yours to
  rename, and a blind substitution rewrites the credit.
- Archived plans and evidence keep the old names. Rewriting history costs review attention and buys
  nothing.
- Sibling-relative paths and path maps fail **silently**; their own tests are the only proof. Run them.

## Evals

- Routing cases name artifacts. Give the family's routable kinds (`controller`, `entry`, and now the
  reclassified stages) cases; a `mechanism` as `must_pick` is rejected by the graph check.
- A recorded baseline pins the case count. Adding cases means re-recording it, and any failure that was
  already failing must be reported as pre-existing, not as damage from this change.

## Live install

- Symlinks die the instant the canonical tree renames the directory: the skill vanishes from the loader
  while allow-lists still hold the old string, so neither name resolves. Do the rename and the host
  switch in one sitting; never park a half-done rename.
- Materialized copies are real files, not symlinks. Re-materialize them; never hand-rename or hand-edit.
- Order: backup → remove the old entries → link the new names → update runtime config and per-profile
  policy lists → materialize → parity check that compares host entries to the repo tree.
- **Count the host state; never describe it from a sample.** "Every skill is a symlink into the repo now"
  is a claim with a command behind it: `find <host>/skills -maxdepth 3 -type l -ls | grep -c '<repo>'`
  counts links by *target*, while `find <host>/skills -type l | grep '<repo>'` matches link paths and
  returns 0 — a false all-clear of exactly the kind that hides real directories. Expect a mixed state
  (links + a handful of drifted real directories) and read the parity check's `drifted` lines before
  saying the switch is done.
- A real directory in the host tree is never replaced by the installer and a stale link is never deleted
  by it. Retire both explicitly — copy the directory to a dated backup path first — or the host keeps
  running a months-old copy of a skill the catalog thinks it owns.
- Config resolution derives the env prefix (`<SKILL_BIG_SNAKE>_<KEY>`) and the config file path from the
  skill name. A rename changes both: keep the old spelling documented as an alias, and state the
  migration in the changelog so an existing config file is not silently ignored.
