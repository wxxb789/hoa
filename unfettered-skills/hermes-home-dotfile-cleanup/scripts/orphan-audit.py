#!/usr/bin/env python3
"""Read-only orphan audit for $HOME dot dirs and .config/.cache/.local/share children.

Prints OK/ORPHAN? per entry plus the resolved binary. Every ORPHAN? MUST be hand-verified:
probe names give false positives for skills, shell functions and self-contained bundles
(server binary in a share dir, tool installed but not on PATH). Extend PROBES for your machine.
"""
import os, shutil, subprocess, time

HOME = os.path.expanduser("~")
BIN_DIRS = [os.path.join(HOME, d) for d in
            [".local/bin", ".npm-global/bin", ".bun/bin", ".cargo/bin", ".deno/bin",
             ".dotnet/tools", ".nix-profile/bin"]] + ["/usr/local/bin", "/usr/bin", "/bin", "/opt/bin"]


def which(name):
    p = shutil.which(name)
    if p:
        return p
    for d in BIN_DIRS:
        cand = os.path.join(d, name)
        if os.path.exists(cand):
            return cand
    return None


def children(subdir):
    p = os.path.join(HOME, subdir)
    if not os.path.isdir(p):
        return []
    out = []
    for e in sorted(os.listdir(p)):
        f = os.path.join(p, e)
        out.append((e, time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(f)))))
    return out


def probe(label, probes):
    hit = [f"{x}->{which(x)}" for x in probes if which(x)]
    print(f"{'OK  ' if hit else 'ORPHAN?'} {label:28s} {', '.join(hit) or 'no binary found'}")


PROBES = {}  # dir name -> candidate binary names


def main():
    print("### inbound symlink check (do this BEFORE trusting any 'orphan' verdict)")
    for store in [".hermes/skills", ".claude/skills", ".pi/skills"]:
        p = os.path.join(HOME, store)
        if not os.path.isdir(p):
            continue
        groups = {}
        for e in os.listdir(p):
            fp = os.path.join(p, e)
            if os.path.islink(fp):
                parts = os.path.realpath(fp).split(os.sep)
                key = parts[4] if len(parts) > 4 else os.path.realpath(fp)
                groups[key] = groups.get(key, 0) + 1
        print(f"   {store}: {groups}")

    print("\n### running processes worth ruling in/out")
    ps = subprocess.run(["ps", "-eo", "comm="], capture_output=True, text=True).stdout
    names = sorted(set(ps.split()))
    for key in ["tty7", "claude", "codex", "opencode", "dsh", "omp", "firefox"]:
        hits = [n for n in names if key in n.lower()]
        if hits:
            print(f"   RUNNING {key}: {hits}")

    print("\n### $HOME dot entries")
    for e in sorted(os.listdir(HOME)):
        if e.startswith(".") and os.path.isdir(os.path.join(HOME, e)):
            probe(e, PROBES.get(e, []))

    for sub in [".config", ".cache", ".local/share"]:
        print(f"\n### {sub} children")
        for e, mt in children(sub):
            probe(f"{e} ({mt})", PROBES.get(e, []))


if __name__ == "__main__":
    main()
