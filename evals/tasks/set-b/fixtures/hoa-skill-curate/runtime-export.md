# Runtime inventory evidence

| Name | Loads in the last year | Disabled |
|---|---:|---|
| carton-map | 0 | no |
| route-proof | 0 | yes |
| queue-digest | 20 | no |
| bin-audit | 0 | no |
| seal-register | 3 | no |

Reference scan over live docs, scheduled jobs and installed skill bodies:

- `job close-dock`, enabled, next run 2026-11-22: "Use bin-audit for
  designated bins before closing the dock."
- `receipt-review` body, "Historical examples": "During spring intake,
  queue-digest grouped the old queue by hour." The current workflow reads
  the daily receipt directly and does not call queue-digest.
- The identity file and team docs contain no references to these five
  names. There were no other job or body hits.
