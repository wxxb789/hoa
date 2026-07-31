# hoa — Project Agent Instructions

## Generated Artifacts Output

All HTML artifacts and their related assets **MUST** be written to `./.tmp-artifacts/`.

- **Scope**: rendered reports, dashboards, visualizations, session/insight
  reports, screenshots, and any backing assets they depend on (CSS, JS,
  images, fonts, and JSON/data files).
- **Location**: always under `./.tmp-artifacts/` at the repo root. Create it
  with `mkdir -p .tmp-artifacts` if it does not exist. Never scatter these
  files in the repo root or in source directories.
- **Bundle per artifact**: every artifact gets its **own subfolder** named
  after it, e.g. `./.tmp-artifacts/<artifact-name>/`. The main file and **all**
  of its related assets (data JSON, CSS, JS, images, fonts) live together in
  that one subfolder so each bundle is self-contained and portable. Never drop
  loose files directly in `./.tmp-artifacts/` — its root holds only bundle
  subfolders.
- **Version control**: `./.tmp-artifacts/` is git-ignored. Never commit its
  contents and never force-add (`git add -f`) files from it.

Example layout:

```
.tmp-artifacts/
  session-report-20260626/      # one bundle
    session-report-20260626.html
    _session-report.json
    _session_index.json
  insights-report-zh-cn/        # another bundle
    insights-report-zh-cn.md
    _insights_data.json
```
