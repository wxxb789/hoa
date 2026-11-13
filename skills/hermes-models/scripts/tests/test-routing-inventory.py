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

    print(f"routing-inventory: {passed}/{total} ok")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
