# Observed UI contract

Read this when a selector fails, a mode/model cannot be verified, or a request
needs a completion claim. These are live DOM observations of the independent
Copilot desktop builds `157.0.4341.16` and `157.0.4341.24`, not app-private API assumptions.

## Target and frame identity

The working target has type `webview` and exact host
`cr.m365copilotapp.svc.cloud.microsoft`. Chat uses `/hwav2/chat` (including
`/hwav2/chat/conversation/...`); Code uses `/hwav2/code`. The outer type `page`
with URL `edge://olympia.top-chrome/` is only a shell. Playwright's ordinary
`connectOverCDP` does not expose that webview as a Page. The bundled connector's
loopback relay normalizes its CDP target classification for Playwright without
creating/navigating targets or modifying the installed dependency. The adapter
still verifies the real working frame's exact host and path.

The adapter inspects frames and requires exactly one working frame. It rejects
unknown hosts, a shell-only attachment, multiple candidate frames, and Cowork.
It does not use a loose `copilot` title match. Localized labels or a different
build require a fresh real DOM observation before changing selectors.

## Mode and model

Observed navigation uses either selected `tab` controls or a sidebar mode button
with `value="chat"` / `value="code"`, an exact `Chat` / `Code` accessible name,
and `aria-haspopup="menu"`. Its menu contains `Chat`, `Cowork`, and `Code` links.
The adapter waits for the requested menu item and resulting mode/route agreement.
Code remains accessible from this menu with Work IQ enabled; changing modes does
not require changing the Work IQ grounding switch.

Chat model control: role `button`, accessible name `<selected>, Model Selector`.
The model menu uses role `menuitem`, `aria-checked`, and a first rendered text
line containing the exact leaf label. Descriptions occupy following lines.
Observed family controls:

- `[data-testid="gptSubMenuModelTrigger-Claude"][aria-haspopup="menu"]`
- `[data-testid="gptSubMenuModelTrigger-OpenAI"][aria-haspopup="menu"]`

Leaf items reuse the family test IDs but have no `aria-haspopup="menu"`; a
family heading is not a selectable model. Enumerate live leaf labels rather
than mapping friendly names to hidden model IDs. The selected toolbar label is
rechecked after selection and immediately before sending. `Auto` is an explicit
choice, not a fallback for an unavailable requested model.

## Chat composing, reading, and completion

- Composer: role `textbox`, exact name `Message Copilot`, contenteditable.
  The observed Lexical editor appends an `aria-hidden="true"` marker span
  containing zero-width characters. Composer checks exclude that hidden node
  structurally, preserve visible Unicode, and retain paragraph/BR newlines.
  They do not strip zero-width characters from the user's text globally.
- Send: role `button`, exact name `Send` (visible when text is entered).
- Turn: `data-testid="m365-chat-llm-web-ui-chat-message"`, with numeric
  `data-message-index`.
- User content: `chatQuestion` containing `chatOutput` test IDs.
- Assistant: `data-testid="copilot-message-div"`, with a nonempty
  `id="chatMessageResponse-..."`; it contains role `article`.
- Rendered reply body: `data-testid="lastChatMessage"` within that assistant.
- Completed historical reply controls: visible enabled
  `data-testid="CopyButtonTestId"` (accessible name `Copy Response`) and
  `data-testid="FeedbackContainerTestId"`, scoped to the same assistant.

A successful send requires a response ID absent from the pre-send snapshot, a
turn index greater than its previous maximum, the exact submitted user prompt
in that same turn, a nonempty assistant body, and the scoped completion
controls. `chatOutput.innerText` adds exactly one renderer-owned trailing LF;
matching therefore requires `rendered === requested + "\n"`, not trimming the
requested text. Authored leading/trailing whitespace and newlines remain
significant. An old reply, cleared composer, click, network response, or fixed
sleep is not completion. An error after click dispatch is uncertain and is never
automatically retried.

Integration on 2026-10-28 verified Chat model selection, a prompt containing an
empty line, a newly completed reply, and read-back of that same turn. A trusted
keyboard event also invalidated the response guard in a separate no-send probe.

## Actual Code surface

Code content is in open shadow DOM. Playwright role/CSS locators pierce it;
ordinary `document.querySelector` does not. The connected app must retain its
native Code host and use the user's existing signed-in profile. The initial
isolated-profile investigation showed only a disabled Code facade and is not a
supported setup; use [the current native setup](setup.md).

### Model menu and composing

- Composer: role `textbox`, `data-testid="lexical-chat-editor"`. Its accessible
  name is `Create anything` initially and `Ask a follow-up or request changes`
  in an existing session; do not bind only the initial name.
- Send: role `button`, exact name `Send message`, `data-testid="send-button"`.
- Model toolbar: `Model: <exact model>, effort: <effort>`, or `Model: <exact
  model>` when no effort is exposed. Effort is separate from the model label.
- Opening that toolbar exposes a group named `Model, effort, and context window`.
  Its `Change model: ...` button opens group `Models`.
- Family buttons are named `Claude Anthropic` and `GPT OpenAI`. Their nested
  groups are `Claude models` and `GPT models`.
- Model leaves are `button[data-model-row]`, with exact rendered model names
  and `aria-pressed` for selection. The adapter verifies the toolbar label after
  selection and leaves the effort slider untouched.
- Project control: `Choose project: New project`; execution location: `Where to
  run this session: Local`; agent mode: `Agent mode: Interactive`. These are
  observations, not controls the adapter is authorized to change.
- First-run onboarding is `Welcome to Copilot Code`. Startup may expose status
  `Loading Code` and `Model: Models unavailable`; a disabled composer is not a
  working Code session. Wait on ready controls, not a fixed delay.

### Session and turn identity

The home route is `#/sessions`; an active session is `#/sessions/<UUID>` on
`/hwav2/code`. The region named `Code session` contains log `Chat messages` and
feed `Conversation messages`.

- User wrapper: article with `data-message-role="user"`, accessible name
  `Your message`. Its inner node has `data-persona="user"` and a
  `data-message-id="turn-<UUID>:user"`.
- The observed user text boundary is that inner node's first-child div,
  first-child bubble div, first-child markdown div. Its `innerText` equals the
  submitted prompt exactly, without Chat's renderer-owned LF.
- Assistant wrapper: article with `data-message-role="assistant"`, accessible
  name `Assistant response`, `data-message-id="turn-<same UUID>:assistant"`,
  and numeric `aria-posinset`.
- The nested article named `Bot message` has `data-persona="bot"` and the same
  assistant message ID. Its first child div is the rendered reply content;
  the later div contains message actions. This structural boundary avoids
  volatile CSS-module class names and excludes thought/action text.

The rendered body may include file-marking annotations. Preserve them as text;
do not reinterpret a model-generated `none` as a filesystem audit.

### Completion and blocked interaction

The assistant's `simplified-chain-of-thought` test ID has `data-live="false"`
after generation. Its `simple-cot-row` children have `data-step-status="done"`.
The same Bot message exposes enabled, visible `Copy Response` and `Regenerate`
buttons. Completion requires all of these conditions plus the paired user and
assistant identity and a nonempty reply. `data-live="true"`, missing completion
controls, missing/mismatched IDs, or a non-done step never count as completed.

A send additionally requires a newly observed assistant ID and feed position,
the exact prompt in its paired user message, and the original session ID (or a
newly assigned session ID when sending from the home route). Reading preserves
generation state rather than treating an old last reply as a new answer.

The no-tools diagnostic produced a real completed response without approval
controls. It did not exercise a permission request. At runtime, visible
dialog/alertdialog roles block the operation; visible approval-intent button
labels (`Approve`, `Allow`, `Grant permission`, including their suffixes) are
reported conservatively as permission-blocked. No such control is clicked.
Unrecognized inline permission UI remains incomplete/uncertain rather than
being reported as success. Native connection consent is outside the Code DOM
and is handled by the user's explicit approval, not this adapter.

## Drafts and atomic submission

Whitespace-only drafts are preserved. Hidden Lexical marker nodes are excluded
structurally, while visible Unicode and actual paragraph/BR newlines remain
significant. A lone placeholder BR is not mistaken for a draft.

Both modes bind concrete composer and Send element handles. An empty-state,
mode, route/session, and exact-model check prepares the selection inside the
editor. Text entry uses page-bound trusted CDP input. Chat accepts a multiline
insert; Code requires separate Shift+Enter events to avoid extra DIV line breaks.
Before submission, one renderer task checks those proofs and exact text again,
then clicks the bound Send button without an intervening await or re-resolution.
Failures preserve drafts; errors after dispatch are uncertain and are not retried.

Response waiting pins the conversation identity using frame navigation events,
not only polling snapshots. An empty surface permits one creation transition after
a verified dispatch. Subsequent identity changes remain invalid even if the user
returns to the original conversation. Trusted pointer/keyboard interaction,
document replacement, and frame detachment invalidate the proof. These checks
support exclusive ownership, not arbitrary concurrent external control of a window.

The final Code integration selected `Claude Haiku 5.5`, preserved a prompt with
an empty line, created a native session, and read its completed reply. No project,
file, command, package, service connection, or tool permission was requested.

## Code history replay boundary

A controlled single-nonce probe recorded one Send click and one completed turn
in the immediate read. After Chat/Code re-entry, the same native session displayed
a second same-text pair under a different ID. The Code ShadowRoot was replaced;
the previous root became detached. No further send was issued by the workflow.

The delivered frontend persists its rendered transcript across Code client
lifetimes, while the native client's turn-correlation maps are instance-local.
History projection uses a stored user-event ID when the original client turn
association is unavailable. Replayed records can therefore be appended alongside
the retained local-ID pair. Source and controlled re-entry behavior strongly
support this client identity-lifetime defect; native execution count was not
directly observed and is not inferred from the number of UI records.

The adapter does not patch the vendor client, modify session storage, change
replay cursors, strip ID prefixes, or deduplicate equal text. Its result proves a
new rendered reply in the selected session, not exactly-once backend execution.
Independent local hardening reads transcript identity, pairing, completion and
blockers in one DOM snapshot and requires the whole conversation to be complete.
That fixes premature UI receipts, not the vendor's history reconciliation.

Delivered source for build `2.20261026.60.0`:
- [Code UI and transcript lifecycle](https://res.public.onecdn.static.microsoft/midgard/2.20261026.60.0/code-app-remote/chunks/2334.4acf3ef9d0643902.js)
- [Native client and history identity mapping](https://res.public.onecdn.static.microsoft/midgard/2.20261026.60.0/code-app-remote/code.remote.js)

