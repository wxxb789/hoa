# Container completeness

Decoding is tolerant by design: libvips, browsers and animation players all render what they can. A
pipeline that publishes bytes it never re-encodes therefore needs its own structural check, because
"it decoded" says nothing about "the file arrived whole".

## Measured tolerance (why the gate is mandatory)

| Input | Damage | What a decoder reports |
|---|---|---|
| 6-frame GIF, 5,043 B | cut to 90 % | `pages: 6` — looks complete, tail is garbage |
| same | cut to 75 % / 50 % | `pages: 5` / `pages: 3`, no error |
| same | cut to 25 % | rejected: corrupt header |
| 96×96 PNG, 535 B | last 4 / 12 / 20 B removed | `96×96 png`, no error |
| same | cut in half (268 B, whole IDAT tail gone) | `96×96 png`, no error |

Consequences: a truncated animation publishes as a shorter animation, and a truncated still publishes
as a smaller-but-valid-looking file. Both violate any "corrupt input fails the build" promise, and the
second one is invisible to every decode-based test.

## Checks, per format

- **PNG**: walk chunks — each length must fit, each CRC-32 must match, the stream must end with a
  zero-length `IEND`, and no bytes may follow it. Trailing garbage after `IEND` is a failure, not a
  tolerance. APNG validates the same way; per-frame completeness is a separate, disclosable limit.
- **GIF**: walk blocks to trailer `0x3B`, count image descriptors, and require that count to equal the
  decoded page count (a truncated stream loses descriptors — that is exactly the 6→5→3 case). The
  trailer must be the last non-padding byte.
- **JPEG**: marker walk must reach `EOI` (`0xFFD9`) at the end of the buffer, in addition to stopping
  the frame scan at `SOS`. A truncated scan-line stream otherwise decodes to a grey band.
- **WebP**: RIFF size field must equal `bytes.length - 8`. A mismatched or truncated RIFF is a failure;
  keep the `VP8 `/`VP8L`/`VP8X` handling for dimensions only.
- **AVIF**: the top-level box walk must consume the buffer exactly, every `mdat` declared size must fit,
  and the primary item's extent must lie inside an `mdat` payload.

## How to wire it

- One function, in the module that identifies formats, e.g. `assertCompleteContainer(format, bytes)`.
- Call it for **every** source that will be published — before the encode as well as before the
  passthrough. Two call sites with two different checks is how one path ships corrupt bytes.
- Failure maps to the pipeline's existing `corrupt` reason: no new taxonomy, no fallback that publishes
  anyway, no "tolerant tail".
- Bounded cost: the walk is linear and allocation-free; run it on the bytes you already read, not on a
  second read.

## Controls to write

- Per format: one real tail removal (whole trailing chunk / whole `IEND` / final marker), one half-cut,
  and the intact file passing. An empty-buffer control proves nothing.
- One full build where a referenced file is truncated: non-zero exit, named failure, and the preceding
  valid output directory intact byte-for-byte.
- Corpus fixtures whose names promise a property must assert it in the factory (an "animated" 69-byte
  GIF with one frame and a loop extension is not animated).
