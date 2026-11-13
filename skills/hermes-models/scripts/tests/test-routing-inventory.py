#!/usr/bin/env python3
"""Fixture test for audit-routing-inventory.py's cron-store attribution.

Each profile store must be attributed to its own home: a `<home>/profiles/<name>/cron/jobs.json`
whose rows all say `profiles` loses the one field that makes the row actionable.

Run: python3 skills/hermes-models/scripts/tests/test-routing-inventory.py
"""
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "audit-routing-inventory.py"


def load():
    spec = importlib.util.spec_from_file_location("inventory_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    module = load()
    passed = total = 0

    def case(name, actual, expected):
        nonlocal passed, total
        total += 1
        if actual == expected:
            passed += 1
            print(f"ok {total} - {name}")
        else:
            print(f"FAIL {total} - {name}: got {actual!r} want {expected!r}")

    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        (home / "cron").mkdir(parents=True)
        (home / "cron" / "jobs.json").write_text(
            json.dumps({"jobs": [{"id": "root-job", "enabled": True}]}), encoding="utf-8"
        )
        for name in ("alpha", "beta"):
            store = home / "profiles" / name / "cron"
            store.mkdir(parents=True)
            (store / "jobs.json").write_text(
                json.dumps({"jobs": [{"id": f"{name}-job", "provider": None, "model": None}]}),
                encoding="utf-8",
            )

        rows = module.cron_rows(home)
        by_id = {r["id"]: r["profile"] for r in rows}
        case("root store is attributed to default", by_id.get("root-job"), "default")
        case("alpha store is attributed to alpha", by_id.get("alpha-job"), "alpha")
        case("beta store is attributed to beta", by_id.get("beta-job"), "beta")
        case(
            "no row is attributed to the literal 'profiles' directory",
            [r for r in rows if r["profile"] == "profiles"],
            [],
        )
        case("every store contributes a row", len(rows), 3)

        # an alias repointed without renaming must show up as a change
        alias_home = home / "profiles" / "alpha"
        (alias_home / "config.yaml").write_text(
            "model_aliases:\n  work:\n    model: old-id\n    base_url: https://old.invalid\n",
            encoding="utf-8",
        )
        before = module.describe(alias_home, "default")["model_aliases"]
        case("alias values are recorded", before.get("work", {}).get("model"), "old-id")
        (alias_home / "config.yaml").write_text(
            "model_aliases:\n  work:\n    model: new-id\n    base_url: https://new.invalid\n",
            encoding="utf-8",
        )
        after = module.describe(alias_home, "default")["model_aliases"]
        case("repointing an alias changes the inventory", before != after, True)

    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        store = home / "profiles" / "broken" / "cron"
        store.mkdir(parents=True)
        (store / "jobs.json").write_text("{not json", encoding="utf-8")
        try:
            module.cron_rows(home)
            raised = ""
        except SystemExit as exc:
            raised = str(exc)
        case("a malformed cron store stops the audit", "broken" in raised, True)

    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        cfg = home / "config.yaml"
        cfg.write_text(
            "providers:\n  p:\n    api: chat\n    base_url: https://a.invalid\n"
            "    models:\n      m:\n        context_length: 1000\n",
            encoding="utf-8",
        )
        before = module.describe(home, "default")["providers"]
        case("provider endpoint is recorded", before["p"]["base_url"], "https://a.invalid")
        case("provider enablement is recorded", "enabled" in before["p"], True)
        cfg.write_text(
            "providers:\n  p:\n    api: chat\n    base_url: https://b.invalid\n"
            "    models:\n      m:\n        context_length: 2000\n",
            encoding="utf-8",
        )
        after = module.describe(home, "default")["providers"]
        case("moving an endpoint changes the inventory", before != after, True)

    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        cfg = home / "config.yaml"

        def delegation(**kw):
            body = "\n".join(f"  {k}: {v}" for k, v in kw.items())
            cfg.write_text(f"delegation:\n{body}\n", encoding="utf-8")
            return module.describe(home, "default")["delegation"]

        before = delegation(fallback_providers="[a]")
        after = delegation(fallback_providers="[b]")
        case("delegation fallback routes are recorded", before.get("fallback_providers"), ["a"])
        case("changing a child fallback route changes the inventory", before != after, True)

        before = delegation(base_url="https://a.invalid")
        after = delegation(base_url="https://b.invalid")
        case("delegation endpoint is recorded", before.get("base_url"), "https://a.invalid")
        case("moving the delegation endpoint changes the inventory", before != after, True)

        before = delegation(reasoning_effort="high")
        after = delegation(reasoning_effort="max")
        case("child reasoning effort is recorded", before.get("reasoning_effort"), "high")
        case("changing child effort changes the inventory", before != after, True)

        store = home / "profiles" / "p" / "cron"
        store.mkdir(parents=True)
        jobs = {
            "jobs": [
                {"id": "a", "name": "a", "enabled": False, "schedule": {"display": "0 * * * *"}},
                {"id": "b", "name": "b", "enabled": False, "schedule": {"display": "0 * * * *"}},
            ]
        }
        (store / "jobs.json").write_text(json.dumps(jobs), encoding="utf-8")
        rows = module.cron_rows(home)
        case("paused jobs are still listed in the store dump", len(rows), 2)
        active = [r for r in rows if r.get("enabled", True)]
        case("paused jobs are excluded from active diagnostics", len(active), 0)

    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        (home / "profiles" / "alpha").mkdir(parents=True)
        (home / "profiles" / "alpha" / "config.yaml").write_text("model: {}\n", encoding="utf-8")
        case("a home without a profile pin reports none", module.describe(home, "alpha")["profile_pin"], {})
        (home / "profiles" / "alpha" / "profile.yaml").write_text(
            "model: gpt-x\nprovider: q\n", encoding="utf-8"
        )
        pin = module.describe(home, "alpha")["profile_pin"]
        case("a profile-level pin is recorded", pin.get("model"), "gpt-x")
        case("a profile-level provider is recorded", pin.get("provider"), "q")

    print(f"routing-inventory: {passed}/{total} ok")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
