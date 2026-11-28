#!/usr/bin/env python3
"""Inventory every Hermes home's instruction surface and profile setup.

Prints, per home: cwd, the AGENTS.md that cwd actually loads (bytes), SOUL size split into
contract-block / generic / role text, the generic-section hash (divergent hashes = the same
rule exists in several wordings), allowed skill count, live skills size and leftover
curator/archive payload.

Usage: python3 audit-profile-lines.py [--home PATH]
Run it with the Hermes venv python when the bare `python3` has no PyYAML:
  ~/.hermes/hermes-agent/venv/bin/python audit-profile-lines.py
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib

import yaml

CI_BEGIN = "<!-- BEGIN CORE-INVARIANTS"
CI_END = "<!-- END CORE-INVARIANTS"
ROLE_MARKERS = ("## \u89d2\u8272\u8986\u76d6", "## Role", "## \u89d2\u8272")


def tree_bytes(p: pathlib.Path) -> int:
    if not p.exists():
        return 0
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def soul_split(text: str):
    i, j = text.find(CI_BEGIN), text.find(CI_END)
    if i < 0 or j < 0:
        return None, text, ""
    ci = text[i:j]
    body = text[j + 5:]
    cut = len(body)
    for m in ROLE_MARKERS:
        k = body.find(m)
        if k >= 0:
            cut = min(cut, k)
    heading = "\n# "
    k = body.find(heading)
    if k >= 0:
        cut = min(cut, k)
    return ci, body[:cut], body[cut:]


def home_row(home: pathlib.Path, root_cwd: str) -> dict:
    cfg = yaml.safe_load(open(home / "config.yaml")) or {}
    model = cfg.get("model") or {}
    cwd = (cfg.get("terminal") or {}).get("cwd") or ""
    agents = pathlib.Path(cwd) / "AGENTS.md" if cwd else None
    agents_bytes = agents.stat().st_size if agents and agents.exists() else 0

    prof = {}
    if (home / "profile.yaml").exists():
        prof = yaml.safe_load(open(home / "profile.yaml")) or {}
    title = (((prof.get("ui_meta") or {}).get("hermes-bots") or {}).get("title")) or ""

    ci, generic, role = soul_split((home / "SOUL.md").read_text())
    skills = home / "skills"
    backups = sum(tree_bytes(p) for p in skills.glob(".curator_backups/*")) if skills.exists() else 0
    live = tree_bytes(skills) - backups if skills.exists() else 0

    return {
        "home": home.name,
        "title": title,
        "model": f"{model.get('provider')}/{model.get('default')}",
        "cwd": cwd.replace(str(pathlib.Path.home()), "~"),
        "agents": agents_bytes,
        "soul": (len(ci) if ci else 0, len(generic), len(role)),
        "ci_ok": ci is not None,
        "generic_hash": hashlib.md5(generic.encode()).hexdigest()[:8],
        "skills": len(prof.get("allowed_skills") or []),
        "live_kb": live // 1024,
        "bak_mb": backups // (1024 * 1024),
        "same_cwd_as_root": bool(cwd) and cwd == root_cwd,
        "paused": bool(prof.get("paused")),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--home", default=str(pathlib.Path.home()))
    args = ap.parse_args()
    H = pathlib.Path(args.home).expanduser()
    homes = [H / ".hermes"] + sorted((H / ".hermes/profiles").glob("*"))
    homes = [h for h in homes if (h / "config.yaml").exists()]
    root_cwd = ((yaml.safe_load(open(homes[0] / "config.yaml")) or {}).get("terminal") or {}).get("cwd") or ""

    rows = [home_row(h, root_cwd) for h in homes]
    print(f"{'home':14} {'ci':3} {'gen':6} {'role':5} {'AGENTS':7} {'skills':6} {'live':5} {'bak':4} model")
    for r in rows:
        ci, generic, role = r["soul"]
        flag = "" if r["ci_ok"] else "!NO-CI-BLOCK"
        print(
            f"{r['home']:14} {'ok' if r['ci_ok'] else '--':3} {generic:<6} {role:<5} "
            f"{r['agents']/1024:6.1f}K {r['skills']:6} {r['live_kb']:4}K {r['bak_mb']:4}M "
            f"{r['model'][:38]} {flag}"
        )

    hashes = {r["generic_hash"] for r in rows if r["generic_hash"] != hashlib.md5(b"").hexdigest()}
    print(f"\ndistinct generic-section hashes: {len(hashes)} "
          f"({'independence is real' if len(hashes) == len(rows) else 'some homes still share one wording'})")
    leaky = [r["home"] for r in rows if r["same_cwd_as_root"]]
    if leaky:
        print(f"homes loading the front-door AGENTS.md via cwd: {', '.join(leaky)}")
    heavy = [f"{r['home']}({r['bak_mb']}MB)" for r in rows if r["bak_mb"] >= 10]
    if heavy:
        print(f"homes carrying replicated skill-archive payload: {', '.join(heavy)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
