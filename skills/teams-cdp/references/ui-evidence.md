# Teams v2 UI evidence

Read this for target selection, supported DOM structure, and selector drift.
Evidence was collected through DOM inspection and authorized self-send tests on
2026-10-28 in an existing English Teams desktop session. No authentication data,
application internals, or private APIs were used. Personal identities, conversation
IDs, and message bodies are omitted from this tracked reference.

## Target and frame selection

- Local endpoint: `http://127.0.0.1:9222`; inspect `/json/list` on each run rather
  than pinning a target ID. Several page targets shared
  `https://teams.microsoft.com/v2/`, including noninteractive bootstrap pages.
- The working target title was `Search | Microsoft Teams` while in Search; title
  is not a stable discriminator and changes with the selected view.
- Working-frame evidence: one visible
  `input[data-tid="AUTOSUGGEST_INPUT"][role="combobox"]`, plus one visible
  `button[data-tid="me-control-avatar-trigger"]`.
- The observed search placeholder was `Search or ask Copilot (Ctrl+E)`. A supplied
  older placeholder differed, so the adapter intentionally uses role/data-tid,
  not placeholder text.
- Chat navigation: button role with exact accessible name `Chat`.
- The main frame hosted the working controls. An unrelated calendar iframe was
  also present and is not an allowed Teams frame. The adapter scans existing
  frames and requires exactly one working HTTPS `teams.microsoft.com/v2/` frame.
- An audio-device transfer dialog appeared during inspection. It was canceled
  through `button[data-tid="hid-control-transfer-workflow-cancel"]`. The adapter
  does not accept such dialogs or transfer device authority automatically;
  obstructed UI fails for the operator to resolve.

## Native window isolation

The existing signed-in desktop process was reused for this inspection. The
application menus exposed these actions:

| Location | Observed action | DOM evidence |
| --- | --- | --- |
| New items | New message in new window, Ctrl+Shift+N | `[data-testid="simple-collab-left-rail-header-create-chat-popout"]` |
| More chat options | Open in new window, Ctrl+O | `[data-tid="chat-header-popout-chat"]` |

Opening the first action created an additional native page target on the same
CDP endpoint and signed-in profile. Its initial title was `New Message | Microsoft
Teams`; its URL was the same `https://teams.microsoft.com/v2/` as the main window.
The main conversation and its composer identity remained unchanged. No message
was composed or sent, no browser page/profile was created, and no user window was
closed. Per-run target IDs are recorded only in the private artifact bundle.

An initial inspection incorrectly treated the last Page object in an already
attached browser as the new target. Exact `Target.getTargetInfo` mapping showed
that it was an older blank page, not the new window. Inspection of every target
by exact ID corrected that finding: the new-message window was usable at 619×703,
with a `people-picker-search` combobox and the standard editor whose conversation
identity was `newchat`. The existing-chat action also produced a usable 619×703
native chat target, with the same conversation ID as the unchanged main chat.
Neither native popup had the main window's global search or profile button.

Both new targets had type `page` and shared the main window's browserContextId in
`Target.getTargets`; `/json/list` also listed both as pages on the same origin.
The older browser tool's `pages()` enumeration omitted these targets even while
the browser's own target inventory contained them. Native-window discovery must
compare complete target-ID sets and inspect each new candidate, not assume the
first page event or the last Page object identifies the native window.
Fresh connection through the actual CLI's Playwright 1.64.1 transport with
`noDefaults: true` materialized both exact native targets as ordinary Pages in
the existing context. No target-type normalization was needed. The older browser
tool's omission is not evidence that the CLI cannot attach to native popouts.

No additional full main-window action was observed in Settings and more, New
items, or More chat options. The observed actions are new-message/per-chat
popouts, not evidence of a separate globally searchable Teams instance. The
adapter keeps search-plus-profile for global discovery. An untouched `newchat`
popup supports the exact-person picker proof below; an existing-group popup can
send after its composer ID and exact
`h2[data-tid="chat-title"] #custom-chat-topic-renderer` name match the request.
Neither popup path navigates/searches the main window or infers a recipient from
the window title. Concurrent global discovery remains unsupported. The original
main conversation ID remained unchanged.

Use the existing profile only. A raw CDP-created Teams page is not a substitute
for a native window: its URL alone does not establish desktop host integration.
Independent profiles, copied authentication, undocumented IPC, and private
backend APIs are outside this workflow.

## Native person picker identity

Safe inspection of the automation-owned new-message popup observed:

- One `input[data-tid="people-picker-search"][role="combobox"]`, initially empty,
  whose `aria-controls` identified its suggestion-list DOM ID.
- A recipient-free `.fui-TagPickerControl` containing only the picker input's
  wrapper. Additional child tags or a nonempty query are not cleared by the adapter.
- After entering an explicitly authorized self email, one visible suggestion with
  `role="option"`, `data-type="Person"`, and
  `data-tid="people-picker-entry-<exact email>"`. The email was exposed in that DOM
  attribute; the row's visible text instead contained name, alias, and role.
- Its rendered avatar `img[src]` exposed the same directory GUID in
  `/api/mt/part/msft/beta/users/<guid>/profilepicturev2/8:orgid:<guid>`. Only that
  existing DOM URL was read; no request to a private API was made.
- The exact self row's visible name ended in `(You)`. Selecting it changed the
  same editor's rendered identity from `newchat` to `48:notes`, removed the picker,
  and left the composer empty. No message was composed or sent, no main-window
  navigation occurred, and the selected self popup was left unchanged afterward.

The implementation requires that directory/email proof, then the selected
one-on-one conversation's participant GUID; only the explicit self marker allows
`48:notes`. Missing avatar identity or unsupported selection UI fails closed.
The final native-popup path passed an authorized self-send test. Other-person
delivery and group delivery have not been exercised against live recipients;
directory observations are not permission to send.


## Search and identities

| Purpose | Observed DOM evidence |
| --- | --- |
| People domain | `button[data-tid="people-tab"][role="tab"]`, `aria-selected="true"` after selection |
| Group domain | `button[data-tid="groupchats-tab"][role="tab"]`, `aria-selected="true"` after selection |
| No results | visible `[data-tid="search-no-results"]` |
| Person card | `[data-tid="search-people-card"][id^="serp-people-card-content-"]`; nested elements may repeat `data-tid`, so the ID-bearing outer card is required |
| Person card identity | card ID suffix is the person's directory GUID; one leaf text node contains the exact email; name is in the card's `[id^="menu"]` descendant |
| Open person | click the ID-bearing outer card; its invisible inner button has `pointer-events:none` and is not a safe click target |
| Group card | `[data-testid="groupChatCard"]` |
| Exact group name | sibling `button[data-tid="carousel-card-button"]` label: `group chat card from <name> is selected. Press Enter to open the group chat and press Tab to navigate within the group chat card.` |
| Open group | click `[data-testid="groupChatCard"]`; card did not expose a conversation ID before opening |
| Sidebar identities | `[data-testid="list-item"][role="treeitem"]` exposed `data-fui-tree-item-value` with group/self/one-on-one conversation types and IDs; not used as a fallback because the sidebar can be virtualized |

The global suggestion list mixed people, files, filters, and in-chat search.
Suggestions exposed display names but did not prove a person email. The adapter
therefore uses full People results and ignores unrelated search domains.

Search begins by opening Chat so prior Search results cannot satisfy a new
search's selector waits. It then uses Enter only in the global search input and
selects the requested result-domain tab. Group searches can contain duplicate
names; they are not resolved by first-match title selection.

## Composer and destination binding

- Visible message editor:
  `[data-tid="ckeditor"][role="textbox"][contenteditable="true"]`.
- Editor accessible label/placeholder: `Type a message`.
- Draft/composer boundary: ancestor `[data-tid="message-pane-footer"]`, containing
  `[data-tid="chat-pane-compose-message-footer"]`. The empty footer contained
  hidden formatting content, so raw `textContent` of the footer is not evidence
  of a draft; the adapter inspects actual text rectangles, editor content, and
  visible media conservatively.
- Editor `id` has a `new-message-` prefix. Its `data-tabster` JSON contains
  `observed.names`, including `chat-input` and a string in this format:
  `compose-editor:["<editor id>","<conversation id>"]`.
- This rendered data attribute is used only as destination evidence. The adapter
  does not read React state, stores, service clients, or application internals.
- Observed self conversation ID: `48:notes`. Observed one-on-one identity shape:
  `19:<directory-guid>_<directory-guid>@unq.gbl.spaces`. Observed ordinary group
  shape: `19:<opaque-id>@thread.v2`. Meeting IDs used a distinct `meeting_`
  prefix and are not accepted as ordinary groups.
- Profile identity: open `button[data-tid="me-control-avatar-trigger"]`, then
  inspect `button[data-tid="me-control-sign-out-button"]` accessible label
  `Sign out from <email>`. No Sign out click is performed. Escape closes the
  profile. This independently binds self-chat sends to the requested email.
- The observed editor's ancestor `message-pane-footer` contained exactly one
  `sendMessageCommands-send` button. The footer and Send button had no stable DOM
  IDs. Input can remount these controls, so the adapter binds the current concrete
  editor, footer, and Send handles after trusted text entry has settled. One renderer
  task rechecks exact composer metadata and text before clicking that button.
  This protects dispatch identity; it does not establish support for concurrent
  use of the same window.

## Send and completion evidence

- Send button: `button[data-tid="sendMessageCommands-send"]` or the observed
  expanded-composer `button[data-tid="newMessageCommands-send"]`, accessible name
  `Send`. No coordinates or keyboard-send convention is required.
- Existing message container: `[data-tid="chat-pane-message"][data-mid]`,
  `role="group"`, DOM ID `message-body-<message-id>`.
- Exact content node: DOM ID `content-<message-id>` inside that message.
  The observed rendered body can wrap paragraphs in `div[data-ask-copilot-content]`.
  An empty paragraph contains an NBSP filler; it matches an empty requested line
  only at that position, without normalizing authored spaces or NBSP characters.
- Existing self-message receipt: `span[id="read-status-icon-<message-id>"]`,
  `role="img"`, `aria-label="Sent"`.
- Message accessibility metadata referenced `failure-status-<message-id>` for
  failures. Existing successful messages had no populated failure text.
- Receipt status could be a sibling rather than a child of the content/message
  node, so the adapter resolves the exact status DOM ID within the same frame.
- Timestamp evidence: a sibling `time#timestamp-<message-id>` exposed an ISO
  `datetime` with millisecond precision matching the numeric message ID's time.
  The adapter requires numeric ID ordering above the rendered high-watermark and
  timestamp freshness at the captured pre-compose second. A newly virtualized old
  row cannot qualify solely by being absent from the initial DOM snapshot.

The final CLI was exercised through a native new-message window on 2026-10-28.
It resolved the exact self email, entered a unique message containing an empty
line, and returned a new message ID with **Sent** status. The main window's
conversation metadata and draft HTML were unchanged across the operation.

CKEditor discards ordinary `execCommand` edits and remounts its footer after input.
The adapter uses page-bound `Input.insertText` plus separate Shift+Enter events,
then binds the current controls for atomic dispatch. It compares logical paragraph
text rather than `innerText` paragraph spacing. During integration, one sent
message initially timed out because the receipt body had a wrapper and NBSP
filler. Its actual Sent state was reconciled without resending; after correcting
receipt parsing, a distinct authorized self-test passed end to end.

Fixtures cover changed/detached composers, newly appearing drafts, modal
interference, historical receipts, wrapped paragraphs, and significant whitespace.
Other-person/group delivery and fresh-host activation evaluation remain separate
acceptance boundaries; neither is implied by a successful self-send.
