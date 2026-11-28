---
name: static-site-media-pipeline
description: Use when a static build publishes, sizes or encodes images.
metadata:
  version: "0.1.0"
  areas: "software-development"
  targets: "runtime-agnostic"
---

# Static-site media pipeline

## When to Use

- A static site (or any build) starts publishing, sizing or encoding images: a new media goal, a
  format/encoder change, an image regression, or a caption/dimension feature on an existing pipeline.
- Reviewing an image pipeline — policy table, container validation, identity/dedupe, budgets, or a
  "smaller and better" cost claim.

Not for: layout/CSS taste around images, runtime CDN configuration, or a server-side image service.

Build-time image handling in a static site generator: the same eight decisions, in the order a build
hits them. This file is the protocol; per-format mechanics live in the two references below.

## Order of operations

1. **Resolve → authorize → then read.** The reference walk (note-relative, then content root;
   exclusions, symlink escapes) decides whether bytes may be published. Read that verdict *before*
   `stat`/`readFile`. A codec is never a publication authority: adding an encoder must not make an
   excluded, missing or escaping file publishable, and the encoder itself should never see a path or a
   filename.
2. **Identify by content, never by extension.** The extension only names the output; the emitted
   extension and MIME must follow the emitted bytes.
3. **Prove the container is complete before decoding or publishing.** →
   [`references/container-completeness.md`](references/container-completeness.md). A successful
   `metadata()`/decode is not proof: several truncations decode silently with fewer frames or with a
   missing tail.
4. **Read intrinsic dimensions from the emitted bytes, and only when the claim is honest.** →
   [`references/image-dimensions.md`](references/image-dimensions.md). Omit the pair rather than
   publish a value that mis-reserves space.
5. **Encode only when strictly smaller; otherwise publish the source bytes unchanged.** Lossless rows
   are compared byte-for-byte or pixel-for-pixel; already-compressed formats and animations are
   passthrough by default (no re-encode, no first-frame flattening, no timing loss).
6. **Identity is the hash of the emitted bytes.** Dedupe on that digest; the artifact carries URL plus
   dimensions only — no second manifest, no database column, no public index.
7. **Bound the work.** Finite decoder limits (never `unlimited`), bounded concurrency, explicit
   decoded-pixel/size/time caps, and `stat` before `readFile` so an oversized file is refused unread.
   Pathological input fails boundedly and leaves the previous valid output intact.
8. **Measure baseline versus optimized on one corpus, twice.** Published bytes per type, wall time,
   peak memory with a statement of what the number includes, encode count, install/tarball delta.
   Never claim a format is always smaller, and name the platforms you did not exercise.

## Gates that actually pin the policy

- One test per policy row over real bytes: smaller candidate kept, larger candidate rejected, each
  passthrough byte-identical, corrupt input fails the build.
- Truncation controls per format that remove a real tail (not one byte, and never an empty buffer) plus
  one full build that fails and preserves the preceding output.
- Determinism: two builds produce identical bytes and identical URLs.
- A browser/decode gate that measures the *served* file (natural size, pixel comparison, alpha) rather
  than trusting the encoder's return value.
- Fixtures assert their own premise: a fixture called animated reports `pages > 1`, a fixture called
  truncated is not intact. A vacuous control passes forever and hides the next regression.

## Pitfalls

- **Decode success is not container completeness.** Truncated animated files decode with fewer pages,
  and an image can lose its entire trailing chunk stream and still report full dimensions — so a
  passthrough publishes corrupt bytes. Walk the container (chunk lengths and checksums, marker reaches
  its terminator, box walk consumes the buffer exactly) before publishing anything, transcoded or not.
- **Dimensions from the coded frame mis-reserve space for an oriented photo.** Browsers apply the
  orientation tag, so the stored frame is not the displayed frame: apply orientation before stripping
  metadata, and omit the pair whenever you cannot honour it.
- **A multi-image container's first property is not necessarily the primary item's.** Resolve the
  primary-item association; if it cannot be established, publish no dimensions.
- **16-bit or wide-gamut PNG reduced to 8-bit WebP silently loses depth** while the docs promise exact
  pixels. Transcode only the depths and colour models the target format carries faithfully; publish the
  rest unchanged and say so.
- **Passthrough keeps the source's metadata.** "Modern format preferred" does not imply scrubbing —
  state the gap instead of letting users assume it.
- **A cache key that re-spells encoder settings drifts from the encoder** (the stringified options
  silently omit a real flag). Key by source digest; derive settings from one function.
- **Measuring by filename stem breaks on dedupe** — two sources that encode to identical bytes collapse
  into one asset, so the second source gets no row and the encode count becomes an asset count. Report
  per emitted asset, or map through the manifest, and say which parts of the number are independent of
  the product.
- **A measurement CLI that ignores unknown flags turns one typo into a silently skipped check.** Refuse
  unknown arguments.
- **The completeness rule belongs to the pipeline, not the encoder.** If two paths (passthrough and
  transcode) each validate differently, the input that skips one publishes corrupt bytes; put one gate
  in front of both and test both.

## References

- [`references/container-completeness.md`](references/container-completeness.md) — per-format completeness
  checks and the measured truncation behaviour that motivates them.
- [`references/image-dimensions.md`](references/image-dimensions.md) — header readers, primary-item
  resolution, orientation, and when to omit.
