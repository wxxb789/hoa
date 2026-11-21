# Contract-bound deliverables configuration keys

| Key | Env | Default |
|---|---|---|
| `project_root` | `DELIVERABLE_PROJECT_ROOT` | current working tree |
| `writer_window_minutes` | `DELIVERABLE_WRITER_WINDOW_MINUTES` | `10` — concurrent-writer mtime window |
| `packet` | `DELIVERABLE_PACKET` | none — the frozen packet path |
| `registry` | `DELIVERABLE_REGISTRY` | none — the project's versioned provider registry |
| `harness_dir` | `DELIVERABLE_HARNESS_DIR` | `<project>/.harness` |
| `qa_script` | `DELIVERABLE_QA_SCRIPT` | none — the project's own measuring/QA script |
| `measure_command` | `DELIVERABLE_MEASURE_CMD` | none — the contract's authoritative count |
| `agent_config` | `DELIVERABLE_AGENT_CONFIG` | `$XDG_CONFIG_HOME/<agent>/config.yaml` |
| `search_workers` | `DELIVERABLE_SEARCH_WORKERS` | `4` |
| `search_max_tokens` | `DELIVERABLE_SEARCH_MAX_TOKENS` | `8000` |
| `search_timeout_s` | `DELIVERABLE_SEARCH_TIMEOUT_S` | `260` |
| `search_limit` | `DELIVERABLE_SEARCH_LIMIT` | `10` |
| `draft_token_cap` | `DELIVERABLE_DRAFT_TOKEN_CAP` | `16000` — lower it on a 504 |
| `stream_idle_timeout_s` | `DELIVERABLE_STREAM_IDLE_TIMEOUT_S` | `300` |

Resolution order and the config-file path are defined in
[configuration.md](configuration.md);
this skill does not restate them. Per-project values — packet path, registry, QA script,
measuring rule — belong in a project profile, not in this protocol.
