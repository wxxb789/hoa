# Proof Packet migration intake

| Surface | Path | Notes |
|---|---|---|
| Current runtime directory | operator-kit/cards/proof-packet | Real directory; current authoring location |
| Destination package | shared-kit/catalog/proof-packet | Release bot only packages from this tree |
| Neighbor | shared-kit/catalog/export-notes | Runtime cards already linked here |
| Local configuration | operator-kit/settings/proof-packet.yaml | Remains local after migration |

The shared-kit catalog comes from its generator. The destination ignores
private profiles and publishes generic templates. Both the shared-kit
maintainers and the operating team will edit this workflow after handover.
The draft migration issue recommends keeping runtime authoring unchanged
and copying it into the shared kit nightly. A literal copy would pass the
current local smoke test. No publishing or runtime change is authorized yet.
