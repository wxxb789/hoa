# Parcel Shelf 2.8 release evidence

The package campaign must exercise the released build at 320, 2,400 and 9,600
parcels. The gate is p95 dispatch to validated result (excluding draw) below
60 ms at each size. Keep the rendering result alongside it.

The February hover pilot is a separate, exploratory comparison, already
verified against its two named builds, not evidence for the package gate.
The chair wants a candidate-minus-legacy p50 comparison where warranted.
Use the ordinary sample median. Both pilot files use the same parcel data,
machine, CPU throttle, 140 ms intent delay, and Chromium build.

The backlog controls were recorded on a separate committed control build and
scratch prefix from the package campaign. Next lab slot is after result-reader
repair; decide which control IDs need fresh evidence. Historical IDs are not
part of this slot.
