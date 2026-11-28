# SQLite credential redaction (log layers only)

When a full key is found in a SQLite store (session/message DBs, tool state DBs).

1. **Scan read-only first, all tables/columns.** Connect `file:<db>?mode=ro`; iterate
   `PRAGMA table_info` per table; prefilter with `WHERE CAST(col AS TEXT) LIKE '%<fragment>%'`, then
   confirm candidates with the standalone-token regex **in Python, over every fetched row** — the
   LIKE count is not a verdict (a LIMIT sample can miss every real hit).
2. **Identify the LAYER, then scrub only logs.** Redact message/session/log tables only. NEVER
   UPDATE the owning tool's credential/account/kv stores, auth tables, or anything it needs to run
   — those are operational by design (e.g. an opencode `credential` table keeps a live key).
3. **Redact.** On a live DB: `PRAGMA busy_timeout=30000`; fetch the row, do the regex sub in Python
   (`re.sub(pattern, '«redacted»', value)`), `UPDATE ... WHERE rowid=?`, commit. Print counts only.
4. **Re-verify.** Re-run the scan; expect zero (excluding deliberately kept stores). Report
   fragment-only mentions (e.g. short key prefixes inside the audit conversation itself) as
   expected residue, explicitly.
5. **FTS shadow tables.** If the table has fts5 sync triggers (`<t>_fts_update` etc.), the UPDATE
   cascades automatically — verify the mirrors anyway (`*_fts_content`, `*_fts_trigram_content`).
   Without triggers, check the `*_content` mirrors manually; never hand-edit shadow tables while a
   rebuild path exists.
6. **State the caveats in the report.** SQLite may retain old bytes in WAL/journal/free pages until
   checkpoint or `VACUUM`; `VACUUM` only on a quiesced store (never casually on a live DB). Key
   rotation is the definitive fix regardless.
