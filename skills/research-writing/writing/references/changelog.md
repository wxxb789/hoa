# Changelog / Release notes

For release notes, CHANGELOG.md, version announcements. Follow "Keep a Changelog" conventions.

## Structure
- **Header:** `## [version] — YYYY-MM-DD`. Newest on top. Link to compare/diff if possible.
- **Grouped bullets** under these headings (omit empty ones):
  - **Added** — new features
  - **Changed** — changes in existing behavior
  - **Deprecated** — soon-to-be-removed
  - **Removed** — now removed
  - **Fixed** — bug fixes
  - **Security** — vulnerabilities addressed
- Most user-impactful items first within each group.

## Tone
- Terse, factual, **user-facing**: describe what changed for the user, not the internal refactor
  (unless the internal change affects them). "Faster cold start (800ms→120ms)" > "rewrote loader".
- Link the PR/issue: `(#1234)`.
- Write for someone deciding whether to upgrade.

## Formatting
- One bullet per change. Start with a verb or the feature name.
- Group by the headings above; keep within-group order by impact.
- Call out **breaking changes** prominently (a `### ⚠️ Breaking` subsection or bold prefix).

## Don'ts
- No raw commit-message dump (`fix typo`, `wip`, `address review comments`).
- No internal jargon without context.
- No vague "various bug fixes and improvements" when you can be specific.
- Don't omit breaking changes or silently change behavior.

## Quick checklist
- [ ] Version + date header, newest on top
- [ ] Grouped: Added/Changed/Deprecated/Removed/Fixed/Security
- [ ] User-facing language, PRs linked
- [ ] Breaking changes called out loudly
