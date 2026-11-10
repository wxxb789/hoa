---
name: contract-bound-deliverables
description: >-
  Produce a deliverable against an explicit, measurable contract — a length budget, citation
  discipline, required section numbering. Freeze the evidence packet first, draft in parallel
  against it, assemble to the number instead of re-prompting, verify with the contract's own
  measuring rule, then publish the artifact and its evidence. Use when acceptance is countable.
  Not for open-ended prose whose quality is the only gate, and not for auditing a report already
  delivered.
metadata:
  version: "0.1.21"
  areas: "work-management,software-development"
  targets: "runtime-agnostic"
---

# Contract-bound deliverables

Use when a brief specifies measurable acceptance — a character/word budget, a citation discipline,
a required section numbering — rather than "write something good". The spine is: fix the evidence
first, draft in parallel against it, assemble to the number, verify with the contract's own wording,
then publish cleanly.

## 0. Pre-flight: find the owning project, and check who else is writing in it

- **Locate the project that already owns the topic before creating one.** Search the target
  repo/workspace for an existing project on the same topic (search on topic keywords, recent commit
  history, the repo's index/registry) and read its README and plan. Building a parallel tree in a
  scratch workspace for work a governed repo already owns produces a duplicate that cannot merge
  cleanly and wastes the entire round.
- **Check for a concurrent writer before editing a shared project.** Another agent session may be
  editing the same files right now. Detect it with
  `find <project> -type f -newermt '-${DELIVERABLE_WRITER_WINDOW_MINUTES:-10} minutes'` (files
  touched during your session that you did not touch) and `git status -s` (untracked files appearing
  mid-session that you did not create). A file whose mtime moved but that `git status` reports clean
  was rewritten with identical bytes — still evidence of another writer.
- **On detecting one: stop writing into that project, do not commit, and report.** Shared-repo
  edits are sequential; two writers on the same files lose work silently. Read the other session's
  newest commit message first — it may explicitly hand you a file to commit, or state that it
  already absorbed your edit.
- **Moving work out of a scratch workspace into the owning project: audit before deleting.** Walk
  the duplicate tree file by file and classify each item as migrated or superseded by a named
  artifact in the owning project; confirm nothing outside the tree references it and no process is
  still writing to it; only then delete, and remove the now-empty date/scratch directory too.
  Deleting on the assumption that "it is all in the repo now" loses exactly the one file you did
  not migrate. Also check what the duplicate encoded: a tool that automates a workflow the project's
  contract rejects (for example, a length-fitting loop over raw drafts) must not be migrated at all.

## 1. Read the acceptance rule before writing a word

- Copy the contract's measuring rule verbatim into your plan: what is counted, what is *included*
  (title? headings? citation markers? reference list?), and the allowed range.
- Note whether the contract names its own authority (for example, "the character count of the file as
  a plain text editor shows it"). That decides the counting convention in step 5.
- **Take the recency window from the owning project, not from the brief's prose.** A brief saying
  "no material older than N years" may have been tightened by the project after earlier rounds (a
  stricter floor, a different start month). Read the project plan's current window and conform to
  the stricter reading. A retrieval round run under the looser interpretation is inadmissible and
  has to be re-run, and its out-of-window hits must be recorded as excluded — not silently dropped,
  and never left in the evidence map where a later draft can cite them.
- Fix the required section schema and numbering up front. Models invent their own numbering and it
  is expensive to retrofit.

## 2. Freeze an evidence packet — one file, the only permitted input

- Gather sources, then distill them into a single packet (`DELIVERABLE_PACKET`): every claim that may
  appear, with the number/date/model/unit allowed to be cited, plus an explicit **do-not-use** list.
  Packet outline and QA checks: [`references/evidence-packet.md`](references/evidence-packet.md).
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

## 3. Draft in parallel from that packet, judge by discipline

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

### 3b. Adding a model that is not in the frozen registry

The owner will name a model to add to the comparison. Route it through the project's own registry;
never silently substitute a reachable model for the named one, and never hand-write "that model's"
draft yourself.

- **A new model needs a new versioned registry, not an edit to the frozen one.** Copy the project
  registry to `providers-vN+1.json`, add the entry, and leave the previous version file intact — the
  earlier drafts must stay reproducible against the registry that produced them.
- **Resolve the model→gateway mapping from the agent config before pronouncing a model unavailable.**
  The agent config (`DELIVERABLE_AGENT_CONFIG`, default `$XDG_CONFIG_HOME/<agent>/config.yaml`) may
  expose a named provider (with a `key_env`) that is absent from the local proxy's `/v1/models`
  list — a missing proxy listing means "not on the proxy", not "unavailable". Registry entries carry
  `key_env` (an environment-variable *name*), never an inline secret.
- **Run and keep an identity/effort preflight for every newly added model.** Send a trivial request
  at `effort=high`, and record the returned model id, whether the effort field was accepted, and
  reasoning tokens > 0; also record the standing caveat that the gateway echoing your request is not
  proof of the provider's internal effort mapping.
- **For "learn the context first, then write", use a multi-turn call.** These transports are
  stateless single-request endpoints: re-send the full frozen packet in *each* call's message array
  and carry the model's learn reply as the preceding assistant turn. A separate one-shot "learn"
  call that is not carried into the write call teaches the model nothing.
- **Label provenance when the only available path is direct authoring.** If the named model cannot
  be reached and you write the draft yourself, name the file for the real author and mark it
  direct-authored (no generation receipt) — never file your own prose under the requested model's
  name.

Supporting depth (registry schema, transport quirks, preflight shape, two-phase message layout):
[`references/model-generation-harness.md`](references/model-generation-harness.md).

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

Assembly-script shape: [`references/evidence-packet.md`](references/evidence-packet.md).

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

## 6. Publish the deliverable and its evidence

- Stage explicit paths; never blanket-stage, and keep unrelated working-tree changes out.
- **Treat commit and push as separate authorization gates.** Authorization to write commits does not
  extend to publishing them; wait for an explicit push instruction and do not infer it from "the work
  is done". Before pushing to a shared branch, `git fetch` and confirm
  `git log --oneline origin/<branch>..HEAD` is a clean fast-forward with no divergence. Never force.
  If the remote moved, report the divergence instead of pushing over another writer's commits.
- **A private repo answers an unauthenticated raw fetch with 404**, which is indistinguishable from
  a failed push. Verify the remote by SHA (`git ls-remote origin refs/heads/<branch>` compared against
  your local `HEAD`) and read files back through the authenticated API
  (`gh api repos/<owner>/<repo>/contents/<path>?ref=<branch>`, base64-decoding `.content`) — never
  conclude a push failed, or succeeded, from a raw link.
- **Before committing any binary, ask the repo what it does with that extension.** If
  `.gitattributes` routes it through Git LFS and the `git lfs` client is unavailable, `git add`
  writes the full blob into ordinary history — irreversible once pushed. Confirm with
  `git cat-file -p HEAD:<an already-tracked file of that type>` (an LFS pointer reads
  `version https://git-lfs.github.com/spec/v1`) and `command -v git-lfs`. When the client is
  missing: leave the binaries out, exclude the exact paths in `.git/info/exclude` (local,
  uncommitted, reversible, and it keeps `git status` clean for downstream automation), keep the files
  on disk, and record the retention decision plus each `sha256sum` in the provenance file. Report it
  as a known limitation instead of silently dropping artifacts.
- `git ls-files | grep '\.pdf$'` lies about what a repo tracks: git C-quotes paths containing
  non-ASCII bytes, so those lines end in a quote and the `$` anchor never matches. Use
  `git ls-files -z | xargs -0 ...` or drop the anchor.
- Read back every external write. Re-fetch a PR/issue body after creating it (a successful create
  call is not proof the body landed), and re-measure a written file rather than assuming.

## Pitfalls

- Treating a length target as a style preference. It is a gate; unverified means unfinished.
- Optimizing against a private proxy metric instead of the project's measuring script. The proxy can
  invert pass/fail, so the "fix" round makes compliant artifacts non-compliant while the report
  claims success.
- Letting one model's plausible addition into the final because it reads well.
- Measuring the deliverable file after leaving generation metadata inside it.
- Forcing a binary into git "just this once" when the repo's LFS client is unavailable.
- Reporting a length or citation result from an earlier build after re-editing the text.
- Re-running integrity hashes or the full verification loop on unchanged files between steps.
  Hash once where it decides something, batch edits, verify the final once — repeated
  re-confirmation reads as stalling and the owner will say so.
- Committing a regenerated artifact whose only diff is its timestamp. Deterministic generators
  (QA reports, lint reports) stamp the run time on every invocation; `git diff` them before staging
  and revert the ones whose only change is the stamp, so the round's commit carries substance only.
- Concluding a push failed because an unauthenticated raw fetch of a private repo returned 404.
  Confirm by remote SHA and authenticated read-back; a private repo's 404 says nothing about whether
  the push landed.
- Declaring a named model unavailable because it is not in the local proxy's model list. Check the
  agent config's named providers and aliases first — a configured gateway can serve it.
- Filing your own prose as the requested model's draft. It destroys the multi-model comparison the
  round exists to produce; if you must author it directly, label it direct-authored.
- Treating a gateway 504 on a long generation as a model failure and abandoning the round. These
  gateways 504 on a large `max_tokens`; retry with a lower cap. Run the long write as a background
  job with completion notification instead of blocking the session on a call that can run many
  minutes.
- Treating a non-streaming long generation's read timeout as a model failure. A reasoning write can go
  silent for tens of minutes and fail with an empty result and no terminal event, not an HTTP error;
  dropping `max_tokens` does not fix it. Retry with `stream=true` and accumulate the deltas.

## Supporting files

- `references/evidence-packet.md` — packet outline, do-not-use list, QA-script check list, and the
  assembly-script shape.
- `references/search-route-batching.md` — fanning themed search routes out in parallel, saving raw
  output per route, and enforcing a recency window against a relevance-ranked search tool.
- `references/model-generation-harness.md` — provider-registry schema, transport quirks (including
  streaming a long write that would otherwise read-timeout), the identity/effort preflight shape, the
  two-phase learn→write message layout, and the generator's retry/background rules.

## Configuration

| Key | Env | Default |
|---|---|---|
| `project_root` | `DELIVERABLE_PROJECT_ROOT` | current working tree |
| `writer_window_minutes` | `DELIVERABLE_WRITER_WINDOW_MINUTES` | `10` — concurrent-writer mtime window |
| `packet` | `DELIVERABLE_PACKET` | none — the frozen packet path |
| `registry` | `DELIVERABLE_REGISTRY` | none — the project's versioned provider registry |
| `harness_dir` | `DELIVERABLE_HARNESS_DIR` | `<project>/.harness` |
| `qa_script` | `DELIVERABLE_QA_SCRIPT` | none — the project's own measuring/QA script |
| `measure_command` | `DELIVERABLE_MEASURE_CMD` | none — the contract's authoritative count |
| `agent_config` | `DELIVERABLE_AGENT_CONFIG` | `$XDG_CONFIG_HOME/<agent>/config.yaml` |
| `search_workers` | `DELIVERABLE_SEARCH_WORKERS` | `4` |
| `search_max_tokens` | `DELIVERABLE_SEARCH_MAX_TOKENS` | `8000` |
| `search_timeout_s` | `DELIVERABLE_SEARCH_TIMEOUT_S` | `260` |
| `search_limit` | `DELIVERABLE_SEARCH_LIMIT` | `10` |
| `draft_token_cap` | `DELIVERABLE_DRAFT_TOKEN_CAP` | `16000` — lower it on a 504 |
| `stream_idle_timeout_s` | `DELIVERABLE_STREAM_IDLE_TIMEOUT_S` | `300` |

Read `$XDG_CONFIG_HOME/contract-bound-deliverables/config.yaml` (fallback `~/.config/...`) when
present; a flag or env var overrides the file. Per-project values — packet path, registry, QA script,
measuring rule — belong in a project profile, not in this protocol.
