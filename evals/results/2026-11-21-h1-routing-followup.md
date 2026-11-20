# H1 retirement routing follow-up

Only the descriptions of `gdd`, `delegated-work-acceptance`, and
`report-claim-audit` were tuned, on DEV only. The English DEV top-1 moved
from 77.78% to 85.62% after label migration, and all nine English merged
requests reached their new owner. No unchanged-label top-1 hit was lost
against main or H1, in either language.

The final descriptions were frozen before a single offline holdout
comparison. Main (`7bd3f3f`) and original H1 (`58252b3`) use the original
labels; the final catalog uses the [label-only migration](../README.md#measure-description-distinctiveness).
The BM25 denominator excludes `none` and labels outside the catalog.

| Catalog | EN N | EN top-1 | EN MRR | ZH N | ZH top-1 | ZH MRR |
|---|---:|---:|---:|---:|---:|---:|
| Main | 148 | 63.51% | 0.7649 | 37 | 21.62% | 0.3125 |
| Original H1 | 128 | 54.69% | 0.7052 | 32 | 18.75% | 0.3085 |
| Final | 140 | 62.86% | 0.7530 | 35 | 17.14% | 0.2838 |

On the unchanged-label cohort (128 EN, 32 ZH), Main to Final was
60.16% / 0.7418 to 61.72% / 0.7448 for EN, and 18.75% / 0.2870 to
18.75% / 0.2957 for ZH. The final catalog had no new top-1 losses on
these rows versus either Main or H1.

| Expected skill | Main hits lost by H1 | Recovered | Final losses vs. Main |
|---|---:|---:|---:|
| `gdd` | 3 | 2 | 1 to `dotnet-repo-workflow` |
| `report-claim-audit` | 3 | 3 | 0 |
| `harness-engineering` | 1 | 1 | 0 |
| `hoa-skill-curate` | 1 | 1 | 0 |

This pinned replay reproduces eight, not nine, unchanged-label English
losses. The cited Hermes-to-package-release row (`r5-holdout-171`) was
already a miss on Main and H1; it remains a miss in Final. A different
Hermes row became a hit. Overall, three unchanged-label English rows
became hits (`gdd-route-omp`, `hermes-ops-claim-verification`, and
`harness-engineering`).

| Retired label | New owner | H1 hits | Final hits (EN + ZH) |
|---|---|---:|---:|
| `cross-agent-repair-routing` | `delegated-work-acceptance` | 0/5 | 3/5 (3 + 0) |
| `project-phase-closeout` | `report-claim-audit` | 3/5 | 3/5 (3 + 0) |
| `ai-coding-agent-delegation` | `gdd` | 3/5 | 3/5 (3 + 0) |

H1 hits in this table count first choices against the new owner, even
though those rows were outside the H1 BM25 denominator. The English
merged rows improved from 5/12 to 9/12, while the sole Chinese hit
(delegation) became an all-zero match. The final Chinese cohort had
21 all-zero rows out of 35; BM25 does not segment Chinese. The full
recovery goal was not met, and no descriptions were changed in response
to the holdout.
