#!/usr/bin/env python3
"""Record and verify the working increment of one repository.

A review dispatches at a commit range, so uncommitted work is invisible to it.
This script makes the increment explicit:

    snapshot  record HEAD plus every dirty path (content digests, index mode)
    diff      compare the current tree with that baseline
    seal      freeze the changed path set and its digests
    verify    recompute the set and refuse when the tree has moved
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


def _git(repo: Path, *args: str) -> bytes:
    proc = subprocess.run(
        ["git", "-C", os.fspath(repo), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
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


def _index_modes(repo: Path) -> dict[str, str]:
    """Map every index path to its mode (gitlink, executable, symlink, file)."""
    modes: dict[str, str] = {}
    for entry in _git(repo, "ls-files", "-s", "-z").split(b"\0"):
        if not entry:
            continue
        meta, _, path = entry.partition(b"\t")
        if not path:
            continue
        modes[os.fsdecode(path)] = meta.split(b" ", 1)[0].decode("ascii")
    return modes


def _status_entries(repo: Path) -> list[tuple[str, str, str | None]]:
    """Parse porcelain v1 -z into (code, path, original path for R/C)."""
    parts = _git(repo, "status", "--porcelain=v1", "-z",
                 "--untracked-files=all").split(b"\0")
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
        path = os.fsdecode(entry[3:])
        original = None
        if code[0] in "RC" or code[1] in "RC":
            if index >= len(parts):
                raise Refusal(f"git status truncated after rename of {path}")
            original = os.fsdecode(parts[index])
            index += 1
        entries.append((code, path, original))
    return entries


def _digest(repo: Path, relative: str) -> str | None:
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
        raise Refusal(
            f"refusing: {relative} is a directory or special file; "
            "nested repositories and gitlinks are not supported -- resolve it by hand")
    return hashlib.sha256(raw).hexdigest()


def _refuse_unrepresentable(repo: Path, relative: str, mode: str) -> None:
    if relative.endswith("/"):
        raise Refusal(
            f"refusing: {relative} is a nested repository or a directory entry git "
            "reports as a unit; remove or resolve it by hand")
    if mode == GITLINK:
        raise Refusal(
            f"refusing: {relative} is a dirty submodule (gitlink {GITLINK}); "
            "commit or clean the submodule before recording scope")
    target = repo / relative
    if target.is_dir() and not target.is_symlink():
        raise Refusal(
            f"refusing: {relative} is a directory entry; nested repositories and "
            "gitlinks are not supported -- resolve it by hand")


def dirty_manifest(repo: Path) -> list[dict]:
    """Every path that is not clean: staged, unstaged, untracked-but-not-ignored."""
    modes = _index_modes(repo)
    seen: set[str] = set()
    manifest: list[dict] = []
    for _code, path, original in _status_entries(repo):
        for relative in (path, original):
            if relative is None or relative in seen:
                continue
            seen.add(relative)
            mode = modes.get(relative, "untracked")
            _refuse_unrepresentable(repo, relative, mode)
            manifest.append({
                "path": relative,
                "mode": mode,
                "sha256": _digest(repo, relative),
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


def _diff(repo: Path, state: dict) -> dict:
    baseline = _baseline_entries(state)
    baseline_head = state["baseline"]["head"]
    current = dirty_manifest(repo)
    candidates = set(baseline)
    candidates.update(entry["path"] for entry in current)
    for raw in _git(repo, "diff", "--name-only", "-z", baseline_head, "--").split(b"\0"):
        if raw:
            candidates.add(os.fsdecode(raw))

    changed: list[str] = []
    excluded: list[str] = []
    overlapping: list[str] = []
    for path in sorted(candidates):
        digest = _digest(repo, path)
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


def cmd_verify(args) -> int:
    repo = repo_root(args.repo)
    state_path = _state_path(repo, args.label, args.state_file)
    state = _load(state_path)
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
            command.add_argument("--accept-overlap", action="store_true",
                                 help="seal overlapping paths explicitly")
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
