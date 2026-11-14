"""Provider-independent machine-review evidence schema (stdlib only).

The digest proves the embedded report's integrity, not reviewer identity or that
an LLM ran. Operators must retain the actual invocation and its report artifact.
"""

import hashlib
import json
import re

DEFAULT_MARKER = "machine-review-state:v1"
FULL_SHA = re.compile(r"[0-9a-fA-F]{40}\Z")
REPORT_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class EvidenceError(ValueError):
    pass


def full_sha(value):
    return isinstance(value, str) and FULL_SHA.fullmatch(value) is not None


def nonempty_text(value):
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        return False
    return True


def report_digest(report):
    """Hash exact UTF-8 bytes: no newline or Unicode normalization."""
    return hashlib.sha256(report.encode("utf-8", errors="strict")).hexdigest()


def validate_marker(marker):
    if not isinstance(marker, str) or re.fullmatch(r"[A-Za-z0-9_.:-]+", marker) is None:
        raise EvidenceError("marker must be a nonempty token (letters, digits, _, ., :, -)")
    return marker


def _unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise EvidenceError(f"duplicate JSON key: {key}")
        obj[key] = value
    return obj


def _reject_constant(value):
    raise EvidenceError(f"non-JSON constant: {value}")


def parse_marker(body, marker=DEFAULT_MARKER):
    """Parse only the first marker occurrence; never rescue malformed evidence.

    Accept a marker followed immediately by whitespace and JSON, optionally
    enclosed in an HTML comment. Do not scan ahead for a brace: that can turn a
    malformed array or prose into apparently valid evidence.
    """
    validate_marker(marker)
    if not isinstance(body, str) or marker not in body:
        raise EvidenceError("marker absent")
    start = body.index(marker) + len(marker)
    tail = body[start:].lstrip()
    try:
        obj, end = json.JSONDecoder(
            object_pairs_hook=_unique_object, parse_constant=_reject_constant
        ).raw_decode(tail)
    except (ValueError, RecursionError) as exc:
        raise EvidenceError(f"marker unparsable: {exc}") from exc
    suffix = tail[end:].lstrip()
    prefix = body[: start - len(marker)].rstrip()
    if prefix.endswith("<!--"):
        if not suffix.startswith("-->"):
            raise EvidenceError("marker HTML comment not closed immediately after JSON")
    elif suffix:
        raise EvidenceError("unexpected text after marker JSON")
    if not isinstance(obj, dict):
        raise EvidenceError("marker JSON must be an object")
    return obj


def review_facts(evidence, head_sha):
    """Fail closed on any missing/malformed field; current head must match exactly."""
    review = evidence.get("code_review") if isinstance(evidence, dict) else None
    if not isinstance(review, dict):
        review = {}
        schema_errors = ["code_review object"]
    else:
        schema_errors = []
    status = review.get("status")
    findings = review.get("has_any_findings")
    commit_sha = review.get("commit_sha")
    model = review.get("model")
    provider = review.get("provider")
    report = review.get("report")
    digest = review.get("report_sha256")
    head_match = full_sha(head_sha) and full_sha(commit_sha) and head_sha == commit_sha
    report_valid = nonempty_text(report)
    hash_match = (
        report_valid
        and isinstance(digest, str)
        and REPORT_SHA256.fullmatch(digest) is not None
        and report_digest(report) == digest
    )
    reasons = list(schema_errors)
    if not isinstance(status, str) or status != "completed":
        reasons.append("status")
    if findings is not False:
        reasons.append("findings")
    if not head_match:
        reasons.append("sha")
    if not nonempty_text(model):
        reasons.append("model")
    if not nonempty_text(provider):
        reasons.append("provider")
    if not report_valid:
        reasons.append("report")
    if not hash_match:
        reasons.append("report_sha256")
    return {
        "pass": not reasons,
        "status": status,
        "has_any_findings": findings,
        "commit_sha": commit_sha,
        "head_match": head_match,
        "model": model,
        "provider": provider,
        "report_valid": report_valid,
        "report_sha256": digest,
        "hash_match": bool(hash_match),
        "reason": ",".join(reasons) if reasons else "ok",
    }


def make_evidence(report_bytes, head_sha, model, provider, findings):
    """Create completed evidence without inferring the report's findings."""
    if not isinstance(report_bytes, bytes):
        raise EvidenceError("report must be bytes")
    try:
        report = report_bytes.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise EvidenceError("report must be valid UTF-8") from exc
    if type(findings) is not bool:
        raise EvidenceError("findings must be an explicit boolean")
    evidence = {"code_review": {
        "status": "completed",
        "has_any_findings": findings,
        "commit_sha": head_sha,
        "model": model,
        "provider": provider,
        "report": report,
        "report_sha256": report_digest(report),
    }}
    facts = review_facts(evidence, head_sha)
    # A completed report with findings is valid evidence, but never merge permission.
    if facts["reason"] not in {"ok", "findings"}:
        raise EvidenceError(f"invalid review evidence: {facts['reason']}")
    return evidence


def evidence_comment(evidence, marker=DEFAULT_MARKER):
    """JSON escaping preserves report bytes while keeping HTML delimiters inert."""
    validate_marker(marker)
    payload = json.dumps(evidence, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    for char in "<>&":
        payload = payload.replace(char, f"\\u{ord(char):04x}")
    # Preambles and HTML delimiters can collide with supported custom tokens.
    return f"{marker} {payload}\n"
