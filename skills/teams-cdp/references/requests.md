# Teams request and result contract

Read this before invoking the adapter. Commands are shown in `../SKILL.md`.
JSON has no comments; unknown fields, missing fields, wrong types, blank strings,
and NUL characters fail before UI mutation. All examples below use synthetic
identities. Put real request/result files only in `.tmp-artifacts/<bundle>/`.

## Request an automation window

```json
{ "operation": "open-window" }
```

Pass the exact existing main-window `--target` to request the app's native
**New items → New message in new window** action. This operation does not search,
navigate the selected conversation, compose, or send. Existing main-window drafts
are left unchanged. It snapshots all CDP target IDs, inspects new
same-context pages until the observed new-message picker/editor or full main UI
is ready, and cross-checks the complete new target set for ambiguity. The bound is
20 seconds; the first Page event or a page's position is never its identity.
It never creates a browser page or profile and never copies auth.

On a usable native window, the result contains `operation`,
`target: { id, title, url }`, `supported: { find, send }`, and `limitation`.
The observed new-message popup returns `{ "find": false, "send": true }`:
`send` there means exact-email person sending through an untouched native picker,
not global discovery or arbitrary existing-group sending. The recipient still
requires the directory and conversation proof described below. An independently
opened existing-group popout supports the group contract without global search.

A blank new window produces an explicit loading/sign-in prerequisite error with
its target ID. If no additional page is established, the command reports that
instead of borrowing an already open user window. New windows are left open for
inspection; neither errors nor success close a user window or trigger a main-chat
fallback. Native window requests can take focus; perform them between human
interactions. They do not establish guaranteed concurrent global discovery.

Use the returned native target only for the capabilities it proves. Global `find`
still needs a full search/profile window. If only the existing human main window
provides that UI, obtain explicit permission to share it sequentially, then name
its exact target. Exact target selection alone is not consent.

## Discover people

```json
{ "operation": "find", "kind": "person", "query": "Taylor" }
```

The query is trimmed. The adapter selects the People search domain and returns
only identity data: `kind`, directory-card `id`, `name`, and visible exact `email`.
It does not return job titles, phone numbers, office locations, or message text.
A card without a unique visible email/name/ID causes an explicit unsupported-UI
error. Search suggestions alone do not prove an email identity.

## Discover existing groups

```json
{ "operation": "find", "kind": "group", "query": "Planning" }
```

The adapter selects Group chats, opens each returned existing group card, and
extracts its conversation ID from the rendered composer's `data-tabster`
`observed.names` entry beginning `compose-editor:`. Each result is a reusable
reference:

```json
{
  "kind": "group",
  "id": "19:0123456789abcdef0123456789abcdef@thread.v2",
  "name": "Planning"
}
```

Duplicate names remain separate groups. A duplicate ID, changed search order,
unsupported meeting-chat ID, or missing metadata fails without sending. The
adapter may finish with the last inspected group selected. It stops rather than
navigating away from a nonempty draft. Search is a UI result set, not a complete
organization-wide directory/inventory; no result is an empty `results` array.

## Send to a person

```json
{
  "operation": "send",
  "target": { "kind": "person", "email": "taylor@example.com" },
  "text": "First line\nSecond line"
}
```

Prefer the automation-owned native popup returned by `open-window`. The input
contract is unchanged. Before typing the email, the adapter requires `newchat`,
an empty composer, an empty recipient query, and no existing selected tags. It
never clears a preselected recipient/query/draft to make the request work.

The popup's `aria-controls` binds the suggestion list. Exactly one visible
`role="option"`, `data-type="Person"`, and exact
`data-tid="people-picker-entry-<email>"` must match. The rendered avatar's existing
`img[src]` URL must expose one consistent directory GUID in both `/users/<guid>/`
and `/8:orgid:<guid>` path segments. This reads a DOM attribute only; the adapter
does not call that endpoint. Missing images, IDs, or ambiguous rows stop instead
of guessing. After selecting that concrete row, the same editor's conversation
must be the one-on-one containing the GUID. `48:notes` additionally requires the
exact selected row's visible `(You)` marker. Only then can composition begin.

This changes only the owned popup's recipient selection. It never navigates the
main window. After selection the picker disappears, so that popup cannot be
reused for a later person request by guessing its email from a title; open another
empty native window. A selection failure leaves the observed UI for inspection.

When explicitly authorized to share a full main window instead, the existing
People-card flow repeats exact-email discovery, verifies the one-on-one ID, and
independently checks profile email for `48:notes`. Display names alone never
authorize or disambiguate a destination.

## Send to an existing group

```json
{
  "operation": "send",
  "target": {
    "kind": "group",
    "id": "19:0123456789abcdef0123456789abcdef@thread.v2",
    "name": "Planning"
  },
  "text": "First line\n\nSecond paragraph"
}
```

Copy `target` from the exact selected group discovery result. In a full main
window, the adapter searches its name, opens exact-name candidates, and requires
exactly one exact ID. It rechecks that identity after reopening the selected group.

Prefer an automation-owned existing-group native popout. When the exact group is
already selected in the main window, **More chat options → Open in new window**
opens it without navigating that main conversation. Inspect the new target ID,
then pass it explicitly to the same group-send request. On a composer-only popup,
the adapter requires its exact composer conversation ID and the exact visible
`h2[data-tid="chat-title"] #custom-chat-topic-renderer` name to match the request.
It does not search, change the popup recipient, or touch the main window before
using the same concrete-node dispatch/receipt path. An ID/name mismatch stops
before composing. A title alone never identifies the destination. A renamed or
vanished group requires discovery again. Person/newchat popouts are not accepted
through this group-only path. Never send to a group just to verify selectors.

## Text, drafts, and receipt

`text` is nonempty plain text; whitespace-only and NUL text are rejected. Leading
and trailing spaces and multiline strings are not trimmed. CRLF/CR line endings
are compared as logical LF lines. The adapter enters lines with Shift+Enter,
preserving empty paragraphs, and compares logical paragraph text before clicking.
A mismatch stops without sending. It uses the Send button, never plain Enter.

The adapter refuses preexisting draft content/media or visible footer text and
never clears existing drafts. Unknown draft UI is handled conservatively. It
fills only after destination verification, binds concrete editor/footer/Send DOM
nodes, and checks their connection, exact identity, exact text, visibility, and
enabled state in the same renderer task as the exact button dispatch. A switched
or detached scope cannot re-resolve to another chat's Send button. A pre-click
failure can retain the newly composed draft; inspect it rather than erasing it
automatically. Keep human activity out of the selected automation window.

A successful result has this shape inside the runner's `{ "ok": true, "result": ... }`:

```json
{
  "operation": "send",
  "target": { "kind": "person", "email": "taylor@example.com" },
  "conversationId": "48:notes",
  "receipt": { "messageId": "1790000000000", "status": "Sent" }
}
```

The synthetic self-chat example only illustrates shape. In a real send, the
adapter snapshots rendered numeric `data-mid` values and their high-watermark
plus the browser's pre-compose time. A receipt must have a new ID above that
watermark, a `time#timestamp-<id>[datetime]` at or after the captured second, exact
rendered content, no visible failure status, and an outgoing English `Sent`
status while the exact editor identity remains present. Thus an older same-text
message newly mounted by virtualization is not accepted merely because its ID
was absent from the snapshot. Missing/changed timestamp evidence or clock skew
fails conservatively with an uncertain outcome. Candidate content is read only
for comparison; message history is never returned.

If clicking throws, delivery fails, the target changes, or the receipt does not
arrive within 20 seconds, stderr reports **Uncertain send outcome** and the
process exits nonzero. This means the message might already exist. Never resend
automatically, including after process interruption. Resolve the outcome by
inspecting the exact chat. Other localized/changed status labels are not treated
as proof and may yield an uncertain outcome.

## Caller acceptance checklist

Run the bundled tests and strict typechecking. Their fixtures are not real-app
acceptance.
For live acceptance, use only a user-authorized self message with a unique marker
and multiline text. Confirm the new message ID plus Sent status in the real UI.
Confirm invalid requests and a nonempty draft produce no sends and preserve the
draft. Inspect duplicate-name group discovery and ID re-selection without sending
unless a group send is separately authorized. Do not replace these with source
text tests or a mocked echo of the expected output.
Request a native window and inspect its additional target and capabilities without
sending. Confirm blank/loading UI and a missing additional target stop without
main-window fallback. Confirm the original selected conversation/draft remains
unchanged. A usable native popout alone does not prove global discovery support.
For a dedicated group popout, inspect the exact rendered ID/name and confirm
mismatched references refuse before composing. Test a real group send only when
separately authorized; the observed usable popup is not a group-send receipt.
For native person acceptance, begin with a new empty popup, not an already selected
person window. Confirm the exact row email/GUID and selected conversation proof;
existing picker queries, selected tags, or drafts must stop without clearing them.
Only the authorized self smoke may send; selector inspection requires no send.
