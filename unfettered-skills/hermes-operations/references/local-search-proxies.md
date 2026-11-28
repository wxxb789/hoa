# Local search proxies — running ghc-search on this host

When a research task needs web/X search and no URL is known, the engine is the local `ghc-proxy`
(OpenAI-compatible Responses endpoint) driven by the vendored `ghc-search` script.

## Preflight (one command, always)

```bash
curl -sS http://127.0.0.1:4141/v1/models -H "authorization: Bearer dummy"
```

`200` = proxy up, **and the body is the authoritative model-id list** for `--model`. A non-200 means
fix the proxy; do not fall through to a different search product silently.

## The two failures that look like "the tool is broken"

1. **Default model not on this proxy** → `HTTP 400 … The selected model could not be resolved`. The
   per-engine defaults are just defaults, not guarantees. Re-pin from the `/v1/models` list
   (`x --model grok-4.7`, `gpt --model gpt-5.6-luna`) or set `GHC_SEARCH_MODEL_X` /
   `GHC_SEARCH_MODEL_GPT`. Re-pin a model; do not drop the engine for the rest of the task.
2. **Default `--max-tokens` is sized for a lookup, not a written answer**. An "analyze / compare /
   best practice" query comes back flagged `[truncated: hit --max-tokens]`, or fails with
   `no 'message' item in response output` when reasoning consumed the budget. Pass
   `--max-tokens 6000`–`8000` whenever you want prose, and re-run rather than trusting the stub — a
   truncated answer still exits 0.

## Working shape

- Engine is a required first argument: `gpt` = web, `x` = X/Twitter. Different corpora, no default.
- Latency 3–20s; date-filtered X queries are the slow end. Budget ~2 min for a 3–5 query sweep.
- Run the sweep **sequentially in one `terminal` call** and tee each answer to its own file under the
task dir (`research/NN-engine-topic.txt`); a foreground `&` background is refused by the tool.
- `--handle` restricts but does not steer, and the script appends handles to the prompt for you.
- An empty source list is possible (answered from model knowledge). No sources ⇒ no citation — say so
  in the report or re-query with `--domain` / an explicit "cite sources" instruction.
- Read the answers back before synthesizing: a truncated or empty file is the normal failure and it is
  cheap to spot with a byte count.

## When the skill itself cannot be patched

`skill_manage` answers `Skill 'ghc-search' not found in active profile` for a vendored/imported skill
that is not in the profile's managed registry. Local corrections then live here or in
`~/.hermes/LOCAL_OVERRIDES.md` — never in the vendored copy, which the next update replaces.
