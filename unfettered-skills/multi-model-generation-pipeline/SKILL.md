---
name: multi-model-generation-pipeline
description: Use when several models must produce one verified result.
version: "0.1.1"
license: MIT
metadata:
  version: "0.1.1"
  areas: "work-management,software-development"
  targets: "runtime-agnostic"
  summary: "parallel model candidates → enumerated audit → one revision round → gated selection"
  kind: "mechanism"
  hermes:
    tags: [multi-model, audit, selection, headless-generation]
    related_skills: [writing, delegated-work-acceptance, omp-headless-orchestration]
---

# Multi-model generation pipeline

One task, N models, one deliverable you can defend. The load-bearing parts are the rubric and the gates;
the models are interchangeable.

## When to Use

- The deliverable goes out under your name and a wrong number or a fabricated sentence would cost more
  than the run.
- You want a second and third model's eyes on text one model wrote, and the comparison has to end in a
  single answer rather than a pile of opinions.
- A headless generation step must be made safe to automate: byte checks, a parseable verdict, a gate that
  a failure cannot slip through.
- Not for prose-level style rules — that contract lives in `writing` (per-channel references).
- Not for steering one interactive agent through a task. This is batch generation plus adjudication.

## Division of labour (default on this machine)

- **Authoring: one model, three rounds** — first draft → revision against a numbered list → targeted
  tightening. Structure and sentence rhythm are more stable than any tournament output.
- **Verification: the cross-model round** — a second and third model exist to catch what the author
  cannot see in its own text. Keep the roles apart; a model asked to both write and judge grades itself.
- **Effort**: every round that produces reader-facing text runs at the low reasoning setting, at any
  stage and for any model — high effort returns smoother, more uniformly machined prose. Audit rounds
  need no pinned level; what matters is that an auditor never rewrites the text it is judging.

## Procedure

1. **Compose one prompt per candidate, identical except the model.** Prepend the destination's style
   contract plus an explicit discipline header (the banned shapes, the quotas, the required hedge). Never
   ship a candidate a bare task statement: clean-context models obey only what is written down.
2. **Generate all candidates in the background**, one file each, named by model. Check every file's byte
   count before moving on (see "Empty artifact" below).
3. **Audit with an enumerated rubric**, one section per candidate, each item answerable yes/no. Require
   *actionable replacements* (which sentence, which paragraph) rather than adjectives like "could be
   tighter".
4. **One revision round, each candidate against its own section of the rubric**, nothing else changed.
   Never let the auditor's notes become the auditor's rewrite.
5. **Select**, then re-verify the selected file mechanically before it counts as delivered.

## The rubric must be gates, not prose

Starter rubric to copy and adapt: `templates/audit-rubric.md` (A provenance / B sources / C opening /
D stated uncertainty / E hard quotas, plus the `SELECTED:` / `UNSOURCED:` output block).

- A criterion written as "judge it against the contract" is scored by taste. The auditor will praise the
  exact shape the contract forbids (a promise-list opening read as "strong structure"). Name each banned
  shape explicitly and require a per-candidate yes/no.
- **Any candidate the auditor lists as fabricated, unsourced, or untraceable is disqualified**, not merely
  annotated. A report line that does not remove the candidate ships the sentence the auditor just
  flagged. If every candidate is flagged, delete those sentences and redo the comparison.
- Ask for a machine-readable verdict line (`SELECTED: <tag>`) and **exit non-zero when it will not
  parse**. Defaulting to the first candidate silently publishes the version nobody chose.
- Keep a fabrication column in the output: verbatim sentences that cannot be traced to the supplied
  material. It is the single most productive line in the whole report.

## Mechanical checks belong to your script

Auditors count wrong and will not run probes. After selection, check with your own tooling and print the
numbers next to the verdict:

- **Link liveness**: `curl -sL -o /dev/null -w '%{http_code}' --max-time 25 <url>`, and **retry a non-200
  once** — a first-attempt timeout is usually transient, and one attempt kills real sources. A 200 on a
  generic landing page is a connectivity pass and a citation-quality fail: report separately.
- **Structural quotas**: section count, links, over-length sentences, prose character count.
- Compare these against the model's self-assessment; when they disagree, the script wins.

## Empty artifact, and other silent successes

A headless model call can exit 0 having written **0 bytes** — the file exists, so every downstream step
accepts it. Two mechanisms produce it: the model decided to call a tool it does not have (check the
session log for a thinking-only assistant block), or the prompt file it was pointed at did not exist yet.
Retry with a guard line ("you have no tools, never say you will look something up, write 'uncertain'
when unsure, output only the body") and then a heterogeneous fallback model. Never let zero bytes flow on
as content, and never diagnose it as an upstream outage before checking the session log.

## A long lane must outlive the orchestrator

- **Launch the lane detached, never as a child of the agent's own shell.** A call started from the
  agent's command runner dies with that runner — a gateway restart mid-run leaves a one-line
  `Request aborted` in the answer file that reads exactly like a model or provider failure. Use the
  host's supervisor (`systemd-run --user --collect --unit=<name> /bin/bash -lc '<cli> … > answer.md 2>&1'`),
  then poll the unit. The lane then finishes whether or not the conversation survives.
- **Declare the unit's working directory, `PATH` and the two output streams explicitly.**
  `--property=WorkingDirectory=<tree>` pins the lane to the tree it must read (an audit lane reads the
  committed tree, not wherever the launcher happened to stand); `--setenv=PATH=<shim dir>:/usr/local/bin:/usr/bin:/bin`
  is required because a non-interactive unit never sources the shell rc, so a shim-resolved CLI is simply
  absent and the unit dies with `command not found`; and use
  `--property=StandardOutput=append:<answer.md> --property=StandardError=append:<log>` instead of `> answer.md 2>&1`
  inside the command string, so the harness's own errors (provider 400s, retry lines, thinking-only notes)
  never land in the artifact you are about to grade. Poll with `systemctl --user is-active <unit>`; before
  reusing a unit name after a failed run, `systemctl --user reset-failed <unit>`.
- **A 0-byte answer file is not a verdict while the lane runs.** These CLIs buffer the whole response and
  write once at exit, so a live lane legitimately shows nothing for minutes. Decide by the unit's state:
  active + 0 bytes = still running (wait); inactive + 0 bytes = exited empty (the section above);
  inactive + bytes = read it. Diagnosing by file size alone either kills a healthy run or waits on a dead
  one.
- **A lane launched from your own runner has no unit state, so elapsed wall-clock is its only verdict.**
  Give it a declared budget before starting (the prompt size is a known factor: a long composite prompt can
  run 30+ minutes with a still-empty file), and on expiry kill it and reroute the same role to a
  heterogeneous model rather than restarting the same lane — a second identical attempt on an expired budget
  burns the same hour twice.
- **Read the CLI's own session log when the answer is empty or truncated.** A tool-calling lane that died
  mid-way leaves the assistant/toolResult records there; that log distinguishes "provider error", "the
  model stopped after N tool calls" and "the model answered nothing" — three causes with three fixes.
- **A lane that died after N tool calls is a scope problem, not an outage.** When the log ends on tool
  calls with no assistant text, rerun a *narrower* prompt (fewer subjects, fewer files, one question)
  rather than resubmitting the same one: breadth x tool count is what ran out, and the same prompt tends
  to die at the same point. Resubmitting once is a fair transient check; twice is a habit that burns an
  hour.

## Running one named model on this host

Every model id belongs to exactly ONE route, and the provider name encodes which. On this machine the same
GHC proxy host is mounted twice: `ghc-proxy-chat` (`openai-completions`) and `ghc-proxy`
(`openai-responses`), both at `http://localhost:4141/v1`. The mismatch surfaces as a 400, not as a missing
model: a responses-only id (the `gpt-6.1-*` family) on the chat sibling answers `… is not accessible via the
/chat/completions endpoint`, and a chat-only id on the responses sibling answers `The selected model does
not support the responses endpoint`. Both are provider-selection errors — never report them as "the model
is down".

Read the route from the catalog instead of remembering it: `~/.pi/agent/models.json` lists
`providers.<name>.api` plus the ids each provider serves, so pick the provider whose `api` matches the id,
then confirm with a one-word ping before spending the real prompt.

- One-shot shape (this host's CLI is `pi`):
  `pi --provider <chat-provider> --model <id> -p @prompt.md > answer.md 2>&1`.
- **Keep `pi`'s normal toolset; constrain read-only/research scope and output destination in the prompt, never by stripping tools (`--tools`, `-nt`, `--no-*`).** Stripping or narrowing the toolset confuses tool-trained models (they spiral in read-only loops or stall with 0 bytes on stdout instead of writing a report). Tell the model in the prompt that this is a read-only research/review task (not coding: do not modify repository files) and, if you want a file artifact, name the exact path it should write its conclusion to.
- **A lane that expires empty on a repo-reading prompt is a model/route fact, not a tool-set artifact.** Record the failing pair here before blaming the tools: one chat-route model wrote 0 bytes on the same composite review three times — twice with a narrowed toolset (34 min, 19 min, killed on budget) and once with the *full* toolset (10 min budget). Its session log showed 10 assistant turns and 31 tool results ending on an empty assistant record: it kept reading the repo and never converged. The sibling responses route's contemporaneous SOTA finished the identical prompt. When a lane dies this way, change model *and* route, and do not generalize "model X is broken" from the toolset-restricted variant alone.
- `--session-dir <dir> -n <lane-name>` keeps one lane's transcript separable from the others.
- Spend one call on a ping (`-p "reply with exactly: ok"`) before the real prompt: a provider/model
  mismatch fails on the first call either way, and finding it on a one-word prompt costs seconds.
- **A repo-aware consult lane that "hangs empty" is usually unbounded *verification* plus a buffered stdout, not a broken model or route.** Evidence that settles it in two calls: (1) probe the same model+route with one trivial tool call ("read `/etc/hostname`, reply with its contents") — if that answers, the plumbing is fine; (2) read the lane's session jsonl and count tool calls with their argument sets — dozens of **distinct** reads (`internal/*.go` at offsets, `rg` for symbols the draft cites) means productive exploration that the clock ran out on, while **repeated** identical calls would mean a retry loop. `gemini-4-carbon`/`ghc-proxy-chat` did 66 distinct reads in 900 s on a question whose own text said "check facts in the repository rather than trusting the draft"; `gpt-6.2-sol`/`ghc-proxy` self-bounded to a few spot checks and answered in ~10 min. Fixes, in this order: state a hard call budget and a stop rule in the prompt ("at most N tool calls, then write the review from what you have" — 6 asked, 4 used), require **incremental output** (append to a file, or `--mode json` streaming as `review-lane.py` does) so a timeout costs the tail rather than the whole run, and narrow the question. **Do not** "fix" it with `--tools`/`-nt`: the same failure reproduced with a narrowed tool set.
- **Do not pass the `--no-extensions --no-mcp --no-skills --no-context-files` bundle to a consult lane.** It is
  not a neutral "clean room": on this host `gemini-4-carbon` over `ghc-proxy-chat` stalls indefinitely with it —
  even on a one-word ping (41 s without the flags, no answer in 240 s with them) — while `gemini-4-argon` and
  `gpt-6.2-sol` are unaffected. It also removes the project grounding `pi` injects by default (`-nc` disables
  `AGENTS.md`/`CLAUDE.md` discovery); with the default setup and no tool calls at all, a lane can still name real
  files and identifiers from the repository it runs in. Keep the model's normal setup and constrain scope in the
  prompt instead.
- Pass the prompt as a file, not inline prose, so the exact bytes are re-runnable and diffable.

## Two independent lanes over one proposal

When the point is *independent* judgement rather than generation, the two lanes must not be able to see
each other and must be comparable afterwards.

- **Write one numbered question set and send the identical list to both lanes.** Divergent prompts produce
two essays you cannot diff; the numbered list is what lets you print them side by side and name the items
where they disagree.
- **Give both lanes the measured facts, not your prose about them.** Point the prompt at the raw scan/report
  file (counts, `path:line`) so each auditor argues from the same numbers and you can tell "wrong number"
  from "different judgement".
- **One detached worktree per lane** (`git worktree add --detach /tmp/<lane> HEAD`): an auditor told to stay
  read-only still gets a sandbox, so a lane that ignores the instruction cannot dirty the real tree. Remove
  the worktrees when the reports land. See `references/audit-lane-launch.md` for the full launch recipe.
- **Write the lane's header line yourself before launching**, so a 0-byte file is obviously "no output yet"
  rather than "the header I forgot to write".
- **Build the composite prompt with a script.** A quoted heredoc (`<<'EOF'`) expands nothing, so
  `$(cat prompt.md)` lands in the file as those literal characters and the lane audits your instructions
  instead of the plan. Compose with python, then verify the byte count and the first lines.
- **Do not drop a lane because its harness cannot authenticate.** Reroute the *same model* through another
  harness that already holds credentials (provider entry in the model catalog) and separately tell the owner
  the login command for the original harness. One working lane plus a named owner action beats one lane and
  a silent gap in the "two independent audits" the work was asked for.

## Verify the audit lane's citations before adopting anything

An audit lane reads code; it does not verify its own references. Pick two or three `path:line` claims per
report and open them. A lane that miscites its own evidence (a line range past the end of the file, a
count that does not match `wc -l`) has its *other* references re-read rather than trusted — while a lane
whose citations hold is worth acting on without re-deriving every one.

- Ask for one verdict per item plus the condition under which the opposite answer wins; "it depends" is a
  failed answer and gets sent back.
- Ask what can be **deleted**, and for one counter-example to any mechanical check ("a state that passes
  every check and is still wrong"). Those two questions turn an audit into a design change; without them
  you get a longer version of the proposal.
- Record the disposition of every item (adopt / adapt / reject + why) next to the plan. Re-planning after
  an audit drops items silently, and a dropped *adopt* is indistinguishable from one nobody read.


## Audit in rounds, and make each round answer a different question

One audit answers one question. A proposal that survived a defect review has not been asked whether it
should exist, and a protocol that reads well has not been compared with its own records.

1. **Defect round** — mechanical and design faults in the proposal as written (the rubric, the
   counter-example question and the citation check below belong here).
2. **Necessity round** — state the artifact's purpose in one sentence, then ask of every member: *would the
   thing fail without this, or is it a good practice that merely sounds related?* `Remove it` must be an
   allowed verdict and the strongest one available; a set of names that only makes the family look tidy is
   the failure this round exists to find. An earlier round's "already accepted" does not bind this round.
3. **Field round** — read the artifact's own operational records (ledger, run logs, PR list, CI history)
   instead of its documentation, and diff the two. A protocol whose records are empty has never been
   followed; a recorded value that lags the process it describes makes every resume point wrong. This is
   the cheap round — it needs reading, not model judgement — and it is the one that finds fiction.

Point every round at the same one-sentence purpose; when rounds disagree, the purpose wins, not the most
recent report.

## Before a lane's spec becomes a dispatch

A design lane sees only the packet you handed it, so adopting its spec verbatim gives an implementer
instructions that are wrong in ways the lane could not detect. Adjudicate in a file of its own that
*overrides* the spec, and make the implementer's prompt read that file first and lose to it on
contradiction — never edit the lane's own text; it is the provenance for what you changed.

- **Grep every symbol the spec names before believing it.** Functions, constants, flags, files: a spec
  that invents API is a rewrite, not a design, and the difference is one `grep -n '<name>' <target>` per
  name.
- **Reproduce each claimed defect yourself, from the cited lines at the cited line numbers.** A defect
  confirmed by reading is a requirement; one you did not confirm is a claim you will end up defending.
- **Before accepting any change to an artifact's *format*, grep the repo for that artifact's readers.**
  The lane was given one route and one packet; shipped plugins, sibling routes, archived contracts and
  the changelog also parse that file, and a silent format change breaks them. Prefer making the new
  authority *additive* — a fresh field inside the existing authoritative record — and leave the old
  surface readable in its existing shape, writing it after the new commit rather than before it.
- **State every deviation as a numbered override** (what the spec said, why it must not be done, what
  replaces it) so the implementer follows one precedence order instead of reconciling two documents.
- **A late second lane is a differential, not a gate.** Do not hold the dispatch for a slower lane; when
  it lands, diff it against the *adjudicated* spec rather than the first lane's raw draft, and file the
  disagreements as more overrides.

Then hand the adjudicated spec to the run: route choice, start verification, the completion watcher and
the scope-freezing prompt shape are in `references/dispatch-handoff.md`.

## Cost and when it is worth it

A four-round pipeline over a short piece is roughly eight calls and a couple of minutes; a long piece is
minutes more. Worth it when the deliverable is published under your name or when a wrong number would
cost more than the run. Not worth it for drafts you will rewrite by hand anyway.

## Pitfalls

- Letting the auditor write the revision: its notes are the input, the low-effort authoring round is the
  hand that edits.
- Treating the auditor's confidence as coverage: it checks what the rubric names, nothing else.
- Comparing candidates by length or by how complete they sound. The rubric's hard items decide.
- Skipping the revision round after a failed candidate list: every candidate gets the same chance under
  the corrected rubric, so the winner stays comparable.
