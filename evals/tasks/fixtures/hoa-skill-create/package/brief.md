---
name: shift-brief
description: Stage or publish a shift handoff brief after checking its inputs.
---

# Shift brief

The brief goes to a local staging area unless the request is to publish it.
Staging is reversible. Publishing sends the brief to the named subscriber
group and is allowed only after explicit release approval for that group.
The host provides a resolved shift time, either from the request or the
workspace rota. If neither source has a time, request it once.

The host's dry-run driver reads the first matching rule in the JSON block.
Each rule has an id, a match object (all fields must match), and one action.
An empty match object matches every input. An ask action emits one question
and stops. A stage or publish action does not ask a question.

```json
[
  {"id": "B-10", "match": {"has_time": false}, "action": "ask"},
  {"id": "B-20", "match": {"release_approved": false}, "action": "ask"},
  {"id": "B-30", "match": {"delivery": "publish"}, "action": "publish"},
  {"id": "B-40", "match": {}, "action": "stage"}
]
```
