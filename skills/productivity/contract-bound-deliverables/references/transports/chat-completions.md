# Chat Completions generation

- For a registry entry with `transport: chat`, use `/v1/chat/completions`. Set effort with
  `reasoning_effort` and cap the response with `max_tokens`; reasoning tokens count against that
  cap. Use the project's provider module to identify any gateway that requires a session header
  and browser User-Agent.
- A large `max_tokens` can trigger HTTP 504 on remote gateways. Start near
  `DELIVERABLE_DRAFT_TOKEN_CAP` (default `16000`); on HTTP 504, retry with a lower cap before
  concluding the model failed.
- Set `"stream": true` for the long write. Read SSE `data:` lines and accumulate
  `choices[0].delta.content`; count `delta.reasoning_content` for progress.
- Check the final `finish_reason`: `stop` means complete; `length` means truncated. Raise the cap or
  split the write into two parts when it is truncated.
