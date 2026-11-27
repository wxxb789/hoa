# Responses API model compatibility

The search script requires a model that supports the proxy's Responses API. Claude models return
HTTP 400 on this proxy's `/v1/responses` route; a model available through Chat Completions is not
necessarily available through Responses.

Check which models the proxy supports on `/v1/responses` for the chosen search engine, then select
one with `--model` or the corresponding `GHC_SEARCH_MODEL_GPT` or `GHC_SEARCH_MODEL_X` variable.
Do not point this script at `/v1/chat/completions`: it builds and parses Responses API payloads
regardless of the endpoint URL.
