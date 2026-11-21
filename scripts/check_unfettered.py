#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["pyyaml>=6"]
# ///
"""Check the `unfettered-skills/` landing zone.

Snapshot checks run on the selected committed tree on every invocation: a
sensitive-content scan of every path and blob, and the shape and name
collision rules for candidates. `--base <rev>` first compares `<rev>..HEAD`
for the write rule: a change set that adds or modifies anything under
`unfettered-skills/` may not touch any other path, while a deletion there may
ship beside an outside change because promotion moves a skill out. `--event`
selects the CI endpoints from environment variables: `GITHUB_EVENT_NAME` plus
`PR_BASE_SHA`/`PR_HEAD_SHA` or `PUSH_BEFORE`/`PUSH_AFTER`; manual dispatch
runs snapshot checks only.

This is a fixed-signature screen, not proof that a file is public-safe, and
it is not a pre-receive hook: a writer must run the same scan before
publishing. It covers net tree changes and the selected tree's contents, not
content removed in intermediate commits.

Usage:
    uv run scripts/check_unfettered.py
    uv run scripts/check_unfettered.py --base origin/main
    python scripts/check_unfettered.py --event

Exit codes: 0 clean, 1 findings or a failed Git/input operation.
"""
from __future__ import annotations

import argparse
import codecs
import ipaddress
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

import yaml

sys.dont_write_bytecode = True

from feed_host import FEED_HOST  # noqa: E402  (script dir is sys.path[0])

ROOT_DEFAULT = Path(__file__).resolve().parent.parent
INSIDE = "unfettered-skills"
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
CURATED = "skills"
RETIRED = "scripts/retired_skills.toml"


class CheckError(Exception):
    """A Git or input operation failed; the check cannot report clean."""


def _creation_flags() -> int:
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        creationflags=_creation_flags(),
    )
    if check and result.returncode != 0:
        # Never forward Git stderr: it can echo a repository path that carries
        # sensitive content.
        raise CheckError(f"git {args[0]} failed with exit code {result.returncode}")
    return result


def _display(path: str) -> str:
    """Escape control characters so a hostile path cannot forge diagnostic lines."""
    return path.translate({0x0A: r"\n", 0x0D: r"\r", 0x09: r"\t"})


def _is_commit(root: Path, rev: str) -> bool:
    return git(root, "cat-file", "-e", f"{rev}^{{commit}}", check=False).returncode == 0


def _resolve_endpoint(root: Path, sha: str, what: str) -> str:
    if _is_commit(root, sha):
        return sha
    git(root, "fetch", "--no-tags", "--quiet", "origin", sha, check=False)
    if _is_commit(root, sha):
        return sha
    raise CheckError(f"{what} commit unavailable: {sha}")


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise CheckError(f"{name} is not set")
    return value


# ---------------------------------------------------------------------------
# Path isolation

@dataclass(frozen=True)
class Record:
    status: str
    path: str


def _parse_name_status(output: bytes) -> list[Record]:
    fields = output.split(b"\0")
    records: list[Record] = []
    index = 0
    while index < len(fields) and fields[index]:
        status = fields[index].decode("ascii", "replace")
        index += 1
        if len(status) != 1 or status not in "AMDT":
            raise CheckError(f"unexpected git diff status {status!r}; "
                             "the comparison cannot be classified")
        if index >= len(fields) or not fields[index]:
            raise CheckError("truncated git diff --name-status output")
        records.append(Record(status, os.fsdecode(fields[index])))
        index += 1
    return records


def _is_inside(path: str) -> bool:
    return path == INSIDE or path.startswith(INSIDE + "/")


def isolation_findings(root: Path, base: str, head: str) -> list[str]:
    output = git(root, "diff", "--name-status", "--no-renames", "-z",
                 base, head, "--").stdout
    records = sorted(_parse_name_status(output), key=lambda record: record.path)
    inside_writes = [record for record in records
                     if _is_inside(record.path) and record.status != "D"]
    outside = [record for record in records if not _is_inside(record.path)]
    if not inside_writes or not outside:
        return []
    findings = [
        f"landing-zone write mixed with other paths: "
        f"{len(inside_writes)} inside write(s), {len(outside)} outside change(s)"
    ]
    findings += [f"  inside  {record.status} {_safe_path(record.path)}"
                 for record in inside_writes]
    findings += [f"  outside {record.status} {_safe_path(record.path)}"
                 for record in outside]
    return findings


# ---------------------------------------------------------------------------
# Tree and blob access

@dataclass(frozen=True)
class Entry:
    mode: str
    kind: str
    object: str
    path: str


def tree_entries(root: Path, rev: str) -> list[Entry]:
    output = git(root, "ls-tree", "-r", "-t", "-z", "--full-tree", rev).stdout
    entries: list[Entry] = []
    for record in output.split(b"\0"):
        if not record:
            continue
        meta, path = record.split(b"\t", 1)
        mode, kind, object_id = meta.split(b" ", 2)
        entries.append(Entry(mode.decode("ascii"), kind.decode("ascii"),
                             object_id.decode("ascii"), os.fsdecode(path)))
    return entries


def _regular(entry: Entry) -> bool:
    return entry.kind == "blob" and entry.mode in ("100644", "100755")


# ---------------------------------------------------------------------------
# Sensitive scan

_BOUND_LEFT = rb"(?<![A-Za-z0-9_-])"
_BOUND_RIGHT = rb"(?![A-Za-z0-9_-])"

_REGEX_RULES: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    ("private-key", re.compile(
        rb"-----BEGIN (?:ENCRYPTED PRIVATE KEY|RSA PRIVATE KEY|EC PRIVATE KEY|"
        rb"DSA PRIVATE KEY|OPENSSH PRIVATE KEY|PGP PRIVATE KEY BLOCK|PRIVATE KEY)-----")),
    ("github-token", re.compile(
        _BOUND_LEFT + rb"(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{20,}" + _BOUND_RIGHT)),
    ("slack-token", re.compile(
        _BOUND_LEFT + rb"xox[baprs]-[A-Za-z0-9-]{20,}" + _BOUND_RIGHT)),
    ("aws-access-key", re.compile(
        _BOUND_LEFT + rb"(?:AKIA|ASIA)[A-Z0-9]{16}" + _BOUND_RIGHT)),
    ("openai-key", re.compile(
        _BOUND_LEFT + rb"(?:(?:sk-proj-|sk-svcacct-)[A-Za-z0-9_-]{20,}"
        rb"|sk-[A-Za-z0-9]{48})" + _BOUND_RIGHT)),
    ("stripe-key", re.compile(
        _BOUND_LEFT + rb"(?:sk_live_|sk_test_)[A-Za-z0-9]{16,}" + _BOUND_RIGHT)),
    ("home-path", re.compile(
        rb"(?<![A-Za-z0-9._-])"
        rb"(?:"
        rb"/(?:home|Users)/(?!(?:<user>|<name>|~)(?=$|[\\/\s\"'<>]))[^\\/\s\"'<>]+"
        rb"|"
        rb"(?i:[A-Za-z]:[\\/]+Users[\\/]+"
        rb"(?!(?:<user>|<name>|~|Public|Default|Default User|All Users)(?=$|[\\/\s\"'<>])))"
        rb"[^\\/\s\"'<>]+"
        rb")")),
    ("corporate-feed", FEED_HOST),
)

_EMAIL_CANDIDATE = re.compile(
    rb"(?<![A-Za-z0-9.!#$%&'*+/=?^_`{|}~@-])"
    rb"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    rb"[A-Za-z0-9.-]+"
)
_EMAIL_LABEL = re.compile(rb"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?")
_EMAIL_FINAL = re.compile(rb"[A-Za-z]{2,}")
_EMAIL_EXEMPT = (b"example.com", b"example.net", b"example.org")

_IPV4_CANDIDATE = re.compile(
    rb"(?<![0-9A-Za-z_.-])"
    rb"((?:\d{1,3}\.){3}\d{1,3})"
    rb"(?::[0-9]{1,5})?"
    rb"\.?"
    rb"(?![0-9A-Za-z_:.-])"
)
_IPV6_CANDIDATE = re.compile(
    rb"(?<![A-Za-z0-9_-])(::[0-9A-Fa-f:.]*|[0-9A-Fa-f][0-9A-Fa-f:.]*)"
)
_ADJACENT = re.compile(rb"[A-Za-z0-9_-]")

# Assembled from integers so this source carries no literal private address.
_IPV4_PRIVATE = tuple(
    ipaddress.ip_network((network, prefix))
    for network, prefix in (
        (10 << 24, 8),
        ((172 << 24) | (16 << 16), 12),
        ((192 << 24) | (168 << 16), 16),
    )
)
_ULA_PRIVATE = ipaddress.ip_network((0xFC00 << 112, 7))

_BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32-le"),
    (codecs.BOM_UTF32_BE, "utf-32-be"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
    (codecs.BOM_UTF8, "utf-8-sig"),
)


def _email_rules(line: bytes) -> list[tuple[str, int, int]]:
    hits: list[tuple[str, int, int]] = []
    for match in _EMAIL_CANDIDATE.finditer(line):
        start, end = match.span()
        candidate = match.group(0)
        if end < len(line) and _ADJACENT.match(line[end:end + 1]):
            continue
        if candidate.endswith(b"."):
            candidate = candidate[:-1]
            end -= 1
        host = candidate.rsplit(b"@", 1)[1].lower()
        labels = host.split(b".")
        if len(labels) < 2 or _EMAIL_FINAL.fullmatch(labels[-1]) is None:
            continue
        if not all(_EMAIL_LABEL.fullmatch(label) for label in labels[:-1]):
            continue
        if any(host == domain or host.endswith(b"." + domain)
               for domain in _EMAIL_EXEMPT):
            continue
        if host.endswith((b".example", b".test", b".invalid")):
            continue
        hits.append(("email", start, end))
    return hits


def _landing_private(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        address = mapped
    if address.version == 4:
        return any(address in network for network in _IPV4_PRIVATE)
    return address in _ULA_PRIVATE


def _ip_rules(line: bytes) -> list[tuple[str, int, int]]:
    hits: list[tuple[str, int, int]] = []
    for match in _IPV4_CANDIDATE.finditer(line):
        try:
            address = ipaddress.ip_address(match.group(1).decode("ascii"))
        except ValueError:
            continue
        if _landing_private(address):
            hits.append(("private-ip", match.start(), match.end()))
    for match in _IPV6_CANDIDATE.finditer(line):
        start, end = match.span()
        candidate = match.group(0)
        if b":" not in candidate:
            continue
        if end < len(line) and _ADJACENT.match(line[end:end + 1]):
            continue
        if candidate.endswith(b"."):
            candidate = candidate[:-1]
            end -= 1
        try:
            address = ipaddress.ip_address(candidate.decode("ascii"))
        except ValueError:
            continue
        if _landing_private(address):
            hits.append(("private-ip", start, end))
    return hits


def scan_line(line: bytes) -> list[tuple[str, int, int]]:
    hits: list[tuple[str, int, int]] = []
    for rule, pattern in _REGEX_RULES:
        for match in pattern.finditer(line):
            hits.append((rule, match.start(), match.end()))
    hits.extend(_email_rules(line))
    hits.extend(_ip_rules(line))
    return hits


def _bom_text(data: bytes) -> str | None:
    for bom, encoding in _BOMS:
        if data.startswith(bom):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                return None
    return None


def _scan_blob(relative: str, data: bytes) -> list[str]:
    hits: set[tuple[int, str]] = set()
    for number, line in enumerate(data.split(b"\n"), start=1):
        for rule, _start, _end in scan_line(line):
            hits.add((number, rule))
    text = _bom_text(data)
    if text is not None:
        for number, line in enumerate(text.split("\n"), start=1):
            for rule, _start, _end in scan_line(line.encode("utf-8")):
                hits.add((number, rule))
    display = _safe_path(relative)
    return [f"{display}:{number}: {rule}"
            for number, rule in sorted(hits)]


def _path_bytes(path: str) -> bytes:
    return path.encode("utf-8", "surrogateescape")


def _redact(data: bytes, spans: list[tuple[int, int]]) -> bytes:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    pieces: list[bytes] = []
    last = 0
    for start, end in merged:
        pieces.append(data[last:start])
        pieces.append(b"<redacted>")
        last = end
    pieces.append(data[last:])
    return b"".join(pieces)


def _safe_path(path: str) -> str:
    """Redact sensitive spans, then escape control characters.

    A landing-zone path is scanned below its root; span bytes are applied to
    the encoded path, so a match that follows a multibyte character is still
    replaced whole.
    """
    data = _path_bytes(path)
    offset = len(INSIDE) + 1 if path.startswith(INSIDE + "/") else 0
    hits = scan_line(data[offset:])
    if hits:
        data = _redact(data, [(offset + start, offset + end)
                              for _rule, start, end in hits])
    return _display(os.fsdecode(data))


def _scan_path(relative: str) -> list[str]:
    if not relative.startswith(INSIDE + "/"):
        return []
    hits = scan_line(_path_bytes(relative)[len(INSIDE) + 1:])
    if not hits:
        return []
    return [f"{_safe_path(relative)}:1: {rule}"
            for rule in sorted({rule for rule, _start, _end in hits})]


def _scan_findings(root: Path, inside: list[Entry]) -> list[str]:
    findings: list[str] = []
    for entry in inside:
        findings.extend(_scan_path(entry.path))
        if entry.kind != "blob":
            continue  # a gitlink has no blob to read and is not traversed
        try:
            data = git(root, "cat-file", "blob", entry.object).stdout
        except CheckError as error:
            findings.append(f"{_safe_path(entry.path)}: {error}")
            continue
        findings.extend(_scan_blob(entry.path, data))
    return findings


# ---------------------------------------------------------------------------
# Shape and collisions

def _frontmatter(text: str) -> str:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        raise ValueError("missing frontmatter opening ---")
    for index, line in enumerate(lines[1:], start=1):
        if line.rstrip("\r\n") == "---":
            return "".join(lines[1:index])
    raise ValueError("missing frontmatter closing ---")


def _frontmatter_findings(root: Path, path: str, object_id: str,
                          directory: str) -> list[str]:
    display = _safe_path(path)
    try:
        data = git(root, "cat-file", "blob", object_id).stdout
    except CheckError as error:
        return [f"{display}: {error}"]
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return [f"{display}: SKILL.md is not valid UTF-8"]
    try:
        frontmatter = _frontmatter(text)
    except ValueError as error:
        return [f"{display}: {error}"]
    try:
        parsed = yaml.safe_load(frontmatter)
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        where = f" at line {mark.line + 1}" if mark is not None else ""
        return [f"{display}: invalid YAML frontmatter{where}"]
    if not isinstance(parsed, dict):
        return [f"{display}: frontmatter must be a YAML mapping"]
    findings = []
    for key in ("name", "description"):
        value = parsed.get(key)
        if not isinstance(value, str) or not value.strip():
            findings.append(f"{display}: {key} must be a nonblank string")
    name = parsed.get("name")
    if isinstance(name, str) and name.strip() and name != directory:
        findings.append(f"{display}: name does not match its directory name")
    return findings


def _shape_findings(root: Path, inside: list[Entry]) -> list[str]:
    findings: list[str] = []
    candidates: list[Entry] = []
    for entry in inside:
        if entry.path == INSIDE:
            if entry.kind != "tree":
                findings.append(f"{_safe_path(entry.path)}: landing root must be a directory")
            continue
        suffix = entry.path[len(INSIDE) + 1:]
        if "/" in suffix:
            continue
        if entry.kind == "tree":
            candidates.append(entry)
        elif suffix != "README.md":
            findings.append(
                f"{_safe_path(entry.path)}: only README.md may sit in the landing root")
        elif not _regular(entry):
            findings.append(f"{_safe_path(entry.path)}: README.md must be a regular file")
    for tree in sorted(candidates, key=lambda entry: entry.path):
        name = tree.path[len(INSIDE) + 1:]
        skill_path = f"{INSIDE}/{name}/SKILL.md"
        skill_md = next((entry for entry in inside if entry.path == skill_path), None)
        if skill_md is None:
            findings.append(f"{_safe_path(f'{INSIDE}/{name}')}: missing SKILL.md")
        elif not _regular(skill_md):
            findings.append(f"{_safe_path(skill_path)}: SKILL.md must be a regular file")
        if skill_md is not None and _regular(skill_md):
            findings.extend(_frontmatter_findings(root, skill_path,
                                                 skill_md.object, name))
    for entry in inside:
        if not entry.path.startswith(INSIDE + "/"):
            continue
        parts = entry.path[len(INSIDE) + 1:].split("/")
        if len(parts) > 2 and parts[-1] == "SKILL.md":
            findings.append(f"{_safe_path(entry.path)}: nested SKILL.md is not allowed")
    return findings


def _collision_findings(root: Path, entries: list[Entry],
                        inside: list[Entry]) -> list[str]:
    findings: list[str] = []
    candidates: set[str] = set()
    for entry in inside:
        if not entry.path.startswith(INSIDE + "/") or entry.kind != "tree":
            continue
        suffix = entry.path[len(INSIDE) + 1:]
        if "/" not in suffix:
            candidates.add(suffix)
    if not candidates:
        return findings
    curated: set[str] = set()
    for entry in entries:
        if entry.kind != "tree" or not entry.path.startswith(CURATED + "/"):
            continue
        suffix = entry.path[len(CURATED) + 1:]
        if "/" not in suffix:
            curated.add(suffix)
    retired: set[str] = set()
    registry = next((entry for entry in entries if entry.path == RETIRED), None)
    if registry is not None:
        try:
            payload = git(root, "cat-file", "blob", registry.object).stdout
            table = tomllib.loads(payload.decode("utf-8")).get("retired", {})
        except (CheckError, UnicodeDecodeError, tomllib.TOMLDecodeError):
            findings.append(f"{RETIRED}: cannot read retired names")
        else:
            if isinstance(table, dict):
                retired = set(table)
    for name in sorted(candidates):
        if name in curated:
            findings.append(
                f"{_safe_path(f'{INSIDE}/{name}')}: name collides with curated "
                f"{_safe_path(f'{CURATED}/{name}')}")
        if name in retired:
            findings.append(
                f"{_safe_path(f'{INSIDE}/{name}')}: name collides with a retired name")
    return findings


def snapshot_findings(root: Path, rev: str) -> list[str]:
    entries = tree_entries(root, rev)
    inside = sorted((entry for entry in entries if _is_inside(entry.path)),
                    key=lambda entry: entry.path)
    findings: list[str] = []
    findings.extend(_shape_findings(root, inside))
    findings.extend(_scan_findings(root, inside))
    findings.extend(_collision_findings(root, entries, inside))
    return findings


# ---------------------------------------------------------------------------
# CLI

def local_findings(root: Path, base: str | None) -> list[str]:
    findings: list[str] = []
    if base is not None:
        if not _is_commit(root, base):
            raise CheckError(f"base revision not found: {base}")
        findings.extend(isolation_findings(root, base, "HEAD"))
    findings.extend(snapshot_findings(root, "HEAD"))
    return findings


def event_findings(root: Path) -> list[str]:
    event = os.environ.get("GITHUB_EVENT_NAME", "").strip()
    if event == "pull_request":
        base = _resolve_endpoint(root, _required_env("PR_BASE_SHA"), "pull_request base")
        head = _resolve_endpoint(root, _required_env("PR_HEAD_SHA"), "pull_request head")
        merge_base = git(root, "merge-base", base, head, check=False)
        if merge_base.returncode != 0:
            raise CheckError(f"no merge base between {base} and {head}")
        return (isolation_findings(root, merge_base.stdout.decode("ascii").strip(), head)
                + snapshot_findings(root, "HEAD"))
    if event == "push":
        before = _required_env("PUSH_BEFORE")
        after = _resolve_endpoint(root, _required_env("PUSH_AFTER"), "push after")
        base = EMPTY_TREE if not before.strip("0") else \
            _resolve_endpoint(root, before, "push before")
        return isolation_findings(root, base, after) + snapshot_findings(root, after)
    if event == "workflow_dispatch":
        return snapshot_findings(root, "HEAD")
    raise CheckError(f"unsupported event {event!r}; expected pull_request, push "
                     "or workflow_dispatch")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check the unfettered-skills/ landing zone.")
    parser.add_argument("--root", type=Path, default=ROOT_DEFAULT,
                        help="repository root (default: the checkout holding this script)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--base", metavar="REV",
                       help="compare the committed tree REV..HEAD for the write rule")
    group.add_argument("--event", action="store_true",
                       help="select CI comparison endpoints from event environment variables")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        findings = event_findings(root) if args.event else local_findings(root, args.base)
    except CheckError as error:
        print(f"check_unfettered: error: {error}", file=sys.stderr)
        return 1
    for finding in findings:
        print(finding)
    if findings:
        print(f"check_unfettered: {len(findings)} finding(s)", file=sys.stderr)
        return 1
    print("check_unfettered: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
