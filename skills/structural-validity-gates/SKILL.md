---
name: structural-validity-gates
description: >-
  Write or audit a gate that decides whether a structured input — an image container, an archive, a
  document, a protocol frame — is intact enough to publish, store or decode. The contract is two-sided:
  reject what is broken, accept everything the format legally allows. Use when adding a completeness or
  integrity check before publish, upload, extraction or decode, or when an existing gate rejects a valid
  file. Do not use for schema validation of a repo's own config, or for a test-suite gate.
metadata:
  version: "0.1.49"
  areas: "software-development"
  targets: "runtime-agnostic"
  summary: "a two-sided integrity gate: reject the broken, accept every legal construct; probe both sides before shipping"
  summary_zh: "两面完整性门禁：拒掉坏的，接受格式合法的一切；上线前两侧都要探针"
  kind: "entry"
---

# Structural validity gates

A gate that decides whether a structured input (image container, archive, document, protocol frame) is
intact enough to publish, store or hand to a decoder. It is a **two-sided** contract: reject what is
broken, accept everything the format legally allows. Most of the cost is the second half, because it is
invisible until a real user's file hits it.

## When to Use

- Adding a completeness / integrity check before publish, upload, extraction or decode.
- A build or import fails on files a decoder opens fine.
- A gate exists but nobody proved it rejects the corruption classes it claims.
- Reviewing someone else's "validate the file" patch.

## Procedure

1. **Separate the two questions.** "Can the decoder open it?" and "is the container complete?" have
different mechanisms. A tolerant decoder opens a PNG with its entire tail missing and a GIF that lost
half its frames — treat decode success as no evidence of completeness.
2. **Put one gate at the single boundary.** One function, called once, where bytes become
   publishable/storable — before any decode, encode, extraction or rename. Not one check per consuming
   format, and never duplicated in producer and consumer. The gate itself only parses bytes: it must
   not import the decoder or encoder, so it stays loadable on a host that has no platform-matched
   native binary (see the native-dependency pitfall).
3. **Walk the format's own self-description, not a heuristic.** Chunk lengths and CRCs plus the terminal
chunk; block walk to the trailer plus a structural count comparable to the decoder's; marker walk to
the end marker; container size field equal to the real length; box walk consuming the buffer exactly
with every item extent inside one container. Per-format constructs and each one's trap:
[`references/format-constructs.md`](references/format-constructs.md).
4. **Decide fail-open vs fail-closed per concern, and write it down.** Structural integrity of bytes
you will publish: fail closed, with a named reason. Presentation-only metadata — dimensions, colour
hints, orientation — fail open (drop the hint, keep the file), unless the format declares a transform
you cannot apply, in which case drop the claim rather than publish a wrong one.
5. **Gate both directions before calling it done.** Matrix: one accepted fixture per legal construction
of the format, one rejected fixture per corruption class with its reason asserted. Half a matrix is a
half-built gate, and the missing half is always the one that breaks a user.
6. **Reproduce every reported rejection with a real file.** Generate it, run the gate, print
`ACCEPTED` / `REJECTED: <reason>` per case, keep that table as the evidence. "Valid files are
rejected" is a hypothesis until you hold the bytes.

## Pitfalls

- **Tightening one side breaks the other, in the same week.** A gate added to stop truncated input
rejects a legal-but-rare construction the first time it meets one (an extra scan, data in a different
container, an omitted optional chunk). Budget the second fix before shipping the first, and put both
matrices in the same dispatch.
- **A stricter gate silently redefines the output contract.** Byte-identical passthrough formats cannot
be re-validated into a stricter shape; if the gate is stricter than the decoder, the producer's own
fixtures stop building. Run the existing corpus through the new gate before adding new cases.
- **Two copies of the rule diverge.** Producer and renderer, writer and reader, uploader and CDN checker
each growing "is this a valid X" means two answers for one file. Import the one function; if the module
boundary is wrong, move the function rather than copying it.
- **Scanning source code is a grammar problem, so hand the gate the language's parser.** A gate that
  looks for a property in source (a platform-bound path literal, a banned call, a magic value) must ask
  the parser, never a regex that grew into a lexer. Each review round then answers one lexical escape
  and reveals the next — quoted form, then raw-string form, then escape decoding, then a rune holding
  the delimiter, then a multi-line string, then `*p = …` read as a doc comment. `go/parser` +
  `ast.Inspect` + `strconv.Unquote` (or the platform's equivalent) settles the class in one pass and
  lets you delete the lexer; take positions from the parser's `FileSet`, not from line arithmetic.
- **An exception marker justifies one construct, not a neighbourhood.** An allow comment that applies
  within N lines lets one justified fixture silence the unjustified value beside it, and the reviewer
  will find that pairing. Attach the marker to the exact line or element it excuses, require a reason
  rather than a bare allow, and pin it with a self-test where an unmarked item sits next to a marked
  one.
- **The gate's own rule table trips the gate.** The list of patterns the scan is built from (path roots,
  banned imports, prefixes) lives in the gate's source and reads as a violation on the first run: mark
  those lines as data with the same exception mechanism, so the evidence is "54 files, zero violations"
  rather than a gate that reports itself.
- **A gate that names a failure without its message costs one round trip per failure.** When the gate
  wraps a test runner, carry the failing case's own output into the result (a bounded tail is enough).
  A green matrix that only says `pkg/Test: failed` forces every remote reader to reproduce it locally.
- **A hand-written spec parser assumes the narrowest legal encoding.** Fixed offsets, "the first X box
is the one that matters", and "the data must be in the main container" are the three shapes that break
on real files. Read the field widths, the version byte and the construction/wrapping method the format
declares; treat anything unresolvable as *incomplete*, never as a guess.
- **An element allowlist and its attribute allowlist are one contract.** Admitting an element while
  refusing the attributes it requires turns a documented feature into an unexplainable refusal: a
  `<feDistantLight>` is allowlisted but its mandatory `azimuth`/`elevation` are not, so a normal export
  fails with an attribute error the author cannot connect to "lighting is supported". Every element you
  admit needs the attributes the spec says it requires, and every family the docs claim needs a fixture
  that actually renders through the build — an allowlist entry is not evidence that the family works.
- **A negative control that passes a zero-length buffer proves nothing.** An empty or all-zero fixture
exercises the early guard, not the truncation class. Each rejection case needs real bytes cut at a real
boundary: mid-chunk, mid-frame, missing terminal marker, size field off by N.
- **The encoder's own bounds are part of the contract, and they are not corruption.** A source can be
  complete, decodable and inside every configured budget, yet be *unrepresentable* in the target
  format — libwebp caps each dimension at 16,383 px, so a 100×20,000 screenshot is 2 MP and still
  cannot become a WebP. Attempting the encode throws, and a catch-all classifier reports `corrupt`:
  a valid file fails the whole build under a damage label. Decide representability **before** calling
  the encoder and route those sources through the passthrough path the format policy already has for
  other untransformable cases; name the bound once beside the codec constants with its provenance, and
  test both sides of the boundary (16,383 transcodes, 16,384 publishes unchanged).
- **A coverage gate that over-reports publishes the bad artifact silently.** When the gate answers "can
  this be represented" — glyph coverage, colour space, codec support — compute it the way the *consumer*
  computes it, from the consumer's data, and close the over-reporting direction first. Reading every
  `cmap` subtable credits a Mac Roman table with covering `é` that the font's Unicode table lacks, so the
  gate passes and the renderer draws tofu; fail-closed means "the renderer will draw this", not "some
  table in the file mentions this". Verify capability claims against the real renderer once, then pin the
  rule with a fixture per direction.
- **A gate must bound its own work, not only the decoder's.** Expansion counting, per-consumer
  attribution, schema or selector matching all run synchronously inside the gate on attacker-chosen
  input; a right-to-left matcher that recurses over every ancestor is combinatorial on a document the
  policy's depth limit still admits, and it stalls the build while returning `accepted`. Memoise the
  recursive state, state the complexity in the code comment, and pin a deep non-matching case with a
  generous time ceiling.
- **Tolerance during input reading is not a license for the published copy.** Accepting a slight tail
  defect while *reading* may be fine; publishing bytes you know are structurally short is not.
- **A byte-walking gate must not need the native codec, at build time or load time.** The walker is
  pure parsing and belongs in the module that identifies formats; the encoder/decoder is imported
  lazily at the boundary that actually processes pixels. A module-scope import of `sharp`/`libvips`/
  `satteri`-style per-platform bindings makes *every* path that loads the module fail with
  `Cannot find native binding` on a host or WSL image whose installed binaries target another
  platform — including paths that never touch an image (metadata-only discovery, cross-platform
  comparison tests, docs tooling). Keep `import type` for the erased types, `await import()` at the
  processing point, and gate it: a corpus with no referenced media must run without evaluating the
  codec.

## Support files

- `references/format-constructs.md` — per-format completeness checks, their legal-but-rare constructs,
and a probe recipe for the `ACCEPTED` / `REJECTED` evidence table.
- `references/gate-review-loop.md` — iterating a gate against an external reviewer: probe recipe
(including the positive control that proves the probe itself works), reproducing a complexity claim on
the branch that actually runs it, the gate's own work budget and memoisation, the verdict shapes that
look like new findings but are not (open threads, re-posted findings, a regression the gate itself
introduced), reading a CI-green and a marker as claims rather than verdicts, when to stop patching
instances and sweep the class, escalating a source-code scan from regex to the language's parser
instead of accepting one more lexical fix, when the fallback is to delete the capability you added, and
why the walker must stay free of the native codec.
- `references/entry-point-acceptance-probes.md` — accepting a gate or publisher through its shipped
entry point: a subprocess probe with a `--import` fetch shim and its own fake server, plus the false
verdicts that shim produces (a `Request` spread losing method and body, a permissive fake, a repeat-run
request count read as a defect).
