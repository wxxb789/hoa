# North Spit route-verification ticket: draft closeout

The provisioner has already staged a change of default model in all active homes.
This ticket is for verifying operator-visible routing, not planning a fleet
cutover or making a second config change. The homes registry is authoritative
for active names. In each home, the newest session in the export is the
ticket probe, and the row immediately before it is the captured pre-change
session. Older rows are retained for troubleshooting. The intended settings are:

| Home ID | Provider | Model | Resolved effort |
|---|---|---|---|
| root | tide | shoal-3 | high |
| desk | eddy | dune-1 | medium |
| filing | tide | shoal-3 | high |

For the background policy report, count enabled model-using jobs and how many
would resolve to provider eddy (the background pool), pinned or unpinned.
Do not count historical paused schedules. These exports describe one ticket
window; the enabled jobs have no external scheduler overrides.

Draft claims to verify:

- The cron highlights widget reports 5 of 5 background jobs on eddy. The
  widget looks only at rows labeled background and does not resolve them.
- By reading OMP's configured model list, shoal-3 is missing, spray-2 is
  selectable, and dune-1 is selectable.
- All three defaults are verified: the config echoes match the table; each
  home's probe log has a successful reply and the newest row has the desired
  model. No more evidence is needed.
