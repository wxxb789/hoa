# Channel: A Little Book (故事引导问答体 · 学习笔记)

> The default note style for "distill to notes / 做成笔记 / 讲讲 X". The DNA is two books:
> *The Little Schemer* (gentle one-Q-one-A that walks you to understanding) and
> *Alice in Wonderland* (a story you follow that quietly teaches as it goes). Language: ZH-CN.
>
> **This is NOT Socratic interrogation.** The engine is a *story*, not relentless questioning.
> The Q&A is the rhythm; the story is the spine. Don't grill the reader — guide them.

## When to use
- User says "distill to notes", "做成笔记", "整理成笔记", "讲讲这个", "学 X" and wants a keepable explainer.
- Default for explaining/teaching a concept unless another channel is explicitly named.
- NOT for: social posts, PRDs, changelogs, formal docs — those have their own channels.

## The two pillars (both required)

### Pillar 1 — One story running through (the spine, the primary driver)
- Pick **one concrete story / world / character** and carry it across the whole piece.
- The story is the **engine**: the reader learns the concept by following what happens next in the story, the way you absorb a lesson from a fable without being lectured.
- Each concept maps onto a **beat** in the story — an obstacle the character hits, a turn in the world, a thing that surprises them. The reader remembers the concept because they remember the beat.
- Good spines: a character with a goal who keeps running into each concept as an obstacle; a small world with its own rules (像爱丽丝掉进的兔子洞) that bends as concepts compound; a running scenario (开一家店 / 招聘 / 找东西 / 破案) extended rigorously.
- Reuse the same characters/props as concepts build — callbacks make it cohesive and fun.
- The story must **illuminate**, not decorate. A beat earns its place if it either advances the main thread *or* reveals genuine complexity — not if it's mere garnish.
- **Keep a clear main thread, but let the world branch.** The spine keeps the reader from getting lost; the branches keep the world honest. As the story walks its main line, deliberately wander sideways now and then — poke at a side corridor, surface a "其实这里没那么简单" aside, show a second or third cause — then return to the thread. Controlled wandering, in service of showing complexity.
- **The world is a web, not a causal chain.** Resist the clean "A → B → C" line; real things are multi-causal, with side effects, exceptions, and accidents. Let the reader *feel* that the world is bigger than one tidy explanation. Don't over-simplify into false single causality just to keep the beat clean.
- Don't force every micro-detail into the story; the spine carries the arc, technical asides can step out briefly then return.

### Pillar 2 — Gentle Q&A rhythm (the form, The Little Schemer DNA)
- **Every concept is drawn out by a Q→A pair, never dropped as a lecture.** The reader walks alongside.
- Questions are short and naive / first-principles ("就这？""那会怎样？""她接下来该怎么办？") — the kind a curious companion asks, not an interrogator.
- **The answer's job is to move the story one beat forward**, and in doing so make the next question feel inevitable. Pull the reader along with curiosity, don't push them with demands.
- A light "你猜猜看？" before revealing is welcome — but as an *invitation to wonder*, not a quiz. Use sparingly; the story's momentum should already make the reader lean in.
- Build in layers: each Q assumes the previous A. A newcomer can follow top-to-bottom.
- Open with a "盖住答案，跟着故事猜猜看" reading instruction.
- Keep answers tight — usually 1–3 sentences. If an A runs long, split into more Q&A.

## Structure
1. **Title**: `<主题> · 小书` or a story-flavored title (e.g. `<角色> 的 <主题> 历险`).
2. **Front matter** (1–2 lines): reading instruction + the story premise in one sentence.
3. **Chapters**: each a story beat = a concept cluster. `## 第N章 · <故事节拍>`.
4. **Q&A body** under each chapter, carried by the story.
5. **金句收尾**: end the last chapter on one memorable line that fuses story + lesson.
6. **附 · 还能往下挖的**: optional bullets for 未展开 threads.

## Formatting
- Bold the **Q:** / **A:** labels. Keep formulas/code/tables when they aid precision — wrap a Q&A around them ("这公式长啥样？" → block → "那个符号是谁？").
- Use `> blockquote` for the running 一句话总结 / memory anchors.
- 中文排版按《中文文案排版指北》：中英文间空格，半角标点配中文。

## Pitfalls (from building the 检索 notes)
- ❌ **Treating it as Socratic grilling** — piling on relentless "那又如何？那又如何？" until the reader feels cornered. Wrong engine. The story pulls; questioning doesn't push.
- ❌ Story that's just a label slapped on ("把它想象成一家店") then never used again. Carry it through — it must drive, not garnish.
- ❌ **Over-simplifying into a single causal chain** — forcing the world into a tidy "A→B→C" so each beat stays clean, when the real thing is multi-causal. That's false clarity. Let the branches and complexity show.
- ❌ **Branching that loses the thread** — wandering so far into side corridors that the reader forgets where the main line was. The fix is *return*, not *don't wander*: every detour comes back to the spine. (Controlled蔓延 good; getting lost bad.)
- ❌ Q&A that doesn't advance the story → turns into a flat FAQ, loses the soul. Each A nudges the narrative forward.
- ❌ Dumping all material into one giant A. Split aggressively into more Q&A.
- ❌ Losing technical accuracy for the sake of the story. Story serves the concept, not vice versa — keep verified facts/formulas intact.

## Inherit
All cross-channel hard rules from SKILL.md apply: clarity > cleverness, no fabrication
(mark gaps `[TODO]`), no flirty padding, long pieces → a file in the task workspace.
Run the AI-smell checklist, but note the genre exception: **uniform Q&A rhythm is a genre
requirement here, not an AI tell** — don't flag it.
