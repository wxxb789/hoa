"""Pure, deterministic approval resolution for distillation candidates."""
from __future__ import annotations


def resolve_approval(candidates: list[dict], approval_token: object) -> dict:
    """Create at most one asset, and only when the approval is unambiguous.

    The gate refuses (creates nothing) unless EVERY candidate has a present,
    non-empty, string id AND all ids are unique - duplicate, missing, or
    non-string ids make "which candidate is approved" ambiguous, so no asset is
    created. With unambiguous ids, exactly the single candidate whose id equals
    a non-empty string approval_token AND whose state is "ready-for-review" is
    created; a group / None / unknown / non-ready token creates nothing.
    """
    ids = [candidate.get("id") for candidate in candidates]
    string_ids = [identifier for identifier in ids if isinstance(identifier, str) and identifier]
    ids_unambiguous = len(string_ids) == len(ids) == len(set(string_ids))

    ready_matches = [
        candidate
        for candidate in candidates
        if ids_unambiguous
        and isinstance(approval_token, str)
        and approval_token
        and candidate.get("id") == approval_token
        and candidate.get("state") == "ready-for-review"
    ]
    created = [approval_token] if len(ready_matches) == 1 else []
    non_terminal = [
        identifier
        for candidate in candidates
        if isinstance((identifier := candidate.get("id")), str)
        and candidate.get("state") != "rejected"
        and identifier not in created
    ]
    if not ids_unambiguous:
        reason = "ambiguous-candidate-ids"
    elif created:
        reason = "single-ready-for-review-approval"
    else:
        reason = "ambiguous-or-no-single-approval"
    return {"created": created, "non_terminal": non_terminal, "reason": reason}
