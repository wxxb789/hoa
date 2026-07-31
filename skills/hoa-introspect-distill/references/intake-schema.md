# Minimal intake schema

`hoa-introspect-distill` consumes a repeatable-work finding, not a complete audit bundle.
Keeping the boundary small lets `hoa-introspect` remain optional while preserving evidence
honesty.

```json
{
  "basis": "introspect-report | user-provided",
  "source": "optional report path or section identifier",
  "finding": "the repeatable multi-step work in plain language",
  "evidence": [
    {"origin": "distinct origin identifier", "locator": "re-checkable location"}
  ],
  "projects": ["sanitized project label"],
  "observations": 3,
  "existing_coverage": "optional known skill/rule, if any"
}
```

Rules for interpreting it:

- When history evidence is absent, set `basis` to `user-provided`. That label is valid
  evidence of user intent, not evidence that the work recurs.
- If `basis` is `introspect-report`, preserve provided origin distinctions; do not count
  duplicate transcript/summary copies as independent observations.
- Qualification normally needs stable multi-step work, three observations, and two
  projects. Those evidence thresholds are a preference, not a reason to overwrite a
  direct user request; state the weaker basis instead.
- Redact sensitive values from proposals. A locator may stay in an untracked report but
  should not be copied into a tracked asset.
