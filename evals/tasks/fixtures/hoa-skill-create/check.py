import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main(phase):
    source = (ROOT / "package/brief.md").read_text(encoding="utf-8")
    frontmatter, body = source.split("---\n", 2)[1:]
    valid = (
        "name: shift-brief" in frontmatter.splitlines()
        and re.search(r"^description: [^\n]+$", frontmatter, re.M)
        and not re.search(r"(?:[A-Za-z]:[\\/]|/home/|/Users/|~/)", source)
    )
    rules = json.loads(body.split("```json\n", 1)[1].split("```", 1)[0])
    fields = {"has_time", "delivery", "release_approved"}
    actions = {"ask", "stage", "publish"}
    valid = valid and all(
        set(rule) == {"id", "match", "action"}
        and set(rule["match"]) <= fields and rule["action"] in actions
        for rule in rules
    )
    cases = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))
    receipt = [f"package={'valid' if valid else 'invalid'}"]
    for label, inputs in cases.items():
        decision = next(
            (rule["action"] for rule in rules
             if all(inputs[key] == value for key, value in rule["match"].items())),
            "no-match",
        )
        receipt.append(f"{label}={decision}")
    output = "\n".join(receipt) + "\n"
    (ROOT / f"{phase}.txt").write_text(output, encoding="utf-8")
    print(output, end="")
    return 0 if valid else 1


if __name__ == "__main__":
    phase, = sys.argv[1:]
    if phase not in {"before", "after"}:
        raise SystemExit("phase must be before or after")
    raise SystemExit(main(phase))
