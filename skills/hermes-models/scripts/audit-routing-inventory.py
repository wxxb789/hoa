#!/usr/bin/env python3
"""Dump every layer that decides a model, for root + every profile home, as JSON.

Read-only. Run before and after a routing change and diff the two dumps instead of trusting
`hermes config get`. Flags the two defects that hide longest:
  * a fallback chain whose every entry sits on the home's own default provider (self-fallback);
  * agent cron jobs with provider/model = null, i.e. background work riding the hot-path model.

Usage:
    python3 audit-routing-inventory.py [--home ~/.hermes] [--out inventory.json]

Caveat: harness catalogs (pi/omp/omo/opencode/dsh) are only partly visible in files. Read the live
list from the harness itself (`omp models`, `opencode models`) before concluding an id is missing.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path


def load_yaml(path: Path) -> dict:
    try:
        import yaml
    except ImportError as exc:
        raise SystemExit(
            f"audit-routing-inventory: PyYAML is required to read {path} ({exc}); "
            "run it with an interpreter that has it"
        )
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except ImportError as exc:  # PyYAML absent: an empty dict would fake an empty fleet
        raise SystemExit(
            f"audit-routing-inventory: PyYAML is required to read {path} ({exc}); "
            "run it with an interpreter that has it"
        )
    except Exception as exc:
        raise SystemExit(f"audit-routing-inventory: cannot parse {path}: {exc}")


def bare(provider: str | None) -> str:
    return str(provider or "").removeprefix("custom:")


def model_block(cfg: dict) -> dict:
    m = cfg.get("model") or {}
    return {k: m.get(k) for k in ("default", "provider", "api_mode", "base_url")}


def describe(home: Path, name: str) -> dict:
    cfg_path = home if name == "default" else home / "profiles" / name / "config.yaml"
    if name == "default":
        cfg_path = home / "config.yaml"
    cfg = load_yaml(cfg_path)
    default_provider = bare((cfg.get("model") or {}).get("provider"))
    chain = cfg.get("fallback_providers") or []
    providers = [bare((e or {}).get("provider")) for e in chain]
    return {
        "home": str(cfg_path),
        "model": model_block(cfg),
        # Child fallback routes decide where delegated work lands; a change there is a routing change.
        "delegation": {k: (cfg.get("delegation") or {}).get(k)
                        for k in ("backend", "provider", "model", "base_url", "api_mode",
                                  "fallback_providers", "fallback_models")},
        "fallback_providers": chain,
        "fallback_heterogeneous": bool(providers) and any(p != default_provider for p in providers),
        # Values, not just names: a switch that repoints an existing alias leaves the name list
        # identical, so a name-only inventory reports "no change" for a real routing change.
        "model_aliases": {
            alias: {k: v for k, v in sorted((body or {}).items())}
            for alias, body in sorted((cfg.get("model_aliases") or {}).items())
        },
        "reasoning_effort": (cfg.get("agent") or {}).get("reasoning_effort"),
        "reasoning_overrides": (cfg.get("agent") or {}).get("reasoning_overrides"),
        "auxiliary": cfg.get("auxiliary"),
        "moa_presets": cfg.get("moa"),
        # Endpoints and transports are what a routing change moves; key names alone hide it.
        "providers": {
            p: {
                "api": (b or {}).get("api"),
                "transport": (b or {}).get("transport") or (b or {}).get("api_mode"),
                "base_url": (b or {}).get("base_url"),
                "models": {m: {"context_length": (mb or {}).get("context_length"),
                               "max_tokens": (mb or {}).get("max_tokens")}
                           for m, mb in sorted(((b or {}).get("models") or {}).items())},
            }
            for p, b in sorted((cfg.get("providers") or {}).items())
        },
    }


def cron_rows(home: Path) -> list[dict]:
    rows: list[dict] = []
    stores = [(home / "cron" / "jobs.json", "default")]
    # <home>/profiles/<name>/cron/jobs.json -> the store's own directory holds the profile name
    # (`parent.parent.parent` is "profiles", which attributed every non-root job to one fake home).
    stores += [(Path(p), Path(p).parent.parent.name)
               for p in glob.glob(str(home / "profiles" / "*" / "cron" / "jobs.json"))]
    for path, prof in stores:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise SystemExit(
                f"audit-routing-inventory: cannot read cron store {path}: {exc} "
                "(an unreadable store must not look like a fleet with no jobs)"
            )
        jobs = data.get("jobs", data) if isinstance(data, dict) else data
        for j in jobs if isinstance(jobs, list) else []:
            rows.append({
                "profile": prof,
                "id": j.get("id"),
                "name": j.get("name"),
                "kind": "script" if j.get("script") else "agent",
                "enabled": j.get("enabled", True),
                "provider": j.get("provider"),
                "model": j.get("model"),
                "schedule": (j.get("schedule") or {}).get("display"),
            })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--home",
        default=os.environ.get("HERMES_HOME")
        or os.environ.get("HERMES_ROOT")
        or str(Path.home() / ".hermes"),
        help="install root (default: $HERMES_HOME / $HERMES_ROOT, else ~/.hermes)",
    )
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    args.home = os.path.expanduser(str(args.home))     # `~` in HERMES_HOME is the shell's job, not Path's
    if not Path(args.home).is_dir():
        raise SystemExit(
            f"audit-routing-inventory: --home {args.home} does not exist — refusing to emit an "
            "empty inventory for a home that was never read"
        )
    home = Path(os.path.expanduser(args.home))

    names = ["default"] + sorted(p.name for p in (home / "profiles").iterdir()
                                 if p.is_dir() and not p.name.startswith(".")) \
        if (home / "profiles").is_dir() else ["default"]
    homes = {n: describe(home, n) for n in names}
    jobs = cron_rows(home)

    # A paused job cannot double-fire or ride a hot-path model; counting it in the diagnostics
    # reports problems the fleet does not have.
    agent_jobs = [j for j in jobs if j["kind"] == "agent" and j.get("enabled", True)]
    findings = {
        "self_fallback_homes": [n for n, h in homes.items() if not h["fallback_heterogeneous"]],
        "unpinned_agent_jobs": [f"{j['profile']}:{j['name']}" for j in agent_jobs
                                if not (j["provider"] and j["model"])],
        "agent_jobs_on_free_pool_like": sum(1 for j in agent_jobs if j["provider"]),
        "duplicate_schedule_groups": _dup_schedules(agent_jobs),
    }
    out = {"homes": homes, "cron": jobs, "findings": findings}
    text = json.dumps(out, ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


def _dup_schedules(jobs: list[dict]) -> list[list[str]]:
    seen: dict[str, list[str]] = {}
    for j in jobs:
        key = str(j.get("schedule") or "")
        if key:
            seen.setdefault(key, []).append(f"{j['profile']}:{j['name']}")
    return [v for v in seen.values() if len(v) > 1]


if __name__ == "__main__":
    sys.exit(main())
