import json
import re
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "target"
SETTINGS = {"bundle_root", "project", "model", "adapter"}


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def demo(route, *, profile, env=None, flags=None):
    receipt = {**profile, **(env or {}), **(flags or {})}
    if route["operation"] != "receipt" or set(route["required"]) != SETTINGS:
        raise ValueError("invalid demo adapter contract")
    return {key: receipt[key] for key in route["required"]}


def proves_ignored():
    kwargs = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    with TemporaryDirectory(prefix="port-ignore-") as work:
        shutil.copyfile(TARGET / ".gitignore", Path(work) / ".gitignore")
        subprocess.run(["git", "init", "-q"], cwd=work, check=True, **kwargs)
        result = subprocess.run(
            ["git", "check-ignore", "-v", "private/profiles/local.json"],
            cwd=work, capture_output=True, check=False, **kwargs,
        )
        return result.returncode == 0 and result.stdout.startswith(b".gitignore:")


def main():
    original = load(ROOT / "source/dispatch.json")
    local = load(TARGET / "private/profiles/local.json")
    route = load(TARGET / "route.json")
    note = (TARGET / "note.md").read_text(encoding="utf-8")
    frontmatter = note.split("---\n", 2)[1]
    original_entry = (ROOT / "source/note.md").read_text(encoding="utf-8")
    public = [
        path.read_text(encoding="utf-8").casefold()
        for path in TARGET.rglob("*")
        if path.is_file() and "private" not in path.relative_to(TARGET).parts
    ]
    other = {"bundle_root": "bundle/demo", "project": "demo", "model": "mock", "adapter": "demo"}
    try:
        demo(route, profile={})
    except KeyError:
        missing_blocked = True
    else:
        missing_blocked = False
    checks = [
        ("public-scan", "clean", not any(v.casefold() in p for v in original.values() for p in public)),
        ("package", "valid", note.startswith("---\n")
         and "name: note-dispatch" in frontmatter.splitlines()
         and re.search(r"^description: [^\n]+$", frontmatter, re.M)),
        ("canonical", "one", original_entry.strip() == "canonical_entry=../target/note.md"),
        ("ignore", "covered", proves_ignored()),
        ("install-a", "pass", local == {k: original[k] for k in SETTINGS}
         and demo(route, profile=local) == local),
        ("install-b", "pass", demo(route, profile=other) == other),
        ("precedence", "pass", demo(
            route, profile=other, env={"model": "env", "adapter": "env"},
            flags={"model": "flag"},
        ) == {**other, "model": "flag", "adapter": "env"}),
        ("missing-profile", "blocked", missing_blocked),
        ("remote", "unchanged", load(ROOT / "publication.json")["updates"] == []),
    ]
    output = "".join(f"{key}={status if passed else 'fail'}\n" for key, status, passed in checks)
    (ROOT / "port-receipt.txt").write_text(output, encoding="utf-8")
    print(output, end="")
    return 0 if all(passed for _, _, passed in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
