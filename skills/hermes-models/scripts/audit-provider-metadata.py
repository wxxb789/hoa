#!/usr/bin/env python3
"""Read-only provider/model metadata audit for a Hermes install.

Compares every declared `providers.<name>.models.<id>` entry (root + served profiles) against the
endpoint's own catalog, the runtime context-length resolver, and real `state.db` usage; flags the
classes of misconfiguration that are otherwise silent.

Run with an interpreter that has PyYAML and can import the Hermes repo, e.g.
  VENV=$(ls -d ~/.hermes/installs/*/environments/*/venv/bin/python | head -1)
  "$VENV" ~/.hermes/skills/devops/hermes-operations/scripts/audit-provider-metadata.py

Optional: --catalog-url http://localhost:4141/dashboard/api/models --repo ~/.hermes/hermes-agent
Nothing is written; no credentials are printed.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sqlite3
import sys
import urllib.request

import yaml


def load_configs(home: str) -> dict[str, dict]:
    paths = {"default": f"{home}/config.yaml"}
    for p in sorted(os.listdir(f"{home}/profiles")):
        f = f"{home}/profiles/{p}/config.yaml"
        if os.path.exists(f):
            paths[p] = f
    out = {}
    for name, path in paths.items():
        out[name] = yaml.safe_load(open(path)) or {}
    return out


def fetch_catalog(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001
        print(f"!! catalog fetch failed ({type(exc).__name__}: {exc}) — comparing config only")
        return {}


def catalog_index(cat: dict) -> dict:
    idx = {}
    for m in (cat.get("models") or []):
        caps = ((m.get("upstream") or {}).get("capabilities") or {})
        idx[m["id"]] = {
            "ctx": (caps.get("limits") or {}).get("max_context_window_tokens"),
            "out": (caps.get("limits") or {}).get("max_output_tokens"),
            "prompt": (caps.get("limits") or {}).get("max_prompt_tokens"),
            "effort": (caps.get("supports") or {}).get("reasoning_effort"),
            "tools": (caps.get("supports") or {}).get("tool_calls"),
            "vision": (caps.get("supports") or {}).get("vision"),
            "structured": (caps.get("supports") or {}).get("structured_outputs"),
        }
    return idx


def usage_rows(home: str) -> list[dict]:
    db = f"{home}/state.db"
    if not os.path.exists(db):
        return []
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "select model, billing_provider, task, sum(api_call_count), max(last_seen) "
            "from session_model_usage group by 1,2,3"
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()
    return [{"model": r[0], "provider": r[1], "task": r[2], "calls": r[3] or 0, "last": r[4]} for r in rows]


def main() -> int:
    ap = argparse.ArgumentParser()
    default_home = os.path.expanduser(os.environ.get("HERMES_ROOT", os.environ.get("HERMES_HOME", "~/.hermes")))
    ap.add_argument("--hermes-home", default=default_home)
    ap.add_argument("--repo", default=os.path.join(default_home, "hermes-agent"))
    ap.add_argument("--catalog-url", default="http://localhost:4141/dashboard/api/models")
    ap.add_argument("--threshold", type=float, default=0.75, help="compression.threshold")
    args = ap.parse_args()

    cfg = load_configs(args.hermes_home)
    cat = catalog_index(fetch_catalog(args.catalog_url))
    use = usage_rows(args.hermes_home)

    helper = None
    if args.repo and os.path.isdir(args.repo):
        sys.path.insert(0, args.repo)
        os.environ.setdefault("HERMES_HOME", args.hermes_home)
        try:
            from hermes_cli.config_providers import get_custom_provider_context_length as helper  # noqa: PLC0415
        except Exception as exc:  # noqa: BLE001
            print(f"!! resolver import failed ({type(exc).__name__}) — skipping 'declared resolves?' column")

    used_ids = {str(u["model"]).split("/")[-1] for u in use}
    declared_all: set[str] = set()

    print(f"\nconfigs: {', '.join(cfg)}   catalog models: {len(cat)}\n")
    for profile, c in cfg.items():
        print(f"== {profile}")
        for pname, pc in (c.get("providers") or {}).items():
            if not isinstance(pc, dict):
                continue
            api = (pc.get("api") or "").rstrip("/")
            for mid in (pc.get("models") or {}):
                raw = str(mid)
                model = raw.replace("\\", "")
                declared_all.add(model)
                mcfg = pc["models"][mid] or {}
                decl = mcfg.get("context_length") if isinstance(mcfg, dict) else None
                ref = cat.get(model, {})
                resolved = helper(model, api, config=c) if helper and api else None
                flags = []
                if raw != model:
                    flags.append("dot-escaped key -> value ignored")
                if helper and decl and resolved is None:
                    flags.append("declared value does NOT resolve")
                if ref.get("ctx") and decl and decl != ref["ctx"]:
                    flags.append(f"ctx != catalog {ref['ctx']}")
                if ref.get("prompt") and decl and int(args.threshold * decl) > ref["prompt"]:
                    flags.append(f"{args.threshold:g}x ctx > prompt cap {ref['prompt']}")
                if model not in used_ids:
                    flags.append("never used in any session")
                if model not in cat and cat:
                    flags.append("not in catalog (servable? probe it)")
                print(f"   {pname:<18}{model:<24} decl={str(decl):<9} resolves={str(resolved):<9} "
                      f"cat_ctx={str(ref.get('ctx')):<9} out={str(ref.get('out')):<8} prompt={str(ref.get('prompt')):<9}"
                      f"effort={ref.get('effort')} {'; '.join(flags)}")
        for al, ac in (c.get("model_aliases") or {}).items():
            if isinstance(ac, dict):
                print(f"   alias {al} -> {ac.get('model')} via {ac.get('provider')} {ac.get('base_url') or ''}")

    served_unused = sorted(u["model"] for u in use if str(u["model"]).split("/")[-1] not in declared_all)
    if cat:
        unadvertised = sorted(m for m in declared_all if m not in cat)
        if unadvertised:
            print(f"\ndeclared but NOT in catalog (verify they still answer): {', '.join(unadvertised)}")
    if served_unused:
        print(f"used but undeclared (context falls back, usually 272k): {', '.join(sorted(set(served_unused)))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
