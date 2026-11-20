# Shared-store installer triage (2026-11-21)

For a `skills` CLI install, verify the installed version and inspect that version's
code when explaining a behavior. Do not infer the live version from a reference to
`latest` or from a random cached bundle. Locate the installed or cached package from
the tool's actual package location.

| Evidence | What to check |
|---|---|
| Shared store and loader links | Resolve the real location and inbound consumers before calling a directory orphaned. |
| Shared-store `.skill-lock.json` | Read `skills.<name>` for source, source type, URL, upstream path, hash and timestamps, when present. Group by source for per-source counts. |
| Temporary source checkout | A warning's path under a clone can identify the scan phase, not an installed location. |
| File and receipt | Check the file at the relevant upstream revision and the effective loader as well as the receipt. |

To identify a repo from a distinctive relative path, use the provider's code search;
retrieve the matched source file without cloning if available. Search the installer
bundle for the exact warning and inspect the call site. Scope local searches to the
relevant installer or skill directory; skip generated indexes and caches.

A scanned fixture can intentionally lack required frontmatter. Before calling the
warning cosmetic, confirm the fixture's contents and show that the warned names
were not installed or expected to be installed. If a real skill was skipped, say
which one and why. Report the emitting phase, impact, and evidence. Route scanner
defects upstream rather than editing local installs or receipts to silence them.
