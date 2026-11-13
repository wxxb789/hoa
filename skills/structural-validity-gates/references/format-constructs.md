# Per-format completeness checks and their traps

Observed against real files with a tolerant decoder (`sharp`/libvips) on the same machine: either the
decoder accepted the broken file, or a naive walk rejected the legal one. Starting matrix, not a
substitute for each format's spec.

| Format | Completeness walk | What it must reject | Legal-but-rare construct a naive walk rejects |
|---|---|---|---|
| PNG | each chunk: declared length fits, CRC-32 matches; final chunk is zero-length `IEND`; no trailing bytes | cut mid-`IDAT`, missing `IEND`, stray tail | ancillary chunks (`eXIf`, `tEXt`, `iCCP`) may appear in any order before `IEND` |
| GIF | block walk to trailer `0x3B`; image-descriptor count must equal the decoder's page count; trailer is the last non-`0x00` byte | truncation before the trailer (a 6-frame GIF decoded as 6 pages at 90 %, 3 pages at 50 %) | plain-text and comment extensions, local colour tables, per-frame sizes |
| JPEG | marker walk to `EOI`; `EOI` final and consuming the buffer; after each entropy-coded segment resume at the `0xff` that introduces the next marker | missing `EOI`, entropy data that never reaches a marker, bytes after `EOI` | progressive JPEG: several `SOS` segments, so the next marker after a scan is `DHT`/`SOS`, not `EOI` — a walk returning a cursor at the marker *code* instead of its `0xff` prefix rejects every progressive file |
| WebP | RIFF size field equals `length - 8`, then the `VP8 `/`VP8L`/`VP8X` payload | truncated RIFF, size field lying about the payload | `VP8X` animation means a stacked frame height; the extended format may carry EXIF/ICC chunks |
| AVIF / HEIF | top-level box walk consumes the buffer exactly; `meta` present; primary item from `pitm`; every `iloc` extent fits inside the container its construction method names | truncated `mdat`, extent past the payload, no data container at all | `iloc` method **1** stores data in `meta/idat`, so a valid file can have **no** `mdat`; property→item associations live in `ipma`, so the first `ispe` need not describe the image |
| ZIP-like container | end-of-central-directory record present and consistent with the declared entry count | truncated archive that still lists entries | data descriptors, prepended stub bytes, archive comment |

## Fail-open decisions that belong next to the gate

- **Dimensions**: a header hint, not decode validation. If the format declares a transform you do not
apply (EXIF `Orientation` ≠ 1, `irot`/`imir`), publish the file and drop the numbers — never the other
way round. A transposed pair mis-reserves layout space, which is the defect the attributes exist to
prevent.
- **Depth / colour model**: a lossless re-encode that changes bit depth (16-bit → 8-bit) breaks a
quality promise silently. Keep such inputs as passthrough bytes instead of converting them.
- **Animated / multi-frame sources**: if the encoder cannot preserve frames, delays and loop count, the
source is not a candidate — validate and publish it unchanged, and document that rule.

## Enumerate the class before shipping the gate

A gate reviewed only against the cases the reviewer happens to imagine converges one legal-but-rare
construction per round. Before dispatch, enumerate five axes for every format in scope and give each
cell a fixture:

1. **Segment / scan layouts the spec allows** — baseline vs progressive JPEG, interlaced PNG, GIF with
extensions between frames, WebP still vs `VP8X` animation.
2. **Containers the data may live in** — top-level `mdat` vs `meta/idat` for `iloc`, a GIF's local
colour tables, a ZIP's data descriptors.
3. **Encoder bounds, read from the installed headers not from docs** — libwebp's
`WEBP_MAX_DIMENSION` (16,383 px per side), animation-frame limits, bit-depth handling. Every bound is
a future `corrupt` mislabel unless the source falls back to passthrough before the encode.
4. **Optional chunks / boxes / version bytes** — anything the walk may meet and skip, plus the version
byte that changes field widths (`iloc`/`ipma` versions, `VP8X` flags).
5. **Metadata-declared transforms** — `Orientation`, `irot`/`imir`, colour profiles; these decide
fail-open behaviour, not completeness.

A named limitation is also a cell: write it in the goal record with the construction it cannot cover,
so the next reviewer round is answering a documented gap instead of discovering one.

## Probe recipe

```js
// temp test file INSIDE the repo (module deps only resolve there); delete after use
import sharp from 'sharp';
import { assertCompleteContainer } from '../src/lib/<module>';

const bytes = readFileSync('/tmp/fixture.<ext>');
for (const cut of [0, Math.floor(bytes.length * 0.1), Math.floor(bytes.length * 0.5)]) {
  const part = bytes.subarray(0, bytes.length - cut);
  try { assertCompleteContainer('<ext>', part); console.log(cut, 'ACCEPTED'); }
  catch (e) { console.log(cut, 'REJECTED:', e.message); }
}
```

Run it under the repo's own runner (`pnpm exec vitest run --reporter=verbose <file>`), keep the printed
`ACCEPTED` / `REJECTED` table as evidence, then delete the probe — a leftover probe becomes an
untracked file that the next gate flags.
