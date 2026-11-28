# Decision brief — one artifact for a multi-question round

The brief is the **reference** the owner can reopen; the form is the **collection** surface. Build both
from the same numbered list, never two slightly different ones.

## When

- More than ~5 questions, several roots, or a round the owner will answer over hours rather than in one
  sitting.
- The owner asks for "advantages and disadvantages of each option" — that does not fit a chat message,
  and a form's choice labels cannot carry it.
- The decisions will be re-read later (contract activation, config change, purchase or privacy
  boundary).

## Shape — one self-contained HTML file

House style from `html-artifact` (tokens, serif headings, mono labels). Structure that works:

1. **Eyebrow + title** naming scope and goal ids, then a lede that says in one sentence what these
   decisions cost if chosen wrongly.
2. **One section per root**, each with a mono tag (`0009 · assessment`) and a heading phrased as the
   concern ("测评口径：真实考试长什么样").
3. **One card per question**: mono `Q3 / holdout floor`, the question as an `h3`, a two-line context
   paragraph naming the fact that makes it real, then the options.
4. **Option rows**: letter column + option name, then `优 …` and `劣 …` lines. The recommended option
   gets a `推荐` badge and the card a clay left border. Colour the labels (olive for 优, rust for 劣)
   with `::before` content so the scan is vertical, not a paragraph read.
5. **A verdict line per card** — "我的建议" plus the reason, and what would change it ("B 已包含 A，将来
   查到真实规格改两个 flag 即可").
6. **A closing answer block** in a dark panel with two copy-paste examples: "全按推荐" and `Q1 A …` /
   `Q2 B …` lines. This is the export — no JS needed.

## Rules

- Every option appears in both the brief and the form with the same letter; a letter that means
  different things in the two surfaces is worse than no brief.
- Prefer a flag over a constant when the unknown is a number the owner may learn later — then the
  recommendation can say "changing two arguments is not a code change".
- Cards must be re-readable on a phone: 820–900px page width, one column, no table that needs
  horizontal scroll.
- Verify numerically before reporting the path: `document.documentElement.scrollWidth <=
  window.innerWidth` (no horizontal overflow) plus a screenshot of the first card, because the 优/劣
  rows are where text wraps and overlaps.
- Report the artifact path in the same message as the first form, not instead of it.

## Thread-delivered rounds — Markdown brief, prose messages

When the round lands in a task thread the owner reads and answers in, and he answers by letter (`Q2 A`),
the brief is a **Markdown** file in the round's task directory — not the HTML artifact above. Discord
renders neither tables nor the HTML niceties, so keep the HTML shape for rounds he opens himself.

- One numbered block per question: 现状 with its evidence paths and `data_as_of`, then each option with
  `优`/`劣`, then the recommended letter and the rollback in one clause. Size a block so two of them fit
  one Discord message.
- Post the round into the thread yourself through the channel's REST helper
  (`discord-forum-post.py comment <thread_id> …`), splitting at question boundaries, then prove the tail
  arrived by fetching the **message object** over the API and checking its length plus the last question's
  title. Do not use the helper's own `read` action as that proof: it caps every message's content at 1200
  characters for display, so a complete 1500-character post and a genuinely truncated one look identical in
  the preview (the script truncates at `[:1200]`; the API returns the whole `content`). Measure with `len()`
  on the string, not `wc -c`: CJK runs about three bytes per character, so a byte count says nothing about
  the 2000-code-point limit (limits and the Components V2 alternative → skill `discord-rich-message`).
- Carry an answer table (`| # | 题面 | 答案 | 落账位置 |`) from the start and fill it as letters arrive;
  the ledger write is still the contract, the table is the visible audit.
- State once, in the first message, which shape is in force and why (prose rather than widgets), so a
  missing form is not read as a dropped question.

## Map before the chain — "what am I unsure about, and what needs your decision, top-down"

When the request is "think top-down through everything you are unsure about and everything I have to decide,
then ask me one at a time", the first message is a **map**, not the first question. Three blocks, in this
order, posted to the durable thread:

1. **已裁定 / already decided — not re-asked.** Read the task's append-only decision ledger (plus the plan of
   record) and list the closed items one per line with their ledger ids. He hates re-deciding what he already
   settled; this block is the proof you checked instead of asking from memory, and it is what keeps the live
   round short enough to answer.
2. **Open, ordered by dependency.** Number + title + one clause on why it sits there. Mark which one is the
   **blocker** (its answer changes what the later questions even ask, so it goes first) and which are
   mutually independent (asked in order, but no answer of theirs is needed to price the next). Name the
   chain rule in one line: one question per turn, next one after the current answer.
3. **Premises, measured now.** The numbers each question's options rest on, measured in this turn — a version
   that drifted under the artifact, the CI matrix the option would have to extend, whether a binary or SDK
   the option assumes is even installed, spend to date. An option priced from memory gets re-argued the
   moment the answer meets the data; a number measured here is quoted by the option and settles it.

Then send question 1 alone (form, or an in-thread message answerable by number), and say that the rest are
queued behind it. Keep the map in the durable surface, not in the widget: the map outlives the chain, so a
later reader can see which questions were open and which he had already decided.
