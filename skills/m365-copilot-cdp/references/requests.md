# Request and result contract

All requests are JSON objects. `operation` is required. Unknown fields fail;
there are no tool-approval, navigation, retry, or execution-permission fields.
The parser runs before UI mutation.

| Operation | Fields | UI effect |
| --- | --- | --- |
| `inspect` | `operation` only | None; reports the active Chat/Code surface |
| `models` | `operation`, `mode` | May switch modes when no draft exists; opens/closes model menus without selecting a model |
| `read` | `operation`, `mode` | None; mode must already be active |
| `send` | `operation`, `mode`, `text`, optional `model` | May switch mode and select an exact model, fills an empty composer, sends once |

`mode` is exactly `chat` or `code`. `text` is a nonblank string without NUL and is
not trimmed or rewritten. `model`, when present, is a nonblank exact UI leaf
label with no leading/trailing whitespace. Discover labels through `models`;
family headings such as `Claude` and `GPT` are not model choices. An unavailable
or duplicate model label fails before send. Omitting `model` retains and verifies
the current model; it does not select a default.

Examples (use only prompts the user authorized):

```json
{"operation":"inspect"}
```

```json
{"operation":"models","mode":"chat"}
```

```json
{"operation":"read","mode":"chat"}
```

```json
{"operation":"send","mode":"chat","model":"Auto","text":"Reply with a short greeting. Do not access files, run commands, or contact services."}
```

For Code, use the actual Code tab and exact Code leaf labels, such as a label
returned by its own model menu rather than Chat's provider aliases. The toolbar
may also display effort; effort is an independent setting and is not part of
the requested model label. This adapter does not move its effort slider.

If the native runtime is not ready, the adapter waits for the model selector's
ready state rather than a fixed sleep, then reports an explicit prerequisite
on timeout. It never switches to Chat as a Code fallback, selects projects,
approves tool permissions, or initializes a separate profile.

## Results

The CLI wraps each successful operation in `{ "ok": true, "result": ... }`:

- `inspect`: `operation`, current `mode`, `host`, `path`, verified `model` (or null
  for a blocked Code prerequisite), `draftPresent` (boolean or null if no unique
  composer is available), and `prerequisite` (string or null). Draft text is not
  returned.
- `models`: `operation`, `mode`, `selected`, and `models`, an array containing
  `label`, `group` (the observed submenu discriminator or null), and `selected`.
- `read`: `operation`, `mode`, and `turns`. Each turn contains opaque assistant
  `id`, numeric turn `index`, rendered `question`, rendered `reply`, and
  `complete`. Chat's rendered question includes exactly one renderer-owned
  trailing LF; send matching accounts for that one LF without trimming user
  whitespace. Code's question has no extra LF.
- Code `read` additionally returns `sessionId`, `state`, and `blocker`. State is
  `empty`, `complete`, `generating`, `incomplete`, `permission-blocked`, or
  `dialog-blocked`. A blocker contains its `kind` and visible control/dialog
  labels. No approval is clicked. Code turns also expose paired `turnId`,
  `userId`, raw generation `live`, and `stepStatuses` evidence.
- `send`: `operation`, actual `mode`, verified `model`, the newly completed `turn`,
  and an `evidence` array naming the checked UI completion signals. Code also
  returns its session ID. An unfinished or permission-blocked conversation is not
  a successful completed send. Code identity/pairing/completion fields come from
  one renderer snapshot; a pending user cannot be hidden by an earlier complete reply.

Rendered Code body text is returned intact, including any file-marking
annotations. Such generated annotations are not proof that files were or were
not modified; the adapter does not inspect the filesystem to manufacture that
claim.

Code turn IDs identify rendered logical records, not canonical backend executions.
The observed client can retain a local-ID record and append its historical form
under another ID after mode re-entry. Read returns those records without text
deduplication; their count is not an execution count. See the
[native replay boundary](ui-contract.md#code-history-replay-boundary).

Private text is returned only because a read/send requested it. Keep stdout and
stderr under `.tmp-artifacts/<bundle>/` when persisting them.

Session request errors are `{ "ok": false, "error": ... }` JSONL responses on
stdout; startup/one-shot failures use stderr and nonzero exit. An explicit final
proof rejection means no click was dispatched and any draft remains for review.
An `UNCERTAIN_SEND` error means the click may have taken effect, including when
an attach/UI error or timeout prevents reply confirmation. Never automatically
retry. A failed operation is not converted into an empty success response.

Session lifecycle commands are handled by the connector rather than this app
parser: `targets`, `select-target` with an exact `target`, and `disconnect`.
Keep one approved connection alive across these commands and app requests; it
avoids repeat approval without claiming a permanent grant.
