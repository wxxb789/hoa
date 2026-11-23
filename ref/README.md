# ref — External references

> **English** · [简体中文](./README.zh-CN.md)

A curated map of agent / skill / harness repos worth learning from. This is
**not vendored code** — just where I go for inspiration and patterns to steal.
When something here proves its worth, adapt it into the matching top-level folder —
[`../skills/`](../skills/), [`../orchestration/`](../orchestration/),
[`../agents/`](../agents/), … (keep attribution).

## Vendored references (submodules)

All rows below are git submodules under `ref/<name>/`, each **branch-tracking**
its upstream default branch. They set `update = none`, so no clone or install
fetches them, and a [daily workflow](../.github/workflows/ref-sync.yml) keeps
their pointers at upstream heads. Check out what you study at depth 1 (omit the
path for all):

```sh
git submodule update --init --checkout --remote --depth 1 ref/<name>
```

| Repo | Category | What it is | What to steal |
|---|---|---|---|
| [EveryInc/compound-engineering-plugin](https://github.com/EveryInc/compound-engineering-plugin)<br>`ref/compound-engineering-plugin` | eng skills | A cross-harness AI coding-agent plugin of 31 chained workflow skills for brainstorm, plan, work, review, debug, and compound-learning loops. | The compounding loop where ce-compound writes docs/solutions learnings that later ce-brainstorm/ce-plan read as grounding. |
| [obra/superpowers](https://github.com/obra/superpowers)<br>`ref/superpowers` | eng skills | A Claude Code plugin of 14 composable, auto-triggering skills encoding a TDD-first agent dev workflow: brainstorm, plan, worktree, subagent-driven implementation, review. | The "writing-skills IS TDD for process docs" meta-skill plus RED-GREEN-REFACTOR-gated subagent-driven-development with two-stage spec-then-code review. |
| [mattpocock/skills](https://github.com/mattpocock/skills)<br>`ref/mattpocock-skills` | eng skills | Matt Pocock's collection of ~41 composable Claude Code agent skills for real engineering: grilling, spec/ticket flows, TDD, code review, and domain modeling. | The "grilling" pattern: a relentless pre-build interview that also emits a CONTEXT.md ubiquitous-language glossary and ADRs (grill-with-docs). |
| [JimLiu/baoyu-skills](https://github.com/JimLiu/baoyu-skills)<br>`ref/baoyu-skills` | content-gen | A Claude Code marketplace plugin bundling 21 baoyu-* AI content skills: image cards, infographics, SVG diagrams, covers, slide decks, comics, publishing (WeChat/Weibo/X), translation, and transcript/markdown utilities. | Combinatorial dimension systems (Style x Layout x Palette, or Type x Palette x Rendering x Text x Mood) that turn one skill into hundreds of looks |
| [lijigang/ljg-skills](https://github.com/lijigang/ljg-skills)<br>`ref/ljg-skills` | thinking-tools | A personal collection of 21 Chinese-language cognition skills that deconstruct concepts, books, papers, and domains into structured thinking frameworks with org-mode/markdown or PNG-card output. | The reusable "framework-as-skill" pattern: fixed-dimension deconstruction (8-axis concept anatomy, book's x→f→f(x) reduction) compressed to one epiphany sentence. |
| [zjp1997720/zhijian-skills](https://github.com/zjp1997720/zhijian-skills)<br>`ref/zhijian-skills` | agent skills | A single-repo portfolio of 11 focused, independently-versioned Agent Skills for Codex ops, workflow orchestration, model routing, knowledge systems, research, and WeChat publishing. | registry/skills.json manifest + split of `skills/<name>/` payload vs `docs/skills/<name>/` bilingual docs, giving each skill its own version |
| [dontbesilent2025/dbskill](https://github.com/dontbesilent2025/dbskill)<br>`ref/dbskill` | skills | A Chinese Claude Code plugin/marketplace of 28 business & content-creation diagnostic Skills plus a 4,176-atom knowledge base mined from tweets. | The `/dbs` router skill: one entry-point that reads conversation context and auto-dispatches to the right specialized skill. |
| [tw93/Waza](https://github.com/tw93/Waza)<br>`ref/Waza` | eng skills | Waza is a cross-agent (Claude Code/Codex/Cursor) plugin of eight engineering-workflow skills: think, ui, check, hunt, write, learn, read, health. | The bilingual `when_to_use`/`dispatch_intent` frontmatter plus RESOLVER.md routing table that lets one skill trigger across agents/languages. |
| [tw93/Kami](https://github.com/tw93/Kami)<br>`ref/Kami` | design | A Claude Code skill and constraint-based design system that typesets professional documents and landing pages into branded PDF/PPTX/PNG deliverables via WeasyPrint. | Deterministic delivery gate: per-type content schema + fact-coverage check + page-image visual QA checklist before shipping |
| [ksimback/looper](https://github.com/ksimback/looper)<br>`ref/looper` | agent skills | A Claude Code slash-command skill that interviews you to design a well-shaped agent loop (goal, typed verification, cross-model review gates, termination guards) and emits a portable, lintable loop spec. | The typed verification taxonomy (programmatic/judge/human) plus a static `looper lint` that flags loop anti-patterns like all-vibe checks and same-vendor judges. |
| [kunchenguid/no-mistakes](https://github.com/kunchenguid/no-mistakes)<br>`ref/no-mistakes` | eng skills | A Go CLI that puts a local git-push gate in front of your remote, running an AI validation pipeline (review, test, docs, lint, push, PR, CI) before opening a clean PR. | The SKILL.md gate-loop contract: drive a TOON machine-readable run, respond on every `gate:`, loop until `outcome:`, escalate `ask-user` findings verbatim to the human. |
| [kunchenguid/gnhf](https://github.com/kunchenguid/gnhf)<br>`ref/gnhf` | orchestration | A cross-platform npm CLI that loops any coding-agent CLI overnight in a git repo, committing one small verified change per iteration until a stop condition. | The SKILL.md Hands-Off vs Companion split with a signal-to-action steering table and the rule "stop condition met is not user acceptance". |
| [kunchenguid/lavish-axi](https://github.com/kunchenguid/lavish-axi)<br>`ref/lavish-axi` | agent tooling | An "AXI" CLI (lavish-axi) plus install skill that opens agent-generated HTML artifacts in a local browser for human element/text/Mermaid annotation and long-poll feedback back to the agent. | Single-source the SKILL.md from CLI runtime guidance via build:skill, with a check gate that fails on drift. |
| [petergyang/no-ai-slop](https://github.com/petergyang/no-ai-slop)<br>`ref/no-ai-slop` | prose | An AI-harness writing skill with two modes: a default edit mode that makes the minimum change to strip 20+ named slop patterns (colon reveals, importance puffery, em-dash clusters) while preserving the writer's voice, then self-checks against eval.md; and a detect mode that quotes each pattern without rewriting or guessing AI authorship. | The paired eval.md pass/fail checklist the same agent self-runs on its own edit — a self-critique loop with no separate evaluator agent. |
| [mvanhorn/last30days-skill](https://github.com/mvanhorn/last30days-skill)<br>`ref/last30days-skill` | research | A multi-host Agent Skills plugin (/last30days) that searches ~20 social platforms in parallel, scores results by engagement, and an AI judge synthesizes one cited brief. | The `doctor` health-check command that probes every source and prescribes exact fixes: missing key, off-PATH CLI, expired cookie. |
| [alchaincyf/huashu-design](https://github.com/alchaincyf/huashu-design)<br>`ref/huashu-design` | design | An agent-agnostic Claude skill turning one prompt into deliverable HTML prototypes, slide decks, MP4/GIF animations, editable PPTX, infographics, and expert design critiques. | Brand Asset Protocol: ask, search official brand page, download, grep hex colors from real assets (never guess), freeze into brand-spec.md |
| [yaojingang/yao-open-skills](https://github.com/yaojingang/yao-open-skills)<br>`ref/yao-open-skills` | research | Curated public collection of Chinese-language Claude Skills that turn decision, business, security, and learning problems into structured multi-format analytical reports. | registry/skills.json as single source of truth auto-rendering README catalog + HTML nav via one render script |
| [yaojingang/yao-meta-skill](https://github.com/yaojingang/yao-meta-skill)<br>`ref/yao-meta-skill` | meta-skill | A Python-driven "Skill OS" that turns workflows into installable agent skills via a semantic Skill IR, multi-target compilers, trigger/output evals, and release-governance gates. | Skill IR: one platform-neutral semantic contract compiled to OpenAI/Claude/generic/VS Code adapters, plus train/dev/holdout trigger eval suites. |
| [virattt/dexter](https://github.com/virattt/dexter)<br>`ref/dexter` | agent | A Bun/TypeScript autonomous financial-research agent that plans, executes tools, self-validates against live market data, and ships DCF/memo/sentiment skills. | write-memo's falsifiable thesis bullets ("Claim — evidence with a number. *Wrong if* observable") plus a steelmanned bear case and tripwire risk table, enforced by a self-critique pass; atomic correctness/contradiction eval rubric. The falsifier rule is absorbed into evidence-backed-analytical-writing. |
| [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill)<br>`ref/taste-skill` | design | A portable Agent Skills library (also a Claude plugin) of anti-slop frontend design and image-generation skills that push AI-built UIs toward premium layout, typography, and motion. | The "anti-slop" pattern: each SKILL.md names the specific AI defaults to break (6-line headings, cards-in-cards, left/right repeats) as hard negative constraints. |
| [affaan-m/ECC](https://github.com/affaan-m/ECC)<br>`ref/ECC` | agent harness | ECC is a harness-native agentic operator plugin (v2.0.0) shipping 278 skills, 67 agents, hooks, rules, and MCP conventions across Claude Code, Codex, Cursor, and other harnesses. | skill-scout: search local/marketplace/GitHub/web for an existing skill before authoring a new one to avoid duplication |
| [garrytan/gstack](https://github.com/garrytan/gstack)<br>`ref/gstack` | eng skills | A suite of 59 Claude Code slash-command skills plus a headless-browser CLI, running an AI engineering sprint from plan through review, QA, and ship. | Generate SKILL.md from .tmpl templates via a config-driven gen-skill-docs generator with shared resolver modules (preamble/jargon), so many skills share one prompt spine. |
| [anthropics/skills](https://github.com/anthropics/skills)<br>`ref/anthropics-skills` | skills | Anthropic's official example Agent Skills repo: 17 self-contained SKILL.md skills (docs, design, MCP, web testing) plus a template and Claude Code plugin marketplace. | The SKILL.md pattern: two-field YAML frontmatter (name + when-to-use description) fronting a self-contained instruction folder. |
| [backnotprop/pstack](https://github.com/backnotprop/pstack) (mirror of `cursor/plugins/pstack`)<br>`ref/pstack` | eng skills | Poteto's ~60 standalone Agent Skills for AI-driven development: principle skills (prove it works, subtract before you add, guard the context window), architect/arena/swarm, verification-skill builders, and teaching skills. | One principle per skill with an explicit dependency table, and verification-skill creators that turn a repo's checks into a reusable skill; gdd borrows heavily from it. |
| [Imbad0202/academic-research-skills](https://github.com/Imbad0202/academic-research-skills)<br>`ref/academic-research-skills` | research | A human-in-the-loop academic pipeline (deep research, paper writing, reviewer, integrity gates) with citation locators and a claim-faithfulness audit. CC BY-NC 4.0: study the ideas, do not copy text. | Stage integrity gates against a named list of AI-research failure modes, and per-citation locator anchors checked against the cited source; a reference for nana-research. |
| [victorchen96/victorchen96.github.io](https://victorchen96.github.io/auto_research/framework.html) (`auto_research/`)<br>`ref/auto_research-site` | orchestration | HTML showcase pages plus survey PDFs documenting Deli_AutoResearch: a long-horizon autonomous-agent protocol and a 5-sub-skill paper-writing pipeline producing ICLR-style surveys. | 3-layer heartbeat watchdog (resident shell guard / durable cron / in-session last_seen) plus stale_count-driven forced structural pivot |

> The repo cell shows the upstream repo (linked) with its local submodule path
> below. One row is a subdirectory of a larger vendored repo — look under the
> path in parentheses (`auto_research/`).

## Link-only references

| Repo | What it is | What to steal |
|---|---|---|
| [multica-ai/andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills) | One SKILL.md distilling four Karpathy anti-slop coding principles: think before coding, simplicity first, surgical changes, goal-driven execution. | The "transform imperative tasks into verifiable goals" table ("Fix the bug" → "write a failing test first") — one page, no vendoring needed. |
| [JimLiu/baoyu-design](https://github.com/JimLiu/baoyu-design) | A portable Agent Skill repackaging Claude Design so local agents produce self-contained HTML mockups, prototypes, and decks. | Harness-agnostic SKILL.md that detects the runtime and loads a per-harness `references/*.md` tool map. |
| [blader/humanizer](https://github.com/blader/humanizer) | Single-SKILL.md rewriter for 26 AI-writing tells from Wikipedia's "Signs of AI writing". | Strength-ordered tells with a "weak alone" rule and a post-edit fact check (absorbed into writing `ai-tells.md`). |
| [op7418/Humanizer-zh](https://github.com/op7418/Humanizer-zh) | Chinese port of humanizer, 31 tells. | Constraint precedence (facts > scope > voice > pattern list) and a keep example per rule (absorbed into writing `ai-tells.md`). |
| [taxueseek/say-it-human](https://github.com/taxueseek/say-it-human) | Chinese plain-writing toolkit: a source map of AI tells across chained skills, plus an archived tech-doc style guide. | Topic-swap test, breather sentences, edit-loss check, tech-doc warning placement (absorbed into writing `ai-tells.md` and `tutorial.md`). |
| [MrGeDiao/shuorenhua](https://github.com/MrGeDiao/shuorenhua) | Chinese-first de-AI editing skill with a 123-case should-fix/should-not-fix benchmark. | Edit scopes (structural/bounded/in-place), quotes judged by function, unsourced-claim handling, register tells judged by object (absorbed into writing `ai-tells.md`). |
| [ayghri/i-have-adhd](https://github.com/ayghri/i-have-adhd) | ADHD-friendly output skill with hooks and blind evals. | Action-first replies, per-turn state, one next step, first/last-line check; its eval showed "cause, then fix" invents causes (absorbed into `prompts/adhd-operator-standing-rules.md`). |
| [juliusbrussee/caveman](https://github.com/juliusbrussee/caveman) | Terse-reply skill plus a token-saving proxy ecosystem; its own eval measures ~3% median output saving over a plain "Answer concisely." control. | Eval design: one-line control arm, length paired with regex fidelity checks, billed totals including added input (absorbed into hoa-skill-create `evaluate.md`). |
| [yaojingang/yao-open-prompts](https://github.com/yaojingang/yao-open-prompts) | 135 scenario-categorized Chinese prompts, mostly marketing and content, with an English mirror and generated catalog (CC-BY-4.0). | Nothing beyond what hoa's prompt index already does. |
| [titanwings/colleague-skill](https://github.com/titanwings/colleague-skill) | Distills a colleague, relationship, celebrity, or the owner into persona and work skills, with chat collectors. | Work-playbook layer ahead of persona; `{scene, wrong, correct}` correction records. |
| [alchaincyf/nuwa-skill](https://github.com/alchaincyf/nuwa-skill) | Researches a person or topic and distills a runnable perspective skill. | Prior snapshot, increment filter, held-out ground truth, boundaries as behavior (absorbed into hoa-skill-create `distill-material.md` and `evaluate.md`). |
| [lyra81604/zhengxi-views](https://github.com/lyra81604/zhengxi-views) | Single Chinese skill answering questions about fund manager Zheng Xi from a source-traceable corpus and fund data. | Say-vs-do check counting only records inside the actor's tenure window; corpus-silent answers flagged as method-based inference. |
| [anthropics/knowledge-work-plugins](https://github.com/anthropics/knowledge-work-plugins) | Anthropic's role-plugin marketplace (finance, data, legal, sales…) bundling skills, connectors, and commands. | `data/validate-data`'s pre-share trap list (denominator shifting, incomplete periods, survivorship, average of averages) and `finance/variance-analysis` narrative anti-patterns. |

> Thin single-skill repos: link them here instead of paying a submodule.
> Worth a submodule only when we actually study the upstream.


## Adding more

Add a reference as a branch-tracking submodule so it can be refreshed to latest:

```sh
git submodule add -b <default-branch> <url> ref/<name>
git submodule set-branch --branch <default-branch> ref/<name>   # if -b was omitted
git config -f .gitmodules submodule.ref/<name>.shallow true
git config -f .gitmodules submodule.ref/<name>.update none
```

Prefer links over vendoring when you only need the idea — submodules inflate the
repo and pull in someone else's history. Never copy code that carries a secret
or a personal path.
