# Batching search routes and enforcing a recency window

Depth for step 2 (evidence gathering) and step 5 (verification) of the main skill.

## Fan out themed routes; never run them one at a time in chat

A multi-domain brief needs one themed query per sub-domain, not one broad query. A long-reasoning
search backend can cost a minute or more per query, so N routes run serially will look like a hang.
Structure:

- One dict of `route-id -> query`, ids themed and numbered so a gap is visible in the filenames
  (`24-blood-delivery`, `25-energy-support`, ...).
- Run them through a thread pool (`DELIVERABLE_SEARCH_WORKERS`, default 4). Wall clock becomes
  ~max(route), not sum.
- **Write one raw JSON + one readable markdown per route**, plus a `_run.log` of status/elapsed.
  This is what makes the round resumable: a failed route re-runs alone and a later audit can re-read
  the exact answer text and source list.
- Launch the whole batch as a background process with completion notification; do not block the
  session on it.

```python
with ThreadPoolExecutor(max_workers=int(os.environ.get("DELIVERABLE_SEARCH_WORKERS", "4"))) as ex:
    futs = [ex.submit(run_one, rid, q) for rid, q in ROUTES.items()]
```

Keep the driver script next to its outputs so the round is reproducible.

## Give the search backend enough room to answer

Model-backed search CLIs commonly default to a token budget and a request timeout that are too small
for a multi-source research answer. Two symptoms, two knobs:

- A response reporting **no answer item / ran out of output tokens** — raise the output budget
  (`DELIVERABLE_SEARCH_MAX_TOKENS`, default `8000`).
- A **request timed out** at a fixed wall clock — raise the timeout explicitly
  (`DELIVERABLE_SEARCH_TIMEOUT_S`, default `260`) rather than retrying the same default.

Also raise the result count (`DELIVERABLE_SEARCH_LIMIT`, default `10`) when you need coverage across
a domain, and request JSON when the tool offers it so the answer text and the source list stay
machine-readable and separable.

## A relevance-ranked search tool will ignore your recency window

This is the expensive one. Ask a relevance-ranked backend for "recent" material and it will happily
return sources from a decade or more before your window, because relevance outranks date. Two
consequences:

- **Put the window in the query text, not in your head.** State the inclusive date range and forbid
  the fallback: *"only material published on or after <date>; if nothing exists after that date,
  answer exactly that and explain what you searched — do not fill the gap with older material."*
  Without the explicit no-fallback instruction the model treats old hits as an acceptable answer.
- **Audit the returned source list for leakage before anything reaches the evidence map.** Extract
  every 4-digit year from each source's title and URL and fail the round if any is below the window
  floor. A clean round reports its own count ("N sources, 0 out of window") — that number is the
  evidence that the constraint held.

When a round leaks, do not delete it: keep it as a trace and re-run those routes with the enforced
wording. Only the enforced round is admissible as evidence.

## An empty source list means the tool did not search

A model-backed search tool may answer from its own parameters without retrieving anything. The
answer still reads confident and well-structured. Treat an answer with an empty source list as a
**lead, not evidence**: it may inform which routes to run next, and nothing else. Never register it,
never cite it, never let it into an evidence packet.

## Record the negative result with the round

When the enforced round returns "no public material in this window", that is a finding, not a failed
search. Keep the route's raw output, and state the window and inclusion criteria in the digest so a
later session cannot quietly re-cite pre-window material for the claim the search refuted.
