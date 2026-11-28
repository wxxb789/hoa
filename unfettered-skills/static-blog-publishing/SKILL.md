---
name: static-blog-publishing
description: "Use when building or publishing the Markdown blog site."
version: 1.0.0
author: Zoe
license: MIT
metadata:
  hermes:
    tags: [blog, static-site, publishing, anc, markdown]
    category: devops
---

# Static blog publishing

Turn a repository of Markdown into a public static site: content layout, frontmatter, build,
local acceptance, then the deploy gate. The engine is `anc` (`~/repos/anc`, writes a static
site with backlinks, tags, search, feed, sitemap); everything here except the CLI lines also
holds for any Markdown SSG.

## When to Use

- Publishing an article or note to the owner's blog, standing the blog up, or changing hosting.
- Not for drafting the article itself (skill `writing`) and not for vault notes that stay
  private (`obflow-vault-contribution`).

## Standing decisions (owner)

- The site is **`undefined noise`** at `https://${BLOG_GH_OWNER}.github.io/` (root of the user site, no
  custom domain). An earlier Quartz v4 site on the same URL is **abandoned** — its branch is
  deleted and its mirror is kept under `~/claw/tasks/2026-11-06/blog-static-site/backups/`.
- Local content repo `~/repos/blog` pushes to `${BLOG_GH_OWNER}/${BLOG_GH_OWNER}.github.io` on branch `main`;
  GitHub Pages serves it with `build_type: workflow`.
- Content lives in its **own repository** (`~/repos/blog`), never the notes vault. The vault
  holds private and `<work-tag-a>/` material.
- A build is accepted only when the owner has seen the rendered result. Deliver `dist` path +
  screenshots, never "it should render fine".
- Public deploy is a Red gate **by default**. `~/repos/blog` carries a standing owner authorization to
  push `main` directly once local acceptance passes; a new site, a new content domain, or a new
  repository still needs one explicit question before anything goes public.

## Procedure

1. Content repo: `posts/<YYYY-MM-DD>-<slug>.md` plus a root `publish.config.yaml` carrying at
   minimum `title:`; add `origin:` only once the host is known.
2. Frontmatter on every post: `title`, `slug` (lowercase ASCII), `language` (`zh-CN`), a quoted
   `description`, and `tags` as a YAML list. A scalar `tags:` is refused rather than guessed.
3. **Commit before building.** Dates come from git history (first and last commit touching the
   path); untracked notes get no `created`/`updated`, and a shallow clone loses `created`.
4. Build: `node ~/repos/anc/bin/anc.mjs build --content ~/repos/blog --out ~/repos/blog/dist`.
5. Read the report, not just the exit code:
   `cat "$(git rev-parse --git-path publish-report/content-report.json)"`. `dropped` must contain
   only non-Markdown config files; a note in that list is a mis-exclusion. Trust the counts
   because a glob that matches nothing fails the build by design.
6. Local acceptance: serve `dist` (`python3 -m http.server 4321 --bind 127.0.0.1` from the dist
   directory), open it in the browser, screenshot home + article + one diagram, and check
   title/H1/TOC/code fences/CJK text. Then hand over paths and screenshots. For a draft that is not
   committed yet, build it in isolation first: copy frontmatter + body into
   `<task>/build-test/content/x.md`, run
   `node ~/repos/anc/bin/anc.mjs build --content <task>/build-test/content --out <task>/build-test/dist`,
   then grep the page for `<h1` (title on one line), `data-diagram="mermaid"` (diagram rendered),
   `href="https://` (link count) and `\\_` (escaped underscore, must be 0). This catches title
   wrapping, diagram, link and escaping faults without touching the repo or waiting for CI.
7. Hosting is **already decided** for `~/repos/blog` (GitHub Pages, `origin` set, Pages workflow
   committed): after local acceptance, re-run `anc review` only if the slug set changed, commit
   `.publish-set.json`, and push. Ask the one hosting question only for a new site or a new content
   domain — repeating it here just stalls a repo that already has an answer.
8. Deploy path for this site (GitHub Pages): local `~/repos/blog` holds `posts/`,
   `publish.config.yaml`, `.publish-set.json`, `.github/workflows/publish.yml`; `git push origin main`
   triggers the CI release build and the Pages deploy. Watch it with
   `gh run watch $(gh run list -R "${BLOG_GH_OWNER}/${BLOG_GH_OWNER}.github.io" --limit 1 --json databaseId --jq '.[0].databaseId') -R "${BLOG_GH_OWNER}/${BLOG_GH_OWNER}.github.io" --exit-status`.
   The CI verdict is build proof, not content proof: then `curl` the live article and assert a body
   marker (first-line phrase, count of a marker string) plus a `404` for every withheld file.
9. Record status in `~/claw/tasks/<date>/<task>/status.md`.

## Pitfalls

- **`uses: <owner>/anc@<short-sha>` is rejected.** GitHub Actions resolves only a full 40-char
  commit SHA; a 7-char ref fails the job at "Set up job" in seconds with a message naming the
  full SHA. Pin the full SHA in the workflow.
- **A fresh `pages` deploy can be blocked by the environment branch policy.** The error is
  `Branch "main" is not allowed to deploy to github-pages due to environment protection rules.`
  The `github-pages` environment keeps `deployment_branch_policy` per branch; add the new one and
  delete the stale one:
  `gh api -X POST repos/<o>/<r>/environments/github-pages/deployment-branch-policies -f name=main -f type=branch`,
  then `gh api -X DELETE .../deployment-branch-policies/<id>`. Renaming or changing the default
  branch does not update it.
- **GitHub Pages ignores `dist/_headers`.** The site serves fine but the CSP and the three other
  security headers never apply; only Cloudflare Pages reads that file. Say so, do not call the
  deploy "hardened".
- **A GitHub Pages project site (`/<repo>/`) is impossible with anc.** `origin` must be a bare
  origin with no path, and every route is root-absolute, so a path under the origin is discarded;
  `scripts/load-config.ts` refuses it outright. Root user site or a bare subdomain only.
- **`origin` defaults to `http://publish.localhost/`.** Canonical links, feed id, sitemap and
  robots all point at loopback: the site looks perfect and is unreachable by anything that
  follows those links. Set `origin` before announcing a deploy.
- **Preview build is not a release build.** Bare `build` is a preview; `build --release` refuses
  a loopback origin and requires the committed, reviewed `.publish-set.json`. A fresh `review`
  leaves the file uncommitted and the release build blocks with
  `release blocked: .publish-set.json must be committed and unchanged` — commit it, then rebuild.
- **No asset pipeline, and the failure is silent.** A relative image (`![x](./images/a.png)`) is dropped
  whole: no `<img>` in the HTML and no file copied into `dist`, because the sanitizer's scheme allowlist
  only grants `http`/`https`/`data` to `img[src]`. Absolute `https://` images do render — as a bare
  `<img src alt>`, with no `figure`/`figcaption`, no width/height, no `loading`. External links ship as
  bare `<a href>` without `target`/`rel`. Already supported: GFM footnotes, Mermaid
  (`figure.diagram > figcaption`), fenced code (`figure.code-block > pre > code`, build-time highlight).
  So a post that needs figures must not promise them yet: either use a Mermaid fence or wait for the
  asset pipeline to land. **Probe capability before promising a layout**: write a throwaway content dir
  under `~/claw/tasks/<date>/<task>/probe/content/` holding one note with a relative image, an `https`
  image, `![alt](src "caption")`, and an external link; run
  `node ~/repos/anc/bin/anc.mjs build --content <dir> --out <dir>/dist`; then on the built page run
  `grep -o '<img[^>]*>'` and `grep -o '<a [^>]*href="https[^"]*"[^>]*>'`. Reading `src/lib/markdown.ts`
  answers *why*, the probe answers *what actually ships* — only the second is evidence to hand the owner.
- **Collection = first folder, ASCII only.** A first folder with no ASCII letters leaves the note
  uncollected (it still publishes); Chinese tags produce percent-encoded `/tags/.../` URLs.
  Decide the folder and tag naming before there is content to migrate.
- **Mermaid renders client-side.** Verify by scrolling the figure into view, waiting a few
  seconds, then counting `figure.diagram svg`. The markup class is `diagram`, not `mermaid`, so a
  `.mermaid` selector reporting zero is a bad probe, not a broken build.
- **`anc init` seeds a commented `publish.config.yaml` and `.gitignore`.** Patch that file after
  reading it; do not overwrite it blind. `init` is idempotent.
- **`pkill -f "<pattern>"` kills the invoking shell** when the pattern matches its own command
  line — a preview-server URL always does. Kill by pid from `pgrep -f 'http[.]server'`; the
  bracket keeps the pattern from matching itself.
- **Instruction files in the content repo publish themselves unless withheld.** Everything Markdown in
  the repo is a note, so `AGENTS.md`, `WRITING.md`, `README.md` land on the public site unless each
  carries `publish: false` in its frontmatter — frontmatter beats any glob, and `dropped` then reports
  `excluded-by-frontmatter` rather than `excluded-by-glob`. After deploy prove it: each withheld path
  must return `404`.
- **markdownlint's defaults fight CJK prose and frontmatter titles.** MD013 (80-char lines) flags every
  paragraph, MD025 counts the frontmatter `title:` as an extra H1, MD060 rejects compact tables — the
  repo's existing posts fail them too, so a red run is not evidence of a bad post. Ship a
  `.markdownlint-cli2.jsonc` disabling those (plus MD033) instead of rewrapping Chinese sentences to
  80 columns.
- **`dist/` inside the content repo inflates the build's `discovered` count.** The builder walks it and
  drops every output file as `not-markdown`; that is expected. Read `published` and the frontmatter
  exclusions, not `discovered`.
- **The frontmatter `description` is the above-the-fold lead block, and it wraps.** A long description
  strands a two-character word on its own line ("兜底" split across lines) and the theme gives you no
  hook to control it. Shorten the description instead of hunting CSS, and check that block in the
  the browser before pushing — fixing it afterwards costs a second commit and a second deploy.
- **A deploy job can die inside a third-party action's download step.** Symptom: `curl: (22) The
  requested URL returned error: 504` while the action fetches a pinned release asset (a secret
  scanner, a toolchain tarball); the job fails there and the build step is skipped. That is
  infrastructure, not content — and the status page can still say all systems operational. Confirm
  from your own host before touching anything: `curl --fail -sIL -o /dev/null -w '%{http_code}'` on
  the exact asset URL, plus one unrelated project's release asset; two 504s mean GitHub's download
  edge is down. A blind `gh run rerun` then fails identically in seconds, so do not spend attempts on
  it: loop every few minutes probing the asset URL, and on a 200 fire
  `gh run rerun <id> --failed` and poll `gh run view <id> --json status`. Log every probe with a
  timestamp — the eventual verdict (“waited N minutes, then it deployed”) needs evidence. The
  content commit is already on `main`, so report this as blocked-on-infrastructure, not as a failed
  publish.

## References

- `references/anc-cli.md` — anc subcommands, config keys, frontmatter fields, output routes,
  release gate, and hosting notes (CSP `_headers`, Pages workflow).
