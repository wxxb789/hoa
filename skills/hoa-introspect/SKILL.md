---
name: hoa-introspect
description: Produce an evidence-cited, cross-agent self-report with deterministic usage facets and a rigorously bounded blind-spot audit. Use only when explicitly asked for "my usage insights", "audit my work patterns", "where am I wasting effort", "blind spots", or a periodic "self-retro". Do not use for raw records or cross-agent search (use hoa-agent-retrieve), a single-session summary, or creating a skill/rule from a finding (use hoa-introspect-distill). Heavyweight and explicit-invocation-only; never run it ambiently.
---

<!-- index: areas=self-management,work-management; targets=runtime-agnostic -->

# hoa-introspect

Turn a bounded set of agent-history records into a layered self-report:

- **L1 — usage panorama:** hard, reproducible counts produced only by
  `scripts/aggregate.py`.
- **L2 — blind-spot audit:** a small set of re-checkable qualitative findings,
  or explicitly none when evidence does not support one.

This is a reflective analysis, not a personality assessment. It describes
observable work patterns within the supplied coverage only.

## Contract

**Input.** Prefer a Retrieval Bundle from **hoa-agent-retrieve** if that sibling
is installed. Do not require it: in bounded mode, accept only a user-provided
bundle, user-provided paths, or records directly accessible in this runtime.
Say exactly what that restriction excludes. Read
[the minimal consumed schema](references/bundle-schema.md) before parsing.

**Output.** Produce all of the following:

1. facets JSON (`aggregated_data` and `facets_summary`) created by
   `scripts/aggregate.py`;
2. shareable HTML and Markdown reports written only after `scripts/pii_gate.py`
   permits their target;
3. a short, redacted at-a-glance chat summary.

**Report language.** Default to `en-US`. Honor `report_language` only from
untracked configuration, or an explicit agent instruction. Render all L1/L2
narrative and headings in that language; preserve numbers, identifiers, and
citations unchanged.

Every report ends with **On the Horizon**, even when it contains only a next
measurement suggestion. When the records have no usable signal, write
`_No insights generated_`; do not invent a conclusion to fill the report.

## Workflow

1. **Set report language and state scope first.** Use `en-US` unless untracked
   `report_language` configuration or an explicit agent instruction selects a
   language. Translate L1/L2 prose and headings only; preserve numbers,
   identifiers, and citations. Load the coverage manifest, record its time window,
   and list only sources whose status is `available`. Never infer absence of a
   behavior from an inaccessible, unsupported, auth-required, or not-found
   source. In bounded mode, say that coverage is partial before interpreting it.
2. **Generate L1 deterministically.** Run:

   ```text
   python scripts/aggregate.py --bundle <bundle> --output <facets.json>
   ```

   The resulting JSON is the sole authority for L1 numbers. Narrate those
   values; never recount records in chat or estimate a percentage.
   See [facet definitions](references/facets.md).
3. **Build L2 candidates conservatively.** Look for repeated work patterns,
   stated-goal versus observable-investment gaps, implicit assumptions, drift,
   friction, and repeatable-work candidates. Seek counter-evidence before
   retaining a candidate. Each retained blind spot needs at least two
   independent origins, not two copies, branches, summaries, or excerpts of one
   origin. Apply [audit rigor](references/audit-rigor.md).
4. **Resolve before claiming.** Put proposed claims and their citations in a
   JSON file, then run:

   ```text
   python scripts/audit.py --bundle <bundle> --claims <claims.json> --output <verified-claims.json>
   ```

   This drops claims with missing records, invalid locators, or fewer than two
   distinct origins. Do not restore a dropped claim in prose. Label each
   surviving statement as **Observation**, **Inference**, or **Speculation**;
   speculation may guide a question but is never evidence.
5. **Write safely.** Before writing HTML or Markdown, ask the PII gate to check
   the exact output path. A tracked-or-unknown repository path is refused and
   redirected to an OS state directory. Never force-add an artifact. Keep raw
   paths, secrets, session IDs, and private text out of chat echoes.
6. **Close honestly.** Summarize coverage, L1 facts, verified L2 findings (or
   `0 qualifying blind spots`), recommendations, candidate rules/configs, and
   On the Horizon. Refer a stable repeatable-work candidate to
   **hoa-introspect-distill** only when the user asks to create an asset.

## Guardrails

- This skill is heavyweight: run only after an explicit request, never as a
  side effect of retrieval, a session summary, or another skill.
- Coverage bounds every conclusion. The manifest is evidence of what was
  inspected, not proof about the operator's entire work history.
- L1 comes from the aggregator, not language-model counting. Preserve its
  zeroes and unknowns.
- The report language changes narrative and headings only; it never translates
  or reformats numbers, identifiers, or citations. See the bundle, facet, and
  audit references for their invariant machine-readable fields.
- `0 blind spots` is a successful result. No quota, no padding, no clinical or
  personality diagnosis.
- A citation must resolve to a supplied record and its locator. `audit.py`
  enforces the mechanical minimum; independently inspect a small citation
  sample before publishing nuanced claims.
- A configured extra source, MCP endpoint, and output override may come only
  from untracked configuration. Do not add personal locators to this package.
- Inputs are read-only. Do not modify agent stores, bundles, source records, or
  repository tracking state.

## Bounded-mode wording

Use wording equivalent to: “This report is limited to the supplied/runtime-
accessible records and cannot make claims about other agents or time periods.”
The same two-independent-origin threshold applies; bounded mode lowers scope,
not rigor.

## Output shape

Use this report outline:

```markdown
# Work-pattern self-report

## Coverage and caveats
## L1 — Usage panorama
## L2 — Evidence-cited audit
_No insights generated_  <!-- when no verified findings exist -->
## Recommendations and repeatable-work candidates
## On the Horizon
```

The at-a-glance chat response is short and redacted: coverage status, the most
useful L1 fact, verified finding count, artifact availability, and one horizon
item. Do not echo artifact paths, session IDs, secret-shaped values, or raw
transcript text.
