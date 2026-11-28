# Briefing the owner on a version gap ("are we current, and what changed?")

This skill owns the *answer*; the upgrade itself belongs to the update skill. Answer from the install
and the release record, never from memory.

## 1. Establish installed vs offered

`hermes update --check` (or `--plan`) from the install names the channel, tag and commit actually
offered. Compare against that — not a release date, not an assumed `origin/main`. Read the installed
version from the CLI itself, and note that a source install can sit on a detached release checkout and
still be healthy.

## 2. Pull the curated notes per tag

`GET /repos/<owner>/<repo>/releases/tags/<tag>` — one request per tag. The whole-list endpoint returns
every long release body in a single payload and stalls or fails to parse, while a single-tag response
parses cleanly. Multi-patch releases frequently carry an "undocumented here on purpose" paragraph that
enumerates the real features; that paragraph and the release's own scope statement (window size, PR
count, whether curated notes are deferred to a later release) are the highest-value text in the file.

## 3. Aggregate the window from the checkout

- `git log --no-merges --format=%s <installed-tag>..<target-tag>` is ground truth. Classify by
  conventional-commit type, then count `feat` by scope: the top scope tells you where development
  actually went. A catalog/marketplace scope can dwarf every product area — report it separately as
  catalog growth instead of letting it bury the product features.
- Files *added* by the target tag are absent from the working tree, which is still at the installed
  revision: read them with `git show <tag>:<path>`. A `grep`/`ls` over the working tree silently returns
  nothing and looks like "the feature does not exist in this build".
- For large diffs, `git diff --name-status <old>..<new> -- <dir>` with `--diff-filter=A` / `D` answers
  added/removed without paging through text.

## 4. Report shape

Conclusion first, then group by what the owner acts on: capabilities that change how we work → cost and
context behaviour → model/provider changes → big fixes and security advisories (quote severity, CVE or
advisory id) → bundled-skill movement (usually small) → catalog/plugin movement (usually huge) →
"what this means for this install", naming our own pending plugin/skill updates and any defect only the
upgrade fixes.

- Phase the answer as offered vs installed and say which side each item is on; never present a feature
  as available while the install is still on the older tag, and never claim the upgrade happened because
  a timer is scheduled.
- Long form to a task artifact (`~/claw/tasks/<date>/<task>/`), chat reply kept to conclusions, the
  grouped bullets and the path.
