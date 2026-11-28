# Adjudicating a consult answer

A consult is a diagnosis, not a spec. Before anything is dispatched on it, re-derive every claim that
decides the fork against the tree, in one pass, and write the result down.

## Artefact shape

`adjudication.md` in the run dir, beside the raw answer:

- header: lane, model, effort, tools or closed-book, byte count, exit code, and the tree revision the lane read;
- table: `# | claim (short) | verdict | evidence` where evidence is the command or `file:line` re-derived on
  the host, not the lane's citation;
- what the adjudication changes: which claims the fork rests on, what was corrected;
- the classification adopted in one line, with its deciding evidence.

## Three verdicts, and what each does

- **confirmed** — re-derived on the host. Quote it as verified in the owner's report.
- **refuted or imprecise** — the substance holds but a detail is wrong (a line number, a count, "one row"
  that is two). Keep the claim, record the correction, and **report it to the owner alongside the fork**.
- **unproven** — could not be re-derived (symbol absent from the file, no such key in the source). Say so
  plainly, and state whether the fork depends on it; if it does not, say that too, and never carry it as
  supporting evidence.

A refuted or unproven claim sinks the diagnosis only if the fork rests on it. Do not drop corrections to make
 the report cleaner — that is how a diagnosis decays into a quotation.

## Claim type → how to check it

| Claim | Check |
|---|---|
| "class/function `X` at line `N` does `Y`" | `grep -n '<symbol>' <file>`. **Check the symbol, never re-quote the line number** — a tools lane's substance holds while its line numbers drift by a few to a dozen lines |
| "the repo's own rule already forbids this" | Read the rule verbatim from the file it names and quote the clause. A repo's written rule is the strongest evidence in play and outranks the model's opinion |
| "the apparatus is `M` lines / `N` tests" | `wc -l`, count the tests. Sizes stated in prose are approximate |
| "one row" / "`K` rounds" / "`J` PRs" | Recompute from the artefact or the tracker. Denominators are often the finding (a data table of 2 rows under 86 lines of prose), so get the numbers exactly right |
| "a duplicate implementation of `Y` exists" | Locate both owners, confirm both are live on the shipped path, and name which one a future change would have to touch twice |
| "same-class sites are still live at head" | Grep each named symbol at head. **This is the bound's evidence**: one live site plus one greppable gap justifies "another round will find more" |
| "this increment produced zero product lines" | Diff the increment against its base and count lines outside tests and harness |
| history ("that attempt ran `K` rounds") | Query the tracker; the ancestry often knows contributions the answerer did not have |

## Rules

- Adjudicate **before** dispatching, and never dispatch an implementation round while the answer is in
  flight — a round started on a recipe locks the framing in.
- Adopt the classification ("abstraction-boundary failure, bound = unbounded") only after its evidence is
  re-derived; the prose classification is a claim like any other.
- Carry the lane's **strongest argument against its own recommendation** into the owner's round together with
  the evidence that settles it. A fork presented only with supporting evidence is advocacy.
- Owner-facing shape: diagnosis in one or two sentences, the decisive rule and verdict, the fork with costs,
  your recommendation, the strongest objection with its settlement, and what you verified that the answer got
  wrong.
