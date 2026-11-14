---
name: html-artifact
description: >-
  Build one self-contained HTML file — no build step, no dependencies, no CDN — to explain, plan,
  report, review, diagram, compare, or prototype something a human should read, share, or poke at.
  Use when the deliverable has color, layout, diagrams, tables, or interaction, or when the user asks
  for an artifact, explainer, plan write-up, diagram, or design variants. Not for markdown-shaped
  notes, brand-matching a known site's look, or generative canvas art.
metadata:
  version: "0.1.59"
  areas: "software-development,work-management"
  targets: "runtime-agnostic"
  summary: "single-file, dependency-free HTML explainers, plans, reports, diagrams and throwaway editors on one house style"
  summary_zh: "零依赖单文件 HTML：解释文、计划、报告、图表与一次性编辑器，统一 house style"
  kind: "entry"
---

# HTML Artifact Skill

Produce a single self-contained `.html` file — no build step, no dependencies, no
CDN — whenever the deliverable is something a human should *read, share, or poke at*:
a concept explainer, an implementation plan, a status/incident report, a code-review
walkthrough, a technical or educational diagram, a set of design variants, or a
throwaway editor that exports its result back to you.

HTML beats Markdown once a doc has color, layout, diagrams, tables, code, or
interaction. It opens in any browser, shares as a link, stays readable past 100
lines, and can carry SVG diagrams and live controls Markdown can't. Default to an
HTML artifact when the user says "make an HTML file/artifact", or asks you to
*explain how X works*, *write up a plan/PR/report*, *diagram* something, *compare*
options, or *prototype* an interaction — even when they don't say "HTML".

## Scope — one mode-switched skill

Three overlapping diagram-ish skills were folded into this one for a concrete reason:
they all emitted the *same artifact* — a single self-contained HTML file with inline
CSS/SVG — and overlapped heavily (three "diagram" paths, two "compare variants" paths,
no shared token system). One mode-switched skill removes the which-one-do-I-load
ambiguity and gives every output the same house style, while keeping what each of them
was actually good at: the fidelity dial + verify loop, the dark infra aesthetic, and the
9-ramp educational system + archetype library.

The footprint argument holds: this skill has **zero dependencies** (no Node, FFmpeg,
Chromium, or pip packages — it authors plain HTML/CSS/SVG), so the only always-in-context
cost is this skill's one-line description. All references, templates, and the example
gallery load on demand.

Use a different tool when: matching a known brand's look → a brand/design-reference
source; a formal design-token spec file → a design-token workflow; a *bespoke
visually-designed* artifact where the look itself is the point → a dedicated design
process; hand-drawn/whiteboard `.excalidraw` files → an Excalidraw editor; generative or
animated canvas art → a creative-coding tool. Diagram-style work with a *real* install
cost (Node + FFmpeg + Chromium) deliberately stays out of scope. This skill is for
everything else that ships as a readable, shareable HTML page.

## Reference files (load on demand)

- `references/house-style.md` — the canonical `:root` token block, type system,
  card/table/callout/code-block patterns. **Read this before authoring any artifact.**
- `references/examples.md` — 20 complete reference HTML files (Anthropic's
  html-effectiveness gallery, MIT) keyed to each mode, plus the script to fetch them.
  Read/fetch one that matches your task to calibrate the house style from a full example.
- `references/svg-diagrams.md` — hand-authored inline SVG: arrow markers, node
  groups, decision diamonds, edge semantics, coordinate-grid discipline. Read for
  any flowchart / architecture / concept diagram.
- `references/concept-archetypes.md` — the 9-ramp educational color system + a
  library of diagram archetypes (timeline, tree, quadrant, layered stack,
  before/after, hub-spoke, cross-section). Read for educational / non-software visuals.
- `references/dark-tech.md` — the dark "infra" token variant. Read for cloud/infra/system
  architecture diagrams.
- `references/throwaway-editors.md` — the single-file editor recipe and the
  copy-to-clipboard export pattern that survives `file://`. Read when the artifact
  needs interactive controls that export state back to a prompt.
- `references/fidelity-and-verify.md` — the throwaway↔presentation fidelity dial,
  the multi-variant comparison layout, and the mandatory browser-vision verify loop.

## Templates

- `templates/base.html` — document scaffold with the house-style `<style>` block.
- `templates/diagram.html` — dual-mode diagram host (light educational + dark infra
  CSS, arrow markers, node/edge classes). Paste your SVG where marked.
- `templates/editor.html` — throwaway-editor skeleton (state → render → export).

Read the template file straight out of the skill package (`templates/base.html` etc.)
and copy it into your working directory before editing.

## Workflow

1. **Pick the mode.** Match the request to one artifact type — explainer, plan,
   report, code review, diagram, variants, or editor. The mode decides which
   template, which references, and which worked example to use.
2. **Read the matching example first — every time.** The 20 files in the
   html-effectiveness gallery are the ground truth this skill is built on; the
   prose references describe them but a full example carries density, spacing, and
   structure no summary can. Before writing anything:
   ```
   bash scripts/fetch-examples.sh      # idempotent: clones if missing, else pulls
   ```
   then read `references/examples/<file-for-your-mode>.html`.
   `references/examples.md` has the mode→file map (e.g. code review →
   `03-code-review-pr.html`, diagram → `13-flowchart-diagram.html`, editor →
   `18-editor-triage-board.html`). Read at least the one example closest to your
   task — two if you're combining modes. Only if the fetch genuinely fails (no
   network) do you fall back to the distilled pattern references alone; note that
   you're working without the examples when you do.
3. **Decide fidelity.** Throwaway exploration or presentation-grade deliverable?
   See `references/fidelity-and-verify.md`. Don't over-polish a quick comparison;
   don't ship a sloppy report.
4. **Start from a template + the house style.** Load `templates/base.html` (or
   `diagram.html` / `editor.html`) and `references/house-style.md`. Reuse the
   `:root` tokens — never invent a new palette per file. Mirror the structure of
   the example you read in step 2; adapt it to the content, don't copy it verbatim.
5. **Author the artifact** by writing the file. Keep everything inline: one `<style>`
   in `<head>`, at most one `<script>` before `</body>`. No `<link>`, no external
   fonts (use OS-native stacks), no CDN, no `<img src>` to remote URLs. All graphics
   are inline SVG or CSS.
6. **Keep JS optional and graceful.** Prefer zero JS. When you need it, keep it to
   a small vanilla IIFE and make the page render meaningfully with JS off (native
   `<details>`, anchor nav, a default-active tab/node).
7. **Verify visually.** Open the file and screenshot it — see the verify loop in
   `references/fidelity-and-verify.md`. This is mandatory for SVG diagrams, where
   hand-placed coordinates drift on edits (overlapping nodes, misaimed arrows).
   If you cannot see images, verify text-first instead of skipping the step: load the
   page in a real browser and assert numerically — for each `<rect>`/`<text>`/`<line>`,
   `getBBox()` max-x/max-y must stay inside the SVG's `viewBox` width/height (a
   `maxY > viewBox height` is a clipped diagram), and
   `document.documentElement.scrollWidth <= window.innerWidth` (a larger value is a
   horizontal-overflow bug). Report the measured numbers as the proof.
8. **Report the path.** Tell the user the absolute file path so they can open it.
   Mention any interactive controls / export buttons.

## Core principles

**One design system, token-driven.** Warm paper (`--ivory`), near-black ink
(`--slate`), one terracotta accent (`--clay`), olive for success/additions, a warm
gray ramp. Semantic convention, held across every mode: **clay = focus/attention,
olive = success/added, rust = error/removed, oat = neutral fill, gray-500 =
secondary text & arrows.** Reference colors only as `var(--…)`.

**Three fonts by role.** Serif (Georgia stack) for headings, sans (system-ui) for
body, mono for every label / code / metric / eyebrow / path. All OS-native — zero
font loading. This serif-heading / mono-label / sans-body split is the house tell.

**Self-contained, always.** The file must render offline when double-clicked.
Inline the style and script; draw graphics as inline SVG or CSS; never reference a
remote asset. This is non-negotiable — it's what makes the artifact shareable.

**Graceful degradation.** Most great artifacts have *no* JS. When interactivity is
the point (sliders, drag, editors), the page must still convey its content without
JS, and exports must work from a `file://` page (clipboard fallback in
`references/throwaway-editors.md`).

**End interactive artifacts with an export.** A throwaway editor is only useful if
it hands its result back: a Copy-as-markdown / Copy-JSON / Copy-diff / Copy-prompt
button that serializes state to the clipboard for pasting into the next prompt.

## Quick reference — mode → what to build

| Request | Mode | Template | Read this example | Key reference |
|---|---|---|---|---|
| "explain how X works" | explainer | base | `14-research-feature-explainer.html` | house-style, svg-diagrams |
| "write up the plan / spec" | plan | base | `16-implementation-plan.html` | house-style |
| "status / incident report" | report | base | `11-status-report.html`, `12-incident-report.html` | house-style |
| "review this PR / diff" | code review | base | `03-code-review-pr.html`, `17-pr-writeup.html` | house-style (diff section) |
| "diagram the architecture / pipeline" | infra diagram | diagram | `13-flowchart-diagram.html`, `04-code-understanding.html` | dark-tech, svg-diagrams |
| "diagram this concept / process" (science, physical, educational) | concept diagram | diagram | `13-flowchart-diagram.html`, `10-svg-illustrations.html` | concept-archetypes, svg-diagrams |
| "show me N takes / compare options" | variants | base | `01-exploration-code-approaches.html`, `02-exploration-visual-designs.html` | fidelity-and-verify |
| "let me tune / triage / edit X and copy it out" | editor | editor | `18-editor-triage-board.html`, `19-editor-feature-flags.html`, `20-editor-prompt-tuner.html` | throwaway-editors |

## Pitfalls

- **Don't skip the example.** The single biggest quality lever is reading the
  matching gallery file before you write (`bash scripts/fetch-examples.sh` then read
  the file). The prose references are a map; the examples are the territory.
  Authoring from memory of "what good HTML looks like" is exactly how the output
  drifts generic.
- **Don't invent a palette.** Reuse the `:root` tokens from `house-style.md`. A
  per-file color scheme breaks the consistency that makes these artifacts feel pro.
- **Don't reach for a library.** No Mermaid, D3, Tailwind CDN, Prism, or web fonts.
  Diagrams are hand-authored SVG; syntax highlighting is hand-marked `<span>`s; the
  token block does the job of a build-time theme.
- **Don't skip the visual check on diagrams.** Manually computed SVG coordinates
  are the #1 source of broken output — arrows landing in whitespace, overlapping
  boxes, text overflow. Screenshot and fix before reporting done.
- **Don't add a JS export where a static `<pre>` suffices.** If the deliverable is
  one snippet, a hand-selectable code block is the bulletproof "export".
- **Don't let JS be load-bearing for content.** If the prose only exists inside a
  `render()` call, the page is blank with JS off. Put real content in the HTML;
  use JS to enhance, not to populate.
