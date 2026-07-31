# L1 facets

These facets use the `/insights`-style approach of deterministic aggregation
followed by narrative. They are not a copy of any third-party prompt. All
values originate in `scripts/aggregate.py` over explicit normalized fields.
Narrative may use untracked `report_language` (default `en-US`), but these
numbers and identifiers are never translated or reformatted.

## `aggregated_data`

- `record_count`: records supplied after deterministic origin de-duplication
  performed upstream.
- `available_agents`: agents with an `available` manifest source.
- `coverage`: manifest statuses and time window, preserved so readers can bound
  every conclusion.
- `measured_records`: denominator availability for each optional facet. A zero
  denominator means **not measured**, never “no usage”.

## `facets_summary`

| Facet | Input fields | Meaning |
| --- | --- | --- |
| `skill_call_frequency` | `skills` or `skill_calls` | Count of explicit skill calls by full name. |
| `plugin_namespace_distribution` | skill names containing `:` | Count by text before the first `:`; names without a namespace are excluded. |
| `mcp_usage` | `mcp` or `mcp_tools` | Calls by exact MCP tool name and measured-record count. |
| `agent_orchestration` | `agent_types` or `uses_agent` | Records with one or more delegated-agent signals divided by records that exposed this measurement. |
| `friction` | `friction_events` | Explicit event counts by normalized event name and measured-record count. |

Percentages are emitted as numeric values rounded to two decimal places. The
aggregator does not derive “friction” from sentiment or search transcript prose:
that would be model interpretation, not an L1 fact.

## Interpretation

Report a missing or zero-denominator facet as “not measured in supplied
records.” A low count can describe only supplied coverage; it cannot prove that
the operator did not use a tool elsewhere. L2 may interpret a repeated pattern
only under the separate evidence rules in `audit-rigor.md`.
