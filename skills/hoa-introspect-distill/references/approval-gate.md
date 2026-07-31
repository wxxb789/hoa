# Approval gate state machine

`scripts/approval.py` is the executable source of truth. Its pure, deterministic
`resolve_approval(candidates, approval_token)` returns:

```json
{"created": ["id"], "non_terminal": ["id"], "reason": "..."}
```

Each candidate is independent. This prevents approval for a useful item from
being misread as permission to create adjacent ideas.

```text
draft ──present──> ready-for-review ──explicit single approval──> approved ──create──> terminal
                          │                           │
                          │                           └──creation failure──> needs-revision
                          ├──specific feedback──> needs-revision ──revised──> ready-for-review
                          └──explicit rejection──────────────────────────────> rejected (terminal)
```

## Resolution contract

- A candidate has an `id` string and one state: `draft`, `ready-for-review`,
  `approved`, `rejected`, or `needs-revision`.
- Create **exactly one** candidate only when `approval_token` is one non-empty
  string that equals the `id` of exactly one `ready-for-review` candidate.
  The result is `{"created": [id], "reason": "single-ready-for-review-approval"}`.
- `None`, an empty token, a list or group token, an unknown id, a non-ready
  candidate, or any non-single match creates nothing. The reason is always
  `ambiguous-or-no-single-approval`.
- Repeating the same valid single approval is idempotent: each resolution
  returns that one id once, never one asset per repetition.
- `non_terminal` contains every candidate except `rejected` and any selected
  id. Thus `draft`, `ready-for-review`, `needs-revision`, and
  `approved-not-selected` remain non-terminal.

## Operational rules

- `draft → ready-for-review`: include identity, contract, workflow, basis,
  intended target, and expected location. Create no file.
- `ready-for-review → needs-revision`: apply specific feedback without changing
  identity. Cap refinement at two rounds by default; then ask to approve,
  reject, or abandon rather than endlessly redraft.
- `approved → terminal`: create only the selected target, validate it, and
  report the creation mechanism and spec-versus-created diff.
- `rejected` is terminal and never retried without a new user request.
- Five candidates is the maximum review set, never a target. Zero candidates
  may qualify; report that honestly and create nothing.
