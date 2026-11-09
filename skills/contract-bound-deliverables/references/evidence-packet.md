# Evidence packet, QA script, and assembly script

Concrete shapes for steps 2, 4 and 5 of the parent skill. Adapt names; keep the sections.

## Packet outline (the only permitted writing input)

```
# Evidence packet — <deliverable>, frozen <version>

## Contract
- Length: <range> characters, counted as: <verbatim measuring rule>
- Schema: <section list with required numbering>
- References: <= N entries, format <...>
- Red lines: <phrases/conclusions that must not appear>

## Domain evidence (one block per required section)
- Claim: <what may be asserted>
- Backing: <source id> — "<short verbatim quote>" (page/section)
- Maturity: installed | prototype | trial | demonstrated | unknown
- Allowed numbers: <exact figures that may be cited, with units and date>

## Cross-cutting constraints
- <constraints that apply to every section>

## Do not use (unverifiable, widely circulated, or model-invented)
- <claim> — reason: <not in any primary source | only in secondary retellings | superseded>

## References (numbered, matching the citation markers used in prose)
1. <author>. <title>. <id/date>. <url if no id>
```

Keep the packet's reference numbering identical to the prose citation markers; a numbering drift is
the most common mechanical failure.

## QA script check list

Write one script (`DELIVERABLE_QA_SCRIPT`), run it over every draft and the final, print one line per
file:

- `chars_contract` — count using the contract's verbatim rule, and `in_range` against the range.
- `cites` — distinct citation markers found, vs the required count.
- `unbacked` — every number in the prose not present in the packet (strip heading lines first, or
  section numbers like `4.1` are reported as unbacked numbers).
- `missing` — required sections/headings absent.
- `red` — banned phrases present.
- `refs` — reference entries parsed; accept both `1. Text` and `[1] Text` styles, since models mix
  them.

Report the raw counts in the reply, not a verdict. A file that fails one check is still useful
output; say which check failed.

## Assembly script shape

```python
SECTIONS = [("title", "..."), ("abstract", "..."), ("4.1 ...", "...")]

body = "".join(s for _, s in SECTIONS)
for name, s in SECTIONS:
    print(f"{name:24} {len(s)}")
print(f"TOTAL {len(body)} target {LO}-{HI} {'OK' if LO <= len(body) <= HI else 'OUT OF RANGE'}")
path.write_text(body, encoding="utf-8")
```

- Print per-section lengths on every run; trimming then has an immediate number attached.
- Write **no** header/metadata into the deliverable file — put provenance in a sidecar or here.
- After the build, confirm with `wc -m <file>` and compare against the printed total.
