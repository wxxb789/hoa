---
name: m365-copilot-cdp
description: >-
  Inspect and operate the independent Microsoft 365 Copilot desktop app through
  local CDP: discover exact model labels, read the active conversation, or send an
  explicitly authorized prompt and capture a newly completed reply. Use for the
  desktop app's Chat or actual Code surface, not a browser PWA, Teams, Cowork, or
  a chat request that merely asks for code.
metadata:
  version: "0.1.0"
---

<!-- index: areas=software-development,work-management; targets=runtime-agnostic -->

# Microsoft 365 Copilot desktop CDP

## Outcome

Use the existing desktop session and exact requested mode/model to obtain the
requested conversation state or a completed new assistant reply. The next
consumer receives JSON containing the actual rendered result and its turn
identity. A Send click, an empty composer, an old reply, or stable text is not
completion evidence.

Chat and Code have separate model/completion contracts. Code needs its native
host, not a generic browser facade. Read [the UI contract](references/ui-contract.md)
when modes, models, selectors, or completion evidence differ.

## Authority

- Inspect/read only what the user requested. Sending a prompt requires explicit
  authorization for its exact purpose; app access alone is not send authority.
- Keep existing drafts. The adapter rejects composing or changing modes with a
  nonempty draft. A pre-existing menu must be closed manually before model
  discovery/selection.
- Code can modify files, run commands, install packages, and connect to services.
  A prompt authorization does not authorize those actions, project creation,
  onboarding acceptance, tool approvals, or persistent permission changes.
- After any error from a Send attempt, treat the result as uncertain. Read the
  conversation and ask the user to reconcile it; never automatically resend.
- Use visible UI roles/test IDs. Keep normal sandboxing, organization policy,
  authentication, and connection/permission prompts intact. Reuse the existing
  signed-in profile; do not create independent profiles or copy authentication
  material. Do not edit profile settings unless the user specifically authorizes
  the documented setting and restart procedure in setup.md.
- Use a dedicated native Copilot window only when its ownership and independence
  are established. Native Chat/Code dual-window operation was not established on
  the observed build; the current session runner is sequential and holds a
  browser-wide writer lock. Coordinate exclusive use of the selected window.
  Do not substitute generic CDP-created windows or automate alongside human input.
- Store request files, output, HTML, screenshots, traces, and other private
  artifacts only under `.tmp-artifacts/<bundle>/`. Do not put personal
  conversation data in source files or tracked documentation.

## Prerequisites and commands

Use Windows and Bun >=1.3 (verified with 1.4.4). Run `bun install --frozen-lockfile`
in `skills/m365-copilot-cdp/scripts/`; with only Node, substitute `npx --yes bun`.
No global Playwright install or browser download is needed.

The independent app must already be running with a loopback-only CDP endpoint
and a working signed-in native session. Prefer `--profile-root` pointing to the
existing profile: it reads only `DevToolsActivePort` to find the current dynamic
browser WebSocket endpoint. An explicit local `--endpoint` is also supported.
The CLI attaches existing targets and disconnects without closing the app; it
never creates pages or navigates a target to another service.

For startup, consent, or unavailable-runtime issues, read
[desktop setup and recovery](references/setup.md). Do not use a PWA, isolated
profile, authentication copy, or policy bypass as a substitute.

From the repository root, prefer one persistent connection:

```powershell
bun skills/m365-copilot-cdp/scripts/copilot.ts --help
$profile = Join-Path $env:LOCALAPPDATA 'Microsoft/Copilot/User Data'
bun skills/m365-copilot-cdp/scripts/copilot.ts --profile-root "$profile" --session
```

If the native app asks **Allow remote debugging?**, explain that this connection
will control the signed-in Copilot window and have the user choose Allow only
for this expected connection. Then keep the process alive. Its initial JSON
contains `ready`, current targets, and JSONL protocol metadata; it is not an app
operation result. Send one JSON object per stdin line:

```jsonl
{"operation":"select-target","target":"EXACT_CDP_TARGET_ID_FROM_READY_OUTPUT"}
{"operation":"inspect"}
{"operation":"models","mode":"code"}
{"operation":"read","mode":"code"}
{"operation":"disconnect"}
```

`{"operation":"targets"}` refreshes discovery within the same connection.
Every app operation requires an explicitly selected exact ID; invalid selection
clears the old one. The working `webview` target is on
`cr.m365copilotapp.svc.cloud.microsoft`, not the `edge://olympia.top-chrome/` shell.

Reusing this connection avoids approval for every command. There is no verified
forever grant: disconnecting or restarting may require fresh consent. The
observed `enableCdpWl` flag was false during a successful native Code interaction;
it is not required by this workflow and its full semantics are undocumented.
Do not toggle it or suppress consent prompts.

For a one-shot request, use `--profile-root "$profile" --target EXACT_ID --request
.tmp-artifacts/copilot-run/request.json`; `--request -` reads JSON from stdin.
That separate connection may ask for approval again, so do not make a separate
`--targets` connection the default discovery workflow.

Results use `{ "ok": true, "result": ... }`; session errors use
`{ "ok": false, "error": ... }` on stdout without disconnecting.
One-shot/startup failures use stderr and nonzero exit.

## Requests

Read [the request and result contract](references/requests.md) before constructing
requests. Unknown fields, unsupported operations/modes, blank text, and inexact
model labels fail before composing.

1. `{"operation":"inspect"}` identifies the current surface, selected model,
   draft presence, and any Code prerequisite without exposing draft text.
2. `{"operation":"models","mode":"chat"}` lists exact selectable leaf labels
   from the live model menus. Use `"code"` for the separate Code model menu.
   Reuse an exact label; never substitute a nearby model or silently fall back.
3. `{"operation":"read","mode":"chat"}` reads the active conversation without
   switching it. Use `"code"` for the active Code session. Incomplete replies are
   marked incomplete; pending permissions are reported without approval.
4. `{"operation":"send","mode":"chat","model":"EXACT LABEL","text":"AUTHORIZED PROMPT"}`
   selects and rechecks the exact model and mode, sends once, and waits for a new
   prompt-linked assistant turn with mode-specific completion evidence. Use
   `"code"` only for an authorized actual Code interaction. Omit `model` only
   when retaining the verified active model is intended.

For Code, inspect the actual Code surface. If onboarding or models are unavailable,
stop with the explicit prerequisite. Do not start a project, approve execution,
or switch to Chat to satisfy the request.

## Completion and handoff

Report mode/model, rendered turn ID, reply, and completion signals. Code IDs are
UI identities, not execution IDs: native history replay can duplicate display
records. Do not infer execution counts, deduplicate text, or resend from them.
Report uncertain sends and unavailable UI explicitly; a read is not a new send.

## Basis

Observed English builds, live acceptance, and the native replay limitation are
recorded in [UI evidence](references/ui-contract.md).
