# Evidence — a run log with a ceiling

Contract: [`docs/goals/archive/2026-11-11-bounded-run-events.md`](../goals/archive/2026-11-11-bounded-run-events.md)
Date: 2026-11-11 · Version: 0.1.33

All commands ran from the repository root on this host, sequentially, never beside a measurement job.
Exit codes are process exit codes. The generated run directories and the judging artifact live under
`.tmp-artifacts/bounded-run-events/` (git-ignored).

## 1. Contract clause audit

| Contract clause | Result | Where |
|---|---|---|
| stream written through a bounded writer the run directory carries; `OMP_RUN_EVENTS_MAX_BYTES`, default 8 MiB, precedence `OMP_*` → default; no absolute host path | met | `scripts/adapters/events-writer.py:41,57-76`; copied per run at `scripts/adapters/omp-run.sh:230`; cap captured for replay at `:457-459` |
| under the cap the file is byte-for-byte the stream | met | `events-writer.py:262-273` (append path before the first eviction); selftest 54 |
| over the cap: head lines ≤ 64 KiB (first line whole), rolling tail, exactly one marker line | met | `events-writer.py:42,149-156,274-294,298-305`; selftest 57-58 |
| total length knowable: sidecar plus `events_bytes`, `events_bytes_total`, `events_truncated`, `events_dropped_bytes`; `status` prints them | met | `events-writer.py:229-260`; `omp-run.sh:388-397,660-667`; selftest 55, 68 |
| session recovery independent of the log head: `session.id` written on first sight, resume path reads it, log head only as fallback | met | `events-writer.py:197-227`; `omp-run.sh:231-232,536-546`; selftest 61-63 |
| `finalize.py` reads through the marker, still writes `state.json`/`exit.code`, counters marked partial | met | `omp-run.sh:322-397`; selftest 64-66 |
| writer never exits non-zero on truncation / file / terminal failure; terminal stream complete | met | `events-writer.py:118-144,184-195,298-321`; selftest 53, 57, 59, 65 |
| crash mid-write leaves a valid file (complete-line appends, atomic compaction) | met | `events-writer.py:125-144,157-182`; unchanged complete lines before the last append |
| unset/non-positive cap warns on the run's `stderr.log`, never unbounded | met | `events-writer.py:57-76`; opt-in run's `stderr.log`, §5 |
| existing oversized run dirs untouched | met | no deletion path anywhere in the diff; `omp-run.sh` only moves a run dir aside on `start` as before |
| out of scope: `stderr.log`, launcher CLI, `gdd.py`, stage templates | untouched | `git diff --stat` lists only the files below |

The audit found three gaps, all fixed before the gates: `status` reported `events_bytes_total: 0` for a
live run before the writer's first sidecar write instead of the retained size as a lower bound
(`omp-run.sh:646-650`), a second writer run in the same run directory appended to the old log and
left `retained_bytes > total_bytes` (now truncated like `tee`, selftest 56), and the end-to-end test
did not prove session recovery when the session event lies beyond the scanned log head (new
selftest 61).

## 2. Bounded writer behaviour

`bash skills/goal-driven-delivery/scripts/tests/run-gdd-selftest.sh` → `selftest: 80/80 ok`, exit 0.
The base commit's suite reports `62/62`; this increment adds 18 checks (53-70).

Direct writer, under the cap (input 424,968 bytes, default cap):

```text
ok 54 - under the cap the file and the terminal stream are byte-identical
ok 55 - under the cap the sidecar reports the full stream and session.id exists
ok 56 - a writer replay in the same run directory replaces the log, like tee
```

Direct writer, over the cap (`OMP_RUN_EVENTS_MAX_BYTES=65536`), printed by selftest 58:

```text
over-cap: retained=130918 total=424968 dropped=294115 marker={"type":"truncated","dropped_bytes":294115,"dropped_lines":2075}
```

The same check asserts: one marker line and only that line; `head_bytes` equal to the sum of the head
block; `total_bytes == head + dropped_bytes + tail`; the first line is the session event; the last
retained line is the last input line; the session id in `session.id`.

Invalid cap (selftest 59-60): `OMP_RUN_EVENTS_MAX_BYTES=0` exits 0, warns
`events-writer: OMP_RUN_EVENTS_MAX_BYTES=0 is not positive; using default 8388608 bytes` on stderr,
keeps the stream byte-identical and records `"max_bytes":8388608` in the sidecar. The non-integer
warning takes the same path (`=nope` was probed and produced the documented `not an integer` line).

## 3. Session recovery beyond the log head

The end-to-end stream starts with a 70,045-byte non-session line, so the session event sits after
byte 65,536 — outside the `head -c 65536` fallback in `omp-run.sh:544`.

```text
ok 61 - the test stream puts the session event beyond the 64 KiB log head
ok 62 - launcher start with the stub agent exits 0
ok 63 - start reports the session id persisted by the writer
```

`start` printed `session id: selftest-session`; only the writer's `session.id` could supply it.

## 4. Judging artifact

Directory: `.tmp-artifacts/bounded-run-events/judging/` (`input.ndjson`, `run/`).

Command: `OMP_RUN_EVENTS_MAX_BYTES=262144 python3 …/events-writer.py run < input.ndjson`, then the
launcher-generated `finalize.py` on `run` with exit code 0 (`finalize` printed
`[finalize] None state=done exit=0 dur=0.0s cost=$0.0 tools=0 session=evidence-session`).

```text
input_bytes 2749019
cap 262144
head_bytes 65405 (limit 65536)
marker_line {"type":"truncated","dropped_bytes":2421660,"dropped_lines":17621}
retained_bytes 327426 <= cap + head_bytes: True
session_in_head evidence-session
sidecar_truncated True sidecar_total 2749019 sidecar_dropped 2421660
state events_bytes = 327426
state events_bytes_total = 2749019
state events_truncated = True
state events_dropped_bytes = 2421660
JUDGING_ARTIFACT_OK
```

Exactly one marker line; the first retained line is `{"type":"session","id":"evidence-session"}`;
`state.json`'s four `events_*` fields equal the sidecar's `retained_bytes`, `total_bytes`,
`truncated` and `dropped_bytes`; `tool_calls_partial`, `turns_partial` and `cost_partial` are true.

## 5. Real opt-in launcher run

`omp-run.sh start --name optin-bounded --prompt … --cwd <repo>` with a stub `OMP_BIN` that cats a
33 MB synthetic stream, and a stub `tmux` on `PATH` (no real tmux server was touched). The cap was
left unset, so the documented default applies; the run's `stderr.log` is exactly:

```text
events-writer: OMP_RUN_EVENTS_MAX_BYTES is unset; using default 8388608 bytes
```

Run directory: `.tmp-artifacts/bounded-run-events/optin/runs/2026-11-11/optin-bounded/`.

| Measure | Bytes |
|---|---|
| input stream (what `tee` retained today) | 33,249,020 |
| retained `events.ndjson` | 8,453,877 |
| dropped from the rolling tail | 24,795,212 (179,171 lines) |
| head region | 65,405 |
| total stream (`events_bytes_total`) | 33,249,020 |
| run directory as run | 8,475,959 |
| control directory: same run dir with `events.ndjson` as `tee` would have written it | 33,270,853 |

Marker line:

```text
{"type":"truncated","dropped_bytes":24795212,"dropped_lines":179171}
```

`status optin-bounded` (excerpt): `state=done exit=0`, `events_bytes=8453877`,
`events_bytes_total=33249020`, `events_truncated=true`,
`events_dropped_bytes=24795212`; these equal the sidecar (`max_bytes=8388608`,
`head_bytes=65405`, `total_lines=240003`).

Terminal completeness: the pane log's first 33,249,020 bytes are byte-identical to the input stream
(`sha256 6e924715a146ef5df6505d6d9f0dc721d6b96656f01c5a2a1597fd2e360c337a` on both). The log then
carries the wrapper's own 95-byte `[finalize] …` summary line — wrapper output, not agent output.
`tail optin-bounded 4` ends in `turn_end`, and `tail … 200000` contains the one `truncated` line.

## 6. Gates

Run on the final tree, sequentially.

| Command | Output | Exit |
|---|---|---|
| `bash skills/goal-driven-delivery/scripts/tests/run-gdd-selftest.sh` | `selftest: 80/80 ok` | 0 |
| `bash skills/goal-driven-delivery/scripts/tests/test-omp-run-stale.sh` | `stale-test: 7/7 ok` | 0 |
| `python scripts/vendor_shared.py --check` | no output | 0 |
| `python scripts/generate_index.py --check` | no output | 0 |
| `python scripts/check_contract_graph.py` | `contract graph: 40 skills, 10 artifacts, ok` | 0 |
| `python scripts/test_check_contract_graph.py` | `Ran 18 tests ... OK` | 0 |
| `python -m unittest scripts.test_skill_config` | `Ran 14 tests ... OK` | 0 |
| `python scripts/test_generate_index.py` | `Ran 29 tests ... OK` | 0 |
| `python -m unittest scripts.test_install_host_skills` | `Ran 21 tests ... OK` | 0 |
| `python -m unittest scripts.test_check_changelog` | `Ran 6 tests ... OK` | 0 |
| `python scripts/check_frontmatter.py` | `check_frontmatter: 40 skills OK` | 0 |
| `python -m unittest scripts.test_check_frontmatter` | `Ran 6 tests ... OK` | 0 |
| `python scripts/version.py check` | no output | 0 |
| `python scripts/version.py check-bump` | `0.1.33` | 0 |
| `python scripts/check_changelog.py --base origin/main` | `check_changelog: VERSION and CHANGELOG.md both changed` | 0 |
| `python scripts/version.py check-merge` | `0.1.33` | 0 |
| `python scripts/test_version.py` | `Ran 42 tests ... OK` | 0 |
| `python scripts/test_release.py` | `Ran 13 tests ... OK` | 0 |
| `python skills/ghc-search/scripts/test_ghc_search.py` | `Ran 14 tests ... OK` | 0 |
| `python skills/hoa-introspect/evals/run.py` | `PASS: zero blind spots; …` | 0 |
| `python skills/hoa-introspect-distill/evals/run_evals.py` | all fixtures `passed: true`; `pii_gate: PASS` | 0 |
| `python skills/define-goal/evals/validate_fixtures.py` | `PASS: define-goal fixtures are structurally valid` | 0 |
| `python evals/run_trigger_evals.py` | `PASS: 25 trigger cases valid … baseline consistent (24/25 passed …)` | 0 |
| `python -m unittest evals.test_judge_trigger_evals` | `Ran 31 tests ... OK` | 0 |
| `python evals/validate_skill_method_cases.py` | `PASS: skill-method cases have valid rubrics …` | 0 |
| `python -m unittest evals.test_validate_skill_method_cases` | `Ran 3 tests ... OK` | 0 |
| `bun test` in `scripts/shared` | `15 pass, 0 fail` | 0 |
| `bun test` in `skills/teams-cdp/scripts` | `29 pass, 0 fail` | 0 |
| `bun test` in `skills/m365-copilot-cdp/scripts` | `41 pass, 0 fail` | 0 |

## 7. Limits

- Truncation starts only when a byte must actually be dropped: a stream whose total is at most
  `max_bytes + head` can stay byte-identical. The tail is bounded by `max_bytes` minus a 128-byte
  marker reserve; the head is additional, so `retained ≤ max_bytes + head_bytes`.
- A crash between compactions leaves the last snapshot plus complete appended lines, at most one
  slack (64 KiB–1 MiB) above the final bound; the final rewrite at EOF is exact. A SIGKILL cannot
  run that rewrite, by construction. A short write followed by an error truncates the file back to
  the last complete line before the sink is disabled.
- `tool_calls`, `turns` and `cost_usd` are partial when the stream was truncated; the `*_partial`
  flags are the only claim about their completeness.
- `answer_chars` is a retained-text length and is not labelled partial.
- The real agent CLI was not exercised: the launcher run used a stub `OMP_BIN`, as the contract
  requires. A real tmux server was not used either; the stub honours the new testing rule.
- A writer replay in the same run directory truncates the log before the first append, matching
  `tee`; sidecar totals then describe exactly that replay.
- The `start` hint advertises `tail -F`, not `tail -f`: compaction replaces the inode, and
  descriptor-following `tail -f` would freeze after the first eviction.
- Existing run directories, including today's oversized ones, are untouched.
