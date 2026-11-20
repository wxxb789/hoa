# Candidate review checks (2026-11-21)

- Compare unlike measurements without relabelling them: keep each attributed value
  with its original definition or unknown definition, scope, date, and source. A newer
  different measure does not supersede the older one.
- For a negative finding, search acronyms and full phrases, section numbers and
  subject terms. Disclose counterexamples and scope the result to versions inspected.
- Attribute access failures to the client, route, date, and response. Track index/link
  visibility, access controls, alternate public copies, and filing requirements separately.
- For a contested claim, give the source URL, exact version, locator, short quote, and
  the limit that matters. Check softened or inverted versions of the rejected conclusion.

For Git targets, use an isolated checkout of the pinned base. Put only the revised
files at their repo-relative destinations in that checkout, then export a
`git diff --binary` (stage intent-to-add for new paths). Validate against pristine
base copies, not the edited checkout. Apply the patch to a second isolated copy and
compare bytes with the deliverable; reject undeclared paths or changes compared with
the rejected candidate. Keep both versions and the original worktree untouched.
