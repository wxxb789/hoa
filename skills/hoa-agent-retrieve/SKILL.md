---
name: hoa-agent-retrieve
description: "Search, gather, or inventory local AI-agent histories across runtimes and return a read-only, coverage-manifested Retrieval Bundle. Use for requests such as 'find every session where I touched X', 'pull my last month across agents', 'search my Claude Code, Codex, and OpenCode history', or when another workflow needs re-checkable cross-agent evidence. Do not use for one known file or session; use hoa-introspect for analysis or conclusions, and hoa-introspect-distill to create a skill."
---

<!-- index: areas=self-management,software-development; targets=runtime-agnostic -->

# hoa-agent-retrieve

Retrieve local, operator-authorized AI-agent history into a normalized evidence
bundle. This is the retrieval primitive: it inventories coverage before it
reports records so later work can distinguish a missing store from missing
behavior.

## Contract

- Accept an optional time window, source allowlist, text/project filters, and
  an untracked local config. Auto-discovery covers the known catalog; optional
  providers require opt-in.
- Produce a JSONL Retrieval Bundle whose first line is its coverage manifest,
  then normalized records with resolvable local locators. See
  [bundle schema](references/bundle-schema.md).
- Read agent stores only. Never create, migrate, vacuum, lock, index, or
  otherwise alter them.
- Write the bundle to the supplied safe state-directory default. Refuse any
  output path that is not provably outside its own Git worktree or ignored by
  that worktree; never auto-redirect a refusal. Do not `git add` generated
  bundles.
- In chat, give only a redacted count-and-gap summary. Keep raw locators,
  session IDs, transcript text, absolute paths, and possible secrets in the
  local bundle, not the response.

Use [the source catalog](references/source-catalog.md) for supported formats
and drift notes. `unsupported`, `not-found`, `inaccessible`, and
`auth-required` are useful results, not errors to hide.

## Workflow

1. Load an untracked config (`~/.config/hoa/config.toml` or
   `.hoa/config.local.toml`) when available. It may enable agents and provide
   explicit source roots; it must not be committed.
2. Define the scope. Probe every requested core adapter and report one status
   per source. Probe optional adapters or MCP memory only when explicitly
   enabled.
3. Parse only documented JSONL, JSON, Markdown, and recognized read-only
   SQLite tables. Treat schema drift, unknown formats, databases without a
   recognized table, and permission failures as manifest states; continue with
   other sources.
4. Normalize each record, preserve a file-and-line/offset locator, deduplicate
   copies by content origin, and canonicalize known parent-linked session
   branches. Do not silently discard parse failures.
5. Emit the coverage manifest first, apply requested filters, then write the
   JSONL bundle. Sample-resolve a few locators before passing it onward.

Run the bundled deterministic helper when a shell is available:

```text
python scripts/retrieve.py --config /path/to/untracked-config.toml --query "auth"
```

The helper is deliberately stdlib-only and read-only. It accepts JSON or TOML
config with a `sources` table/object mapping an adapter name to an explicit
file or directory (or list of them). `--source agent=/explicit/path` is the
CLI equivalent. Without roots it probes documented patterns; this is an
inventory, not a claim that every runtime was searched.

## Safety and evidence boundaries

- **Manifest first:** make no statement about an agent whose source status is
  not `available`. A `not-found` store can mean an alternate config location,
  disabled persistence, a version change, or permission limits.
- **Honest empty is valid:** when no source is available, write an empty bundle
  with its manifest and say so. Never synthesize sessions, summaries, or
  coverage.
- **No secret scavenging:** search only selected sources; do not scan arbitrary
  disks, cloud accounts, credentials, or unrelated private folders. Excerpts
  should be minimal and only for the requested retrieval.
- **No hard sibling dependency:** `hoa-introspect` may consume this bundle when
  installed. If it is absent, the bundle remains independently useful;
  conversely, this skill does not require its files.
- **No conclusions here:** report records, coverage, and deterministic counts.
  Send interpretation, work-pattern claims, and recommendations to
  `hoa-introspect`; send reusable-skill authoring to `hoa-introspect-distill`.

## Verification and stop condition

Stop after the manifest is built and the bundle is safely written. Confirm
that manifest counts equal emitted records, that source statuses are explicit,
and that a locator sample resolves. For a zero-availability run, stop after
the honest empty manifest; do not retry by widening private discovery.

See `evals/run_evals.py` for a synthetic present/absent/unsupported check. It
never reads a real history store.
