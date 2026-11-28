# MEMORY.md / USER.md: migrate into the provider, then slim to a thin hard-rule layer

Use when the owner decides long-term memory lives in the fact store and the built-in
MEMORY.md / USER.md become an auxiliary layer. Order matters: nothing is deleted or shrunk until
coverage is proven.

## Why the built-in files stay (never delete the mechanism)

- MEMORY.md / USER.md are injected into the system prompt every turn — deterministic. The provider is
  recall-only: at most ~5 facts per turn (`_PREFETCH_FACTS = 5`), gated on `prefetch_min_coverage`
  (default 0.3), skipped on trivial prompts ("ok" / "继续"), deduped for `prefetch_repeat_turns`, and
  there is no pinned / always-include mechanism. Anything that must be present in EVERY turn —
  authorization gates, banned models, identity — cannot rely on recall.
- It is also the fail-open fallback: if the provider is missing or disabled after an update, MEMORY.md
  still works. That is why a thin layer survives.
- Target ≤6 rules: pointers plus "missing this once causes harm" rules. Facts, environment detail,
  procedures and preferences belong in the store or in skills, not here.
- Once the files are a thin layer, turn mirroring off or every write double-stores the same text:
  `hermes config set plugins.hermes-memory-store.mirror_memory_writes false`. Booleans are safe here;
  the string-coercion trap is only `embeddings` / `rerank`.

## Hard budget — overflow is silent, and the session view is not the file

`memory.memory_char_limit` / `memory.user_char_limit` (per profile) cap what reaches the system prompt.
Text past the cap is dropped at injection: the file keeps every line, the model sees a prefix, and the
lines you just added are exactly what disappears. Measured once at 3248 bytes against a 2200 cap with no
warning anywhere.

- Measure the FILE, not the rendered block: `wc -c ~/.hermes/memories/MEMORY.md` (and `USER.md`). The
  size shown in the session's memory section is the injected view after truncation — treating it as the
  file's size is how the overflow stays invisible.
- When it is full, compress — never append. Merge rules that restate each other, demote fact-shaped
  lines to the fact store, and keep only "missing this once causes harm" text.
- Do the whole consolidation as one batch (a single write), so the cap is checked against the final
  state rather than against a half-merged file.
- After compressing, re-read the file and confirm every P0 rule survived; the surviving-rule diff is the
  proof, not the byte count.

## Procedure

1. **Migrate, verbatim, per profile.** Parse each `memories/MEMORY.md` and `USER.md` on `§`; drop the
   `> Format:` header and `<!-- -->` comments; strip the `[P0]/[P1]/[P2]` marker but keep it as a tag
   or content prefix so priority survives. Merge paragraphs that share a `prefix:` label into one fact
   (`prefix：body1；body2`). Write with `st.add_fact_status(...)`; record `{fact_id, content}` per
   profile for rollback. Dry-run by default, `--apply` to write.
   - Guard the prefix regex with `` [^:：\n`]{1,60} `` — without excluding the backtick,
     ``ghc-proxy `localhost:4141` `` gets split at the colon and the technical string is corrupted.
2. **Union across drifted revisions.** Profiles do not share their MEMORY.md; they diverge (an older
   revision silently lacks whole sections a newer one has). Compare by hash; for each older profile,
   add the newer revision's facts that are missing (normalized-content dedupe). Never assume one
   profile's file is a superset of another's — a union is what preserves everything.
3. **Coverage gate before any shrink.** The invariant: every paragraph of the current file is already
   in that profile's store. Per paragraph, require its normalized body to be a substring of some
   fact's normalized text; print uncovered ones and backfill them BEFORE touching the file. Pitfalls
   that make the checker lie:
   - strip dates (`YYYY-MM-DD` and `YYYYMMDD`) before comparing, or merged facts (which drop the date)
     never match and you get dozens of false negatives;
   - match on the prefix **body**, not the whole paragraph: a merged fact carries the prefix once, so a
     second paragraph sharing that prefix is not a contiguous substring of it;
   - direction matters: only `paragraph_body ∈ fact` counts. `fact ∈ paragraph` invents coverage and
     loses information.
4. **Verbatim backfill.** Where the store was hand-rewritten (same meaning, different wording) the
   coverage gate cannot prove equivalence. Insert the missing original paragraphs as-is (marker
   stripped) so "delete the file" is provably lossless.
5. **Dedupe, strict only.** After a union, drop a fact only when its normalized text is a strict
   substring of a longer fact (`len(a) < 0.92 * len(b)` to avoid near-identical mutual kills). Strip
   `[P0]/[P1]` inside the normalizer or the priority prefix blocks every match. Leave semantic
   near-duplicates (same claim, different wording) for the nightly dream — deleting them breaks the
   no-information-lost guarantee.
6. **Slim the files.** Back up every `MEMORY.md` / `USER.md` to `backups/memory-slim-<ts>/` first, then
   write the thin versions. Keep them byte-identical across profiles (later maintenance edits one file,
   not N) except per-profile bans the owner set (e.g. a banned model for the research profile).
7. **Restart the gateway — mandatory here.** A live agent holds the MEMORY.md / USER.md content it
   loaded at init. Editing the files on disk while it lives is unsafe: its next memory-tool write
   rewrites the file from that stale in-memory copy and silently undoes the slimming. The
   provider-activation rule ("a new session is enough") does NOT apply to file edits, and the gateway
   cannot restart itself — hand off `hermes gateway restart`.
8. **Verify.** `wc -m` each file, `hermes memory status` per profile, and
   `memory-provider-reconcile.py --dry-run` silent.

Reference implementations of the four scripts (migrate / backfill / dedupe / slim, all with
`--apply` opt-in and a per-run JSON result file for rollback) live under
`claw/tasks/<task>/memory-system/` from the session that built them — copy the pattern, keep dry-run
the default.

## Surgical maintenance (memory-tool edits, not the migration script)

When the job is "review MEMORY.md / USER.md and move the facts to the store" rather than the whole
slim-everything project, work through the `memory` tool — the file is not the source of truth.

- **The tool is authoritative; a file read can be stale.** A live gateway rewrites `MEMORY.md` from its
  in-memory copy, so a `read_file` taken earlier in the same session can disagree with the live entry
  (a mid-session rewrite even changes a line's wording). Apply the edit with the `memory` tool's
  `add`/`patch`/`remove`; read the file only to confirm the result.
- **A `remove` batch is all-or-nothing.** One `old_text` that no longer occurs aborts every operation
  (`No operations were applied`). That response carries `closest_entries` with the LIVE text — copy
  `old_text` verbatim from there and retry the whole batch once; never hand-edit the file to force it.
- **Only facts move; rules stay.** The store is recall-on-demand (~5 facts/turn, gated on coverage),
  while `MEMORY.md`/`USER.md` inject every turn — so anything that must be present in *every* turn
  (hard limits, authorization gates, banned models, identity) stays. Do NOT demote a rule to `AGENTS.md`
  to free room: `AGENTS.md` loads only at its own cwd, so the rule silently becomes cwd-conditional.
  Environment facts, pitfalls, paths and procedures are what leave.
- **Search the store before adding.** It is usually already richer than the file (the file is a
  compressed rule-copy of facts the store holds in full). `fact_store search` first, then dedupe —
  `add` reports the similar facts it found.
- **Verify load-bearing claims before storing them.** A migrated sentence becomes durable, so confirm
  the ones carrying a safety or ownership stake instead of copying them as-is — e.g. repo visibility
  with `gh repo view <owner>/<repo> --json name,visibility` (a stale line called a public repo private).
- Report the char delta (the `memory` tool returns `usage: N/limit`) and the fact ids created/changed.
