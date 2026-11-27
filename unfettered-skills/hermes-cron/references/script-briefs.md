# Script-generated briefs (0-LLM digests into a chat channel)

For a recurring brief whose content is "what arrived / changed since the last window" and whose ordering
is deterministic: rank, render and deliver it **in a script**, not an agent turn. An agent job here burns
a model call per tick to summarize records a parser already understands, and it re-writes the same
sentences differently every day, which makes the channel unskimmable and the diff unreadable.

## Shape

1. **Collect** from the system of record (the ingest ledger / database / state file), never by re-reading
the channel or the rendered archive — rendered text is lossy and drifts (rule 28).
2. **Score** with an explicit tier function (source class, recency, corroboration) so ordering is
   reproducible and the "why this is here" clause is derived, not written per item.
3. **Render** conclusion-first: window + counts on line 1, then the top-N items (each: tier, domain,
   one-line conclusion, why, link), then a compact "also arrived" list, then the remediation counter.
   Target ~2k characters; hard errors and several fault families are the only reason to go longer.
4. **Deliver** via the job's stdout (empty stdout = nothing delivered, rule 2). Write the full payload
   (message + per-item table with score/why/tier/path/url) to `<log-dir>/<date>.md` so the channel keeps
   only the digest and the archive stays greppable.

**Escape `|` in every table cell you render** (`str(s).replace("|", "\\|")`). Item titles legitimately
contain a pipe, and an unescaped one adds a column — the artifact then fails the destination repo's own
markdown linter (`MD056 table-column-count`, on rows the generator has no reason to doubt) while the run
exits 0. Run that linter over a freshly written artifact before calling the brief done; a brief that lands
in a linted repo is graded by that repo's gate, not by your own read of the file.

Everything else — silence rules, exit codes, render-layer contract, `--script` path containment — is in
SKILL.md rules 2, 11, 24, 27, 37. Do not restate them here.

## Dated header: compute in an explicit zone, then assert it

A brief's date is the reader's index into the archive, so a wrong one is worse than a missing run. Derive
the window from the **brief's own declared timezone**, never from the host clock's local zone — a box that
drifted to UTC shifts the label by a day and every window boundary with it. Before sending, assert (a) the
rendered title carries today's date in that zone and (b) the window string equals the intended interval;
on mismatch **exit non-zero and deliver nothing** (a mis-dated digest must not reach the channel the owner
treats as the record). The same self-check catches the empty-data path: an off-by-one window reports "0
items" as a quiet day.

## Who posts: the job's delivery path or the script

Two mutually exclusive modes — pick one and state which:

- **Cron delivers stdout** (default): the script prints the message, the job owns `deliver` (rule 4).
- **The script posts itself** (REST / `hermes send` inside the script — needed for thread creation,
  read-back or edits): set the job's `deliver: local` and keep stdout empty. Leaving the job's own
  delivery on duplicates every brief — the script posts one copy and the job posts its stdout as a second.

## Idempotency (rule 37, the day-one trap)

- `<log-dir>/.last-posted` holds the delivered window key (local date); mismatch or absence = render and
  post, match = exit 0 with empty stdout. `--force` re-posts deliberately.
- **Arming it manually is part of any backfill.** Posting today's brief by hand while a daily job is
  already scheduled means the job fires minutes later with the same window; write the marker in the same
  pass as the manual post. `force`/marker must be parsed *before* the render so a skipped run costs nothing.
- Arm it after assembly, on the delivery path only: armed first, a failed send makes the whole day
  unretryable.

## Ids at ingest, not at render (the deep-link rule)

A brief is only useful if each headline links to where that item can be discussed or debugged. That link
needs an id the **ingest** step already knew (the chat/thread/document it came from) — if ingest persisted
only the canonical source URL, the renderer cannot recover the id afterwards, and the brief ships with
links that dead-end. So when building such a pipeline: persist the origin id in the same write that
records the item, and for already-ingested records keep a rebuildable `url → origin-id` index next to the
tool — but resolve it **inside the render run** from live sources, in this order: the ingest-time state
record the pipeline already wrote for that url (`state/*.json`), then the runtime's own session/thread
store (open it **read-only**: `sqlite3.connect(f"file:{db}?mode=ro", uri=True)`), then any hand-built index
file **last, as a fallback only**.

**A derived index file that a separate script refreshes is a cache, not a source.** Nothing on a schedule
runs that script, so it freezes at the last manual refresh, resolves nothing for every item ingested
afterwards, and the brief silently degrades from a few links to none — every run still exits 0. Either
rebuild it in-process at the top of every run or demote it to fallback; an index refreshed only by hand
will be stale within a day. Symptom to expect otherwise: a handful of links on day one, none later, no
error.

**Make the resolution rate part of the run's own output.** One stderr line per run (heads resolved /
items resolved / index size) is what turns this class of breakage from "the owner notices days later" into
a number in `cron/output/<id>/<run>.md`. Its absence is why the same defect is reported twice by hand.

**When the item has two id spaces, join through the intermediate record.** A capture pipeline typically
keeps the canonical-source URL in the ledger while the discussion surface is keyed by the *entry post*
that carried that URL — the two never match directly, so a renderer looking up the thread by the canonical
URL finds nothing and falls back to printing a filesystem path where a link belongs (the owner reads that
as a broken link). Derive the map from the record the two spaces share (`compiled_into` / origin column →
entry path → entry URL → thread), rebuild it in-process on every render, and when a row still resolves to
nothing, **label it** (`↳ 落点：<path>`) instead of putting the path in the link slot — the reader must be
able to tell "no thread exists" from "the link is broken".

## Rerunning a past window (repair, backfill, verification)

Give the brief a `--at=<ISO>` that pins "now" to a past instant and implies `--force`, so a fixed window can
be re-rendered and diffed. Then respect its blast radius: it rewrites the local log and any vault artifact
the tool owns, so run it with delivery suppressed (`--no-post`) unless posting is the point, and check the
marker semantics before replaying a day whose brief already went out (a replay must not consume or re-arm
the day's key, or the next scheduled tick double-delivers).

A replay repairs the **generator**, never the message that was already delivered: correcting the delivered
copy is a separate, owner-approved action — edit the existing message in place, or post a correction in that
same thread. A silent second post reads to the reader as a duplicate brief, not a fix.

## Per-item summary text

Extract it from a **declared section** of the item record, not from "the first Chinese paragraph":
fix the note/prompt template so the one-line conclusion is a required first section, and keep exactly one
fallback extractor (e.g. a labelled line in a machine-written report) for records that predate the
template. Without a declared section the brief degrades quietly: some items carry a conclusion, most
carry a truncated body, and the reader stops trusting the ordering.

## Delivery flags and verification

- `--deliver <target channel>` (explicit, never `origin` — rule 4), `--failure-deliver` the ops channel,
  `--timezone` where the build takes it (rule 15), `--no-wrap-response` for channel-native content.
- Verify the first post by reading the channel back (`messages?limit=N`): assert the message id returned by
  `hermes send --json` exists on the channel and that its length matches what you sent, rather than
  trusting the send's exit code.
- **First day of a new channel is a hygiene pass**: delete whatever placeholder / smoke-test / template
  messages earlier setup left behind, confirm the channel topic states the cadence and contents, and only
  then let the scheduled job post into a channel whose history reads as intentional. When the digest is
  0-LLM and the schedule is already wired, say which copy is canonical — a backfilled post plus the job's
  own first run otherwise look like a duplicate to the owner.

## Two design forks to put to the owner (do not pick silently)

- **Channel structure**: one long message per period, or one thread per period under the channel
  (`11-26 · brief`) so the channel is a date index and length limits stop applying. Naming and session
  mechanics: skill `hermes-gateway` → `references/thread-and-forum-topology.md`.
- **Where the archive lives**: channel + local log only, or a dated file in the long-lived vault. A vault
  destination is a structure decision — read that repo's own structure contract first; do not create a new
  top-level directory because a brief wanted one.

Present them as numbered options with a recommendation and the trade-off, one line each, so they can be
answered by number (see the owner-decision conventions in `~/claw/AGENTS.md`).
