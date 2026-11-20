# Release dashboard, auto-assembled after rehearsal

Recommendation: go. The last candidate entry was green, and the historical
importer is substantially faster on the large fixture.

| Rows | Candidate run | Candidate p95 ms | Comparator run | Comparator p95 ms |
|---:|---|---:|---|---:|
| 100 | r01 | 48 | r02 | 61 |
| 500 | r03 | 119 | r04 | 138 |
| 1000 | r08 | 218 | r09 | 9 |

The job titles for r05 and r08 both say "2.4.0". Entries with the same title
and size were grouped by latest completion time.

A second dashboard tab marks replay-06 as serial: it saw no overlap on the
candidate lane or on the comparator lane considered independently. All its
reported candidate workloads were under the ceiling.
