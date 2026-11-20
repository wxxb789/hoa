# Alder release contract, 4 May 2028

The incoming auditor may inspect this packet and advise the release owner. No edits to
the release, acceptance register or case dispositions are authorized.

The release matrix pins one revision per QA case. A case is ready only when a final
receipt for that exact revision has exit code 0. Preflight receipts and receipts for
neighboring revisions never certify the release.

An exhibit is a file named `AL-NN.md` in the top-level `exhibits` directory. The
manifest's `groups[].entries[]` lists registered paths, including reserved ones.
The signed acceptance register alone determines acceptance.

The owner may hold the packet or open the replacement lane. In that lane each
scheduled signing packet is re-reviewed in full, even if a page also occurs in the
other packet. Review-only previews are not signing packets.
