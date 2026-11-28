# Recovering the open decision set

For the "ask me everything I missed" round. The goal is a short digest of questions whose answers still
change something, plus a one-line accounting of everything judged moot.

## 1. Harvest the clarify backlog from the session store

Clarify results are tool messages (`role='tool'`, `tool_name='clarify'`) whose content is JSON with a
`responses` array; each response carries `question`, `choices_offered`, `status`, `user_response`, and
the message itself carries `outcome`. Chat prose never records a form, so this is the only complete
source.

```python
import sqlite3, os, glob, json, datetime

dbs = ["~/.hermes/state.db"] + glob.glob("~/.hermes/profiles/*/state.db")
recs = []
for db in dbs:
    con = sqlite3.connect(f"file:{os.path.expanduser(db)}?mode=ro", uri=True)
    q = """select m.id, m.session_id, m.content, m.timestamp, s.title
           from messages m left join sessions s on s.id = m.session_id
           where m.tool_name = 'clarify' and m.role = 'tool'"""
    for mid, sid, content, ts, title in con.execute(q):
        try:
            obj = json.loads(content or "")
        except Exception:
            continue
        if isinstance(obj, dict) and "responses" in obj:
            recs.append(dict(mid=mid, sid=sid, ts=ts, title=title, obj=obj))
```

144 `submitted` / `timed_out` / `undelivered` mixes show up in a normal month; the raw count is not the
open count.

## 2. Reduce to one row per question, judge the latest

Normalize the question text (strip whitespace and parentheticals, take a prefix), group by
`(profile, normalized text)`, sort each group by timestamp, and keep the **last** element. Resolved if
that last response's `status == 'answered'`; open otherwise. Then drop anything older than the re-ask
horizon the owner cares about (a few days; older nodes are usually superseded).

Excluded on the way through:

- `local-*` session ids — cron/test lanes confirming writes to themselves, not questions to the owner.
- sessions whose only records are identical duplicates from a retry loop — the group collapse handles
  this.

## 2b. Read the hanging turn, and the round before this one

The backlog says a form was never answered; it cannot say whether a later turn settled it in prose.

- **Session tails.** For every session whose last activity is after its last open form, read the tail from
  that profile's own store — root conversations in `~/.hermes/state.db`, a bot's in
  `~/.hermes/profiles/<p>/state.db`: `select role, tool_name, substr(content,1,240) from messages where
  session_id=? order by id desc limit 8`. A trailing agent line that names "the two decisions I am waiting
  on" is a live hanging question no form carries.
- **The previous round's own record.** An earlier recovery round leaves a decision artifact (a
  `decisions.md` under its task dir: evidence-face table, each judgement, and the moot list). Read it
  before writing the new round — the moot list and the evidence path for each judgement are already there,
  so re-deriving them costs a session and risks re-asking what the owner answered.

Expect the reduction to be brutal: low-three-figure clarify records collapse to a handful of live
questions. Never publish a count from the raw backlog before the mootness pass — a wall of questions the
owner has to re-judge is the failure mode this whole reference exists to prevent.

## 3. Other surfaces the backlog misses

A question can be pending without ever having been a form:

| Surface | What to read |
|---|---|
| Repo ledgers | `<repo>/docs/decisions/OPEN-QUESTIONS.md`, `docs/**/decision-record.md`, task `decisions*.md` — entries with `Status: open` or `decided(default taken)` whose `Revisit when` has arrived |
| Task artifacts | `status.md` **body** (a header saying "N awaiting approval" is often stale), sections listing owner-only blocking items |
| Hanging turns | sessions whose last message is the agent's, ending in an unanswered question — read only the tail, they are usually already answered in a sibling thread |
| Ops state | cron incidents not `resolved`, health state files with a failing item, staged-write queues with a non-zero pending count |
| Remote state | `gh pr list --state open` per repo — a green PR with no owner merge authorization is a pending approval |

## 4. Prove each candidate live or moot

Mootness needs an artifact, one per candidate:

- the measured number now meets the bound the choice was about → default succeeded;
- the ledger entry says `resolved` with an owner+date resolution → answered elsewhere;
- the job/file/queue named in the question no longer exists → superseded;
- `gh pr list --state all --search <subject>` shows `MERGED` → the branch left behind is not pending
  work; check `git log --oneline main..<branch>` for genuinely unmerged follow-ups and report only
  those.

Anything left over is live: it goes into one form (≤5, recommended first, each option with one advantage
and one cost) plus a chat digest naming the moot ones and the evidence path for each judgement.

## 5. Digest shape

The reply the owner reads has three parts and nothing else:

1. One conclusion line — how many were genuinely open, how many executed on the spot, how many stay on
   their default.
2. The answered questions quoted back by letter, each with what actually happened (commit, branch, run
   id, file path).
3. A single "judged moot, not re-asked" block, one clause per item with the reason — this is what keeps
   the next re-ask round small.

Land the round in a decision artifact (`decision ledger` shape: option, consequence, reversal) rather
than leaving it in chat, so a later session can tell an answered round from a timed-out one.
