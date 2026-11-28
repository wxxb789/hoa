# Auditing a plan before the first edit

Use when a change is cross-cutting enough that being wrong is expensive — renaming a family, splitting a
loop, porting several skills, anything that touches a published repo *and* a live runtime. The owner's
ask is a design audit before the first edit, not a review of the finished diff.

## Prompt

One file under the task dir, passed as a single string. Required parts:

1. The requirement **verbatim**. Do not paraphrase: catching that the plan misread it is part of the job.
2. Decisions already made, marked as such — not open for re-litigation, but ask "which of these is most
   likely wrong, and under what condition?" Unanimous compliance is the least useful output.
3. Fact boundary: absolute read-only roots, forbidden roots (memories, identity files, other repos), no
   writes, and the state of the working tree ("a first mechanical pass exists; judge the design").
4. Phase gate: judge from the repository plus the requirement first; only then read the plan, and then
   answer exactly one question — did it drop, distort or over-simplify?
5. One verdict per item with `path:line` evidence or an explicit `(Inference)`, plus the condition under
   which the other answer wins. "It depends" is a failed answer.
6. A counter-example: a state where every CI check is green and the result is still wrong.
7. A closing "three things to fix first", in impact order, with no "investigate further" filler.

## Running the lane

- Resolve the model to its provider **before** writing the lane. Ids served by a chat-completions
  provider can be rejected by a responses-endpoint provider with a 400; prove the pair with a one-word
  ping (`-p "reply with exactly: ok"`) and only then send the real prompt.
- Keep `prompt.md` and `answer.md` side by side in the task dir; the disposition table cites them.
- Verify two or three of its citations against the real files before adopting anything. A reviewer reads
  the branch, not the repo's rulebook, and will confidently propose what the owner already banned. A
  cited line range that runs past the file's real length is fabricated — `wc -l` the target first, and
  when one range is wrong, re-read the rest of that report before adopting any of it.
- Honour a model the owner names literally, even if a sibling id is the usual one for that family.
- **Run the lane detached from the session that dispatched it.** A lane spawned as a background child of
  the chat process dies with the gateway, and a lane run in the foreground dies at the call cap mid-tool
  loop — both leave a partial answer that reads like a verdict. Give it its own transient unit and poll
  the file:

  ```bash
  systemd-run --user --collect --unit=<lane>-$(date +%H%M%S) \
    --property=WorkingDirectory=<task dir> /bin/bash -lc \
    'pi --provider <provider> --model <id> -p "$(cat prompt.md)" > answer.md 2>&1; echo "exit=$?" >> answer.md'
  ```

  `wc -c answer.md` and `systemctl --user list-units '<lane>*'` are the whole status surface; the file
  fills only at the end, so an empty file means "no answer yet", never "thin answer".
- **Zero bytes with `exit=0` is a dead lane, not a slow one.** It means the model aborted inside its tool
  loop. Read its session log before re-running: record count, whether the last record is a tool result, and
  whether any assistant text exists at all. Then re-run **narrowed** — fewer read-only roots, a smaller
  ask — because the identical prompt fails the same way. Narrowing the fact boundary is not feeding lane A
  into lane B; the question stays independent, only the surface shrinks.

## What such an audit reliably catches — ask for these

- Mechanical ripple the plan stopped short of: maintenance scripts, vendored-copy path maps,
  sibling-relative paths, duplicated prose counts, the same reference in two READMEs.
- Exemption-table cheating: green CI bought by declaring every edge external/terminal instead of finding
  the real producer.
- Kind semantics: a phase written like a utility, an entry written like a mechanism, a stage the
  controller never routes to (it exists in the graph and is an island in the protocol text).
- Blind CI: test scripts that exist in the tree but no workflow runs, so a broken path merges green.
- Caps and budgets: a file already at its limit with no room for the section being added.
- Two protocols that look like one: a per-task-commit flow beside a single-run-no-commit flow breaks the
  other's invariants when confused. Write the boundary into both files, not into a chat message.

## Second question: does the decomposition need to exist?

A design audit polishes the premise it was handed; it almost never overturns one. When the plan creates
or preserves a family of skills, run a **separate** necessity audit whose only test is per artifact:

- State in one sentence what the whole loop must guarantee. That sentence is the acceptance test; every
  member is judged against it, not against "is this good practice".
- Per member, name the phase that calls it — a pointer you yourself added while integrating it does not
  count, that is circular evidence — and check whether its rules are *already* written in the phase
  file or in a sibling skill. Duplication means fold-and-delete, never keep-both.
- Ask per member: does the loop fail without this, or is it a good practice that merely sounds related?
  State "delete it" as an explicitly legitimate verdict, or the audit conserves everything by default.
- Expect scope to shrink hard. A loop is usually one entry skill plus playbooks; a skill per phase is the
  exception that each member must earn.
- Fold only the net-new rules into the phase file that needs them, then delete the directory. A fold that
  copies whole sections back is a move, not a simplification.

Precedent worth mining for shape (not for literals): a mature harness keeps its multi-stage flows as
`playbooks/*.md` under one entry skill, exposes only cross-cutting 20-line principles as their own
skills, and disables model-invocation on nearly every skill so nothing competes for routing. Copy the
playbook collapse. Do not copy a monolithic mode file with model ids baked in, and do not copy a fleet of
micro-skills that would blow a profile's `allowed_skills` quota.

## Carry it forward

Every item keeps a row — adopt / adopt-with-change / reject — with a one-line reason. Rejections need
their reason recorded where the work lands: a dropped *adopt* is indistinguishable from one nobody read,
and nobody notices until an auditor diffs the two documents. When the second audit overturns the first,
the disposition table is also the record of which earlier verdicts died, and why.
