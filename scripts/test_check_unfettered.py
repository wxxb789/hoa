"""CLI tests for the unfettered-skills landing-zone checker.

Run: python -m pytest scripts/test_check_unfettered.py

Every repository here is synthetic and throwaway. Token-shaped and
address-shaped samples are assembled at runtime so this file carries no
token-like or address-like literal; the feed-host sample is assembled for the
same reason.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parent.parent
CHECKER = Path(__file__).resolve().parent / "check_unfettered.py"
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
BS = chr(92)

# --- synthetic samples (never real values) ---------------------------------

def ip4(a: int, b: int, c: int, d: int) -> str:
    """Assemble an IPv4 sample so this source carries no literal address."""
    return ".".join(str(part) for part in (a, b, c, d))


def ip6(*hextets: str) -> str:
    """Assemble an IPv6 sample; an empty hextet makes the `::` run."""
    return ":".join(hextets)


PRIVATE_KEY = "-----BEGIN RSA " + "PRIVATE KEY-----"
OPENSSH_KEY = "-----BEGIN OPENSSH " + "PRIVATE KEY-----"
ENCRYPTED_KEY = "-----BEGIN ENCRYPTED " + "PRIVATE KEY-----"
PGP_KEY = "-----BEGIN PGP " + "PRIVATE KEY BLOCK-----"
GITHUB_TOKEN = "gh" + "p_" + "A" * 20
GITHUB_PAT = "github" + "_pat_" + "A" * 20
SLACK_TOKEN = "xoxb" + "-" + "A" * 20
AWS_KEY = "AKIA" + "A1B2C3D4E5F6G7H8"
AWS_SESSION_KEY = "ASIA" + "A1B2C3D4E5F6G7H8"
OPENAI_PROJECT = "sk-" + "proj-" + "A" * 20
OPENAI_SERVICE = "sk-" + "svcacct-" + "A" * 20
OPENAI_LEGACY = "sk-" + "A" * 48
STRIPE_KEY = "sk_" + "live_" + "A" * 16
STRIPE_TEST_KEY = "sk_" + "test_" + "A" * 16
EMAIL_SAMPLE = "person@" + "acme-corp.com"
HOME_POSIX = "/home/" + "alice42"
HOME_WINDOWS = "C:" + BS + "Users" + BS + "bob"
FEED_URL = "https://" + "pkgs." + "dev" + ".azure.com/org/_packaging/npm"

CLEAN_SAMPLES = [
    "person@example.com",
    "person@" + "sub" + ".example.net",
    "person@host.test",
    "person@host.example",
    "person@host.invalid",
    "person@host.com1",
    "gh" + "p_" + "A" * 19,
    "gh" + "p_" + "A" * 20 + "-",
    "AKIA" + "A" * 15,
    "AKIA" + "A" * 17,
    "AKIA" + "A" * 16 + "z",
    "ASIA" + "A" * 15,
    "ASIA" + "A" * 17,
    "ASIA" + "A" * 16 + "z",
    "sk-" + "A" * 47,
    "sk-" + "svcacct-" + "A" * 19,
    "sk_" + "test_" + "A" * 15,
    "sk_" + "test_" + "A" * 16 + "-",
    "-----BEGIN PUBLIC " + "KEY-----",
    "/home/" + "<user>" + "/project",
    "/Users/" + "<name>",
    "/home/" + "~" + "/x",
    "C:" + BS + "Users" + BS + "Public" + BS + "x",
    "C:" + BS + "Users" + BS + "Default" + BS + "x",
    "C:" + BS + "Users" + BS + "Default User" + BS + "x",
    "C:" + BS + "Users" + BS + "All Users" + BS + "x",
    "C:" + BS + "Users" + BS + "~",
    "/srv/home/" + "alice",
    "/home//x",
    ip4(127, 0, 0, 1),
    ip4(169, 254, 10, 10),
    ip4(192, 0, 2, 1),
    ip4(198, 51, 100, 1),
    ip4(203, 0, 113, 1),
    ip6("fe80", "", "1"),
    ip6("", "", "1"),
    ip4(172, 15, 255, 255),
    ip4(172, 32, 0, 0),
    ip4(192, 169, 0, 1),
    ip4(11, 0, 0, 1),
    ip6("", "", "ffff", ip4(8, 8, 8, 8)),
    ip6("", "", "ffff", ip4(127, 0, 0, 1)),
    ip6("2001", "db8", "", "1"),
    "dev." + "azure.com/org/project/_git/repo",
]


# --- helpers ---------------------------------------------------------------

def git_bytes(root: Path, *args: str, input: bytes | None = None) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        input=input, capture_output=True, creationflags=NO_WINDOW)
    assert result.returncode == 0, f"git {args}: {result.stderr!r}"
    return result.stdout


def git_text(root: Path, *args: str, input: bytes | None = None) -> str:
    return git_bytes(root, *args, input=input).decode("utf-8", "replace").strip()


def init_repo(tmp_path: Path, name: str = "repo") -> Path:
    root = tmp_path / name
    root.mkdir()
    git_text(root, "init", "--quiet", "--template=")
    git_text(root, "config", "user.email", "test@example.invalid")
    git_text(root, "config", "user.name", "Test")
    return root


def write(root: Path, relative: str, content: str | bytes) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def valid_skill(name: str, description: str | None = None) -> str:
    if description is None:
        description = f"{name} does one thing."
    return (f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n")


def commit_all(root: Path, message: str = "change") -> str:
    git_text(root, "add", "-A")
    git_text(root, "commit", "--quiet", "-m", message)
    return git_text(root, "rev-parse", "HEAD")


def run_checker(root: Path, *args: str, env: dict[str, str] | None = None):
    process_env = dict(os.environ)
    process_env.update(env or {})
    return subprocess.run(
        [sys.executable, str(CHECKER), "--root", str(root), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=NO_WINDOW, env=process_env)


def assert_no_sample_leak(output: str, sample: str, min_len: int = 4) -> None:
    """No diagnostic may echo the value or any part of it."""
    for size in range(min_len, len(sample) + 1):
        for start in range(len(sample) - size + 1):
            part = sample[start:start + size]
            assert part not in output, f"diagnostic leaked {part!r}"


def _blob(root: Path, data: bytes) -> str:
    return git_text(root, "hash-object", "-w", "--stdin", input=data)


def _mktree(root: Path, records: list[tuple[str, str, str, str]]) -> str:
    payload = b"".join(
        f"{mode} {kind} {object_id}\t".encode("utf-8") + name.encode("utf-8") + b"\0"
        for mode, kind, object_id, name in records)
    return git_text(root, "mktree", "-z", input=payload)


def _build(root: Path, node: dict) -> str:
    records: list[tuple[str, str, str, str]] = []
    for name, value in node.items():
        if isinstance(value, dict):
            records.append(("040000", "tree", _build(root, value), name))
            continue
        if isinstance(value, tuple):
            mode, data = value
        else:
            mode, data = "100644", value
        if mode == "160000":
            records.append((mode, "commit", data.decode("ascii"), name))
        else:
            records.append((mode, "blob", _blob(root, data), name))
    return _mktree(root, records)


def _tree(root: Path, files: dict[str, object]) -> str:
    nodes: dict = {}
    for path, value in files.items():
        cursor = nodes
        parts = path.split("/")
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = value
    return _build(root, nodes)


def plumb_commit(root: Path, files: dict[str, object], parent: str | None = None,
                 message: str = "plumb") -> str:
    tree = _tree(root, files)
    args = ["commit-tree", tree]
    if parent is not None:
        args += ["-p", parent]
    args += ["-m", message]
    commit = git_text(root, *args)
    git_text(root, "update-ref", "HEAD", commit)
    return commit


def push_env(before: str, after: str) -> dict[str, str]:
    return {"GITHUB_EVENT_NAME": "push", "PUSH_BEFORE": before, "PUSH_AFTER": after}


def pr_env(base: str, head: str) -> dict[str, str]:
    return {"GITHUB_EVENT_NAME": "pull_request",
            "PR_BASE_SHA": base, "PR_HEAD_SHA": head}


# --- path isolation --------------------------------------------------------

class TestPathIsolation:
    def test_inside_only_write_passes(self, tmp_path):
        root = init_repo(tmp_path)
        write(root, "keep.txt", "keep\n")
        base = commit_all(root)
        write(root, "unfettered-skills/probe/SKILL.md", valid_skill("probe"))
        commit_all(root)
        result = run_checker(root, "--base", base)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_outside_only_change_passes(self, tmp_path):
        root = init_repo(tmp_path)
        write(root, "keep.txt", "keep\n")
        base = commit_all(root)
        write(root, "other.txt", "other\n")
        commit_all(root)
        result = run_checker(root, "--base", base)
        assert result.returncode == 0, result.stdout + result.stderr

    @pytest.mark.parametrize("action", ["add", "edit", "delete"])
    def test_mixed_inside_write_with_outside_change_fails(self, tmp_path, action):
        root = init_repo(tmp_path)
        write(root, "keep.txt", "keep\n")
        base = commit_all(root)
        if action == "add":
            write(root, "other.txt", "other\n")
            outside = "other.txt"
        elif action == "edit":
            write(root, "keep.txt", "edited\n")
            outside = "keep.txt"
        else:
            (root / "keep.txt").unlink()
            outside = "keep.txt"
        write(root, "unfettered-skills/probe/SKILL.md", valid_skill("probe"))
        commit_all(root)
        result = run_checker(root, "--base", base)
        assert result.returncode == 1
        assert "landing-zone write mixed with other paths" in result.stdout
        assert "inside  A unfettered-skills/probe/SKILL.md" in result.stdout
        status = {"add": "A", "edit": "M", "delete": "D"}[action]
        assert f"outside {status} {outside}" in result.stdout

    def test_promotion_delete_inside_add_outside_passes(self, tmp_path):
        root = init_repo(tmp_path)
        write(root, "unfettered-skills/foo/SKILL.md", valid_skill("foo"))
        base = commit_all(root)
        shutil.rmtree(root / "unfettered-skills/foo")
        write(root, "skills/foo/SKILL.md", valid_skill("foo"))
        commit_all(root)
        result = run_checker(root, "--base", base)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_inbound_rename_fails(self, tmp_path):
        root = init_repo(tmp_path)
        write(root, "skills/foo/SKILL.md", valid_skill("foo"))
        base = commit_all(root)
        shutil.rmtree(root / "skills/foo")
        write(root, "unfettered-skills/foo/SKILL.md", valid_skill("foo"))
        commit_all(root)
        result = run_checker(root, "--base", base)
        assert result.returncode == 1
        assert "outside D skills/foo/SKILL.md" in result.stdout

    def test_internal_rename_passes(self, tmp_path):
        root = init_repo(tmp_path)
        write(root, "unfettered-skills/foo/SKILL.md", valid_skill("foo"))
        base = commit_all(root)
        shutil.rmtree(root / "unfettered-skills/foo")
        write(root, "unfettered-skills/bar/SKILL.md", valid_skill("bar"))
        commit_all(root)
        result = run_checker(root, "--base", base)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_promotion_with_second_inside_edit_fails(self, tmp_path):
        root = init_repo(tmp_path)
        write(root, "unfettered-skills/foo/SKILL.md", valid_skill("foo"))
        write(root, "unfettered-skills/bar/SKILL.md", valid_skill("bar"))
        base = commit_all(root)
        shutil.rmtree(root / "unfettered-skills/foo")
        write(root, "skills/foo/SKILL.md", valid_skill("foo"))
        write(root, "unfettered-skills/bar/SKILL.md", valid_skill("bar", "edited."))
        commit_all(root)
        result = run_checker(root, "--base", base)
        assert result.returncode == 1
        assert "inside  M unfettered-skills/bar/SKILL.md" in result.stdout
        assert "outside A skills/foo/SKILL.md" in result.stdout

    def test_whitespace_and_lookalike_paths(self, tmp_path):
        root = init_repo(tmp_path)
        write(root, "keep.txt", "keep\n")
        base = commit_all(root)
        write(root, "unfettered-skills/probe/SKILL.md", valid_skill("probe"))
        write(root, "unfettered-skills/probe/with space.txt", "x\n")
        write(root, "unfettered-skills-extra/x.txt", "x\n")
        write(root, "unfettered-skillsx/y.txt", "x\n")
        commit_all(root)
        result = run_checker(root, "--base", base)
        assert result.returncode == 1
        assert "inside  A unfettered-skills/probe/with space.txt" in result.stdout
        assert "outside A unfettered-skills-extra/x.txt" in result.stdout
        assert "outside A unfettered-skillsx/y.txt" in result.stdout

    def test_newline_path_is_reported_escaped(self, tmp_path):
        root = init_repo(tmp_path)
        write(root, "keep.txt", "keep\n")
        base = commit_all(root)
        plumb_commit(root, {
            "unfettered-skills/probe/SKILL.md": valid_skill("probe").encode(),
            "unfettered-skills/probe/evil\nname.txt": b"x\n",
            "outside.txt": b"o\n",
        }, parent=base)
        result = run_checker(root, "--base", base)
        assert result.returncode == 1
        assert r"unfettered-skills/probe/evil\nname.txt" in result.stdout
        assert "outside.txt" in result.stdout


# --- CI event endpoint selection -------------------------------------------

class TestEventEndpoints:
    def test_push_squash_compares_before_to_after(self, tmp_path):
        root = init_repo(tmp_path)
        write(root, "keep.txt", "keep\n")
        base = commit_all(root)
        write(root, "unfettered-skills/probe/SKILL.md", valid_skill("probe"))
        write(root, "outside.txt", "o\n")
        squash = commit_all(root)
        result = run_checker(root, "--event", env=push_env(base, squash))
        assert result.returncode == 1
        assert "unfettered-skills/probe/SKILL.md" in result.stdout
        assert "outside.txt" in result.stdout

    def test_push_multi_commit_catches_earlier_outside_change(self, tmp_path):
        root = init_repo(tmp_path)
        write(root, "keep.txt", "keep\n")
        base = commit_all(root)
        write(root, "outside.txt", "o\n")
        commit_all(root, "first")
        write(root, "unfettered-skills/probe/SKILL.md", valid_skill("probe"))
        tip = commit_all(root, "second")
        result = run_checker(root, "--event", env=push_env(base, tip))
        assert result.returncode == 1
        assert "outside.txt" in result.stdout

    def test_push_force_uses_before_not_merge_base(self, tmp_path):
        root = init_repo(tmp_path)
        write(root, "keep.txt", "keep\n")
        base = commit_all(root)
        write(root, "gone.txt", "o\n")
        old_tip = commit_all(root, "old")
        git_text(root, "checkout", "--quiet", base)
        write(root, "unfettered-skills/probe/SKILL.md", valid_skill("probe"))
        new_tip = commit_all(root, "new")
        result = run_checker(root, "--event", env=push_env(old_tip, new_tip))
        assert result.returncode == 1
        assert "gone.txt" in result.stdout

    def test_push_all_zero_before_uses_empty_tree(self, tmp_path):
        root = init_repo(tmp_path)
        write(root, "unfettered-skills/probe/SKILL.md", valid_skill("probe"))
        tip = commit_all(root)
        result = run_checker(root, "--event", env=push_env("0" * 40, tip))
        assert result.returncode == 0, result.stdout + result.stderr

    def test_push_all_zero_before_still_rejects_mixed(self, tmp_path):
        root = init_repo(tmp_path)
        write(root, "unfettered-skills/probe/SKILL.md", valid_skill("probe"))
        write(root, "outside.txt", "o\n")
        tip = commit_all(root)
        result = run_checker(root, "--event", env=push_env("0" * 40, tip))
        assert result.returncode == 1
        assert "outside.txt" in result.stdout

    def test_push_missing_before_fails_with_sha(self, tmp_path):
        root = init_repo(tmp_path)
        write(root, "unfettered-skills/probe/SKILL.md", valid_skill("probe"))
        tip = commit_all(root)
        missing = "1" * 40
        result = run_checker(root, "--event", env=push_env(missing, tip))
        assert result.returncode == 1
        assert f"commit unavailable: {missing}" in result.stderr

    def test_push_fetches_missing_before_from_origin(self, tmp_path):
        origin = tmp_path / "origin.git"
        origin.mkdir()
        git_text(origin, "init", "--bare", "--quiet", "--template=")
        git_text(origin, "config", "uploadpack.allowAnySHA1InWant", "true")
        git_text(tmp_path, "clone", "--quiet", str(origin), "seed")
        seed = tmp_path / "seed"
        git_text(seed, "config", "user.email", "test@example.invalid")
        git_text(seed, "config", "user.name", "Test")
        write(seed, "keep.txt", "keep\n")
        git_text(seed, "add", "-A")
        git_text(seed, "commit", "--quiet", "-m", "base")
        git_text(seed, "push", "--quiet", "origin", "HEAD:main")
        git_text(origin, "symbolic-ref", "HEAD", "refs/heads/main")
        git_text(tmp_path, "clone", "--quiet", str(origin), "work")
        work = tmp_path / "work"
        write(seed, "unfettered-skills/probe/SKILL.md", valid_skill("probe"))
        git_text(seed, "add", "-A")
        git_text(seed, "commit", "--quiet", "-m", "landing")
        missing = git_text(seed, "rev-parse", "HEAD")
        git_text(seed, "push", "--quiet", "origin", "HEAD:main")
        after = git_text(work, "rev-parse", "HEAD")
        result = run_checker(work, "--event", env=push_env(missing, after))
        assert result.returncode == 0, result.stdout + result.stderr

    def test_pr_non_main_branch_compares_merge_base_to_head(self, tmp_path):
        root = init_repo(tmp_path)
        write(root, "keep.txt", "keep\n")
        fork = commit_all(root)
        git_text(root, "checkout", "--quiet", "-b", "release")
        write(root, "release-only.txt", "release\n")
        target = commit_all(root, "release change")
        git_text(root, "checkout", "--quiet", fork)
        git_text(root, "checkout", "--quiet", "-b", "feature")
        write(root, "unfettered-skills/probe/SKILL.md", valid_skill("probe"))
        head = commit_all(root, "candidate")
        assert target != fork
        result = run_checker(root, "--event", env=pr_env(target, head))
        assert result.returncode == 0, result.stdout + result.stderr

    def test_pr_non_main_branch_mixed_change_fails(self, tmp_path):
        root = init_repo(tmp_path)
        write(root, "keep.txt", "keep\n")
        fork = commit_all(root)
        git_text(root, "checkout", "--quiet", "-b", "release")
        write(root, "release-only.txt", "release\n")
        target = commit_all(root, "release change")
        git_text(root, "checkout", "--quiet", fork)
        git_text(root, "checkout", "--quiet", "-b", "feature")
        write(root, "unfettered-skills/probe/SKILL.md", valid_skill("probe"))
        write(root, "outside.txt", "o\n")
        head = commit_all(root, "candidate and outside")
        result = run_checker(root, "--event", env=pr_env(target, head))
        assert result.returncode == 1
        assert "outside.txt" in result.stdout
        assert "release-only.txt" not in result.stdout

    def test_pr_snapshot_uses_checked_out_merge_tree(self, tmp_path):
        root = init_repo(tmp_path)
        write(root, "keep.txt", "keep\n")
        base = commit_all(root)
        git_text(root, "checkout", "--quiet", "-b", "feature")
        write(root, "unfettered-skills/probe/SKILL.md", valid_skill("probe"))
        feature = commit_all(root)
        git_text(root, "checkout", "--quiet", base)
        git_text(root, "merge", "--quiet", "--no-ff", "--no-commit", "feature")
        write(root, "unfettered-skills/probe/secret.txt", "x " + GITHUB_TOKEN + "\n")
        commit_all(root, "merge with secret")
        result = run_checker(root, "--event", env=pr_env(base, feature))
        assert result.returncode == 1
        assert "unfettered-skills/probe/secret.txt:1: github-token" in result.stdout

    def test_pr_missing_ref_fails(self, tmp_path):
        root = init_repo(tmp_path)
        write(root, "unfettered-skills/probe/SKILL.md", valid_skill("probe"))
        head = commit_all(root)
        missing = "1" * 40
        result = run_checker(root, "--event", env=pr_env(missing, head))
        assert result.returncode == 1
        assert f"pull_request base commit unavailable: {missing}" in result.stderr

    def test_manual_dispatch_runs_snapshot_only(self, tmp_path):
        root = init_repo(tmp_path)
        write(root, "unfettered-skills/probe/SKILL.md", valid_skill("probe"))
        commit_all(root)
        env = {"GITHUB_EVENT_NAME": "workflow_dispatch", "PUSH_BEFORE": "1" * 40}
        result = run_checker(root, "--event", env=env)
        assert result.returncode == 0, result.stdout + result.stderr
        write(root, "unfettered-skills/probe/secret.txt", "x " + GITHUB_TOKEN + "\n")
        commit_all(root)
        result = run_checker(root, "--event", env=env)
        assert result.returncode == 1
        assert "github-token" in result.stdout

    def test_push_snapshot_scans_after_tree(self, tmp_path):
        root = init_repo(tmp_path)
        write(root, "keep.txt", "keep\n")
        base = commit_all(root)
        write(root, "unfettered-skills/probe/SKILL.md", valid_skill("probe"))
        write(root, "unfettered-skills/probe/secret.txt", "x " + GITHUB_TOKEN + "\n")
        after = commit_all(root)
        git_text(root, "checkout", "--quiet", base)
        result = run_checker(root, "--event", env=push_env(base, after))
        assert result.returncode == 1
        assert "unfettered-skills/probe/secret.txt:1: github-token" in result.stdout


# --- shape and collisions --------------------------------------------------

class TestShape:
    def test_absent_tree_passes(self, tmp_path):
        root = init_repo(tmp_path)
        write(root, "keep.txt", "keep\n")
        commit_all(root)
        result = run_checker(root)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_readme_only_passes(self, tmp_path):
        root = init_repo(tmp_path)
        write(root, "unfettered-skills/README.md", "# Landing zone\n")
        commit_all(root)
        result = run_checker(root)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_root_file_other_than_readme_fails(self, tmp_path):
        root = init_repo(tmp_path)
        write(root, "unfettered-skills/NOTES.md", "notes\n")
        commit_all(root)
        result = run_checker(root)
        assert result.returncode == 1
        assert "only README.md may sit in the landing root" in result.stdout

    def test_readme_as_symlink_fails(self, tmp_path):
        root = init_repo(tmp_path)
        plumb_commit(root, {
            "unfettered-skills/README.md": ("120000", b"real-readme.md"),
        })
        result = run_checker(root)
        assert result.returncode == 1
        assert "README.md must be a regular file" in result.stdout

    def test_missing_skill_md_fails(self, tmp_path):
        root = init_repo(tmp_path)
        write(root, "unfettered-skills/probe/notes.txt", "notes\n")
        commit_all(root)
        result = run_checker(root)
        assert result.returncode == 1
        assert "unfettered-skills/probe: missing SKILL.md" in result.stdout

    def test_empty_candidate_tree_reports_shape_and_path(self, tmp_path):
        root = init_repo(tmp_path)
        plumb_commit(root, {
            "unfettered-skills/" + EMAIL_SAMPLE: {},
        })
        result = run_checker(root)
        assert result.returncode == 1
        lines = result.stdout.splitlines()
        assert any(line.endswith("missing SKILL.md") for line in lines)
        assert any(line.endswith(":1: email") for line in lines)
        assert EMAIL_SAMPLE not in result.stdout + result.stderr

    def test_skill_md_as_symlink_fails(self, tmp_path):
        root = init_repo(tmp_path)
        plumb_commit(root, {
            "unfettered-skills/probe/SKILL.md": ("120000", b"elsewhere/SKILL.md"),
        })
        result = run_checker(root)
        assert result.returncode == 1
        assert "SKILL.md must be a regular file" in result.stdout

    def test_name_directory_mismatch_fails(self, tmp_path):
        root = init_repo(tmp_path)
        write(root, "unfettered-skills/probe/SKILL.md", valid_skill("other"))
        commit_all(root)
        result = run_checker(root)
        assert result.returncode == 1
        assert "does not match its directory name" in result.stdout

    @pytest.mark.parametrize("field, line", [
        ("name", 'name: ""'),
        ("name", 'name: "   "'),
        ("name", "name: 123"),
        ("name", "name: [a]"),
        ("description", 'description: ""'),
        ("description", 'description: "  "'),
        ("description", "description: 123"),
    ])
    def test_nonblank_string_fields(self, tmp_path, field, line):
        root = init_repo(tmp_path)
        fields = {"name": "name: probe", "description": "description: ok."}
        fields[field] = line
        text = f"---\n{fields['name']}\n{fields['description']}\n---\n\n# x\n"
        write(root, "unfettered-skills/probe/SKILL.md", text)
        commit_all(root)
        result = run_checker(root)
        assert result.returncode == 1
        assert f"{field} must be a nonblank string" in result.stdout

    @pytest.mark.parametrize("field", ["name", "description"])
    def test_missing_field_fails(self, tmp_path, field):
        root = init_repo(tmp_path)
        fields = {"name": "name: probe", "description": "description: ok."}
        del fields[field]
        text = "---\n" + "\n".join(fields.values()) + "\n---\n\n# x\n"
        write(root, "unfettered-skills/probe/SKILL.md", text)
        commit_all(root)
        result = run_checker(root)
        assert result.returncode == 1
        assert f"{field} must be a nonblank string" in result.stdout

    def test_invalid_yaml_fails(self, tmp_path):
        root = init_repo(tmp_path)
        write(root, "unfettered-skills/probe/SKILL.md",
              "---\nname: [unclosed\ndescription: ok\n---\n")
        commit_all(root)
        result = run_checker(root)
        assert result.returncode == 1
        assert "invalid YAML frontmatter" in result.stdout

    def test_frontmatter_must_be_mapping(self, tmp_path):
        root = init_repo(tmp_path)
        write(root, "unfettered-skills/probe/SKILL.md", "---\n- a\n- b\n---\n")
        commit_all(root)
        result = run_checker(root)
        assert result.returncode == 1
        assert "frontmatter must be a YAML mapping" in result.stdout

    @pytest.mark.parametrize("text, expected", [
        ("name: probe\ndescription: ok\n", "missing frontmatter opening"),
        ("---\nname: probe\ndescription: ok\n", "missing frontmatter closing"),
    ])
    def test_missing_delimiters_fail(self, tmp_path, text, expected):
        root = init_repo(tmp_path)
        write(root, "unfettered-skills/probe/SKILL.md", text)
        commit_all(root)
        result = run_checker(root)
        assert result.returncode == 1
        assert expected in result.stdout

    def test_nested_skill_md_fails(self, tmp_path):
        root = init_repo(tmp_path)
        write(root, "unfettered-skills/probe/SKILL.md", valid_skill("probe"))
        write(root, "unfettered-skills/probe/references/SKILL.md", "nested\n")
        commit_all(root)
        result = run_checker(root)
        assert result.returncode == 1
        assert "nested SKILL.md is not allowed" in result.stdout

    def test_extra_frontmatter_passes(self, tmp_path):
        root = init_repo(tmp_path)
        text = ("---\nname: probe\ndescription: probe does one thing.\n"
                "metadata:\n  revision: \"1\"\n---\n\n# probe\n")
        write(root, "unfettered-skills/probe/SKILL.md", text)
        commit_all(root)
        result = run_checker(root)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_crlf_frontmatter_passes(self, tmp_path):
        root = init_repo(tmp_path)
        write(root, "unfettered-skills/probe/SKILL.md",
              valid_skill("probe").replace("\n", "\r\n"))
        commit_all(root)
        result = run_checker(root)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_bom_frontmatter_passes(self, tmp_path):
        root = init_repo(tmp_path)
        write(root, "unfettered-skills/probe/SKILL.md",
              valid_skill("probe").encode("utf-8-sig"))
        commit_all(root)
        result = run_checker(root)
        assert result.returncode == 0, result.stdout + result.stderr


class TestCollisions:
    def test_curated_name_collision_fails(self, tmp_path):
        root = init_repo(tmp_path)
        write(root, "unfettered-skills/foo/SKILL.md", valid_skill("foo"))
        write(root, "skills/engineering/foo/SKILL.md", valid_skill("foo"))
        commit_all(root)
        result = run_checker(root)
        assert result.returncode == 1
        assert "name collides with curated skills/engineering/foo" in result.stdout

    def test_candidate_named_for_a_category_does_not_collide(self, tmp_path):
        root = init_repo(tmp_path)
        write(root, "unfettered-skills/engineering/SKILL.md", valid_skill("engineering"))
        write(root, "skills/engineering/foo/SKILL.md", valid_skill("foo"))
        commit_all(root)
        result = run_checker(root)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_retired_name_collision_fails(self, tmp_path):
        root = init_repo(tmp_path)
        write(root, "scripts/retired_skills.toml",
              '[retired.foo]\nreplacement = "skills/bar"\nreason = "test"\n')
        write(root, "unfettered-skills/foo/SKILL.md", valid_skill("foo"))
        commit_all(root)
        result = run_checker(root)
        assert result.returncode == 1
        assert "name collides with a retired name" in result.stdout

    def test_collision_reported_on_outside_only_change(self, tmp_path):
        root = init_repo(tmp_path)
        write(root, "unfettered-skills/foo/SKILL.md", valid_skill("foo"))
        base = commit_all(root)
        write(root, "skills/engineering/foo/SKILL.md", valid_skill("foo"))
        commit_all(root)
        result = run_checker(root, "--base", base)
        assert result.returncode == 1
        assert "landing-zone write mixed" not in result.stdout
        assert "name collides with curated skills/engineering/foo" in result.stdout

    def test_empty_curated_tree_still_collides(self, tmp_path):
        root = init_repo(tmp_path)
        plumb_commit(root, {
            "unfettered-skills/foo/SKILL.md": valid_skill("foo").encode(),
            "skills/engineering/foo": {},
        })
        result = run_checker(root)
        assert result.returncode == 1
        assert "name collides with curated skills/engineering/foo" in result.stdout

    def test_curated_gitlink_is_not_a_curated_directory(self, tmp_path):
        root = init_repo(tmp_path)
        write(root, "keep.txt", "keep\n")
        seed = commit_all(root)
        plumb_commit(root, {
            "unfettered-skills/foo/SKILL.md": valid_skill("foo").encode(),
            "skills/engineering/foo": ("160000", seed.encode()),
        })
        result = run_checker(root)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_retired_collision_on_outside_only_registry_change(self, tmp_path):
        root = init_repo(tmp_path)
        write(root, "unfettered-skills/foo/SKILL.md", valid_skill("foo"))
        base = commit_all(root)
        write(root, "scripts/retired_skills.toml",
              '[retired.foo]\nreplacement = "skills/bar"\nreason = "test"\n')
        commit_all(root)
        result = run_checker(root, "--base", base)
        assert result.returncode == 1
        assert "name collides with a retired name" in result.stdout

    def test_candidate_free_snapshot_ignores_a_malformed_registry(self, tmp_path):
        root = init_repo(tmp_path)
        write(root, "keep.txt", "keep\n")
        write(root, "scripts/retired_skills.toml", "this is not = [ toml\n")
        commit_all(root)
        result = run_checker(root)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_malformed_registry_still_fails_with_candidates(self, tmp_path):
        root = init_repo(tmp_path)
        write(root, "unfettered-skills/foo/SKILL.md", valid_skill("foo"))
        write(root, "scripts/retired_skills.toml", "this is not = [ toml\n")
        commit_all(root)
        result = run_checker(root)
        assert result.returncode == 1
        assert "cannot read retired names" in result.stdout


# --- sensitive scan --------------------------------------------------------

def scan_repo(tmp_path: Path, assets: dict[str, str | bytes]) -> Path:
    root = init_repo(tmp_path)
    write(root, "unfettered-skills/probe/SKILL.md", valid_skill("probe"))
    for relative, content in assets.items():
        write(root, f"unfettered-skills/probe/{relative}", content)
    commit_all(root)
    return root


class TestSensitiveScan:
    def test_each_signature_is_reported(self, tmp_path):
        samples = [
            (PRIVATE_KEY, "private-key"),
            (OPENSSH_KEY, "private-key"),
            (ENCRYPTED_KEY, "private-key"),
            (PGP_KEY, "private-key"),
            (GITHUB_TOKEN, "github-token"),
            (GITHUB_PAT, "github-token"),
            (SLACK_TOKEN, "slack-token"),
            (AWS_KEY, "aws-access-key"),
            (AWS_SESSION_KEY, "aws-access-key"),
            (OPENAI_PROJECT, "openai-key"),
            (OPENAI_SERVICE, "openai-key"),
            (OPENAI_LEGACY, "openai-key"),
            (STRIPE_KEY, "stripe-key"),
            (STRIPE_TEST_KEY, "stripe-key"),
            (EMAIL_SAMPLE, "email"),
            (HOME_POSIX, "home-path"),
            (HOME_WINDOWS, "home-path"),
            (ip4(10, 0, 0, 0), "private-ip"),
            (ip4(10, 255, 255, 255), "private-ip"),
            (ip4(172, 16, 0, 0), "private-ip"),
            (ip4(172, 31, 255, 255), "private-ip"),
            (ip4(192, 168, 0, 0), "private-ip"),
            (ip4(192, 168, 255, 255), "private-ip"),
            (ip6("fc00", "", ""), "private-ip"),
            (ip6("fdff", "ffff", "ffff", "ffff", "ffff", "ffff", "ffff", "ffff"),
             "private-ip"),
            (ip6("", "", "ffff", ip4(10, 20, 30, 40)), "private-ip"),
            ("[" + ip6("fd00", "", "1") + "]:443", "private-ip"),
            (ip4(192, 168, 1, 1) + ":8080", "private-ip"),
            (FEED_URL, "corporate-feed"),
        ]
        hits = "\n".join(sample for sample, _rule in samples) + "\n"
        root = scan_repo(tmp_path, {
            "assets/hits.txt": hits,
            "assets/wide16.txt": ("x " + GITHUB_TOKEN + "\n").encode("utf-16"),
            "assets/wide32.txt": ("x " + GITHUB_TOKEN + "\n").encode("utf-32"),
            "assets/binary.bin": b"\x00\x01" + GITHUB_TOKEN.encode() + b"\xff",
            "assets/invalid.bin": b"\xff" + GITHUB_TOKEN.encode() + b"\xfe",
        })
        expected = {
            f"unfettered-skills/probe/assets/hits.txt:{line}: {rule}"
            for line, (_sample, rule) in enumerate(samples, start=1)
        }
        expected |= {
            "unfettered-skills/probe/assets/wide16.txt:1: github-token",
            "unfettered-skills/probe/assets/wide32.txt:1: github-token",
            "unfettered-skills/probe/assets/binary.bin:1: github-token",
            "unfettered-skills/probe/assets/invalid.bin:1: github-token",
        }
        result = run_checker(root)
        assert result.returncode == 1
        assert set(result.stdout.splitlines()) == expected

    def test_false_positives_and_placeholders_pass(self, tmp_path):
        root = scan_repo(tmp_path, {
            "assets/clean.txt": "\n".join(CLEAN_SAMPLES) + "\n",
            "assets/malformed.bin": b"\xff\xfe\x81",
            "assets/clean.bin": b"\x00\x01\x02\xfe\xff",
        })
        result = run_checker(root)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_exempt_candidate_does_not_hide_a_hit_on_the_same_line(self, tmp_path):
        root = scan_repo(tmp_path, {
            "assets/mixed.txt":
                "/home/<user> and " + HOME_POSIX + "\n"
                "C:" + BS + "Users" + BS + "Public and " + HOME_WINDOWS + "\n"
                + ip4(10, 0, 0, 1) + " " + ip4(10, 0, 0, 2) + "\n",
        })
        result = run_checker(root)
        assert result.returncode == 1
        assert set(result.stdout.splitlines()) == {
            "unfettered-skills/probe/assets/mixed.txt:1: home-path",
            "unfettered-skills/probe/assets/mixed.txt:2: home-path",
            "unfettered-skills/probe/assets/mixed.txt:3: private-ip",
        }

    def test_path_hit_is_reported_redacted(self, tmp_path):
        root = init_repo(tmp_path)
        write(root, "unfettered-skills/probe/SKILL.md", valid_skill("probe"))
        write(root, "unfettered-skills/probe/" + EMAIL_SAMPLE + "+t1", "clean\n")
        commit_all(root)
        result = run_checker(root)
        assert result.returncode == 1
        assert result.stdout.splitlines() == [
            "unfettered-skills/<redacted>+t1:1: email",
        ]

    def test_home_path_in_a_tree_path_is_redacted(self, tmp_path):
        root = init_repo(tmp_path)
        plumb_commit(root, {
            "unfettered-skills/probe/SKILL.md": valid_skill("probe").encode(),
            "unfettered-skills/probe/" + HOME_WINDOWS + ".txt": b"clean\n",
        })
        result = run_checker(root)
        assert result.returncode == 1
        assert result.stdout.splitlines() == [
            "unfettered-skills/probe/<redacted>:1: home-path",
        ]

    def test_malformed_addresses_are_not_reported(self, tmp_path):
        malformed = [
            ip4(10, 0, 0, 1) + ".:8080",
            ip4(10, 0, 0, 1) + "..",
            ip6("fc00", "", "1", "", ""),
        ]
        root = scan_repo(tmp_path, {
            "assets/malformed.txt": "\n".join(malformed) + "\n",
        })
        result = run_checker(root)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_field_delimited_address_is_found(self, tmp_path):
        root = scan_repo(tmp_path, {
            "assets/field.txt": "src:" + ip4(10, 0, 0, 5) + "\n",
        })
        result = run_checker(root)
        assert result.returncode == 1
        assert result.stdout.splitlines() == [
            "unfettered-skills/probe/assets/field.txt:1: private-ip",
        ]

    def test_email_whole_candidate_validation(self, tmp_path):
        invalid_final_label = "person@" + "host.com.invalid9"
        unapproved_after_approved = "person@" + "example.com.evil.com"
        root = scan_repo(tmp_path, {
            "assets/emails.txt":
                invalid_final_label + "\n" + unapproved_after_approved + "\n",
        })
        result = run_checker(root)
        assert result.returncode == 1
        assert result.stdout.splitlines() == [
            "unfettered-skills/probe/assets/emails.txt:2: email",
        ]

    def test_path_and_blob_hits_never_echo_the_filename(self, tmp_path):
        root = scan_repo(tmp_path, {
            "assets/" + EMAIL_SAMPLE + ".txt": "x " + GITHUB_TOKEN + "\n",
        })
        result = run_checker(root)
        assert result.returncode == 1
        output = result.stdout + result.stderr
        assert "email" in output and "github-token" in output
        assert_no_sample_leak(output, EMAIL_SAMPLE)
        assert_no_sample_leak(output, GITHUB_TOKEN)

    def test_unicode_prefix_path_hit_never_leaks_a_match_part(self, tmp_path):
        root = init_repo(tmp_path)
        plumb_commit(root, {
            "unfettered-skills/probe/SKILL.md": valid_skill("probe").encode(),
            "unfettered-skills/probe/\u65e5\u672c\u8a9e" + EMAIL_SAMPLE + ".txt":
                b"clean\n",
        })
        result = run_checker(root)
        assert result.returncode == 1
        output = result.stdout + result.stderr
        assert "email" in output
        assert_no_sample_leak(output, EMAIL_SAMPLE)

    def test_mixed_change_diagnostics_never_echo_matched_text(self, tmp_path):
        root = init_repo(tmp_path)
        write(root, "keep.txt", "keep\n")
        base = commit_all(root)
        write(root, "keep.txt", "edited\n")
        write(root, "unfettered-skills/" + EMAIL_SAMPLE + "/SKILL.md",
              valid_skill(EMAIL_SAMPLE) + "\n" + GITHUB_TOKEN + "\n")
        write(root, "outside/" + EMAIL_SAMPLE + ".txt", "o\n")
        commit_all(root)
        result = run_checker(root, "--base", base)
        assert result.returncode == 1
        output = result.stdout + result.stderr
        assert "landing-zone write mixed with other paths" in result.stdout
        assert_no_sample_leak(output, EMAIL_SAMPLE)
        assert_no_sample_leak(output, GITHUB_TOKEN)

    def test_shape_diagnostics_never_echo_a_frontmatter_value(self, tmp_path):
        root = init_repo(tmp_path)
        write(root, "unfettered-skills/probe/SKILL.md",
              "---\nname: " + EMAIL_SAMPLE + "\ndescription: ok.\n---\n\n# x\n")
        commit_all(root)
        result = run_checker(root)
        assert result.returncode == 1
        output = result.stdout + result.stderr
        assert "does not match its directory name" in result.stdout
        assert_no_sample_leak(output, EMAIL_SAMPLE)

    def test_collision_diagnostics_never_echo_a_candidate_name(self, tmp_path):
        root = init_repo(tmp_path)
        write(root, "unfettered-skills/" + EMAIL_SAMPLE + "/SKILL.md",
              valid_skill(EMAIL_SAMPLE))
        write(root, "skills/engineering/" + EMAIL_SAMPLE + "/SKILL.md",
              valid_skill(EMAIL_SAMPLE))
        commit_all(root)
        result = run_checker(root)
        assert result.returncode == 1
        output = result.stdout + result.stderr
        assert "name collides with curated" in result.stdout
        assert_no_sample_leak(output, EMAIL_SAMPLE)

    def test_diagnostics_never_echo_matched_text(self, tmp_path):
        samples = [PRIVATE_KEY, GITHUB_TOKEN, EMAIL_SAMPLE, HOME_POSIX, FEED_URL]
        root = scan_repo(tmp_path, {
            "assets/hits.txt": "\n".join(samples) + "\n",
            "assets/" + EMAIL_SAMPLE + ".txt": "clean\n",
        })
        result = run_checker(root)
        assert result.returncode == 1
        output = result.stdout + result.stderr
        for sample in samples:
            assert sample not in output
            assert_no_sample_leak(output, sample, min_len=5)


# --- repository integration confirmations ----------------------------------

def test_pytest_root_collection_skips_landing_zone(tmp_path):
    shutil.copyfile(REPO / "pytest.ini", tmp_path / "pytest.ini")
    candidate = tmp_path / "unfettered-skills" / "test_candidate.py"
    candidate.parent.mkdir()
    candidate.write_text("def test_candidate():\n    assert True\n", encoding="utf-8")
    control = tmp_path / "scripts" / "test_control.py"
    control.parent.mkdir()
    control.write_text("def test_control():\n    assert True\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "."],
        cwd=tmp_path, capture_output=True, text=True, encoding="utf-8",
        errors="replace", creationflags=NO_WINDOW)
    assert result.returncode == 0, result.stderr
    assert "test_control" in result.stdout
    assert "test_candidate" not in result.stdout


def test_generated_install_commands_never_name_landing_zone():
    commands = []
    for name in ("index.md", "index.zh-CN.md"):
        for line in (REPO / name).read_text(encoding="utf-8").splitlines():
            if "npx skills add" in line:
                commands.append(line)
    assert commands
    for line in commands:
        assert "unfettered-skills" not in line
