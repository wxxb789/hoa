---
name: teams-cdp
description: >-
  Find people or existing group chats in Microsoft Teams, or send an authorized
  plain-text message to an exact person email or discovered group-chat identity
  through an already signed-in desktop Teams CDP session. Use for Teams UI
  discovery and sending, not channels, meetings, browser login, or Microsoft Graph.
metadata:
  version: "0.1.0"
  areas: "work-management"
  targets: "runtime-agnostic"
---

# Teams CDP

## Outcome

Return structured person/group discovery results, or a new message identifier
with the Teams UI's **Sent** receipt for an authorized exact destination. The
next consumer is the calling agent or user. A click, an empty composer, an old
matching message, or successful script exit without a receipt is not a send.

This skill reuses the current signed-in Teams desktop profile over local CDP.
It can request the app's native new-message window; it does not create an
independent profile, copy authentication, create a raw Teams browser page, call
private Teams APIs, or change operating-system policy. It supports the observed
English Teams v2 UI; unsupported or ambiguous UI fails explicitly.

## Authority and safety

- Choose an automation-owned native window before discovery/sending. An exact
  `--target` is mandatory, but naming a target does not authorize taking over
  the human's window. Sharing the main window requires explicit user permission
  and sequential use; never run it concurrently with human interaction.
- Prefer `open-window` through the app-provided action in the existing profile.
  A blank or limited popout is a real stop, not permission to fall back to the
  main window. The observed client has not established a separate globally
  searchable main window; see [native-window evidence](references/ui-evidence.md#native-window-isolation).
- Find is read-only with respect to messages, but may open existing conversations
  and change the selected chat/search. Send only when the user has authorized the
  exact recipient and message. Discovery results never authorize a send.
- A person destination must be an explicit email, not a display name. A group
  destination must contain both the exact `id` and `name` returned by discovery.
  Duplicate names are resolved by ID; missing, changed, or ambiguous IDs stop
  before composing. Do not silently substitute a person, group, channel, or meeting.
- Preserve drafts. The adapter refuses nonempty composers, visible draft text,
  or media/attachments detected in the composer footer. It never clears an
  existing draft. If composing fails, inspect the retained new draft manually.
- An error at or after the single Send click is an **uncertain outcome**. Never
  retry automatically: inspect the exact chat first, even if the click timed out.
- Keep request/response JSON, screenshots, HTML, and diagnostic data only in a
  dedicated `.tmp-artifacts/<bundle>/` under the repository root. Discovery
  contains personal data; do not commit it or paste unrelated messages.
- Do not copy cookies/tokens, bypass tenant controls, disable sandboxing, change
  registry/environment settings, or enable remote CDP exposure. If CDP is not
  available, obtain the approved application-start procedure rather than inventing
  flags or changing system configuration.

## Prerequisites and commands

Use **Bun >= 1.3** (verified with 1.4.4). With only Node/npm, replace `bun` with
`npx --yes bun`. No global Playwright install or browser download is needed.
The independent package includes locked dependencies and strict TypeScript settings.
Install from `skills/teams-cdp/scripts/` when authorized:

```text
bun install --frozen-lockfile
```

For an installed skill, replace `skills/teams-cdp` with this SKILL.md's directory
and quote paths containing spaces. Keep request JSON in the caller's private
artifact directory. Only local CDP endpoints are supported:

```text
bun skills/teams-cdp/scripts/teams.ts --help
bun skills/teams-cdp/scripts/teams.ts --endpoint http://127.0.0.1:9222 --targets
bun skills/teams-cdp/scripts/teams.ts --endpoint http://127.0.0.1:9222 --target EXACT_TARGET_ID --request .tmp-artifacts/teams-run/request.json
```

`--request -` reads JSON from stdin. Every request requires `--target`, an exact
CDP target ID rather than a URL/title substring. The runner attaches only to the
named existing page and disconnects without closing Teams. Target IDs and titles
do not prove window ownership or recipient identity. Hidden bootstrap pages and
native popouts can share the main window's URL. See
[the UI evidence](references/ui-evidence.md) when diagnosing target/selector drift.

If the endpoint is unavailable, read [Windows startup](references/startup.md).
It supplies the observed process-scoped WebView2 launch procedure. Obtain
permission for any necessary restart; never kill existing Teams processes,
persist debug flags, or add automatic connection/send retries.

## Workflow

Read [the request and result contract](references/requests.md) before constructing
a request. Validate it before UI mutation. Prefer `open-window` for an owned native
popup; report unsupported capabilities rather than falling back to the main window.

An explicit person email can use the popup's recipient picker. Global `find`
requires a full main window authorized for sequential use; its results are not a
complete directory. Send only to the authorized exact email or unchanged group
reference, preserving the text and line breaks without adding a signature.

Run once. Success is JSON `{ "ok": true, "result": ... }` with a new message ID and
**Sent** evidence. Errors use stderr and nonzero exit. Report the exact destination
and receipt without unrelated private data. An uncertain outcome stops further
sends until a human or authorized inspection has reconciled it.

## Supported boundary

Supported: native new-message windows, person and existing non-meeting group
discovery, and plain-text sends to exact identities. Global discovery needs the
full search/profile frame. Empty new-message popups support exact-email persons;
existing recipient selections, picker queries, and drafts cause a stop.

Existing-group popouts can send when their composer ID and rendered name match
the request. Open one through **More chat options → Open in new window** while
the group is already selected. This does not navigate the main chat. The adapter
enforces directory identity and concrete composer/Send binding;
[UI evidence](references/ui-evidence.md) defines those checks.

Not supported: guaranteed concurrent global discovery, sending from an unverified
per-chat/new-message popout, channels, meeting chats, group creation or membership
changes, attachments, edits/deletes, rich formatting, mentions, localized UI
variants, background delivery guarantees, or read receipts. A **Sent** UI receipt
does not prove the recipient read the message. An existing chat draft, tenant
restriction, changed UI, or missing identity evidence is a real stop, not permission
to guess.

## Provenance and verification limits

Live integration on 2026-10-28 verified an exact-email self-send with an empty
line, a fresh **Sent** receipt, and an unchanged main-window conversation/draft.
Other-person/group delivery and fresh-host activation remain unverified.
Behavioral fixtures are in `scripts/teams.test.ts`; live evidence and its limits
are recorded in [UI evidence](references/ui-evidence.md).
