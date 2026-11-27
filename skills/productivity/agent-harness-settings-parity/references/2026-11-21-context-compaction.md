# Context-compaction thresholds per harness

Snapshot carried forward on 2026-11-21. The source notes did not pin CLI versions; the paths, keys,
defaults and commands in this map are lookup candidates, not current guarantees. Check the installed
version's help, schema and runtime. A successful parse does not prove composition or activation.

Normalize to the trigger in tokens. For a reserve-based knob, threshold = model window − reserve;
apply any additional limits before comparing effective thresholds. The example policy used below is
a trigger at 50% of the model window, or 500,000 tokens for a 1M-token window.

Read only the entries for harnesses in scope:

| Harness in scope | Read for |
|---|---|
| [OMP](harnesses/omp.md) | Percent vs absolute precedence |
| [OpenCode](harnesses/opencode.md) | Buffer syntax and schema |
| [Pi](harnesses/pi.md) | Token reserve and per-model overrides |
| [Codex](harnesses/codex.md) | Post-turn percent and absolute token limit |
| [DSH](harnesses/dsh.md) | Effective threshold, profile layers and preset realms |

For a gateway harness in scope, check its documented config root for `compression.threshold`
(fraction 0–1, snapshot default `0.75`, example `0.5`) and read back with its
`config get compression.threshold` command.
