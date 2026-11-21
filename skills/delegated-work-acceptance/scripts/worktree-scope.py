#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""Record and verify the working increment of one repository.

A review dispatches at a commit range, so uncommitted work is invisible to it.
This script makes the increment explicit:

    snapshot  record HEAD plus every dirty path (content digests, index mode)
    diff      compare the current tree with that baseline
    seal      freeze the changed path set and its digests
    seal --index      freeze the staged index (Git mode and OID per path)
    verify    recompute the set and refuse when the tree has moved
    verify --commit   verify one commit against the index seal, including history
    status    print the recorded facts

State location, first match wins:

    --state-file DIR
    $HOA_SCOPE_STATE
    $XDG_STATE_HOME/hoa/scope
    ~/.local/state/hoa/scope

The file is ``<DIR>/<repo-key>/<label>.json`` where ``repo-key`` is the first
12 hex characters of sha256(realpath(repo)) and ``label`` defaults to
``default``.  One repository per invocation.

``scope_sha`` hashes sorted ``"<path>\\0<sha256>\\n"`` lines; a deleted path
contributes an empty digest.  ``--json`` prints machine-readable output; the
default prints one line per fact plus a verdict line.

Exit codes: 0 success / scope ok, 1 scope drift, 2 missing state or refusal
(dirty submodule, nested repository, gitlink, missing baseline, overlap).
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

SCHEMA = 1
DEFAULT_LABEL = "default"
KIND = "worktree-scope"
GITLINK = "160000"
EMPTY_SHA = hashlib.sha256(b"").hexdigest()
_LABEL = re.compile(r"[A-Za-z0-9._-]+")


class Refusal(Exception):
    """A condition the script must not guess around; exits 2."""


def _now() -> str:
    stamp = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    return stamp.isoformat().replace("+00:00", "Z")


def _git_process(repo: Path, arguments: list[str],
                 no_replace: bool = False) -> subprocess.CompletedProcess:
    argv = ["git"]
    if no_replace:
        argv.append("--no-replace-objects")
    argv += ["-C", os.fspath(repo), *arguments]
    return subprocess.run(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


def _git(repo: Path, *args: str, no_replace: bool = False) -> bytes:
    proc = _git_process(repo, list(args), no_replace)
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()
        raise Refusal(f"git {' '.join(args)} failed: {detail or 'unknown error'}")
    return proc.stdout


def repo_root(path: str) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_dir():
        raise Refusal(f"not a directory: {candidate}")
    toplevel = _git(candidate, "rev-parse", "--show-toplevel").decode(
        "utf-8", "surrogateescape").strip()
    return Path(os.path.realpath(toplevel))


def head(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD").decode("ascii").strip()


def _decode_path(raw: bytes, context: str, flag_scope: bool) -> str:
    """Decode one raw Git path; flagged modes refuse undecodable or changed bytes."""
    if not flag_scope:
        return os.fsdecode(raw)
    try:
        path = os.fsdecode(raw)
        encoded = os.fsencode(path)
    except UnicodeError as error:
        raise Refusal(
            f"refusing: git path {raw!r} in {context} cannot be decoded: "
            f"{error}") from error
    if encoded != raw:
        raise Refusal(
            f"refusing: git path {raw!r} in {context} does not round-trip "
            "through os.fsdecode/os.fsencode")
    return path


def _index_modes(repo: Path, no_replace: bool = False,
                 flag_scope: bool = False) -> dict[str, str]:
    """Map every index path to its mode (gitlink, executable, symlink, file)."""
    modes: dict[str, str] = {}
    for entry in _git(repo, "ls-files", "-s", "-z",
                      no_replace=no_replace).split(b"\0"):
        if not entry:
            continue
        meta, _, path = entry.partition(b"\t")
        if not path:
            continue
        modes[_decode_path(path, "git ls-files", flag_scope)] = (
            meta.split(b" ", 1)[0].decode("ascii"))
    return modes


def _status_entries(repo: Path, no_renames: bool = False,
                    no_replace: bool = False,
                    flag_scope: bool = False) -> list[tuple[str, str, str | None]]:
    """Parse porcelain v1 -z into (code, path, original path for R/C)."""
    arguments = ["status", "--porcelain=v1", "-z", "--untracked-files=all"]
    if no_renames:
        arguments.append("--no-renames")
    parts = _git(repo, *arguments, no_replace=no_replace).split(b"\0")
    entries: list[tuple[str, str, str | None]] = []
    index = 0
    while index < len(parts):
        entry = parts[index]
        index += 1
        if not entry:
            continue
        if len(entry) < 4:
            raise Refusal(f"cannot parse git status entry {entry!r}")
        code = entry[:2].decode("ascii", "replace")
        path = _decode_path(entry[3:], "git status", flag_scope)
        original = None
        if code[0] in "RC" or code[1] in "RC":
            if index >= len(parts):
                shown = json.dumps(path) if flag_scope else path
                raise Refusal(f"git status truncated after rename of {shown}")
            original = _decode_path(parts[index], "git status", flag_scope)
            index += 1
        entries.append((code, path, original))
    return entries


def _digest(repo: Path, relative: str, flag_scope: bool = False) -> str | None:
    """sha256 of the working-tree bytes, None when the path is absent."""
    target = repo / relative
    try:
        info = os.lstat(target)
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode):
        raw = os.fsencode(os.readlink(target))
    elif stat.S_ISREG(info.st_mode):
        digest = hashlib.sha256()
        with open(target, "rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    else:
        shown = json.dumps(relative) if flag_scope else relative
        raise Refusal(
            f"refusing: {shown} is a directory or special file; "
            "nested repositories and gitlinks are not supported -- resolve it by hand")
    return hashlib.sha256(raw).hexdigest()


def _refuse_unrepresentable(repo: Path, relative: str, mode: str,
                            flag_scope: bool = False) -> None:
    shown = json.dumps(relative) if flag_scope else relative
    if relative.endswith("/"):
        raise Refusal(
            f"refusing: {shown} is a nested repository or a directory entry git "
            "reports as a unit; remove or resolve it by hand")
    if mode == GITLINK:
        raise Refusal(
            f"refusing: {shown} is a dirty submodule (gitlink {GITLINK}); "
            "commit or clean the submodule before recording scope")
    target = repo / relative
    if target.is_dir() and not target.is_symlink():
        raise Refusal(
            f"refusing: {shown} is a directory entry; nested repositories and "
            "gitlinks are not supported -- resolve it by hand")


def _refuse_prefix_collisions(paths, context: str) -> None:
    """One path cannot be a component prefix of another in a sealed path set."""
    present = set(paths)
    for path in sorted(present):
        parts = path.split("/")
        for count in range(1, len(parts)):
            prefix = "/".join(parts[:count])
            if prefix in present:
                raise Refusal(
                    f"refusing: path set for {context} contains both "
                    f"{json.dumps(prefix)} and {json.dumps(path)}; a file/directory "
                    "transition cannot be sealed -- resolve the shape by hand")


def dirty_manifest(repo: Path, no_renames: bool = False,
                   no_replace: bool = False,
                   flag_scope: bool = False) -> list[dict]:
    """Every path that is not clean: staged, unstaged, untracked-but-not-ignored."""
    modes = _index_modes(repo, no_replace=no_replace, flag_scope=flag_scope)
    entries = _status_entries(repo, no_renames=no_renames, no_replace=no_replace,
                              flag_scope=flag_scope)
    if flag_scope:
        _refuse_prefix_collisions(
            [name for _code, path, original in entries
             for name in (path, original) if name is not None],
            "the worktree scope")
    seen: set[str] = set()
    manifest: list[dict] = []
    for _code, path, original in entries:
        for relative in (path, original):
            if relative is None or relative in seen:
                continue
            seen.add(relative)
            mode = modes.get(relative, "untracked")
            _refuse_unrepresentable(repo, relative, mode, flag_scope)
            manifest.append({
                "path": relative,
                "mode": mode,
                "sha256": _digest(repo, relative, flag_scope),
            })
    return sorted(manifest, key=lambda entry: entry["path"])


def _baseline_entries(state: dict) -> dict[str, dict]:
    baseline = state.get("baseline")
    if not isinstance(baseline, dict):
        return {}
    entries = baseline.get("entries", [])
    if not isinstance(entries, list):
        raise Refusal("state file is corrupt: baseline.entries is not a list")
    return {entry["path"]: entry for entry in entries}


def _diff(repo: Path, state: dict, no_renames: bool = False,
          no_replace: bool = False, flag_scope: bool = False) -> dict:
    baseline = _baseline_entries(state)
    baseline_head = state["baseline"]["head"]
    current = dirty_manifest(repo, no_renames=no_renames, no_replace=no_replace,
                             flag_scope=flag_scope)
    candidates = set(baseline)
    candidates.update(entry["path"] for entry in current)
    arguments = ["diff", "--name-only", "-z"]
    if no_renames:
        arguments.append("--no-renames")
    arguments += [baseline_head, "--"]
    for raw in _git(repo, *arguments, no_replace=no_replace).split(b"\0"):
        if raw:
            candidates.add(_decode_path(raw, "git diff --name-only", flag_scope))
    if flag_scope:
        _refuse_prefix_collisions(candidates, "the recomputed scope")

    changed: list[str] = []
    excluded: list[str] = []
    overlapping: list[str] = []
    for path in sorted(candidates):
        digest = _digest(repo, path, flag_scope)
        previous = baseline.get(path)
        if previous is None:
            changed.append(path)
        elif digest == previous.get("sha256"):
            excluded.append(path)
        else:
            changed.append(path)
            overlapping.append(path)
    return {
        "head": head(repo),
        "recorded_at": _now(),
        "changed_paths": changed,
        "excluded_preexisting_paths": excluded,
        "overlapping_paths": overlapping,
    }


def _scope_sha(paths: list[dict]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(paths, key=lambda item: item["path"]):
        digest.update(os.fsencode(entry["path"]))
        digest.update(b"\0")
        digest.update((entry.get("sha256") or "").encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _commit_scope_sha(paths: list[dict]) -> str:
    """SHA-256 over sorted records of path bytes, mode, OID; deletion is empty."""
    digest = hashlib.sha256()
    for entry in sorted(paths, key=lambda item: item["path"]):
        digest.update(os.fsencode(entry["path"]))
        digest.update(b"\0")
        digest.update((entry.get("mode") or "").encode("ascii"))
        digest.update(b"\0")
        digest.update((entry.get("oid") or "").encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


_TREE_DIFF_ARGS = ("diff-tree", "-r", "--raw", "-z", "--no-abbrev", "--no-renames",
                   "--ignore-submodules=none", "--no-commit-id")
GRAFT_FILE = "info/grafts"
_LEAF_MODES = ("100644", "100755", "120000")
_OID_LENGTHS = {"sha1": 40, "sha256": 64}


def _tree_entries(repo: Path, left: str | None = None, right: str | None = None,
                  *, root: str | None = None) -> list[tuple[str, str, str, str, str, str]]:
    """Parse a raw recursive tree diff as (path, oldmode, newmode, oldoid, newoid, status)."""
    if root is not None:
        arguments = [*_TREE_DIFF_ARGS, "--root", root]
        context = f"root commit {root}"
    else:
        arguments = [*_TREE_DIFF_ARGS, left, right]
        context = f"{left}..{right}"
    raw = _git(repo, *arguments, no_replace=True)
    tokens = raw.split(b"\0")
    entries: list[tuple[str, str, str, str, str, str]] = []
    index = 0
    while index < len(tokens):
        header = tokens[index]
        index += 1
        if not header:
            continue
        if index >= len(tokens) or not header.startswith(b":"):
            raise Refusal(f"cannot parse git diff-tree output {header!r} in {context}")
        fields = header[1:].split(b" ")
        path_bytes = tokens[index]
        index += 1
        if len(fields) != 5 or not path_bytes:
            raise Refusal(f"cannot parse git diff-tree record {header!r} in {context}")
        oldmode, newmode, oldoid, newoid, status = fields
        path = _decode_path(path_bytes, context, True)
        for mode in (oldmode, newmode):
            if mode.decode("ascii", "replace") == GITLINK:
                raise Refusal(
                    f"refusing: {json.dumps(path)} is a gitlink (mode {GITLINK}) "
                    f"in {context}; submodules are not supported")
        entries.append((path, oldmode.decode("ascii"), newmode.decode("ascii"),
                        oldoid.decode("ascii"), newoid.decode("ascii"),
                        status.decode("ascii")))
    return entries


def _refuse_unsupported_history(repo: Path) -> None:
    shallow = _git(repo, "rev-parse", "--is-shallow-repository",
                   no_replace=True).decode("ascii", "replace").strip()
    if shallow == "true":
        raise Refusal(
            f"refusing: {json.dumps(os.fspath(repo))} is a shallow repository; "
            "commit-bound verification needs the complete history")
    raw = _git(repo, "rev-parse", "--git-path", GRAFT_FILE, no_replace=True)
    if raw.endswith(b"\n"):
        raw = raw[:-1]
    graft_path = Path(os.fsdecode(raw))
    if not graft_path.is_absolute():
        graft_path = repo / graft_path
    try:
        active = graft_path.is_file() and graft_path.stat().st_size > 0
    except OSError as error:
        raise Refusal(
            f"refusing: cannot inspect graft file "
            f"{json.dumps(os.fspath(graft_path))}: {error}") from error
    if active:
        raise Refusal(
            f"refusing: active graft file {json.dumps(os.fspath(graft_path))} "
            "rewrites history; commit-bound verification is disabled")


def _is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    proc = _git_process(repo, ["merge-base", "--is-ancestor", ancestor, descendant],
                        no_replace=True)
    if proc.returncode == 0:
        return True
    if proc.returncode == 1:
        return False
    detail = proc.stderr.decode("utf-8", "replace").strip()
    raise Refusal(f"git merge-base --is-ancestor failed: {detail or 'unknown error'}")


def _commit_seal_entries(state: dict, repo: Path,
                         label: str) -> tuple[str, dict[str, tuple[str | None, str | None]], str]:
    seal = state.get("commit_seal")
    if not isinstance(seal, dict):
        raise Refusal(
            f"no index seal for {repo} [{label}]; run diff then "
            "seal --index before verifying a commit")
    baseline = state.get("baseline")
    if not isinstance(baseline, dict) or not isinstance(baseline.get("head"), str):
        raise Refusal(
            f"no baseline snapshot for {repo} [{label}]; "
            f"run: worktree-scope.py snapshot --repo {repo} --label {label} "
            "(before verify)")
    base = seal.get("base")
    if base != baseline["head"]:
        raise Refusal(
            f"index seal base {base!r} does not match baseline head "
            f"{baseline['head']!r}; re-snapshot and run seal --index")
    raw_paths = seal.get("paths")
    if not isinstance(raw_paths, list):
        raise Refusal("state file is corrupt: commit_seal.paths is not a list")
    raw_format = _git(repo, "rev-parse", "--show-object-format",
                      no_replace=True).decode("ascii", "replace").strip()
    oid_length = _OID_LENGTHS.get(raw_format)
    if oid_length is None:
        raise Refusal(
            f"refusing: unsupported git object format {raw_format!r}; "
            "commit-bound verification needs sha1 or sha256")
    entries: dict[str, tuple[str | None, str | None]] = {}
    for entry in raw_paths:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise Refusal("state file is corrupt: commit_seal has an invalid path record")
        path = entry["path"]
        if path in entries:
            raise Refusal(
                f"state file is corrupt: commit_seal repeats {json.dumps(path)}")
        if "mode" not in entry or "oid" not in entry:
            raise Refusal(
                f"state file is corrupt: commit_seal record {json.dumps(path)} must "
                "carry explicit mode and oid keys (null for a deletion)")
        mode = entry["mode"]
        oid = entry["oid"]
        if mode is None and oid is None:
            entries[path] = (None, None)
            continue
        if not isinstance(mode, str) or not isinstance(oid, str):
            raise Refusal(
                f"state file is corrupt: commit_seal record {json.dumps(path)} must "
                "have both mode and oid as strings or neither")
        if mode not in _LEAF_MODES:
            raise Refusal(
                f"state file is corrupt: commit_seal record {json.dumps(path)} has "
                f"unsupported mode {mode!r}")
        if not re.fullmatch(f"[0-9a-f]{{{oid_length}}}", oid):
            raise Refusal(
                f"state file is corrupt: commit_seal record {json.dumps(path)} has "
                f"invalid oid {oid!r}; expected {oid_length} hexadecimal characters")
        entries[path] = (mode, oid)
    _refuse_prefix_collisions(list(entries), "the sealed scope")
    scope = seal.get("scope_sha")
    canonical = [{"path": path, "mode": mode, "oid": oid}
                 for path, (mode, oid) in entries.items()]
    if not isinstance(scope, str) or not re.fullmatch("[0-9a-f]{64}", scope):
        raise Refusal(
            "state file is corrupt: commit_seal.scope_sha is missing or not a "
            "sha256 digest")
    if scope != _commit_scope_sha(canonical):
        raise Refusal(
            "state file is corrupt: commit_seal.scope_sha does not match its path "
            "records; rerun seal --index")
    return base, entries, scope


def _state_dir(override: str | None) -> Path:
    if override:
        return Path(override).expanduser()
    env = os.environ.get("HOA_SCOPE_STATE")
    if env:
        return Path(env).expanduser()
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return Path(xdg).expanduser() / "hoa" / "scope"
    return Path.home() / ".local" / "state" / "hoa" / "scope"


def _state_path(repo: Path, label: str, override: str | None) -> Path:
    if not _LABEL.fullmatch(label) or label in (".", ".."):
        raise Refusal(f"invalid label {label!r}; use letters, digits, '.', '_' or '-'")
    key = hashlib.sha256(os.fsencode(os.path.realpath(repo))).hexdigest()[:12]
    return _state_dir(override) / key / f"{label}.json"


def _load(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise Refusal(f"cannot read state file {path}: {error}") from error
    if not isinstance(data, dict):
        raise Refusal(f"state file {path} does not contain a JSON object")
    return data


def _save(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp",
                                        dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(state, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    except BaseException:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass
        raise


def _require_baseline(state: dict, repo: Path, label: str, verb: str) -> dict:
    baseline = state.get("baseline")
    if not isinstance(baseline, dict) or not isinstance(baseline.get("head"), str):
        raise Refusal(
            f"no baseline snapshot for {repo} [{label}]; "
            f"run: worktree-scope.py snapshot --repo {repo} --label {label} "
            f"(before {verb})")
    return baseline


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _emit(args, payload: dict, lines: list[str]) -> None:
    if args.json:
        _print_json(payload)
    else:
        for line in lines:
            print(line)


def cmd_snapshot(args) -> int:
    repo = repo_root(args.repo)
    state_path = _state_path(repo, args.label, args.state_file)
    baseline = {
        "head": head(repo),
        "recorded_at": _now(),
        "entries": dirty_manifest(repo),
    }
    state = {
        "schema": SCHEMA,
        "repo": os.fspath(repo),
        "label": args.label,
        "baseline": baseline,
    }
    _save(state_path, state)
    count = len(baseline["entries"])
    lines = [f"snapshot: {count} dirty paths at {baseline['head'][:12]} [{args.label}]"]
    lines += [f"dirty {entry['path']} {entry['mode']} "
              f"{(entry['sha256'] or 'deleted')[:12]}"
              for entry in baseline["entries"]]
    lines.append(f"state: {state_path}")
    _emit(args, {"state_file": os.fspath(state_path), "baseline": baseline}, lines)
    return 0


def cmd_diff(args) -> int:
    repo = repo_root(args.repo)
    state_path = _state_path(repo, args.label, args.state_file)
    state = _load(state_path)
    _require_baseline(state, repo, args.label, "diff")
    result = _diff(repo, state)
    state["diff"] = result
    _save(state_path, state)
    overlap = result["overlapping_paths"]

    lines = [f"changed {path}" for path in result["changed_paths"]]
    lines += [f"excluded {path}" for path in result["excluded_preexisting_paths"]]
    lines += [f"overlapping {path}" for path in overlap]
    lines += [
        f"changed_paths: {len(result['changed_paths'])}",
        f"excluded_preexisting_paths: {len(result['excluded_preexisting_paths'])}",
        f"overlapping_paths: {len(overlap)}",
        "verdict: overlapping paths need an operator decision"
        if overlap else "verdict: scope defined",
    ]
    _emit(args, {"state_file": os.fspath(state_path), **result}, lines)
    return 0


def cmd_seal(args) -> int:
    repo = repo_root(args.repo)
    state_path = _state_path(repo, args.label, args.state_file)
    state = _load(state_path)
    _require_baseline(state, repo, args.label, "seal")
    if not isinstance(state.get("diff"), dict):
        raise Refusal(
            f"no prior diff for {repo} [{args.label}]; run diff before seal")
    if args.index:
        return _seal_index(args, repo, state_path, state)
    result = _diff(repo, state)
    state["diff"] = result
    overlap = result["overlapping_paths"]
    if overlap and not args.accept_overlap:
        _save(state_path, state)
        listing = "\n".join(f"  overlapping {path}" for path in overlap)
        raise Refusal(
            "overlapping paths are dirty in the baseline and changed since; "
            "decide which writer owns each one, then pass --accept-overlap:\n"
            + listing)
    paths = [{"path": path, "sha256": _digest(repo, path)}
             for path in result["changed_paths"]]
    seal = {
        "head": result["head"],
        "sealed_at": _now(),
        "paths": paths,
        "scope_sha": _scope_sha(paths),
        "accepted_overlap": bool(overlap) and args.accept_overlap,
        "overlap_paths": overlap if args.accept_overlap else [],
    }
    state["seal"] = seal
    _save(state_path, state)
    lines = [f"seal ok: {len(paths)} paths, scope_sha {seal['scope_sha'][:12]}"]
    if seal["accepted_overlap"]:
        lines.append(f"accepted_overlap: {len(overlap)} paths")
    lines.append(f"state: {state_path}")
    _emit(args, {"state_file": os.fspath(state_path), "seal": seal}, lines)
    return 0


def _seal_index(args, repo: Path, state_path: Path, state: dict) -> int:
    _refuse_unsupported_history(repo)
    result = _diff(repo, state, no_renames=True, no_replace=True, flag_scope=True)
    overlap = result["overlapping_paths"]
    if overlap and not args.accept_overlap:
        listing = "\n".join(f"  overlapping {json.dumps(path)}" for path in overlap)
        raise Refusal(
            "overlapping paths are dirty in the baseline and changed since; "
            "decide which writer owns each one, then pass --accept-overlap:\n"
            + listing)
    changed = set(result["changed_paths"])
    unstaged = sorted({
        path for code, path, _original in _status_entries(
            repo, no_renames=True, no_replace=True, flag_scope=True)
        if path in changed and (code == "??" or code[1] != " ")
    })
    if unstaged:
        listing = "\n".join(f"  unstaged {json.dumps(path)}" for path in unstaged)
        raise Refusal(
            "scoped paths still have unstaged or untracked changes; stage exactly "
            "the intended content, then rerun seal --index:\n" + listing)
    base = state["baseline"]["head"]
    current = result["head"]
    if not _is_ancestor(repo, base, current):
        raise Refusal(
            f"refusing: baseline head {base} is not an ancestor of current HEAD "
            f"{current}; re-snapshot and replay the increment before sealing")
    tree = _git(repo, "write-tree", no_replace=True).decode("ascii").strip()
    entries = _tree_entries(repo, base, tree)
    index_paths = {entry[0] for entry in entries}
    if index_paths != changed:
        listing = ([f"  staged {json.dumps(path)}"
                    for path in sorted(index_paths - changed)]
                   + [f"  missing {json.dumps(path)}"
                      for path in sorted(changed - index_paths)])
        raise Refusal(
            "the staged index does not match the recomputed scope; an extra staged "
            "path or a scoped path that is not staged breaks the binding:\n"
            + "\n".join(listing))
    paths = []
    for path, _oldmode, newmode, _oldoid, newoid, _status in entries:
        mode, oid = (None, None) if newmode == "000000" else (newmode, newoid)
        paths.append({"path": path, "mode": mode, "oid": oid})
    paths.sort(key=lambda entry: entry["path"])
    seal = {
        "base": base,
        "paths": paths,
        "scope_sha": _commit_scope_sha(paths),
        "accepted_overlap": bool(overlap) and args.accept_overlap,
        "overlap_paths": overlap if args.accept_overlap else [],
    }
    state["commit_seal"] = seal
    _save(state_path, state)
    lines = [f"commit seal ok: {len(paths)} paths, scope_sha {seal['scope_sha']}"]
    if seal["accepted_overlap"]:
        lines.append(f"accepted_overlap: {len(overlap)} paths")
    lines.append(f"state: {state_path}")
    _emit(args, {"state_file": os.fspath(state_path), "commit_seal": seal}, lines)
    return 0


def _verify_commit(args, repo: Path, state_path: Path, state: dict) -> int:
    _refuse_unsupported_history(repo)
    base, sealed, scope = _commit_seal_entries(state, repo, args.label)
    resolved = _git(repo, "rev-parse", "--verify", "--end-of-options",
                    f"{args.commit}^{{commit}}", no_replace=True)
    oid = resolved.decode("ascii", "replace").strip()
    if not _is_ancestor(repo, base, oid):
        raise Refusal(
            f"refusing: {args.commit!r} resolves to {oid}, which does not descend "
            f"from sealed base {base}")
    endpoint = {entry[0]: ((None, None) if entry[2] == "000000" else (entry[2], entry[4]))
                for entry in _tree_entries(repo, base, oid)}
    drift: list[tuple[str, str]] = []
    for path in sorted(set(sealed) | set(endpoint)):
        if path not in endpoint:
            drift.append(("removed", path))
        elif path not in sealed:
            drift.append(("added", path))
        elif sealed[path] != endpoint[path]:
            drift.append(("modified", path))
    touched: set[str] = set()
    history = _git(repo, "rev-list", "--parents", f"{base}..{oid}", no_replace=True)
    for line in history.splitlines():
        fields = line.split()
        commit = fields[0].decode("ascii")
        parents = [field.decode("ascii") for field in fields[1:]]
        if parents:
            for parent in parents:
                touched.update(entry[0] for entry in _tree_entries(repo, parent, commit))
        else:
            touched.update(entry[0] for entry in _tree_entries(repo, root=commit))
    drift += [("transient", path)
              for path in sorted(touched - set(sealed) - set(endpoint))]
    drift.sort(key=lambda item: item[1])
    if drift:
        lines = [f"SCOPE_DRIFT: {len(drift)} paths", f"commit: {oid}"]
        lines += [f"{kind} {json.dumps(path)}" for kind, path in drift]
        _emit(args, {"ok": False, "state_file": os.fspath(state_path), "commit": oid,
                     "drift": [{"kind": kind, "path": path} for kind, path in drift]},
              lines)
        return 1
    count = len(sealed)
    _emit(args, {"ok": True, "state_file": os.fspath(state_path), "paths": count,
                 "scope_sha": scope, "commit": oid},
          [f"scope ok: {count} paths, scope_sha {scope[:12]}", f"commit: {oid}"])
    return 0


def cmd_verify(args) -> int:
    repo = repo_root(args.repo)
    state_path = _state_path(repo, args.label, args.state_file)
    state = _load(state_path)
    if args.commit is not None:
        return _verify_commit(args, repo, state_path, state)
    if not isinstance(state.get("seal"), dict):
        raise Refusal(
            f"no seal for {repo} [{args.label}]; run diff then seal")
    _require_baseline(state, repo, args.label, "verify")
    seal = state["seal"]
    sealed = {entry["path"]: entry.get("sha256") for entry in seal.get("paths", [])}
    result = _diff(repo, state)
    current = {path: _digest(repo, path) for path in result["changed_paths"]}

    drift: list[tuple[str, str]] = []
    for path in sorted(set(current) | set(sealed)):
        if path not in sealed:
            drift.append(("added", path))
        elif path not in current:
            drift.append(("removed", path))
        elif current[path] != sealed[path]:
            drift.append(("modified", path))

    if drift:
        lines = [f"SCOPE_DRIFT: {len(drift)} paths"]
        lines += [f"{kind} {path}" for kind, path in drift]
        _emit(args, {"ok": False, "state_file": os.fspath(state_path),
                     "drift": [{"kind": kind, "path": path} for kind, path in drift]},
              lines)
        return 1
    scope = seal.get("scope_sha", "")
    count = len(sealed)
    _emit(args, {"ok": True, "state_file": os.fspath(state_path),
                 "paths": count, "scope_sha": scope},
          [f"scope ok: {count} paths, scope_sha {scope[:12]}"])
    return 0


def cmd_status(args) -> int:
    repo = repo_root(args.repo)
    state_path = _state_path(repo, args.label, args.state_file)
    state = _load(state_path)
    if not state:
        raise Refusal(
            f"no state for {repo} [{args.label}]; run snapshot")
    baseline = state.get("baseline") or {}
    diff = state.get("diff") or {}
    seal = state.get("seal") or {}
    entries = baseline.get("entries") or []
    lines = [
        f"repo: {repo}",
        f"label: {args.label}",
        f"baseline head: {baseline.get('head', '-')}",
        f"baseline recorded_at: {baseline.get('recorded_at', '-')}",
        f"baseline dirty: {len(entries)}",
    ]
    if diff:
        lines += [
            f"diff head: {diff.get('head', '-')}",
            f"changed: {len(diff.get('changed_paths') or [])}",
            f"excluded: {len(diff.get('excluded_preexisting_paths') or [])}",
            f"overlapping: {len(diff.get('overlapping_paths') or [])}",
        ]
    else:
        lines.append("diff: none")
    if seal:
        lines += [
            f"seal: {len(seal.get('paths') or [])} paths, "
            f"scope_sha {str(seal.get('scope_sha', ''))[:12]}",
            f"accepted_overlap: {str(bool(seal.get('accepted_overlap'))).lower()}",
        ]
    else:
        lines.append("seal: none")
    _emit(args, {"state_file": os.fspath(state_path),
                 "baseline": baseline, "diff": diff, "seal": seal}, lines)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record, diff, seal and verify a repository's working increment.")
    sub = parser.add_subparsers(dest="verb", required=True)
    for name, handler, help_text in (
        ("snapshot", cmd_snapshot, "record HEAD and every dirty path as the baseline"),
        ("diff", cmd_diff, "compare the current tree with the baseline"),
        ("seal", cmd_seal, "freeze the changed path set and its digests"),
        ("verify", cmd_verify, "refuse when the sealed scope has drifted"),
        ("status", cmd_status, "print the recorded facts"),
    ):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("--repo", required=True, help="repository path")
        command.add_argument("--label", default=DEFAULT_LABEL,
                             help=f"state label (default: {DEFAULT_LABEL})")
        command.add_argument("--state-file", default=None,
                             help="state directory override")
        command.add_argument("--json", action="store_true",
                             help="print machine-readable output")
        if name == "seal":
            command.add_argument("--index", action="store_true",
                                 help="seal the staged index as a commit-bound scope")
            command.add_argument("--accept-overlap", action="store_true",
                                 help="seal overlapping paths explicitly")
        if name == "verify":
            command.add_argument("--commit", metavar="REV", default=None,
                                 help="verify one resolved commit against seal --index")
        command.set_defaults(handler=handler)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except Refusal as error:
        print(f"{KIND}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
