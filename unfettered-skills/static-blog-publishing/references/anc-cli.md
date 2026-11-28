# anc — CLI, config, and output map

Engine checkout: `~/repos/anc` (owner's own project, MIT, pre-release, not on npm). Run it from
the checkout; there is no `npx anc` until it is published.

## Commands

```bash
node ~/repos/anc/bin/anc.mjs init     # seeds .gitignore + commented publish.config.yaml; idempotent
node ~/repos/anc/bin/anc.mjs build  --content <dir> [--out <dir>] [--release]
node ~/repos/anc/bin/anc.mjs review --content <dir>   # produces the exact public slug set
node ~/repos/anc/bin/anc.mjs preview [--dist <dir>] [--port 4321]
```

Defaults: `--content` = cwd, `--out` = `<cwd>/dist`, `--port` = 4321. Node >= 22.18.

## `publish.config.yaml` (root of the content dir)

Every key optional. Unknown key → build fails with the line number and a suggestion.

| Key | Meaning |
| --- | --- |
| `title` | Site name: tab, metadata, feed |
| `origin` | Public base URL, no path. **Required before deploying** — default is `http://publish.localhost/` |
| `exclude` | gitignore-style globs; `"!"` re-includes. Quote every pattern (unquoted `!` parses as a tag and inverts the rule) |

- A pattern matching zero files **fails the build** with no override — the guard against a typo
  that would publish what was meant to be withheld. A not-yet-created folder must lose its line.
- Never add `dist/**`: build output is already dropped as `not-markdown`, and the discovered count
  goes up, not down.

## Frontmatter fields that reach the page

`title`, `slug` (lowercase ASCII route override), `language` / `lang` (BCP 47), `description`,
`tags` (YAML list; scalars refused), `aliases` (searchable metadata, not link targets),
`publish: false` (absolute; no glob re-includes it).

`created` / `updated` are **not** read: git history is the sole date authority.

Skipped without being asked: `.git/`, `.obsidian/`, `node_modules/`, anything dot-prefixed, and
**the root `README.md`** (a `README.md` inside a folder is an ordinary note).

## Build report

Path: `"$(git rev-parse --git-path publish-report/content-report.json)"` — inside `.git/`, so
`git add -A` and `git clean -xfd` cannot touch it. Stdout gives counts only; the report gives
paths, drop reasons, and link failures. Outside a git repo the report falls back to the user
state dir keyed by build-directory digest (128 reports, 90-day expiry).

## Output routes

`/` (home), `/notes/<slug>/`, `/collections/<first-folder>/`, `/tags/<tag>/`, `/recent/`,
`/graph/`, `/about/`, `/privacy/`, `/private/` (withheld targets land here), `404.html`,
`rss.xml` (Atom), `sitemap.xml`, `robots.txt`, `_headers` (CSP), `_redirects`,
`data/site.<sha256>.sqlite` (public preview snapshot), `pagefind/`.

## Release gate

1. `anc review --content <dir>` → inspect → commit `.publish-set.json` (exact public slug set).
2. Non-loopback `origin` in `publish.config.yaml`.
3. `anc build --content <dir> --out <dir> --release`.

A missing, dirty, or stale `.publish-set.json` stops the release build before any deployable
artifact exists. The shipped GitHub Action runs exactly this and refuses loopback origins too.

## Hosting notes

- The output is plain static files; any host serves it.
- `dist/_headers` is in **Cloudflare Pages** format (CSP + three security headers). A host that
  ignores `_headers` serves the site without them — works, weaker.
- The Mermaid mode is `client`, which ships a ~201 KB diagram runtime and needs
  `style-src 'self' 'unsafe-inline'` in the deployed policy; `public/_headers` is asserted against
  the selected mode, so do not hand-edit one without the other.
- Git-based CI (GitHub Pages): `fetch-depth: 0` (a shallow clone cannot prove `created`), set
  `origin` first, commit the reviewed publish set, run on a Linux runner (the secret-scan
  installer is Linux x64/arm64).
