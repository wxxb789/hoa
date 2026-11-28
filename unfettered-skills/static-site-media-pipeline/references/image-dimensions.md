# Intrinsic dimensions from headers

Goal: reserve the right box before the image loads, without a decode, a dependency or a lie.

## Readers

| Format | Where the size lives |
|---|---|
| PNG | `IHDR` (width, height as 32-bit big-endian at offsets 16/20) |
| JPEG | first `SOFn` marker segment; skip `TEM` (`0x01`) and `RSTn`; stop at `SOS` |
| GIF | logical screen descriptor (canvas, not the first frame) |
| WebP | `VP8 ` (lossy frame), `VP8L` (lossless, 14-bit packed), `VP8X` (canvas + flags) |
| AVIF | `ispe` **associated with the primary item**, not the first `ispe` in the container |

All readers operate on the bytes the pipeline already authorized and hashed — never a second read, a
remote fetch, or a decoder call.

## AVIF: properties are not items

`ipco` is a property *list*; `ipma` decides which item owns which property. Reading the first `ispe`
reports another item's size when a container carries an unused property. Resolve in this order:

1. `meta/pitm` → primary item ID (both versions; refuse if absent or if more than one primary).
2. `meta/iprp/ipma` → property indices for that item (support the 7-bit and 15-bit field widths).
3. `meta/iprp/ipco` → the `ispe` at the associated index.

Any ambiguity — no `pitm`, duplicate primary row, unresolvable index, no associated `ispe` — yields
**no dimensions**, never a fallback to container order. `irot`/`imir` veto the pair when they apply to
the primary item; do not attempt transposition.

## Orientation

The frame header describes the **coded** frame; browsers apply the orientation tag on top. A phone photo
with orientation 5–8 therefore needs a transposed pair, and emitting the stored pair is the exact
defeat of the attribute (wrong aspect box, layout jump on load).

- Applying orientation at transcode time: do it **before** metadata removal, validate the produced
  file's own format/dimensions/orientation, then read dimensions from the produced bytes.
- Passthrough with a non-neutral orientation (JPEG `APP1`/EXIF, PNG/WebP `eXIf`, AVIF `irot`/`imir`):
  emit **no** pair. Fail open, never fail the build.

## Failing open, and what must not fail open

- Missing, malformed or truncated header → publish the image with no attributes. The image still
  publishes; only the size claim is dropped. (Truncated *bytes* are a different matter — that is a
  container-completeness failure, see the sibling reference.)
- Dimensions are a hint, not decode validation: corrupt pixel data can carry a valid header size. Say
  so in the docs instead of implying the pair certifies the image.
- Emit a pair only when both values are positive, and validate pair-or-absent at the artifact schema
  boundary so a half-pair cannot reach a renderer.

## Where the numbers must come from

When the pipeline transcodes, the artifact's dimensions must come from the **emitted** bytes, not the
source's header: a lossy re-encode can change nothing, but a format change or an applied orientation
does. Reading the source header after encoding is a silent source of wrong reserved boxes.
