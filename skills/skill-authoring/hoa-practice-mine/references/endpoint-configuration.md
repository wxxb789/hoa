# Mining endpoint settings

Read before configuring or changing the decision endpoint for `judge` or `anchor-check`.

See [configuration lookup](configuration.md). After the skill-specific
lookup, unset keys fall back to `SESSION_HISTORY_MINING_*` (legacy alias),
`RUBRIC_JUDGE_*`, `GHC_DECISIONS_*`, then `EVALS_*` environment variables.
The config file is `$XDG_CONFIG_HOME/hoa-practice-mine/config.yaml` (fallback
`~/.config/hoa-practice-mine/config.yaml`); the fallback reads environment
variables only, never another skill's config file.

| Key | Flag | Environment variable | Default |
|---|---|---|---|
| `base_url` | `--base-url` | `HOA_PRACTICE_MINE_BASE_URL` (falls back to `RUBRIC_JUDGE_BASE_URL`) | none (required for `judge` / `anchor-check`) |
| `model` | `--model` | `HOA_PRACTICE_MINE_MODEL` (falls back to `RUBRIC_JUDGE_MODEL`) | none (required for `judge` / `anchor-check`) |
| `api` | `--api` | `HOA_PRACTICE_MINE_API` | `decisions` (`decisions` or `chat-completions`) |
| `workers` | `--workers` | `HOA_PRACTICE_MINE_WORKERS` | `16` |
| `api_key` | — | `HOA_PRACTICE_MINE_API_KEY` | `dummy` |
