#!/usr/bin/env python3
"""Pure-function tests for gdd.dispatch_problems / goal_state_header.

Run: python3 skills/gdd/scripts/tests/test-dispatch-guards.py
Exit 0 when every case matches, 1 otherwise.
"""
import importlib.util
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GDD = os.path.join(os.path.dirname(HERE), "gdd.py")


def load():
    spec = importlib.util.spec_from_file_location("gdd_under_test", GDD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    gdd = load()
    passed = 0
    total = 0

    def case(name, actual, expected):
        nonlocal passed, total
        total += 1
        if actual == expected:
            passed += 1
            print(f"ok {total} - {name}")
        else:
            print(f"FAIL {total} - {name}: got {actual!r} want {expected!r}")

    def blocked(*args, **kwargs):
        return bool(gdd.dispatch_problems(*args, **kwargs))

    case("no contract blocks implement", blocked("implement", "-", [], "a", "b"), True)
    case("archived contract blocks implement", blocked("implement", "docs/goals/archive/0001-x.md", [], "a", "b"), True)
    case("force overrides every guard", blocked("implement", "-", ["x.py"], "a", "a", force=True), False)
    case("empty range blocks review", blocked("review", "g.md", [], "abc1234", "abc1234"), True)
    case("committed range passes review", blocked("review", "g.md", [], "abc1234", "def5678"), False)
    case("dirty worktree blocks implement", blocked("implement", "g.md", ["a.py", "b.py"], "a", "b"), True)
    case("dirty worktree is expected for apply", blocked("apply", "g.md", ["a.py"], "a", "b"), False)
    case("verify stage has no extra guard", blocked("verify", "-", [], "a", "a"), False)

    case("first implement round is allowed", gdd.budget_problem("implement", 0), None)
    case("second implement round is allowed", gdd.budget_problem("implement", 1), None)
    case("third implement round is refused", bool(gdd.budget_problem("implement", 2)), True)
    case("over-budget flag lets it through", gdd.budget_problem("implement", 5, over_budget=True), None)
    case("stages without a cap are never refused", gdd.budget_problem("apply", 9), None)

    import tempfile as _tmp

    with _tmp.TemporaryDirectory() as ledger_dir:
        ledger = os.path.join(ledger_dir, "ledger.tsv")
        with open(ledger, "w", encoding="utf-8") as handle:
            handle.write("\t".join(gdd.LEDGER_COLUMNS) + "\n")
            for stage in ("implement", "implement", "simplify"):
                handle.write("\t".join(["ts", "/tmp/repo", "0007", stage] + ["-"] * 9) + "\n")
        case("ledger counts the stage rows", gdd.ledger_rounds(ledger, "repo", "0007", "implement"), 2)
        case("ledger ignores other stages", gdd.ledger_rounds(ledger, "repo", "0007", "review"), 0)
        case("ledger ignores other goals", gdd.ledger_rounds(ledger, "repo", "0008", "implement"), 0)
        case("missing ledger counts zero", gdd.ledger_rounds(ledger + ".nope", "repo", "0007", "implement"), 0)

    case("authoring stage records the post-run head", gdd.final_head_for("implement", False, "aaa1111", "bbb2222"), "bbb2222")
    case("report stage keeps the reviewed head", gdd.final_head_for("review", False, "aaa1111", "bbb2222"), "aaa1111")
    case("supplied head wins for an authoring stage", gdd.final_head_for("fix", True, "ccc3333", "bbb2222"), "ccc3333")
    case("supplied head wins for a report stage", gdd.final_head_for("simplify", True, "ccc3333", "bbb2222"), "ccc3333")

    with tempfile.TemporaryDirectory() as tmp:
        ready = os.path.join(tmp, "0007-ready.md")
        with open(ready, "w", encoding="utf-8") as handle:
            handle.write("# 0007\n\nState: Ready\n\nDone when: ...\n")
        provisional = os.path.join(tmp, "0011-provisional.md")
        with open(provisional, "w", encoding="utf-8") as handle:
            handle.write("# 0011\n\n**State:** Provisional\n\nNeeds refinement.\n")
        case("state header reads Ready", gdd.goal_state_header(ready), "ready")
        case("state header reads Provisional", gdd.goal_state_header(provisional), "provisional")
        case("ready contract dispatches", blocked("implement", ready, [], "a", "b"), False)
        case("provisional contract blocks", blocked("implement", provisional, [], "a", "b"), True)
        case("missing file header is empty", gdd.goal_state_header(os.path.join(tmp, "nope.md")), "")

    print(f"dispatch-guards: {passed}/{total} ok")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
