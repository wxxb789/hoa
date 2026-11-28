# Discord tasks board — reading and closing a card

`~/.hermes/scripts/discord-forum-post.py` is the only card-manipulation entry point.
Actions: `create`, `tag`, `list`, `read`, `comment`, `archive`, `delete`.

## Field map — know what each key really is

`list` (guild active threads filtered to the forum) returns per card: `thread_id`, `name`, `tags`
(ids resolved to names), `message_count`, and `last_message`.

- **`last_message` is misnamed.** It is filled from `thread_metadata.archive_timestamp` — when the
  thread's *archive status* last changed — not from the newest message. Do not age a card from it, and
  never quote a stall duration that came from it. It also jumps forward the instant you archive the
  card, so a hostility check must not be read before/after an action as if it were activity.
- Fix candidate when touching the script: drop the key and let callers use `read`, or derive it from
  `last_message_id` with one extra message fetch. Until then, treat it as `archive_timestamp`.

`read <thread_id> --limit N` returns the newest N messages, oldest-first, each with `at` (UTC,
minute resolution), `author`, and `content` (truncated ~1200 chars). **The newest `at` is the card's
real last-activity time.** When a status or decision line depends on a body that was cut, lift the cap
for that one message via `channels/<thread_id>/messages?limit=N`.

## Tag semantics

`tag <thread_id> <names...>` sends `applied_tags` as the **complete** list — one
`PATCH /channels/<id>`. It replaces rather than adds: pass every tag the card should keep, in one call
(`tag <id> done` clears `wip`, which is usually what you want when closing).

## Closing a card

1. `tag <thread_id> done`
2. `comment <thread_id> "$(cat closeout.md)"` — post long bodies from a file; backticks and `$` inside a
   double-quoted shell string are command-substituted and the body lands mangled.
3. `archive <thread_id>`
4. Read back from the channel object — these commands report success even when nothing changed:

```python
import importlib.util, os
p = os.path.expanduser("~/.hermes/scripts/discord-forum-post.py")
spec = importlib.util.spec_from_file_location("dfp", p)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
s, r = m.api(f"/channels/{tid}")
tm = r.get("thread_metadata") or {}
print(r.get("applied_tags"), tm.get("archived"), tm.get("locked"))
```

Expect the tag you set, `archived: True`, `locked: False` — unlocked means the owner reopens by typing a
message. Piping the script's own stdout into `json.load` fails with `Invalid control character`: the raw
API JSON carries literal newlines inside `content`. Use `json.loads(..., strict=False)`, or the import
above and inspect the returned dict.

## Before you archive

- Archiving is reversible: the thread leaves `/threads/active` (so `list` stops showing it), history is
  intact, and the owner can reopen. Post one closing note first (what lives where, how to surface a
  block, that unarchiving restores history).
- `grep -rl '<thread_id>' ~/claw/tasks ~/.hermes/cron/jobs.json` and check each hit: a `enabled: false`
  / never-run job is not a live driver; a scheduled job with recent runs that delivers into this thread
  is, and it must be repointed before you close.
