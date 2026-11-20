# Study controls

The navigation index lives at [Fieldwork](../fieldwork/README.md). The study
runner reads `artifacts.tsv` directly; README redirects are not consulted.
Each path is repo-relative and must resolve to the bytes named by its
content ID. Content IDs in this rehearsal are stable labels for exact bytes,
not recomputed from filenames. Preserve every row and content ID.

For intake, file `relocations.tsv` with tab-separated columns
`old_path`, `canonical_path`, and `action`. Record the retired stream root
as `moved` and each retired duplicate as `deduplicated`. Use repo-relative
paths. This historical log does not substitute for updating `artifacts.tsv`.
