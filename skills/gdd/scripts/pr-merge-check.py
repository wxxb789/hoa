#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Mechanical merge gate for one PR: may it be squashed or queued for auto-merge?

By default this is read-only. With --auto, confirmed required status checks plus
allow_auto_merge delegate CI to GitHub, and passing the other gates submits the
auto-merge request for the full, verified PR head. Unconfirmed capability keeps
the ordinary manual gate. A submitted request is not proof of landing.

Usage:
    pr-merge-check.py 123 --repo PATH --gates-rc 0 --verified-head SHA
    pr-merge-check.py 123 --repo PATH --gates-rc 0 --verified-head SHA --json
    pr-merge-check.py 123 --repo PATH --gates-rc 0 --verified-head SHA --auto
    pr-merge-check.py 123 --repo PATH --marker 'my-bot-state:v2'
    pr-merge-check.py 123 --repo PATH --allow-no-machine-review
    pr-merge-check.py 123 --repo PATH --gates-rc 0 --verified-head SHA --allow-no-checks
    pr-merge-check.py --selftest

Exit codes: 0 MERGE-OK or MERGE-QUEUED, 1 BLOCKED, 2 usage/gh/git error.

Checks:
  1. Manual CI reads `gh pr checks --json name,state,bucket`. All checks must
     pass, skip or be neutral; unknown buckets block. An unreadable response
     exits 2. `--allow-no-checks` accepts only a confirmed zero-check result.
  2. Newest --marker comment: completed, no findings, full 40-hex commit_sha
     equal to the PR head, nonempty model/provider, and full UTF-8 report with
     matching SHA256. A malformed newest marker blocks older evidence.
     --allow-no-machine-review accepts only the absence of the selected marker.
  3. No unresolved review threads.
  4. Local gates supplied via --gates-rc 0 count only on the verified head.

Head precondition: verify the exact full PR head via --verified-head (the SHA
the gates ran on) or local HEAD when the PR branch is checked out.

Environment: none. All inputs are flags, so a merge decision is reproducible
from the command line. Launcher: not used — this tool starts no run.
"""

import argparse
import json
import os
import re
import gdd_process
import sys
from datetime import datetime
from urllib.parse import quote

from machine_review import (
    DEFAULT_MARKER, EvidenceError, make_evidence, parse_marker, review_facts, validate_marker,
)

GOOD_CONCLUSIONS = {"SUCCESS", "SKIPPED", "NEUTRAL"}
# A conclusion that waits: never ok, and reported as pending rather than failing so the verdict
# reason names the real state (`checks pending`, not `checks`).
PENDING_CONCLUSIONS = {"PENDING"}
# Only the structured bucket is authoritative; unknown tokens are pending.
CHECK_VOCABULARY = {
    "pass": "SUCCESS",
    "skipping": "SKIPPED",
    "neutral": "NEUTRAL",
    "fail": "FAILURE",
    "cancel": "CANCELLED",
    "pending": "PENDING",
}
GRAPHQL = (
    "query($owner:String!,$repo:String!,$pr:Int!,$cursor:String){"
    "repository(owner:$owner,name:$repo){pullRequest(number:$pr){"
    "reviewThreads(first:100,after:$cursor){pageInfo{hasNextPage endCursor}"
    "nodes{isResolved path line}}}}}"
)


class GateError(Exception):
    pass


def sh_raw(cmd, cwd=None):
    """Run cmd and hand back (returncode, stdout, stderr); a non-zero exit is data, not an error."""
    try:
        proc = gdd_process.run(cmd, cwd=cwd, capture_output=True, text=True)
    except OSError as exc:
        raise GateError(str(exc)) from exc
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def sh(cmd, cwd=None):
    returncode, stdout, stderr = sh_raw(cmd, cwd)
    if returncode != 0:
        reason = (stderr or stdout or f"exit {returncode}").strip()
        raise GateError(reason.splitlines()[0] if reason else f"exit {returncode}")
    return stdout.strip()


def extract_marker(body, marker=DEFAULT_MARKER):
    """Strict first-marker parsing, including duplicate-key rejection."""
    try:
        return parse_marker(body, marker)
    except EvidenceError:
        return None


def evaluate_review(
    comments, head_sha, marker=DEFAULT_MARKER, allow_no_machine_review=False
):
    """comments are newest-first. Pure: no gh/git."""
    validate_marker(marker)
    for comment in comments or []:
        if not isinstance(comment, dict):
            raise GateError("comment must be an object")
        body = comment.get("body", "")
        if body is None:
            body = ""
        if not isinstance(body, str):
            raise GateError("comment body must be text")
        if marker not in body:
            continue
        parsed = extract_marker(body, marker)
        if parsed is None:
            return {
                "found": True,
                "allowed": False,
                "pass": False,
                "status": None,
                "has_any_findings": None,
                "commit_sha": None,
                "head_match": False,
                "comment_id": comment.get("id"),
                "reason": "marker unparsable",
            }
        return {
            **review_facts(parsed, head_sha),
            "found": True,
            "allowed": False,
            "comment_id": comment.get("id"),
        }
    return {
        "found": False,
        "allowed": bool(allow_no_machine_review),
        "pass": bool(allow_no_machine_review),
        "status": None,
        "has_any_findings": None,
        "commit_sha": None,
        "head_match": False,
        "comment_id": None,
        "reason": "none" if allow_no_machine_review else "marker unknown",
    }


def evaluate_checks(checks, allow_no_checks=False):
    """A PR with no check runs is not green: no workflow ran, or none was dispatched."""
    total = len(checks)
    ok = pending = failing = 0
    for check in checks:
        state = str(check.get("state") or "").upper()
        conclusion = str(check.get("conclusion") or "").upper()
        if state == "COMPLETED" and conclusion in GOOD_CONCLUSIONS:
            ok += 1
        elif state in {"PENDING", "QUEUED", "IN_PROGRESS", "WAITING"}:
            pending += 1
        else:
            failing += 1
    if total == 0:
        return {
            "total": 0,
            "ok": 0,
            "pending": 0,
            "failing": 0,
            "pass": bool(allow_no_checks),
            "reason": "no checks (allowed by flag)" if allow_no_checks else "no checks",
        }
    return {
        "total": total,
        "ok": ok,
        "pending": pending,
        "failing": failing,
        "pass": pending == 0 and failing == 0,
        "reason": "ok" if pending == 0 and failing == 0 else "checks not green",
    }


def bucket_check(entry):
    """One `--json name,state,bucket` row, in the state/conclusion vocabulary evaluate_checks reads."""
    bucket = str(entry.get("bucket") or "").lower()
    conclusion = CHECK_VOCABULARY.get(bucket)
    # A declared pending bucket and an unknown one alike carry no completed verdict, so both reach
    # evaluate_checks as a pending state — an unknown bucket with no conclusion to report either.
    waits = conclusion is None or conclusion in PENDING_CONCLUSIONS
    return {
        "name": entry.get("name"),
        "state": "PENDING" if waits else "COMPLETED",
        "conclusion": conclusion,
    }


def fetch_checks(pr, repo):
    returncode, stdout, stderr = sh_raw(
        ["gh", "pr", "checks", str(pr), "--json", "name,state,bucket"], cwd=repo
    )
    if returncode == 0:
        try:
            data = json.loads(stdout)
        except ValueError as exc:
            raise GateError(f"gh pr checks --json: malformed output: {exc}") from exc
        if not isinstance(data, list):
            raise GateError("gh pr checks --json: expected a list of checks")
        for entry in data:
            if not isinstance(entry, dict):
                raise GateError(
                    "gh pr checks --json: expected an object per check, got "
                    + type(entry).__name__
                )
        return [bucket_check(entry) for entry in data]

    # gh reports an empty rollup as an error before reaching its JSON exporter.
    if (returncode == 1 and not stdout.strip()
            and re.fullmatch(r"no checks reported on the '[^\r\n]+' branch", stderr.strip())):
        return []
    detail = (stderr or stdout).strip().splitlines()
    raise GateError(f"gh pr checks --json: exit {returncode}" + (f": {detail[0]}" if detail else ""))


def fetch_review_threads(owner, name, pr, repo):
    """Every review thread, following pageInfo — a 100-thread PR must not hide one."""
    nodes, cursor = [], None
    while True:
        args = [
            "gh", "api", "graphql",
            "-f", f"query={GRAPHQL}",
            "-f", f"owner={owner}",
            "-f", f"repo={name}",
            "-F", f"pr={pr}",
        ]
        if cursor:
            args.extend(["-f", f"cursor={cursor}"])
        payload = json.loads(sh(args, cwd=repo))
        if payload.get("errors"):
            raise GateError(f"graphql: {payload['errors']}")
        block = (
            payload.get("data", {})
            .get("repository", {})
            .get("pullRequest", {})
            .get("reviewThreads", {})
            or {}
        )
        nodes.extend(block.get("nodes") or [])
        page = block.get("pageInfo") or {}
        cursor = page.get("endCursor")
        if not page.get("hasNextPage") or not cursor:
            return nodes


def fetch_issue_comments(owner, name, pr, repo):
    """Every issue comment, oldest first — `gh pr view --json comments` truncates on big PRs."""
    comments, page = [], 1
    while True:
        raw = sh(
            ["gh", "api",
             f"repos/{owner}/{name}/issues/{pr}/comments?per_page=100&page={page}"],
            cwd=repo,
        )
        batch = json.loads(raw or "[]")
        if not isinstance(batch, list):
            raise GateError("gh api comments: expected a JSON array")
        comments.extend(batch)
        if len(batch) < 100:
            return comments
        page += 1


def evaluate_pr_state(state, is_draft):
    """Pure. A merged/closed PR or a draft can never be merged right now."""
    facts = {"state": state or "?", "draft": bool(is_draft), "open": state == "OPEN"}
    if state != "OPEN":
        return facts, ["pr not open"]
    if facts["draft"]:
        return facts, ["pr is draft"]
    return facts, []


def pr_state_line(facts):
    state = facts.get("state") or "?"
    if state != "OPEN":
        return f"state: {state} (not open)"
    if facts.get("draft"):
        return "state: OPEN draft: yes"
    return "state: OPEN"


def resolve_head(head, ref, local_head, local_branch, verified_head):
    """Pure. Decide how the PR head was verified: (facts, reasons, verified)."""
    facts = {
        "local": local_head,
        "remote": head,
        "ref": ref,
        "verified": verified_head or None,
        "match": None,
    }
    if verified_head:
        facts["mode"] = "verified"
        facts["match"] = verified_head == head and bool(re.fullmatch(r"[0-9a-f]{40}", head))
        if not facts["match"]:
            return facts, ["head mismatch"], False
        return facts, [], True
    if ref and local_branch == ref:
        facts["mode"] = "local"
        facts["match"] = local_head == head and bool(re.fullmatch(r"[0-9a-f]{40}", head))
        if not facts["match"]:
            return facts, ["head mismatch"], False
        return facts, [], True
    facts["mode"] = "unknown"
    return facts, ["head not verified"], False


def head_line(head):
    remote = str(head.get("remote") or "")[:7]
    mode = head.get("mode")
    if mode == "verified":
        return "head: {} verified {} {}".format(
            remote,
            str(head.get("verified") or "")[:7],
            "match" if head.get("match") else "MISMATCH",
        )
    if mode == "local":
        return "head: {} local {} {}".format(
            remote,
            str(head.get("local") or "")[:7],
            "match" if head.get("match") else "MISMATCH",
        )
    return "head: {} local: branch {} not checked out".format(
        remote, head.get("ref") or "?"
    )


def evaluate_gates(gates_rc, gates_note, head_verified, now):
    """Pure. A gate result only counts when the head it ran on is known."""
    facts = {"rc": gates_rc, "ts": now, "note": gates_note, "pass": None}
    if gates_rc is None:
        facts["status"] = "UNKNOWN"
        return facts, ["gates missing"]
    if not head_verified:
        facts["status"] = "UNKNOWN"
        return facts, ["verified head missing"]
    facts["pass"] = gates_rc == 0
    facts["status"] = "PASS" if facts["pass"] else "FAIL"
    return facts, [] if facts["pass"] else ["gates unverified"]


def supports_auto_merge(repo, name_with_owner, base):
    """Only positive evidence permits GitHub to take over the CI gate."""
    if not isinstance(base, str) or not base:
        return False
    endpoint = f"repos/{name_with_owner}"

    def api(path, *args):
        try:
            return json.loads(sh(["gh", "api", endpoint + path, *args], cwd=repo))
        except (GateError, ValueError):
            return None

    def named_checks(rows):
        return isinstance(rows, list) and any(
            isinstance(row, dict) and isinstance(row.get("context"), str) and row["context"].strip()
            for row in rows
        )

    if api("", "-q", ".allow_auto_merge") is not True:
        return False
    branch = quote(base, safe="")
    pages = api(f"/rules/branches/{branch}", "--paginate", "--slurp")
    if isinstance(pages, list) and any(
        isinstance(rule, dict) and rule.get("type") == "required_status_checks"
        and isinstance(rule.get("parameters"), dict)
        and named_checks(rule["parameters"].get("required_status_checks"))
        for page in pages if isinstance(page, list) for rule in page
    ):
        return True

    classic = api(f"/branches/{branch}/protection/required_status_checks")
    if not isinstance(classic, dict):
        return False
    contexts = classic.get("contexts")
    return named_checks(classic.get("checks")) or (
        isinstance(contexts, list)
        and any(isinstance(context, str) and context.strip() for context in contexts)
    )


def evaluate_ci(pr, repo, facts, reasons, allow_no_checks):
    checks = evaluate_checks(fetch_checks(pr, repo), allow_no_checks=allow_no_checks)
    facts["checks"] = checks
    facts["checks_source"] = "json"
    if not checks["pass"]:
        if checks["total"] == 0:
            reasons.append("no checks")
        elif checks["pending"] and not checks["failing"]:
            # A run still in flight is not a failure; the verdict must say which it is.
            reasons.append("checks pending")
        else:
            reasons.append("checks")


def evaluate(
    pr,
    repo,
    gates_rc,
    gates_note=None,
    verified_head=None,
    marker=DEFAULT_MARKER,
    allow_no_machine_review=False,
    allow_no_checks=False,
    auto=False,
):
    facts = {"pr": int(pr) if str(pr).isdigit() else pr, "gates": {}, "marker": marker}
    reasons = []
    now = datetime.now().astimezone().isoformat(timespec="seconds")

    local_head = sh(["git", "-C", repo, "rev-parse", "HEAD"])
    local_branch = sh(["git", "-C", repo, "rev-parse", "--abbrev-ref", "HEAD"])
    view_cmd = [
        "gh", "pr", "view", str(pr), "--json", "headRefOid,headRefName,state,isDraft",
    ]
    if auto:
        view_cmd[-1] += ",baseRefName"
    view = json.loads(sh(view_cmd, cwd=repo))
    pr_state, state_reasons = evaluate_pr_state(view.get("state"), view.get("isDraft"))
    facts["pr_state"] = pr_state
    if state_reasons:
        facts["gates"], _ = evaluate_gates(gates_rc, gates_note, False, now)
        return facts, state_reasons

    head = view.get("headRefOid") or ""
    head_facts, head_reasons, head_verified = resolve_head(
        head, view.get("headRefName"), local_head, local_branch, verified_head,
    )
    facts["head"] = head_facts
    reasons.extend(head_reasons)

    facts["gates"], gate_reasons = evaluate_gates(gates_rc, gates_note, head_verified, now)
    reasons.extend(gate_reasons)

    name_with_owner = sh(
        ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
        cwd=repo,
    )
    owner, _, name = name_with_owner.partition("/")

    base = view.get("baseRefName")
    if auto and supports_auto_merge(repo, name_with_owner, base):
        facts["checks_source"] = "github"
        facts["base"] = base
    else:
        evaluate_ci(pr, repo, facts, reasons, allow_no_checks)

    comments = fetch_issue_comments(owner, name, pr, repo)
    review = evaluate_review(
        list(reversed(comments)), head, marker, allow_no_machine_review
    )
    facts["review"] = review
    if not review["pass"]:
        reasons.append(review["reason"] if not review["found"] else "review")

    nodes = fetch_review_threads(owner, name, pr, repo)
    unresolved = [node for node in nodes if not node.get("isResolved")]
    facts["threads"] = {
        "total": len(nodes),
        "unresolved": len(unresolved),
        "pass": len(unresolved) == 0,
    }
    if unresolved:
        reasons.append("threads")

    facts["repo"] = name_with_owner
    return facts, reasons


def print_human(facts, reasons):
    if facts.get("pr_state"):
        print(pr_state_line(facts["pr_state"]))
    head = facts.get("head")
    if head:
        print(head_line(head))
    checks = facts.get("checks")
    if checks:
        print(
            "checks: {} total, {} ok, {} pending, {} failing{}".format(
                checks["total"],
                checks["ok"],
                checks["pending"],
                checks["failing"],
                " (no checks)" if checks["total"] == 0 else "",
            )
        )
    elif facts.get("checks_source") == "github":
        print(f"checks: enforced by GitHub on {facts['base']}")
    review = facts.get("review")
    if review:
        marker = facts.get("marker") or DEFAULT_MARKER
        if review["found"]:
            findings = review["has_any_findings"]
            findings_text = "-" if findings is None else json.dumps(findings)
            print(
                "review: marker={} status={} findings={} sha={} head_match={} comment={} "
                "model={} provider={} report_hash={} reason={}".format(
                    marker,
                    review["status"],
                    findings_text,
                    str(review["commit_sha"])[:7] if review["commit_sha"] else "-",
                    "yes" if review["head_match"] else "no",
                    review["comment_id"] if review["comment_id"] is not None else "-",
                    review.get("model") or "-",
                    review.get("provider") or "-",
                    "match" if review.get("hash_match") else "INVALID",
                    review["reason"],
                )
            )
        elif review.get("allowed"):
            print(
                "review: marker: none (no {!r} comment; accepted by "
                "--allow-no-machine-review)".format(marker)
            )
        else:
            print(
                "review: marker: UNKNOWN (no {!r} comment; blocked)".format(marker)
            )
    threads = facts.get("threads")
    if threads:
        print(f"threads: {threads['unresolved']} unresolved of {threads['total']}")
    gates = facts["gates"]
    note = f" note={gates['note']}" if gates.get("note") else ""
    if gates.get("status") == "UNKNOWN":
        print(
            "gates: UNKNOWN (rc={}) at {}{}".format(
                gates["rc"] if gates["rc"] is not None else "-", gates["ts"], note
            )
        )
    else:
        print(
            "gates: rc={} at {}{}".format(
                gates["rc"] if gates["rc"] is not None else "-", gates["ts"], note
            )
        )
    verdict = facts.get("verdict", "MERGE-OK") if not reasons else "BLOCKED: " + ", ".join(reasons)
    print(f"verdict: {verdict}")


def selftest():
    head = "abc1234" + "0" * 33
    other = "5a6d4ea" + "0" * 33
    ref = "feat/x"
    marker_ok = make_evidence(b"No findings.\n", head, "fixture-model", "fixture-provider", False)
    marker_findings = make_evidence(b"One finding.\n", head, "fixture-model", "fixture-provider", True)
    marker_old = make_evidence(b"No findings.\n", other, "fixture-model", "fixture-provider", False)
    custom_marker = "alt-review-state:v2"
    marker_cases = [
        (
            "marker-clean-on-head",
            [{"id": 1, "body": DEFAULT_MARKER + "\n" + json.dumps(marker_ok)}],
            DEFAULT_MARKER,
            False,
            True,
            "ok",
        ),
        (
            "marker-stale-sha",
            [{"id": 2, "body": DEFAULT_MARKER + "\n" + json.dumps(marker_old)}],
            DEFAULT_MARKER,
            False,
            False,
            "sha",
        ),
        (
            "marker-with-findings",
            [{"id": 3, "body": DEFAULT_MARKER + "\n" + json.dumps(marker_findings)}],
            DEFAULT_MARKER,
            False,
            False,
            "findings",
        ),
        (
            "marker-unparsable",
            [{"id": 4, "body": DEFAULT_MARKER + "\n{not json"}],
            DEFAULT_MARKER,
            False,
            False,
            "marker unparsable",
        ),
        (
            "marker-absent-blocked",
            [{"id": 5, "body": "looks good to me"}],
            DEFAULT_MARKER,
            False,
            False,
            "marker unknown",
        ),
        (
            "marker-absent-allowed",
            [{"id": 6, "body": "looks good to me"}],
            DEFAULT_MARKER,
            True,
            True,
            "none",
        ),
        (
            "custom-marker-absent-by-default",
            [{"id": 7, "body": custom_marker + "\n" + json.dumps(marker_ok)}],
            DEFAULT_MARKER,
            False,
            False,
            "marker unknown",
        ),
        (
            "custom-marker-present",
            [{"id": 8, "body": custom_marker + "\n" + json.dumps(marker_ok)}],
            custom_marker,
            False,
            True,
            "ok",
        ),
        (
            "newest-bad-blocks-older-clean-even-with-opt-out",
            [
                {"id": 10, "body": DEFAULT_MARKER + "\n{not json"},
                {"id": 9, "body": DEFAULT_MARKER + "\n" + json.dumps(marker_ok)},
            ],
            DEFAULT_MARKER,
            True,
            False,
            "marker unparsable",
        ),
    ]
    head_cases = [
        (
            "verified-head-match",
            (head, ref, other, "main", head),
            "head: abc1234 verified abc1234 match",
            [],
            True,
        ),
        (
            "verified-head-mismatch",
            (head, ref, other, "main", other),
            "head: abc1234 verified 5a6d4ea MISMATCH",
            ["head mismatch"],
            False,
        ),
        (
            "no-verified-head-no-local-branch",
            (head, ref, other, "main", None),
            "head: abc1234 local: branch feat/x not checked out",
            ["head not verified"],
            False,
        ),
        (
            "local-branch-match",
            (head, ref, head, ref, None),
            "head: abc1234 local abc1234 match",
            [],
            True,
        ),
    ]
    gate_cases = [
        ("gates-unknown-without-rc", (None, None, True), ["gates missing"], "UNKNOWN"),
        ("gates-unknown-without-head", (0, None, False), ["verified head missing"], "UNKNOWN"),
        ("gates-pass-on-verified-head", (0, None, True), [], "PASS"),
        ("gates-fail-on-verified-head", (1, None, True), ["gates unverified"], "FAIL"),
    ]
    state_cases = [
        (
            "merged-pr-not-mergeable",
            ("MERGED", False),
            "state: MERGED (not open)",
            ["pr not open"],
        ),
        (
            "closed-pr-not-mergeable",
            ("CLOSED", False),
            "state: CLOSED (not open)",
            ["pr not open"],
        ),
        (
            "draft-pr-not-mergeable",
            ("OPEN", True),
            "state: OPEN draft: yes",
            ["pr is draft"],
        ),
        (
            "open-ready-pr",
            ("OPEN", False),
            "state: OPEN",
            [],
        ),
    ]
    check_cases = [
        ("no-checks-refuses", ([], False), (False, "no checks")),
        ("no-checks-allowed-by-flag", ([], True), (True, "no checks (allowed by flag)")),
        (
            "checks-pending-blocks",
            ([{"state": "PENDING", "conclusion": None}], False),
            (False, "checks not green"),
        ),
        (
            "checks-failing-blocks",
            ([{"state": "COMPLETED", "conclusion": "FAILURE"}], False),
            (False, "checks not green"),
        ),
        (
            "checks-all-green-passes",
            (
                [
                    {"state": "COMPLETED", "conclusion": "SUCCESS"},
                    {"state": "COMPLETED", "conclusion": "SKIPPED"},
                ],
                False,
            ),
            (True, "ok"),
        ),
    ]
    bucket_cases = [
        ("bucket-pass", "SUCCESS", "pass", ("COMPLETED", "SUCCESS")),
        ("bucket-skipping", "SKIPPED", "skipping", ("COMPLETED", "SKIPPED")),
        ("bucket-neutral", "NEUTRAL", "neutral", ("COMPLETED", "NEUTRAL")),
        ("bucket-fail", "FAILURE", "fail", ("COMPLETED", "FAILURE")),
        ("bucket-cancel", "CANCELLED", "cancel", ("COMPLETED", "CANCELLED")),
        ("bucket-pending", "PENDING", "pending", ("PENDING", "PENDING")),
        ("bucket-unreleased", "MYSTERY", "unreleased-bucket", ("PENDING", None)),
        # The bucket is the authority: a recognized raw state under an unknown bucket is pending.
        ("bucket-unknown-with-success-state", "SUCCESS", "unreleased-bucket", ("PENDING", None)),
    ]
    total = (
        len(marker_cases)
        + len(head_cases)
        + len(gate_cases)
        + len(state_cases)
        + len(check_cases)
        + len(bucket_cases)
        + 1  # bucket tally
    )
    passed = 0

    for name, comments, marker, allow, expected_pass, expected_reason in marker_cases:
        result = evaluate_review(comments, head, marker, allow)
        actual = (result["pass"], result["reason"])
        expected = (expected_pass, expected_reason)
        mark = "ok" if actual == expected else "FAIL"
        print(
            f"  {mark}  {name}: pass={actual[0]} reason={actual[1]} "
            f"allowed={result['allowed']}"
        )
        passed += 1 if actual == expected else 0

    for name, args, expected_line, expected_reasons, expected_verified in head_cases:
        facts, reasons, verified = resolve_head(*args)
        actual = (head_line(facts), reasons, verified)
        expected = (expected_line, expected_reasons, expected_verified)
        mark = "ok" if actual == expected else "FAIL"
        print(f"  {mark}  {name}: {actual[0]!r} reasons={actual[1]} verified={actual[2]}")
        passed += 1 if actual == expected else 0

    for name, args, expected_reasons, expected_status in gate_cases:
        gates, reasons = evaluate_gates(*args, now="ts")
        actual = (reasons, gates["status"])
        expected = (expected_reasons, expected_status)
        mark = "ok" if actual == expected else "FAIL"
        print(f"  {mark}  {name}: status={gates['status']} reasons={reasons}")
        passed += 1 if actual == expected else 0

    for name, args, expected in check_cases:
        result = evaluate_checks(*args)
        actual = (result["pass"], result["reason"])
        mark = "ok" if actual == expected else "FAIL"
        print(
            f"  {mark}  {name}: total={result['total']} pass={actual[0]} reason={actual[1]}"
        )
        passed += 1 if actual == expected else 0

    for name, state, bucket, expected in bucket_cases:
        row = bucket_check({"name": name, "state": state, "bucket": bucket})
        actual = (row["state"], row["conclusion"])
        mark = "ok" if actual == expected else "FAIL"
        print(f"  {mark}  {name}: state={actual[0]} conclusion={actual[1]}")
        passed += 1 if actual == expected else 0

    tally = evaluate_checks(
        [
            bucket_check({"name": name, "state": state, "bucket": bucket})
            for name, state, bucket, _ in bucket_cases
        ]
    )
    actual = (tally["total"], tally["ok"], tally["pending"], tally["failing"], tally["pass"])
    expected = (8, 3, 3, 2, False)
    mark = "ok" if actual == expected else "FAIL"
    print(f"  {mark}  bucket-tally: total/ok/pending/failing/pass={actual}")
    passed += 1 if actual == expected else 0

    for name, args, expected_line, expected_reasons in state_cases:
        pr_state, reasons = evaluate_pr_state(*args)
        actual = (pr_state_line(pr_state), reasons)
        expected = (expected_line, expected_reasons)
        mark = "ok" if actual == expected else "FAIL"
        print(f"  {mark}  {name}: {actual[0]!r} reasons={actual[1]}")
        passed += 1 if actual == expected else 0

    print(f"selftest: {passed}/{total} ok")
    return 0 if passed == total else 1


def build_parser():
    parser = argparse.ArgumentParser(
        description="Mechanical merge gate for one PR.",
        epilog="Exit 0 MERGE-OK or MERGE-QUEUED, 1 BLOCKED, 2 usage/gh/git error.",
    )
    parser.add_argument("pr", nargs="?", help="PR number")
    parser.add_argument("--repo", default=os.getcwd(), help="repo path (default: cwd)")
    parser.add_argument("--gates-rc", type=int, default=None, help="local gate exit code")
    parser.add_argument("--gates-note", default=None, help="gate context")
    parser.add_argument(
        "--verified-head",
        default=None,
        help="SHA the gates actually ran on (required to make --gates-rc count)",
    )
    parser.add_argument(
        "--marker",
        default=DEFAULT_MARKER,
        help="machine-review marker token; same strict evidence schema for all markers (default: %(default)s)",
    )
    parser.add_argument(
        "--allow-no-machine-review",
        action="store_true",
        help="accept a repo with no machine-review marker (prints `marker: none`)",
    )
    parser.add_argument(
        "--allow-no-checks",
        action="store_true",
        help="accept a PR with zero check runs (only for repos with no CI; explicit opt-out)",
    )
    parser.add_argument("--json", action="store_true", help="emit one JSON object")
    parser.add_argument("--auto", action="store_true",
                        help="submit auto-merge if GitHub enforces required checks; otherwise gate only")
    parser.add_argument("--selftest", action="store_true", help="offline fixture test")
    return parser


def main():
    args = build_parser().parse_args()
    if args.selftest:
        return selftest()
    if not args.pr:
        print("pr-merge-check: PR number is required", file=sys.stderr)
        return 2
    if not str(args.pr).isdigit():
        print(f"pr-merge-check: PR must be numeric, got {args.pr!r}", file=sys.stderr)
        return 2
    try:
        validate_marker(args.marker)
        facts, reasons = evaluate(
            args.pr,
            args.repo,
            args.gates_rc,
            args.gates_note,
            verified_head=args.verified_head,
            marker=args.marker,
            allow_no_machine_review=args.allow_no_machine_review,
            allow_no_checks=args.allow_no_checks,
            auto=args.auto,
        )
        verdict = "BLOCKED" if reasons else "MERGE-OK"
        if not reasons and facts.get("checks_source") == "github":
            sh(["gh", "pr", "merge", args.pr, "--auto", "--squash", "--match-head-commit",
                facts["head"]["remote"]], cwd=args.repo)
            verdict = "MERGE-QUEUED"
    except (GateError, ValueError, KeyError) as exc:
        print(f"pr-merge-check: {exc}", file=sys.stderr)
        return 2
    facts["verdict"] = verdict
    facts["reasons"] = reasons
    if args.json:
        print(json.dumps(facts, indent=2, ensure_ascii=False))
    else:
        print_human(facts, reasons)
    return 0 if not reasons else 1


if __name__ == "__main__":
    sys.exit(main())
