# The design consult (a draft design, not a defect)

The same lane as the root-cause consult answers a second question — *is this design right?* — asked about a
proposal (a goal file, a plan, an interface, a contract change) **before** the owner is asked to decide it,
sometimes because the owner required exactly that order ("have the proposal read by <model>, integrate what it
says, then bring it to me for approval"). Keep the shapes apart: a defect consult asks for a root cause, a
design consult asks for a position, so it must also demand the argument *against* that position.

## Prompt shape that produces a usable answer

- Attach the draft itself as a file (`@<draft>.md`) plus a **separate question file** naming exactly what to
  judge: each decision point's option set, and the questions you cannot settle yourself. Option sets written
  inline on the command line are not re-runnable and cannot be diffed against the next round.
- Ask per question for **the position, the strongest argument against that position, and what evidence would
  settle it.** An answer without its own counter-argument is a vote, and a vote cannot be adjudicated.
- Ask it to name **which of your questions is the real one** and why the others are downstream. The order you
  wrote them in is rarely the dependency order, and the real question usually collapses two of yours.
- Have it **attack the draft against the repository's own binding rules** (point it at the repo's operating
  contract, the core-design notes, the conventions) instead of against general taste — a design review that
  cites no file is an opinion.
- **When the owner asks for options, demand exactly N *distinct* schemes** — a different philosophy each,
  not three shades of one — and for every scheme: a one-line thesis, the structural change, a mapping of the
  fix to each problem, cost/risk/what it gives up, when to prefer it, and a migration path. Give the problems
  **short IDs** in the brief (A1, B2, …) so the mapping is checkable and the next round diffable, and close by
  asking for a ranked verdict plus the single highest-leverage choice — an unranked scheme set is raw material
  labelled as a menu.
- Give it read-only tools (`--tools read,grep,find,ls`) and state in the prompt that you will re-derive every
  claim before adopting it. Advice, not a spec: the decision stays with the owner.
- **Smoke-test the channel with a one-line probe before dispatching the long consult.** A misrouted provider
  or model id fails identically on the real prompt but costs the whole timeout; the probe costs seconds and
  prints its own verdict, which is what you report as "the channel works".
  Read the probe's failure for what it is, and do not re-derive the id: a "not found for provider" is a missing
  **catalog row** (the harness's own catalog, not the proxy's — restart the proxy for a stale one, add the row
  when it is absent), while an HTTP 400 naming an endpoint ("… does not support the responses endpoint") is a
  **transport** mismatch — the model exists but not on the transport the harness picked, so switch model inside
  the same provider. A catalog lists existence, never transport.

## Across several rounds of the same design

**The lane is stateless — restate the settled design in every brief.** A consult lane has no memory of its
earlier answers (number the rounds #1, #2 … so "no memory of #N" is unambiguous), so each brief must re-carry
the decision reached so far; a brief that assumes continuity gets an answer to a design you are no longer
building. Close the pre-build round with a **gap check**: hand the lane your own numbered candidate gaps and
ask it to confirm / refute / refine each, name any you missed, give a **GO / NO-GO plus the one thing to
settle first**, and the minimal ordered first steps each with a one-line "done means". Then **verify the
lane's blocking claims on the host before you accept the verdict** — a NO-GO is usually one cheap probe (does
the sandbox actually run here? can the tool actually be withheld here?), and the probe's result, not the
opinion, is what flips it to GO.

Then **integrate, and only then ask the owner**: the consult's option set is raw material for the round
(options, costs, your recommendation), never the owner's menu and never his answer. The round's own shape
lives in `owner-decision-requests`.
