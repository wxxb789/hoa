---
name: writing
description: >-
  Draft and revise publishable prose per channel — technical blog, academic, X/Twitter, Reddit,
  Xiaohongshu, WeChat MP, tutorial, changelog, a-little-book notes — behind one shared layer of
  content-first rules, measurable self-checks, and an AI-smell audit. Use when the text has a
  destination and a reader whose decision it must move. Not for chat replies, commit messages, or
  any piece where the content is still missing and only the packaging is being polished.
metadata:
  version: "0.1.54"
  areas: "work-management,self-management"
  targets: "runtime-agnostic"
  summary: "per-channel prose contracts behind one content-first layer: blog, academic, X, Reddit, 小红书, 公众号, tutorial, changelog; plus a measurable AI-smell audit"
  summary_zh: "一套内容优先的共同层加分渠道契约：博客、论文、X、Reddit、小红书、公众号、教程、changelog；附可量化的 AI 味自查"
  kind: "entry"
---

# Writing (per-channel, one skill)

This SKILL.md is the **shared layer**: how to pick a channel + rules that apply to every piece.
**Each channel's detailed contract is a separate file** under `references/` — load only the one
you need (keeps this skill iterable: improve one channel without touching the rest).

> Methodology note: the structure + the AI-smell checklist below are adapted from **dbskill**
> (dontbesilent), a public writing-method set whose current licence is **all-rights-reserved**:
> adapting its methods for your own work is allowed; redistribution, repackaging, publishing
> modified copies and AI training are not. So absorb the frameworks in our own words and
> **never paste its skill text into a repo we publish** — and don't copy its specific copy/voice
> either. Nothing here depends on the original being installed.

## Step 1 — pick the channel, then load its file

| Destination | Load this | Lang default | One-line shape |
|-------------|-----------|--------------|----------------|
| Academic paper/section | `references/academic.md` | EN (or ZH) | claim → evidence → method → limitation |
| Technical blog | `references/blog.md` | EN/ZH | series: one article = one decision; 表象（标题/开头/骨架）+ 内核（误判故事/可回溯事实） |
| X / Twitter | `references/x-thread.md` | EN/ZH | one idea/post, hook first |
| Reddit | `references/reddit.md` | EN | TL;DR top, anti-marketing, honest |
| 小红书 / RedNote | `references/xiaohongshu.md` | ZH-CN | 标题钩子 + emoji 分段 + 干货 + tags |
| 微信公众号 | `references/wechat-mp.md` | ZH-CN | 标题钩子 + 小标题 + 金句 + CTA |
| Tutorial / Docs | `references/tutorial.md` | EN/ZH | prereqs → steps → verify → troubleshoot |
| Changelog / Release | `references/changelog.md` | EN | Added/Changed/Fixed/Removed |
| A Little Book / 学习笔记 | `references/a-little-book.md` | ZH-CN | 一个故事贯穿全文 + 温和一问一答引导 |

If the user names a channel, load that file and follow it. If ambiguous, **ask once**: which
channel + who's the audience. Don't guess across channels — a公众号 long-form and an X post are
not interchangeable.

Nothing here assumes *where* the piece is published. Each channel file describes the reader and the
form; the site or platform's own style contract (if one exists) wins on local mechanics — say so in
one line rather than inventing platform rules.

## Step 2 — content before packaging (the core lesson of the method this adapts)

**Diagnose the content before polishing the form.** A hook/title/封面 is the "试用装" (free
sample) of the content. If the content itself has no value — no data, no story, no real point —
no amount of style fixes it. Before writing the surface:

- Is there a real point the reader couldn't get elsewhere? If not, say so.
- Is there material? For a technical post, at least **one class of hard material** (a real
  misjudgement, a counter-intuitive number, a verbatim line, an executable action, a controlled
  comparison). Process statistics alone are not material — the channel file sets the exact gate.
- Can the core be said in one sentence? If it takes 99% effort to package 1% substance, stop.

**One piece carries one decision.** If the core claim needs 「并且」 to hold two of them, split it
into a series and link the pieces both ways; length is never the reason to split, a second claim is.

**Titles ship as candidates, not as one guess.** Offer 3, each with a promise/fulfilment pair
(what the reader expects to see / which section delivers it). A title the body cannot pay off is
title-bait even when it is clickable — and never reuse the series name or a number as the title.

When the ask is "optimize my opening/title" but the underlying content is weak, name that first.

### Rewriting an existing piece: 重构 or 从零

Decide the mode before you touch the model; they take different inputs and give different output.

- **重构** — new skeleton, old draft supplied as the fact source. Cheap, preserves the sentences
  that were already accurate. Expect ~60% character overlap and 20%+ verbatim sentences; say that
  number out loud, because "is this a real rewrite or the old one in new clothes?" is the next
  question the operator asks.
- **从零** — old draft withheld entirely. Feed a numbered fact inventory + verbatim material
  (code blocks, quoted contracts, log lines) + the structural directives; never the old prose.
  Lands well under 40% overlap with reuse confined to quoted material and fixed trailing links.

Measure, don't assert: `python3 scripts/zh_draft_check.py draft.md --old previous.md` reports
similarity and lists every verbatim-reused sentence. A reused narrative sentence means the draft
was not actually rewritten; `[材料/固定句]` is fine.

Every number in the new draft is unverified again — rewriting does not launder inherited statistics.
Run `scripts/fact_check.py` and trace each MISS.

## Step 3 — cross-channel hard rules (always apply)

- **Clarity > cleverness. Concrete > vague. Numbers/examples/code > adjectives.**
- **数字分性质**：读者能拿去用的（参数、可验证的对比）可以密集；自己的产出统计必须降成数量级且全篇
  ≤3 处。按总量卡配额是错的，病在性质不在数量，见 `references/blog.md` 的数字一节。
- **篇幅由内容边界决定，不设字数配额**：能独立成篇的主张就拆出去、用双链互指；材料只够 1,200 字就写
  1,200 字，不为凑长度加过渡段。字数上下限都不是判据（"篇幅 3,500–4,500" 这类 hard rule 已被明确否掉）。
- **语气是节奏工具，不是文风装饰**：停顿（独立成行的短句）/ 反问（放在读者要做判断的位置）/ 降温
  （强判断后紧跟限定或自嘲）/ 换气（引用块、图、表、代码块）。相邻两段不复用同一种；删掉它论证仍成立
  才算合格。逐条配额与位置见 `references/blog.md`。
- **正文一律低推理档**：凡是要给人读的文字——初稿、修订、多模型迭代——都跑在 clean context + low
  reasoning effort，不分模型、不分轮次。正文开高会交回更均匀、更像算法排版的文字。
  审计（核验、契约评审、选版判断、诊断）不设档位约束，用模型默认即可；审计只出意见，
  不许直接生成或改写正文。
- **No flirty / emotional padding** (operator's global preference).
- **Don't fabricate** data, quotes, citations, benchmarks. Mark gaps as `[TODO]`.
- **Re-check every number before publishing** when the draft builds on existing material: numbers
  inherited from an older draft are the highest-risk kind. Run
  `python3 scripts/fact_check.py <draft.md> --corpus <dir> --corpus <file>` and trace every MISS
  to a source line or delete it.
- **发布不是 push 完就算**：站点对"已发布集合"常有复核闸门，带 release 标记的构建在集合变化时拒绝；
  先跑站点的 review 步骤、看集合锁文件的 diff、再提交，然后带 cache-buster 回读线上页。CI 失败先分辨
  是内容还是上游依赖。步骤与探针写法见 `references/blog.md` 的发布一节。
- Long pieces → a file in the task workspace; reply with summary + path.
- Match the requested language norm per the table; respect 《中文文案排版指北》 for ZH.

## AI-smell checklist (adapted from dbskill `dbs-ai-check`)

The essence of "AI 味": **too perfect, too smooth, too uniform** — no rough edges, no hesitation,
nothing the author hadn't fully figured out. Scan for these; **but check 体裁 first** (some are
genre requirements, not AI tells — see exceptions). Goal is NOT to "remove AI smell" as disguise,
it's to make writing clearer and more genuinely yours.

Strong tells (🔴 almost only AI does this):
- Knowledge-dump: piling terms/data to look expert. Keep the one you actually think with.
- "不是 X 是 Y" at high density (3+ in 800 字). Low density is normal rhetoric.
- No hesitation anywhere / uniform confidence. Real writing has a spot the author isn't sure of.
- Suspiciously precise emotional detail ("1.7 秒") never actually measured.
- Every paragraph ends on a polished 金句. (Exception: short-video scripts — genre requirement.)
- Opening "钩子+痛点+承诺" three-piece selling anxiety. Start from the actual thing instead.

Medium tells (⚠️ AI-frequent but humans do it):
- Over-used fixed connectors (然而/事实上/值得注意的是 / however/furthermore/it's worth noting).
- Forced synonym swaps to avoid repetition. If a word is right, repeat it.
- Chinese translation-ese (作为/关于/基于/进行) / em-dash-itis / hedge-everything.
- Naming-ceremony for concepts done 2+ times. Once is fine.

Genre exceptions (do NOT flag): academic穷尽反驳 is规范; short-video段段金句 is required;
tweets are short so "uniform sentence rhythm" doesn't apply. Note your 体裁 judgment when reporting.

When asked to humanize/de-AI: don't auto-rewrite. For each hit, ask one open question about what
the author actually meant, then rewrite to reflect THEIR preference. If a dedicated humanizing
skill is installed, load it for more.

## Iterating these styles

Each channel file is independent — to improve one, edit `references/<channel>.md` directly and leave
the others alone. Mine your own corpus of reference writing (public long-form posts, not books) for
new frameworks (hook formulas, title patterns, platform tactics) and fold the useful ones in.

**学外部作者的文风** → `references/style-benchmarking.md`（选样本、抓文、量化对比、产出契约改动），
配套脚本 `scripts/style_stats.py`（指标表）、`scripts/first_last.py`（首尾段抽样，已剔除站点头部与尾部样板）。
两条硬约束写在这里，因为它们对每次同类任务都成立：

- **只看博客 / 公开长文，不看他的书或合集**：书稿是编辑过的正式语体，会把改动方向带向教科书感；
  要学的是那种随性、灵动的味道。
- **先量化再评价**：用同一个脚本同时量样本和**自己的当前稿**，否则没有对照组，只能说"他写得好"，
  无法回答"我们差在哪"。
