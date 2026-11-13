#!/usr/bin/env python3
"""Mechanical merge gate for one PR: may it be squashed right now?

Answers with booleans only. Every fact comes from git/gh; nothing is inferred.

Usage:
    pr-merge-check.py 123 --repo PATH --gates-rc 0 --verified-head SHA
    pr-merge-check.py 123 --repo PATH --gates-rc 0 --verified-head SHA --json
    pr-merge-check.py 123 --repo PATH --marker 'my-bot-state:v2'
    pr-merge-check.py 123 --repo PATH --allow-no-machine-review
    pr-merge-check.py 123 --repo PATH --gates-rc 0 --verified-head SHA --allow-no-checks
    pr-merge-check.py --selftest

Exit codes: 0 MERGE-OK, 1 BLOCKED, 2 usage/gh/git error.

Checks:
  1. every CI check completed with SUCCESS/SKIPPED/NEUTRAL
  2. newest --marker comment: status completed, has_any_findings false, commit_sha
     equal to the PR head. With no marker this clause is UNKNOWN and blocks;
     A PR with zero check runs blocks the merge: no workflow ran, or none was dispatched
     (a CONFLICTING PR gets no workflows at all). `--allow-no-checks` accepts that state
     explicitly, for a repo that has no CI.
     --allow-no-machine-review prints `marker: none` and accepts the clause
     explicitly (never silently).
  3. unresolved review threads == 0
  4. local gates supplied via --gates-rc 0; a gate result only counts when the
     head it ran on is verified, otherwise gates are UNKNOWN

Head precondition: the PR head is verified via --verified-head (the SHA the gates
actually ran on) or, when the PR branch is checked out, via local HEAD.

Environment: none. All inputs are flags, so a merge decision is reproducible
from the command line. Launcher: not used — this tool starts no run.
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime

DEFAULT_MARKER = "codex-review-state:v1"
GOOD_CONCLUSIONS = {"SUCCESS", "SKIPPED", "NEUTRAL"}
GRAPHQL = (
    "query($owner:String!,$repo:String!,$pr:Int!,$cursor:String){"
    "repository(owner:$owner,name:$repo){pullRequest(number:$pr){"
    "reviewThreads(first:100,after:$cursor){pageInfo{hasNextPage endCursor}"
    "nodes{isResolved path line}}}}}"
)
TEXT_CONCLUSIONS = {
    "pass": "SUCCESS",
    "failing": "FAILURE",
    "fail": "FAILURE",
    "skipping": "SKIPPED",
    "skip": "SKIPPED",
    "neutral": "NEUTRAL",
    "cancelled": "CANCELLED",
    "canceled": "CANCELLED",
    "timed_out": "TIMED_OUT",
    "pending": "PENDING",
}


class GateError(Exception):
    pass


def sh(cmd, cwd=None):
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    except OSError as exc:
        raise GateError(str(exc)) from exc
    if proc.returncode != 0:
        reason = (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()
        raise GateError(reason.splitlines()[0] if reason else f"exit {proc.returncode}")
    return proc.stdout.strip()


def extract_marker(body, marker=DEFAULT_MARKER):
    """First JSON object following the marker token in a comment body."""
    start = body.find(marker)
    while start != -1:
        brace = body.find("{", start + len(marker))
        if brace != -1:
            try:
                obj, _ = json.JSONDecoder().raw_decode(body[brace:])
                if isinstance(obj, dict):
                    return obj
            except ValueError:
                pass
        start = body.find(marker, start + len(marker))
    return None


def evaluate_review(
    comments, head_sha, marker=DEFAULT_MARKER, allow_no_machine_review=False
):
    """comments are newest-first. Pure: no gh/git."""
    for comment in comments or []:
        body = comment.get("body") or ""
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
        review = parsed.get("code_review") or {}
        status = review.get("status")
        findings = review.get("has_any_findings")
        commit_sha = review.get("commit_sha") or ""
        head_match = same_sha(head_sha, commit_sha)
        passed = status == "completed" and findings is False and head_match
        reasons = []
        if status != "completed":
            reasons.append("status")
        if findings is not False:
            reasons.append("findings")
        if not head_match:
            reasons.append("sha")
        return {
            "found": True,
            "allowed": False,
            "pass": passed,
            "status": status,
            "has_any_findings": findings,
            "commit_sha": commit_sha,
            "head_match": head_match,
            "comment_id": comment.get("id"),
            "reason": ",".join(reasons) if reasons else "ok",
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


def parse_text_checks(text):
    checks = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("NAME") or "\t" not in line:
            continue
        cells = line.split("\t")
        name = cells[0].strip()
        verdict = cells[1].strip().lower() if len(cells) > 1 else "pending"
        conclusion = TEXT_CONCLUSIONS.get(verdict, "FAILURE")
        state = "COMPLETED" if conclusion != "PENDING" else "PENDING"
        checks.append({"name": name, "state": state, "conclusion": conclusion})
    return checks


def fetch_checks(pr, repo):
    try:
        out = sh(
            ["gh", "pr", "checks", str(pr), "--json", "name,state,conclusion"],
            cwd=repo,
        )
        data = json.loads(out or "[]")
        if isinstance(data, list):
            return data
    except (GateError, ValueError):
        pass
    text = sh(["gh", "pr", "checks", str(pr)], cwd=repo)
    return parse_text_checks(text)


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


def same_sha(left, right):
    """True when two SHAs denote one commit; short forms must be >= 7 chars."""
    left = str(left or "")
    right = str(right or "")
    if not left or not right:
        return False
    if left == right:
        return True
    if len(left) < 7 or len(right) < 7:
        return False
    return left.startswith(right) or right.startswith(left)


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
        facts["match"] = same_sha(verified_head, head)
        if not facts["match"]:
            return facts, ["head mismatch"], False
        return facts, [], True
    if ref and local_branch == ref:
        facts["mode"] = "local"
        facts["match"] = same_sha(local_head, head)
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
        return facts, []
    if not head_verified:
        facts["status"] = "UNKNOWN"
        return facts, ["verified head missing"]
    facts["pass"] = gates_rc == 0
    facts["status"] = "PASS" if facts["pass"] else "FAIL"
    return facts, [] if facts["pass"] else ["gates unverified"]


def evaluate(
    pr,
    repo,
    gates_rc,
    gates_note=None,
    offline=False,
    verified_head=None,
    marker=DEFAULT_MARKER,
    allow_no_machine_review=False,
    allow_no_checks=False,
):
    facts = {"pr": int(pr) if str(pr).isdigit() else pr, "gates": {}, "marker": marker}
    reasons = []
    now = datetime.now().astimezone().isoformat(timespec="seconds")

    if offline:
        facts["gates"], gate_reasons = evaluate_gates(gates_rc, gates_note, True, now)
        reasons.extend(gate_reasons)
        return facts, reasons

    local_head = sh(["git", "-C", repo, "rev-parse", "HEAD"])
    local_branch = sh(["git", "-C", repo, "rev-parse", "--abbrev-ref", "HEAD"])
    view = json.loads(
        sh(
            [
                "gh",
                "pr",
                "view",
                str(pr),
                "--json",
                "headRefOid,headRefName,state,isDraft",
            ],
            cwd=repo,
        )
    )
    pr_state, state_reasons = evaluate_pr_state(
        view.get("state"), view.get("isDraft")
    )
    facts["pr_state"] = pr_state
    if state_reasons:
        facts["gates"], _ = evaluate_gates(gates_rc, gates_note, False, now)
        return facts, state_reasons

    head = view.get("headRefOid") or ""
    head_facts, head_reasons, head_verified = resolve_head(
        head,
        view.get("headRefName"),
        local_head,
        local_branch,
        verified_head,
    )
    facts["head"] = head_facts
    reasons.extend(head_reasons)

    facts["gates"], gate_reasons = evaluate_gates(
        gates_rc, gates_note, head_verified, now
    )
    reasons.extend(gate_reasons)

    checks = evaluate_checks(fetch_checks(pr, repo), allow_no_checks=allow_no_checks)
    facts["checks"] = checks
    if not checks["pass"]:
        reasons.append("no checks" if checks["total"] == 0 else "checks")

    name_with_owner = sh(
        ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
        cwd=repo,
    )
    owner, _, name = name_with_owner.partition("/")

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
    review = facts.get("review")
    if review:
        marker = facts.get("marker") or DEFAULT_MARKER
        if review["found"]:
            findings = review["has_any_findings"]
            findings_text = "-" if findings is None else ("true" if findings else "false")
            print(
                "review: marker={} status={} findings={} sha={} head_match={} comment={}".format(
                    marker,
                    review["status"],
                    findings_text,
                    str(review["commit_sha"])[:7] if review["commit_sha"] else "-",
                    "yes" if review["head_match"] else "no",
                    review["comment_id"] if review["comment_id"] is not None else "-",
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
    print(
        "verdict: MERGE-OK"
        if not reasons
        else "verdict: BLOCKED: " + ", ".join(reasons)
    )


def selftest():
    head = "abc1234def5678abc1234def5678abc1234def5"
    other = "5a6d4ea000000000000000000000000000000000"
    ref = "feat/x"
    marker_ok = {
        "code_review": {
            "status": "completed",
            "has_any_findings": False,
            "commit_sha": "abc1234",
        }
    }
    marker_findings = {
        "code_review": {
            "status": "completed",
            "has_any_findings": True,
            "commit_sha": "abc1234",
        }
    }
    marker_old = {
        "code_review": {
            "status": "completed",
            "has_any_findings": False,
            "commit_sha": "9999999",
        }
    }
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
    ]
    head_cases = [
        (
            "verified-head-match",
            (head, ref, other, "main", "abc1234"),
            "head: abc1234 verified abc1234 match",
            [],
            True,
        ),
        (
            "verified-head-mismatch",
            (head, ref, other, "main", "5a6d4ea"),
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
    sha_cases = [
        ("same-sha-exact", ("abc1234def", "abc1234def"), True),
        ("same-sha-seven", ("abc1234def", "abc1234"), True),
        ("same-sha-short-prefix-rejected", ("abc1234def", "abc"), False),
        ("same-sha-empty", ("abc1234def", ""), False),
    ]
    total = (
        len(marker_cases)
        + len(head_cases)
        + len(gate_cases)
        + len(state_cases)
        + len(check_cases)
        + len(sha_cases)
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

    for name, args, expected in sha_cases:
        actual = same_sha(*args)
        mark = "ok" if actual == expected else "FAIL"
        print(f"  {mark}  {name}: {args[0][:8]}~{args[1][:8]} -> {actual}")
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
        epilog="Exit 0 MERGE-OK, 1 BLOCKED, 2 usage/gh/git error. Environment: none (all inputs are flags).",
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
        help="machine-review marker token (default: %(default)s)",
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
        facts, reasons = evaluate(
            args.pr,
            args.repo,
            args.gates_rc,
            args.gates_note,
            verified_head=args.verified_head,
            marker=args.marker,
            allow_no_machine_review=args.allow_no_machine_review,
            allow_no_checks=args.allow_no_checks,
        )
    except (GateError, ValueError, KeyError) as exc:
        print(f"pr-merge-check: {exc}", file=sys.stderr)
        return 2
    facts["verdict"] = "MERGE-OK" if not reasons else "BLOCKED"
    facts["reasons"] = reasons
    if args.json:
        print(json.dumps(facts, indent=2, ensure_ascii=False))
    else:
        print_human(facts, reasons)
    return 0 if not reasons else 1


if __name__ == "__main__":
    sys.exit(main())
