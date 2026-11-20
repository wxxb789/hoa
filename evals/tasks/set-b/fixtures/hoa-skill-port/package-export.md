# Package export and local replay

The private wrapper uses `amber-checkout` for the repo, calls
`bridge-one`, treats `ACK-LOCAL` as the review marker, and times out at
35 seconds. These were implementation choices on the original machine,
not part of the proof-packet procedure. The adapter must keep producing
one receipt with a job ID and exit code; the replay adapter already does.

Destination option contract:

| Key | Purpose | Documented published default |
|---|---|---|
| repo | checkout directory | current working tree |
| adapter | launcher adapter ID | none |
| marker | review receipt marker | none; an explicit no-marker mode exists but was not requested |
| timeout_s | seconds before giving up | 60 |

For the owner's proposed first invocation, compute settings after portability
work, not what the old wrapper would silently use.
