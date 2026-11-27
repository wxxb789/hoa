# Responses API generation

- For a registry entry with `transport: responses`, use `/v1/responses`. Set effort with
  `reasoning.effort` and cap the response with `max_output_tokens`.
- On HTTP 504, retry with a lower `max_output_tokens` before concluding the model failed.
- Set `"stream": true` for the long write. Use the project's provider module to parse Responses
  events, accumulate output text and distinguish completion from truncation. Raise the cap or split
  the write if the transport reports truncation.
