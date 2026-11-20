# Run ledger

| Run | Environment | Observed event |
|---|---|---|
| P-11 | Mock importer, North | Mock stripped fences, then captured release_code D17. Badge: PASS. |
| P-12 | Desktop host, North | Operator used an explicit command to load the workflow; runner confirmed the body was read. Importer stub only. |
| P-13 | Prompt simulator, South | The simulation prepended the workflow body; its catalog heuristic printed auto_selected=yes. No importer. |
| P-14 | Integration shell, North | Shipped dock_import 2.4 parse_only called with the exact north.txt bytes: JSONDecodeError at byte 0. No database connection. |

North came from desktop with an operator-injected body and workspace reads.
South was submitted from an isolated simulator with no file tool; both saw
the same release record as text. No unforced live invocation or staging
transaction receipt was retained for either reply. This packet is the full
available record; staging access is not available during this review.
