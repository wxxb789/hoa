#!/usr/bin/env python3
"""Fixture test for audit-provider-metadata.py's catalog indexing.

Two payload shapes reach this script: a metadata catalog (`models[].upstream.capabilities`) and an
OpenAI-compatible id list (`data[]`). Both must index; neither may be silently dropped.

Run: python3 skills/hermes-models/scripts/tests/test-provider-metadata.py
"""
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "audit-provider-metadata.py"


def load():
    spec = importlib.util.spec_from_file_location("metadata_under_test", SCRIPT)
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

    metadata = {
        "models": [
            {
                "id": "m-1",
                "upstream": {
                    "capabilities": {
                        "limits": {"max_context_window_tokens": 1000},
                        "supports": {"reasoning_effort": True},
                    }
                },
            }
        ]
    }
    idx = module.catalog_index(metadata)
    case("metadata catalog indexes by id", sorted(idx), ["m-1"])
    case("metadata catalog keeps the limits", idx["m-1"]["ctx"], 1000)
    case("metadata catalog keeps the effort flag", idx["m-1"]["effort"], True)

    listing = {"object": "list", "data": [{"id": "gpt-x"}, {"id": "gpt-y"}]}
    idx = module.catalog_index(listing)
    case("an OpenAI id list indexes too", sorted(idx), ["gpt-x", "gpt-y"])
    case("an id list is marked ids-only", idx["gpt-x"].get("ids_only"), True)

    case("an empty payload indexes to nothing", module.catalog_index({}), {})
    case("a missing payload indexes to nothing", module.catalog_index({"models": []}), {})

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        (home / "config.yaml").write_text("model:\n  provider: p\n", encoding="utf-8")
        cfgs = module.load_configs(str(home))
        case("a single-home install loads without profiles/", sorted(cfgs), ["default"])
        (home / "profiles" / "alpha").mkdir(parents=True)
        (home / "profiles" / "alpha" / "config.yaml").write_text(
            "model:\n  provider: q\n", encoding="utf-8"
        )
        cfgs = module.load_configs(str(home))
        case("profiles are picked up when present", sorted(cfgs), ["alpha", "default"])

    print(f"provider-metadata: {passed}/{total} ok")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
