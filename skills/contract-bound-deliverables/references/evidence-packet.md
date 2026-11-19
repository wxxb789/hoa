# Evidence packet, QA script, and assembly script

Concrete shapes for steps 2, 4 and 5 of the parent skill. Adapt names; keep the sections.

## Packet outline (the only permitted writing input)

```
# Evidence packet — <deliverable>, frozen <version>

## Contract
- Length: <range> characters, counted as: <verbatim measuring rule>
- Schema: <section list with required numbering>
- References: <= N entries, format <...>
- Red lines: <phrases/conclusions that must not appear>

## Domain evidence (one block per required section)
- Claim: <what may be asserted>
- Backing: <source id> — "<short verbatim quote>" (page/section)
- Maturity: installed | prototype | trial | demonstrated | unknown
- Allowed numbers: <exact figures that may be cited, with units and date>

## Cross-cutting constraints
- <constraints that apply to every section>

## Do not use (unverifiable, widely circulated, or model-invented)
- <claim> — reason: <not in any primary source | only in secondary retellings | superseded>

## References (numbered, matching the citation markers used in prose)
1. <author>. <title>. <id/date>. <url if no id>
```

Keep the packet's reference numbering identical to the prose citation markers; a numbering drift is
the most common mechanical failure.

## QA script check list

Write one script (`DELIVERABLE_QA_SCRIPT`), run it over every draft and the final, print one line per
file:

- `chars_contract` — count using the contract's verbatim rule, and `in_range` against the range.
- `cites` — distinct citation markers found, vs the required count.
- `unbacked` — every number in the prose not present in the packet (strip heading lines first, or
  section numbers like `4.1` are reported as unbacked numbers).
- `missing` — required sections/headings absent.
- `red` — banned phrases present.
- `refs` — reference entries parsed; accept both `1. Text` and `[1] Text` styles, since models mix
  them.

Report the raw counts in the reply, not a verdict. A file that fails one check is still useful
output; say which check failed.

## Assembly script shape

```python
SECTIONS = [("title", "..."), ("abstract", "..."), ("4.1 ...", "...")]

body = "".join(s for _, s in SECTIONS)
for name, s in SECTIONS:
    print(f"{name:24} {len(s)}")
print(f"TOTAL {len(body)} target {LO}-{HI} {'OK' if LO <= len(body) <= HI else 'OUT OF RANGE'}")
path.write_text(body, encoding="utf-8")
```

- Print per-section lengths on every run; trimming then has an immediate number attached.
- Write **no** header/metadata into the deliverable file — put provenance in a sidecar or here.
- After the build, confirm with `wc -m <file>` and compare against the printed total.

## 2. Freeze an evidence packet — one file, the only permitted input

- Gather sources, then distill them into a single packet (`DELIVERABLE_PACKET`): every claim that may
  appear, with the number/date/model/unit allowed to be cited, plus an explicit **do-not-use** list.
  See the packet outline and QA checks above.
- For multi-domain briefs, gather through resumable scripted routes: one themed query batch per
  sub-domain, a raw output plus a digest note each, skipping already-completed outputs so re-runs
  fetch only gaps; run slow batches in the background rather than serially in chat.
- Record provenance per source (origin, date, bytes, `sha256sum`) and **verify every recorded hash
  against the actual file with `sha256sum` before committing**. A copy-pasted hash in a provenance
  file is a silent integrity bug that downstream readers trust.
- When the evidence base is a **union** (a second research stream merged in, an accepted-claims
  set), state each source's evidence level and run the number-provenance QA against the union
  corpus — a summary-level item must not borrow the authority of a claim-level set just because
  both now live in one folder.
- Reject widely-circulated claims you cannot find in a primary source, and write the rejection into
  the packet so no later draft resurrects it. "Frequently repeated" is not evidence.
- Grade maturity honestly — installed vs prototype vs trial vs demonstrated. A negative claim ("no
  fielded system exists") needs the same primary support as a positive one.
- After the packet is frozen and drafts exist, later evidence never edits the packet: append an
  addendum plus a new verification-log batch (see `evidence-backed-analytical-writing` for the
  addendum discipline). The packet is the input those drafts already consumed; retro-editing it
  destroys the audit trail.
- When the owner changes a research constraint (recency window, source classes) after a round is
  delivered, version the chain instead of editing in place: new packet version, new draft
  filenames, new QA report; leave the earlier artifacts untouched as the audit trail.
- When later evidence is merged into a new delivered version, version the whole chain too: archive
  the previous final (`final-report-vN.md`), copy the frozen packet to `vN+1` appending only the
  increments, re-point the QA script's packet path at the new version, and re-run QA before writing
  the new final. Verifying against the old packet fails digit provenance for every newly added
  number.
- Keep **one driver per round** beside its outputs. When a new round reuses an existing driver,
  parameterize it (input packet, output tag, prompt log) rather than forking a near-copy — with
  default arguments that still reproduce the previous round byte-for-byte, so the old round stays
  reproducible. After generalizing any version→path mapping, push the *previous* version through it
  as a regression check: a mapping that resolves `v02` to `-v02.md` when the file is `-v2.md` breaks
  the older round silently while the new one looks fine.
- If the version series skips a number (no `draft-v03` because that packet fed an editorial merge
  rather than a model round), record the reason in the project's recording rules. Otherwise a later
  reader hunts for a round that never existed, or assumes it was lost.

## Draft comparison and citation adoption

- Give every model the same packet and schema; forbid anything outside it.
- Name every draft so provider+model is unambiguous in the filename (gateway and model id, not just
  the model family) — the owner compares drafts side by side and must map file → model instantly.
- Score drafts on: unbacked numbers, invented specifics (designations, serial/hull IDs, dates absent
  from the packet), citation-marker compliance, section numbering, banned wording.
- Take the skeleton from the most disciplined draft; graft details from others only after checking
  each against the packet. Good prose never outranks discipline — an attractive fabricated detail is
  the most expensive kind of error.
- **Audit which evidence a draft adopted by its citation marker, not by topic keywords.** A model
  can cite a source without repeating the vocabulary you chose for it (it cites `[n]` while writing
  "multi-source energy supply" rather than your packet's wording), so a keyword grep produces false
  negatives. You will report "N of 5 drafts ignored this evidence" and be wrong. Match the citation
  number/id first, then read the surrounding sentence to see how the source was actually used, and
  only then state an adoption rate to the owner.

## 4. Assemble to the number; never re-prompt for it

Single-shot generation does not hit a hard length budget, and re-prompting burns rounds. Build the
deliverable instead:

- **Scope: this applies to the assembled final, not to raw model drafts.** When the contract keeps
  drafts as unedited model output so each one stays attributable to its model, rewriting a draft to
  hit the range is a contract violation — an auto-correct loop (generate → measure → rewrite → retry)
  silently converts an audit artifact into your own prose and destroys the multi-model comparison.
  Constrain length in the prompt, verify with the QA script, and fit the number only in the
  editorial merge into the final; the drafts stay as they came out, overshoot included. If the owner
  asks for a *checked* draft that itself meets the range, keep the raw output as its own receipt and
  apply bounded *model-side* passes (re-prompt the same model to expand or trim with every citation,
  evidence ceiling and condition frozen) — the prohibition is on the host rewriting the model's only
  copy, which is what destroys attribution.
- One string per section in a small build script that prints each section's length and the total,
  then writes the file. Trimming becomes a per-section edit against an immediate number.
- Keep non-deliverable metadata (provenance/generation headers, HTML comments) **out of the
  deliverable file**. When acceptance is "the file's character count", an in-file header silently
  inflates it past the contract. Put metadata in a sidecar README or in the build script.
- For a draft that already exists as one long file, trim it with a batch of exact `old → new`
  replacements applied by a single script that asserts each `old` string occurs **exactly once**
  and writes only after every replacement matched (all-or-nothing). A partial application
  silently corrupts the text; assert-first turns that into a clean failure.
- Cut the least load-bearing text first when fitting the budget: reference titles may compress,
  but report numbers, URLs and dates are the handles that keep entries traceable — never drop
  them. Log what was cut in the sidecar, not in the deliverable.

## 5. Verify with the contract's own metric, then independently

- Compute the count using the contract's exact wording. "Total characters including title, headings,
  citation markers and references" is **not** "body text with citation markers stripped" — the proxy
  differs by tens of characters and flips pass/fail.
- **Invoke the project's own measuring script; never reimplement the metric.** A private
  reimplementation is a *different count*, not a cross-check. It can invert the result: optimizing a
  deliverable against a private metric can push every compliant artifact out of range while your own
  report reads as passing. If you have already measured with a private metric, re-measure under the
  authoritative one and discard the private numbers rather than trying to reconcile them.
- **Re-measure the existing artifacts under the authoritative metric *before* optimizing.** A bound
  added mid-project ("must also exceed N") is frequently already satisfied; a regeneration round run
  without that check burns rounds and can leave previously compliant artifacts non-compliant.
- Re-measure the written file with an independent tool (`wc -m`) instead of trusting your own
  script's arithmetic, and report the measured number — never "about N".
- **Name the proof level.** Provisioned (config/files exist), probed (an identity or model echo
  answered), accepted (the real path ran and the artifact met its gate). A green config/drift check
  plus `reply with exactly: OK` is provisioning; reporting it as "verified" overstates the evidence
  and forces a correction later.
- Mechanize the rest of the contract into a QA script: length range, citation-marker count, every
  number in the prose found in the packet, missing sections, banned phrases. Run it over every draft
  *and* the final, and keep the report as evidence.
- Both ends of a length range are gates: a floor can appear mid-project (a short report that must
  also stay near the cap), and a script that checks only the cap passes an undershot report. While
  trimming to fit, stop before crossing the floor.
- Treat the QA script as shared tooling: if the owner or another session tightens it while you work
  (new bounds or checks), re-run it against your artifact and adopt the stricter gate — a pass under
  the older script is not a pass. When the final's citation style changes to simple sourcing, invert
  the marker check into a no-marker-residue check instead of dropping it.
- When a check flags verbatim-captured source text (`git diff --check` whitespace warnings inside
  extracted source), document it as a known exception — never reformat captured sources to silence
  a check.
