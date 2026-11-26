"""Step formatting shared by the Claude and OMP transcript adapters."""

from .redact import EXIT_ERR_RE, RegexPatterns, _text_blocks, matches_high_signal, redact_text


def user_step(line: int, text: str, extra_redact: RegexPatterns | None) -> dict:
    return {"line": line, "pivot": True, "kind": "user", "text": f"[L{line} USER] " + redact_text(text, extra_redact)[:560]}


def assistant_step(line: int, text: str, extra_redact: RegexPatterns | None) -> dict:
    text = redact_text(text, extra_redact)
    snippet = text[:360] + " ... " + text[-260:] if len(text) > 660 else text
    return {"line": line, "pivot": False, "kind": "assistant", "text": f"[L{line} ASST] {snippet}"}


def tool_result_step(
    line: int, call_line: int, summary: str, content: object, error: bool, extra_redact: RegexPatterns | None,
    extra_high_signal: RegexPatterns = (),
) -> dict:
    text = _text_blocks(content).strip()
    special = matches_high_signal(summary, extra_high_signal)
    summary = redact_text(summary, extra_redact)
    if error or EXIT_ERR_RE.search(text):
        text = redact_text(text, extra_redact)
        snippet = text[:340] + (" ... " + text[-220:] if len(text) > 600 else "")
        return {
            "line": line, "pivot": True, "kind": "tool_error",
            "text": f"[L{call_line}->{line} TOOL_ERR {summary}] {snippet}",
        }
    if special:
        snippet = redact_text(text, extra_redact)[:200].replace("\n", " | ")
        return {
            "line": line, "pivot": False, "kind": "tool_special",
            "text": f"[L{call_line}->{line} TOOL_OK {summary}] {snippet}",
        }
    return {
        "line": line, "pivot": False, "compact_ok": True, "kind": "tool_ok",
        "text": f"[L{call_line} TOOL_OK {summary[:75]}]",
    }
