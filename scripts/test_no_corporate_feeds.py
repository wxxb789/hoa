"""Reject corporate package feeds and legacy npm lockfile integrity hashes."""

import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FEED_HOST = re.compile(
    rb"""
    (?<![a-z0-9_.-])
    (?:[a-z0-9_-]+\.)*
    (?:
        pkgs\.(?:visualstudio|dev\.azure)\.com
        | [a-z0-9_-]*packagefeed[p]roxy[a-z0-9_-]*(?:\.[a-z0-9_-]+)*
        | (?:visualstudio\.com|dev\.azure\.com)
          (?=(?::[0-9]+)?/(?:[^\s"'<>?#]*/)?_packaging(?:[/\s"'<>?#]|$))
    )
    (?![a-z0-9_-]|\.[a-z0-9_-])
    """,
    re.IGNORECASE | re.VERBOSE,
)
SHA1_INTEGRITY = re.compile(rb'"integrity"\s*:\s*"(sha1-[^"\s]+)')


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(
        ["git", "-C", str(root), *args],
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


def corporate_feed_findings(root: Path) -> list[str]:
    findings = []
    paths = git(root, "ls-files", "-z", "--", ".", ":(exclude,top)ref")
    for path in paths.split(b"\0")[:-1]:
        relative = os.fsdecode(path)
        tracked = root / relative
        with tracked.open("rb") as file:
            for number, line in enumerate(file, start=1):
                for match in FEED_HOST.finditer(line):
                    findings.append(f"{relative}:{number}: {match[0].decode('ascii')}")
                if tracked.name == "package-lock.json":
                    for match in SHA1_INTEGRITY.finditer(line):
                        findings.append(f"{relative}:{number}: {match[1].decode('ascii', 'replace')}")
    return findings


def test_tracked_files_use_no_corporate_feeds_or_sha1_integrity():
    findings = corporate_feed_findings(ROOT)
    assert not findings, "\n".join(findings)


@pytest.mark.parametrize(
    "host, path",
    [
        ("mirror.PKGS." + "VisualStudio.COM", "/org/_packaging/npm"),
        ("pkgs." + "dev.azure.com", "/org/_packaging/npm"),
        ("npm.packagefeed" + "proxy.example.test", "/npm"),
        ("visualstudio.com", "/_packaging"),
        ("team.visualstudio.com", "/project/_packaging/npm"),
        ("dev.azure.com", "/org/project/_packaging/npm"),
    ],
)
def test_feed_scan_reports_tracked_feeds_only(tmp_path, host, path):
    git(tmp_path, "init", "--quiet", "--template=")
    tracked = tmp_path / "lock file.json"
    tracked.write_text(
        "https://registry.npmjs.org/pkg/-/pkg-1.0.0.tgz\n"
        "https://dev.azure.com/org/project/_git/repo\n",
        encoding="utf-8",
    )
    (tmp_path / "ref").mkdir()
    url = f"https://{host}{path}\n"
    (tmp_path / "ref" / "excluded.txt").write_text(url, encoding="utf-8")
    (tmp_path / "untracked.txt").write_text(url, encoding="utf-8")
    git(tmp_path, "add", "-f", "--", tracked.name, "ref/excluded.txt")
    assert corporate_feed_findings(tmp_path) == []

    with tracked.open("a", encoding="utf-8") as file:
        file.write(url)
    assert corporate_feed_findings(tmp_path) == [f"{tracked.name}:3: {host}"]


def test_feed_scan_rejects_sha1_only_in_tracked_package_locks(tmp_path):
    git(tmp_path, "init", "--quiet", "--template=")
    weak = '{"packages":{"node_modules/example":{"integrity":"sha1-dGVzdA=="}}}\n'
    strong = weak.replace("sha1-", "sha512-")
    for path in (
        "app/package-lock.json",
        "ref/package-lock.json",
        "ignored/package-lock.json",
        "other.json",
    ):
        file = tmp_path / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(strong if path.startswith("app/") else weak, encoding="utf-8")
    git(tmp_path, "add", "-f", "--", "app/package-lock.json", "ref/package-lock.json", "other.json")
    assert corporate_feed_findings(tmp_path) == []

    (tmp_path / "app/package-lock.json").write_text(weak, encoding="utf-8")
    assert corporate_feed_findings(tmp_path) == ["app/package-lock.json:1: sha1-dGVzdA=="]
