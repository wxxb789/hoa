# Promoting a reviewed candidate into live state (atomic, guarded)

For state a running system reads at any moment — a cache/ledger JSON, an inventory snapshot, a generated
config. The delivery is not "the file looks right" but "the bytes that landed are the bytes that were
reviewed, and nobody else was writing". Steps in order.

## 1. Pre-write surface check

Run the owner's write-scope verifier against the concrete absolute path and record the exit code:

```bash
python3 -B <repo>/bots/verify_writes.py --role <role> --hermes-home <home> --path <absolute live path>
```

A path the schema allows resolves to the profile/state home, not to the repo or scratch. Report the code;
"the write surface check passed" without it is a claim.

## 2. Prove no concurrent writer, before touching anything

Quadruple-compare live against the retained before-copy: size, mode, `st_mtime_ns`, sha256. All four equal
means the live file *is* the reviewed base. Equal bytes with a moved `mtime_ns` still means someone
re-wrote it — re-capture the before-copy and re-verify whatever depended on it.

## 3. Replace atomically, guarded

Same-directory, uniquely-named temp sibling: write → `flush` → `os.fsync(file)` → `chmod` to the **old**
file's mode → `os.replace` → `fsync` the directory. Same directory is required: `os.replace` is atomic
only within one filesystem, and a staging file in the system temp dir turns the move into a copy. An
in-place truncate leaves a reader, or a restart, looking at half a file.

Pass both expected digests as argv — the reviewed candidate's sha256 **and** the live file's pre-write
sha256 — and exit non-zero *without writing* when either has drifted:

```
promote.py <candidate> <live-path> <after-meta.json> <label> <expected-candidate-sha> <expected-live-sha>
-> REFUSED (no write) | exit 0
```

That makes the step re-runnable and makes "the candidate that was approved" a checkable fact.

## 4. Receipts and read-back

- before/after stat (size, mode, `mtime_ns`) plus sha256 for both, in a JSON beside the run;
  `changed: true` and `temp_sibling_absent_after: true` cheaply catch a silent no-op.
- Keep the before-copy at a stable path and **do not overwrite it on a retry** — it is the rollback unit,
  and re-capturing it after a partial write destroys the only restoration point.
- Read the live file back and print the *semantic* identity (snapshot date, base commit, record counts),
  not just the exit code. The acceptor recomputes the digest independently; a number quoted back is not a
  recomputation.

## 5. Prove the reserved lanes did not move

List the artifacts deliberately left alone — the mirror file, the generated profile identity, the job
definitions — and report their unchanged mtimes. "Live state moved, everything else still" is the finding;
without those stamps the boundary claim is unproven.
