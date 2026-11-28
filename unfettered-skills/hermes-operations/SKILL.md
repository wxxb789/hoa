---
name: hermes-operations
version: 3.3.0
description: "Use when maintaining a Hermes install: config, data, skills."
author: Zoe
license: MIT
metadata:
  hermes:
    tags: [hermes, operations, config, backup, sessions, skills, maintenance]
---

# Hermes Operations

Install and host hygiene that no subsystem skill owns: config/env edits, backups, session data, the
skill library, retirements, host resource review, and "is this capability real?".

## When to Use

| You hear / see | Load |
|---|---|
| "清理/整理一下这个 Hermes"、"配置对不对" | this skill, then the matching subsystem |
| "现在 Hermes 还好吗"、"everything looks good?"、跑一次健康检查 | this skill → `references/health-signal-triage.md` |
| "这台 VM 跑得怎么样"、"内存/磁盘爆了"、"要不要加内存" | `references/host-resource-review.md` |
| "帮我清理一下磁盘"、"空间不够了"、"把这台机器清一遍" | `references/install-disk-hygiene.md` |
| "桌面 APP 一直重连 SSH"、"登录风暴还有吗"、"内存又高了" | `references/host-resource-review.md` → Step 3b（量化要按天，不看此刻快照）|
| "这几个不停重试的 IP 是谁"、"我哪台机器是这个 IP"、"这是暴力破解还是合法登录" | `references/source-ip-attribution.md` |
| review 已出结论要动手改、"swap 要不要加大"、要回滚方案 | `references/host-remediation.md` |
| "Hermes 不见了 / 好像被卸载了"、所有会话同时断、进程突然消失 | `references/incident-triage.md` |
| "都在跑吗"、"真的在跑吗、还是 hang 住了"、某个后台 lane / 派给别的 profile 的看板卡半天没动静 | `references/live-run-triage.md` |
| "找不到某条命令"、某工具版本落后、想统一 toolchain / 收掉 nvm 与 pipx | `toolchain-provisioning` |
| "为什么没自动重启"、"接口断了"、要不要把后端做成 systemd 服务 | `references/host-remediation.md` |
| "备份我的 setup"、chezmoi / dotfiles / 同步配置 | `references/backups-and-cockpit.md` |
| "把已合并的 <private-repo>/配置改动落到本机"、chezmoi source 落后 repo main、只想 `apply` 一部分 | `references/chezmoi-cockpit-backup.md` → Landing a merged repo change |
| repo auto-sync 一直没提交、`sync-state/*.fail` 存在、vault 工作区越积越多 | `references/backups-and-cockpit.md` → repo auto-sync 诊断 |
| "今天各平台收到多少消息"、DB/WAL 多大、state.db 涨到几百 MB、想压库 | `references/session-data.md` |
| "记忆系统 / dreaming 跑得怎么样了"、"memory 好用吗"、"装完到现在多久" | `references/memory-provider-stack.md` → 审计运行中的安装 |
| "Honcho / 换别的 memory provider 会更好吗"、要不要换记忆 provider | `references/memory-provider-stack.md` → replacing the provider |
| "整理一下 memory"、"MEMORY.md 太满了"、把记忆里的事实搬进 holographic、review MEMORY/USER/AGENTS/SOUL 的分层 | `references/memory-file-migration.md` → surgical maintenance |
| "装这个 GitHub skill"、"为什么 skill 不更新" | `references/skill-library-ops.md` |
| profile 继承 root 身份 / `skills/` 是符号链接 / 白名单要改 | `hermes-profile-independence` |
| 用 ghc-search / 本地检索代理查资料时报错、结果被截断、模型解析不到 | `references/local-search-proxies.md` |
| "Hermes 支持 X 吗"（文档 vs 实现） | `references/capability-verification.md` |
| "最近 Hermes 更新了什么"、"我们是不是最新版" | `references/release-diff-brief.md`（只做简报；真升级 → `hermes-updates`）|
| 某技能被改过 / 想本地化一份官方技能 | `references/skill-library-ops.md` → de-fork |
| "官方删掉的 skill 我们还有残留吗"、清掉废弃的官方内置技能 | `references/skill-library-ops.md` → cleaning local residue |
| 退役旧平台、清理残留 | `references/retiring-platforms.md` |
| "重写/精简/重构指令文件"、"SOUL/AGENTS 太啰嗦"、按层重新分配规则、把活对象（名单/模型/频道/作业）从契约里挪出去 | this skill → `references/instruction-layer-authoring.md` |

**Not for**: upgrades → `hermes-updates`; gateway/profiles/channels → `hermes-gateway`;
cron → `hermes-cron`; providers/models/routing → `hermes-models`; product usage → `hermes-agent`;
toolchain/runtime 安装、PATH 解析与版本漂移 → `toolchain-provisioning`.

## Rules

1. **Inspect before mutating**: `hermes config path`, `hermes profile list`, `hermes gateway status`,
   `hermes cron list --all`, `hermes sessions stats`. Reviews stay read-only until the owner approves a
   restart, deletion, or cutover; never read or print a credential value.
2. **Root and profiles are different homes.** Every setting the owner relies on must exist in root *and*
   each served profile; a successful `config set` proves nothing — parse it and run a live probe.
3. **Back up before any write.** Config and `.env` are protected files: `hermes config set|unset` for
   config, terminal only for `.env`, timestamped copy first — and make it a **pre-change** copy: the
   `backups/config/config.yaml.good.<ts>` a `config set` leaves behind is written *after* the edit and is
   byte-identical to the new file, so it is not a rollback point. Instruction files (`AGENTS.md`, `SOUL.md`)
   are gated: the write can raise an owner prompt, and a **timed-out prompt is not consent** — do not
   retry *that* write or reach the same edit through another path (heredoc, `python`, patch alias).
   The gate reads session state, not just the file: a **complete** read of the file in this session
   (no `offset`/`limit` slices) turns a subsequent anchored `patch` into a silent write, while the same
   patch issued after a partial read prompts and can time out unattended; a whole-file
   `write_file`/overwrite stays prompt-gated regardless. So when a contract edit is blocked, the next
   move is `read_file` on the whole file once, then a minimal `old_string` → `new_string` patch — not a
   retry, and not a shell detour. Re-request the interactive prompt only when the owner asks for it
   ("再问我一遍" is that word), then make the whole change in one patch so they approve once. **Collect every pending change to that file into that one batch — including a patch another lane is holding for the same file** — because the approval is granted per write: two lanes issuing separately cost two of the owner's clicks and leave the file half-updated whenever only one of them is approved. Each
   re-issue is a *fresh* prompt and the owner can miss it repeatedly — a timeout is not an error to route
   around, and never switch to a shell/script detour to "get it done".   Re-validate the patch's own
   arguments before every re-issue: the same block hides a malformed diff too, so an approval can land on
   an `old_string` that carries the added text.
   **Two habits cut those misses to one.** (a) *Issue it as the first action of an owner-present turn* —
   the prompt window is time-boxed (~10 min) from the moment the call is made, so preparation done after
   the owner says "re-send it" spends the window while they look elsewhere; prepare, announce, then call.
   (b) *Pre-validate the exact patch text on a byte-identical scratch copy before spending the card* —
   validation runs behind the same block, so a malformed patch and an unanswered prompt look identical;
   applying the same text to a `cp -p` copy and comparing result bytes/`sha256sum` against a
   deterministic reference (canonical `patch -p1` of the intended diff) proves the bytes first — but only for a config/`.env` target: for the **instruction file itself** the same guard refuses the copy (`… writes an agent-instruction file`), so preview by reading it once and printing `difflib.unified_diff` over the in-memory old/new, which shows the owner the exact diff without a scratch write or a spent card. Then a
   timeout is reportable as "nothing written, file still at hash X" — check it, since the gate returns
   before any apply — and one approval lands exactly the validated bytes. Collapse every pending hunk
   (including another lane's) into ONE multiple-hunk patch call; the prompt is per call, and the V4A
   traps that bounce a multi-hunk patch are in `references/protected-write-batching.md`.
4. **Docs track upstream `main`, not the installed build.** Before recommending a command *for this
   build*: `hermes <cmd> --help`, `grep -n 'CommandDef("<name>"' <repo>/hermes_cli/commands.py`, or
   `ls <repo>/website/docs/**/<feature>.md`. A `CommandDef` in source ≠ a top-level CLI verb.
5. **Freeze auto-update timers before gateway/DB maintenance**; restore their exact prior state only after
   the final acceptance check.
6. **Session store**: integrity check before/after; truncate WAL through SQLite
   (`wal_checkpoint(TRUNCATE)`), never by deleting sidecars. For size reclaim use
   `hermes sessions optimize-storage` inside a stopped-gateway window (`references/session-data.md`) —
   `VACUUM` alone reclaims nothing at `freelist_count = 0`, and `--force` against a live writer can leave
   every agent refusing turns. **A stopped gateway is not a free database**: app-spawned backends still
   hold it, so clear them with `scripts/state-db-holders.py --reap-backends` and retry the run — a client
   reconnect storm replaces them in seconds. A deleted WAL/SHM generation is a
   preservation incident — stop writers, capture stable `/proc/<pid>/fd` generations, fail closed when
   ordering is ambiguous. Exception: an orphan WAL/SHM on a home whose main DB is absent cannot be
   checkpointed at all — removal is legal only behind an explicit owner live-write grant, after
   confirming quiescence (`fuser` clean) and proving in private scratch that the sidecar reconstructs
   to zero facts; back up both files with hashes first (full gate:
   `references/profile-backup-restore.md`). **Attribute the bytes to a table before proposing a retention
   policy**: per-table/index `dbstat` shows where the size actually is (one install's weight sat in
   `state_meta` admission-result blobs that no runtime code prunes, while the in-force
   `sessions.retention_days` had already left zero sessions past its window). A policy aimed at the obvious
   target reclaims nothing, and the attribution is one query — measure, then propose.
7. **Health checks must be status-complete** (read-only SQLite, no shell pipelines, exit code and
   stdout/stderr checked separately). A checker that greps for a string the helper may legitimately print
   produces false greens and false reds alike — assert on the helper's own failure signature.
   **An acquisition that cannot succeed on a live home is a checker defect, not an `unknown` finding.**
   A read-only snapshot that refuses while the WAL is non-empty reports `acquisition/unavailable` for
   every profile whose gateway is running — permanent, severity `unknown`, and it buries the drift that
   matters. Repair the acquisition (SQLite backup API, or read only while the home is stopped and say
   which verdicts stay unknown) instead of re-reporting the same unknown forever.
   **One invariant, several writers.** Profile skill entries, SOUL head blocks and whitelist membership
   are each asserted by more than one checker (`profile-skill-materialize.py --check`,
   `profile-soul-deinherit.py --check`, `profile-layer-reconcile.py`, `post-update-check.py`, the daily
   `hermes_health.py`). Grep
   `~/.hermes/scripts/` for the invariant before declaring drift fixed — patching one generator leaves
   the daily digest re-reporting the same false positive every TTL, and that second finding reads like a
   new fault. Adding the digest's own probe (registry entry → probe → findings adapter → `main()` → a
   standalone flag) → `references/health-check-extension.md`.
8. **Multi-stage owner-authorized remediation**: plan artifact → independent review → execute →
   after-action review against fresh evidence. A plan or a successful write is not execution proof.
9. **Checker expectations drift, not jobs.** If a post-update checker demands an absent or renamed job,
   reconcile checker/docs with owner intent; remove only the stale expectation, keep the health assertion.
   **Locate the cause before choosing.** Diff live `~/.hermes/cron/jobs.json` against
   `cron/backups/jobs.json.bak-*` / `jobs.json.pre-refactor-*`: a consolidation refactor renames jobs and
   leaves the old names only in backups, while an accidental loss leaves no successor capability anywhere.
   Then hand the owner one numbered line (re-add the job / drop the expectation) — trimming the checker
   silently buries a lost capability, re-adding silently fights the refactor.
   Same rule after a roster change: assert invariants that survive it — verify a bot's model only when the
   instruction file actually declares one, match profile names case-insensitively (`Forge` in prose,
   `forge` on disk), and treat `skills.disabled` as asymmetric (a profile may narrow the catalogue, never
   re-enable a root-disabled skill). A checker that hardcodes today's profile names turns every future
   roster edit into a permanent red.
   **Trimming a bot's catalogue.** root `skills.disabled` is the *front door's* catalogue, not a
   fleet-wide floor, so narrowing another bot needs a declared exception channel
   (`~/.hermes/skills-reenable-exceptions.yaml`, `profile: [skill, …]`), checked by
   `contract-drift-check.py`: an undeclared re-enable fails and a declared-but-no-longer-true entry fails
   too, so the file cannot rot silently. Repo-materialized profiles must have their entries recomputed
   after the materializer rewrites their config.
   Two mechanics silently defeat the edit. **(a) `hermes -p <p> skills list` truncates long names** with
   `…`, so a `disabled` list built from that table contains strings no skill matches: the write reports
   success and disables nothing, and because it *replaces* a correct list it can leave the profile with
   **more** skills than before. Read real names from
   `find -L ~/.hermes/profiles/<p>/skills -name SKILL.md` (basename of each parent dir). **(b) The checker
   compares name sets, not files**, so `disabled` must also carry `root_disabled − declared` for skills the
   profile does not even have; otherwise each of those reads as "re-enabled without declaration".
   Formula: `disabled = (root_disabled ∪ profile_skills) − desired`, `declared = desired ∩ root_disabled`.
   Verify with `hermes -p <p> skills list | tail -1` (enabled count == `|desired|`) **and** a drift run, not
   the exit code of `config set`.
   **A profile-local skill is a category, not drift** — loader test and checker fix live in rule 19. In a
   repo-materialized profile, `skill_manage` refuses with `not found in active profile` unless the
   binding's `skills.allowed` lists the name; such a lesson's durable home is repo-side
   (`bots/roles/<role>/`), not the profile.
10. **Bundled skills stay stock.** Official skills under `<repo>/skills/` are tracked by
    `.bundled_manifest` and refreshed by `hermes update`. A locally edited one silently freezes (and
    usually stops being reported once its manifest entry is gone). Local notes live here or in
    `LOCAL_OVERRIDES.md`; de-fork procedure, and removing the local residue of skills upstream has since
    **dropped** (derive the set from `.bundled_manifest` vs the checkout's `skills/` tree — names and
    authors false-match) → `references/skill-library-ops.md`.
11. **A runtime-code fix goes upstream, never into the runtime checkout.** Keep
    `~/.hermes/hermes-agent` byte-clean; do the work in a separate clone, run the clone's own test
    env, and open a PR — procedure and pitfalls → `references/upstream-pr-workflow.md`.
12. **History lives in `references/cases.md`, never in per-incident files.** One `cases.md` per skill,
    one `##` per case, and the durable rule extracted into SKILL.md; a year-prefixed case file is never
    re-read and rots against the live build. Merge procedure (heading demotion, anchor rewriting) →
    `references/skill-library-ops.md`; verify the result with `scripts/verify-skill-links.py`.
13. **A resource review starts at the host and measures before it recommends.** Get CPU idle %,
    `%memused`, swap size, and the kernel's OOM kill list before touching anything about the agent
    install; on a swapless host with `MemoryMax=infinity` the kernel kills by heuristic score, so the
    process named in the log is a victim, not the cause. Rank findings by the number each one moves, and
    check `lsblk` / `fstab` for a second (usually ephemeral) disk before proposing cleanup of the root.
14. **Remediation is a second pass with its own gates.** Every applied change carries its rollback on the
    same line; anything that regrows (package caches, generation backups, journal) ships with a periodic
    job or it is undone within a quarter; and a cgroup property on a running unit is applied with
    `set-property` plus a drop-in — never by restarting `user@<uid>.service`, which tears down every
    process in it, the gateway and the session you are typing in included.
15. **A package that ships kill-policy drop-ins is armed by the install, not by your config.**
    `apt-get install systemd-oomd` alone activates Ubuntu's
    `user@.service.d/10-oomd-user-service-defaults.conf` (`ManagedOOMMemoryPressure=kill` @50%); a higher
    `set-property` limit only moves the threshold. Before and after installing anything that selects OOM
    victims, read `dpkg -L <pkg> | grep '\.d/'`, `systemctl show <unit> -p DropInPaths`, and `oomctl`.
    **The marked cgroup IS the victim pool** — `systemd-cgls` it before choosing a level. UI backends sit
    in `session-*.scope` under the slice but *not* under `user@<uid>.service`, so marking the service
    leaves oomd exactly one candidate: the gateway, and that is what it takes. Mark the level that holds
    the real offenders, then `ManagedOOMPreference=omit` the process you cannot lose (`avoid` only
    re-ranks it, it does not remove it). Bound the growing unit with `MemoryHigh`/`MemoryMax` instead.
    Scoping tree, omissions and the negative-`OOMScoreAdjust` trap → `references/host-remediation.md`.
16. **"The whole thing vanished" is a triage, not a reinstall.** Check process tree → install state →
    data, in that order, before touching the install; `pm status` ok plus a receipt saying `already in
    sync` proves the install was never damaged, and a reinstall that reports it fixed nothing. Rebuild
    what the agent ran from `state.db` (read-only sqlite over `messages.tool_calls`) instead of guessing.
    Procedure, forensic query, and reporting shape → `references/incident-triage.md`.
    Before opening an OOM investigation on `Previous gateway life … exited UNCLEANLY`, compare `uptime` and
    `last -x reboot` with the ledger's `last_heartbeat_at`: a host reboot produces that exact signature with
    `suspected_oom=False`, and the honest answer is "systemd brought it back", not a memory bug.
17. **An app-spawned backend has no supervisor: reap it or give it a unit — never promise a restart.**
    The desktop app spawns one `hermes serve --isolated` per SSH session, so a reconnect storm leaves a
    dozen ~190 MB orphans holding the shared `state.db` (15 procs / 3.4 GB observed); that leak, not the
    OOM killer, is what put the slice under pressure. Reap with all four guards — `--isolated`, session
    log silent, no children, **never the freshest session** — because the last guard is what stops an
    idle window from being killed. Keep the gateway on `Restart=always`, and when the owner asks why it
    did not come back, answer with the ownership table (systemd / app-spawned / machine-level unit)
    instead of a promise.    Reaper script, supervision map, OOM-protection drop-in →
    `references/host-remediation.md`; naming the client behind the storm →
    `references/source-ip-attribution.md`. **A quiet minute is not a fix**: the storm is periodic, so answer
    "is it still there" with the multi-day login series, the last-event timestamp and the reaper's peak
    concurrency (`references/host-resource-review.md` → Step 3b), never with one `ss` snapshot.
    **Attribute the lull before crediting the close**: compare the last successful login's timestamp with
    when the owner actually acted — quiet that began earlier proves nothing, so confirm with a bounded
    watcher (30–40 min) and quote it as a range. **Name the credential before the machine** (auth-class
    table and fingerprint check in `references/source-ip-attribution.md`): a matching
    `Accepted publickey` fingerprint against `authorized_keys` is a client bug; a successful login the
    owner cannot account for is a leaked key, and rotation — not rate limiting — is the fix.

18. **Prove recoverability against required components, not copied files.** Declare approved recovery
    scope before packaging; snapshot live SQLite through its backup API, exclude unsafe symlinks, and
    extract only into private scratch. Missing/corrupt required DBs must fail verification, not merely
    print a warning. Test missing, corrupt and valid synthetic archives through the actual verifier.
    Distinguish provider policy, legacy-cache flags and initialized/absent stores; never fabricate an empty
    DB to pass. Config sync is not a backup of primary facts or pending approvals. Keep independent
    verification verdicts separate from producer success and preserve approved cadence/retention until
    an RPO decision changes them. **Verification is not a restore.** A verifier that unpacks and
    hash-checks proves the archive is complete; only a boot drill proves the home can serve — extract it to
    private scratch and hand the finished tree over with one `mv` into `~/.hermes/profiles/<drill>`
    (extracting in place races the gateway, which opens the new home's `state.db` mid-write, parks the
    profile as `malformed` and keeps serving that cached reason afterwards — `hermes-profile-independence`
    rule 14), `hermes -p <drill> chat … DRILL_OK`, delete it, then remove the
    phantom profile with `hermes profile delete <drill> --yes` — a gateway restart does **not** clear it
    (`served_profiles` is carried across the restart, and the gateway re-creates the skeleton dir).
    Profile identity comes from the **directory position**,
    so a home restored elsewhere cannot be driven with `HERMES_HOME=<dir>`. **Trimming old backup trees is
    an only-copy test, not a size sweep**: delete what a live owner or newer retained generation covers
    (pre-upgrade copies of repo-canonical trees, duplicated one-off snapshots, retired bots, cache
    payloads), keep retired homes' state, un-promoted raw evidence and the last skills tarball, grep the
    scripts for the path first, and record path + size + superseding artifact in the batch's
    `DELETIONS.md`. Batches are retained by a job (30 days), never by memory. Recipe:
    `references/profile-backup-restore.md`.

19. **A skill the profile cannot see is a directory-shape bug — let the loader decide, not the path.**
    `hermes -p <p> skills list` is the verdict: an entry shown as source `local`, status `enabled` is
    loaded correctly, and `skills/<category>/<skill>/SKILL.md` is ordinary category nesting, not a stray
    level (its table truncates long names with `…`, so `find ~/.hermes/profiles/<p>/skills -maxdepth 3
    -name SKILL.md` when matching by name). Only an entry absent from that list is mis-nested — then move
    the inner directory up one level; never delete it. Depth-1 name comparison in a checker
    (`sync-profile-skills.py --check`, the daily `hermes_health.py` skills check) reads a category dir as
    `extra`, and `--apply` would delete a live skill: never apply drift you have not explained, and teach
    the checker the same predicate (a real dir holding `SKILL.md` within two levels is `profile-local`,
    kept and reported) rather than teaching the owner to move a working skill.

20. **Gateway terminal commands are lifecycle-scanned; `/dev/null` breaks the scan.** A command that
    references `/dev/null` (silent redirects, throwaway comparison targets), a process substitution such
    as `<(cat file)`, or any other non-regular file is refused whole with `could not scan this command
    or referenced script`. Write probe output to real
    files under the scratch dir and compare those files instead; keeping the redirect anywhere in the
    command still fails, so re-issue the command without it rather than retrying it.
    **The same scanner refuses on the command's literal text, not only on the files it opens.** A command
    whose words look like bouncing the service — a script name such as `gw-restart-verify.py`, a
    `<x>-sync.sh` path next to `stop`/`install`, or any string matching the restart/stop/uninstall pattern
    — is refused whole with `cannot restart, stop, or uninstall the gateway from inside the gateway
    process`, even when the command only lists files or prints their contents. Rewrite the command instead
    of retrying: pass candidate filenames through a written list file that the script reads, read
    service/config files with `read_file` rather than a shell dump of them, and keep restart-ish
    literals out of the invocation.

21. **A skill the profile disables is still runnable — read it from disk, never flip the catalogue.** When
    the owner asks to run a named skill (often a bundled/CE one such as `ce-commit-push-pr`) and
    `skill_view` answers `disabled`, do not edit `allowed_skills`/`skills.disabled` to enable it for one
    run: that whitelist is derived and reconciled by `profile-layer-reconcile.py`, so the edit is durable
    state churn for a one-off need. Load `~/.hermes/skills/<name>/SKILL.md`, and when the installed copy
    differs, `~/.agents/skills/<name>/SKILL.md`, then follow the procedure with its `references/` and
    bundled `scripts/` — they are self-contained, so `python3 scripts/<helper> …` still runs from the skill
    directory. Honor the skill's own handoffs: a shipping skill that delegates follow-on work (PR
    babysitting, review resolution) is not finished at "PR created". Say in the report which skill you
    executed    and from which path, since the profile index shows it as disabled.

22. **Wait on a background job's completion signal, never on a foreground `sleep`.**
    `terminal(background=true, notify_on_complete=true)` already reports the exit: end the turn and take
    the notification, or block once with `process_manage` wait/poll under a 600s budget. A `sleep N` poll
    occupies the session for its whole duration, blocks any parallel work in that window, and the
    notification arrives anyway; because the foreground default timeout is 180s, any `sleep` beyond that
    fails as a timeout and burns the wait twice. Reserve `sleep` for fixed eventless latency (a CI run
    that has not appeared in `gh run list` yet) and keep it ≤30s per call.
    **A foreground command that outlives the turn budget takes the turn down with it.** The long call does
    not merely time out: the turn ends as `session turn lease lost`, everything the agent was mid-way
    through stops where it stood, and any authorization or question the owner typed into that thread goes
    unanswered until some later session reads it back — hours later, from a clean start. So bound every
    scan that can run long (`-x`, `-maxdepth`, one parent instead of `/`, `timeout`) or dispatch it as in
    the next paragraph, and after any turn that died mid-work re-read the conversation before answering
    (detection and recovery → `open-work-sweep`, "the conversation itself").
    **A long job needs a supervisor, not just a detached session.** `setsid` gives a child its own
    session but not its own cgroup, so work dispatched from a chat turn is still inside that turn's
    cgroup and is SIGTERM'd about a minute after the turn ends or the gateway restarts. The signature is
    easy to misread as "still working": the job's log/event stream stops mid-operation, its own state
    file keeps saying `running` for hours, and no exit code is ever written. Dispatch such work as a
    transient user unit instead — `systemd-run --user --collect --unit=<name> --property=Type=exec
    --property=WorkingDirectory=<dir> <command>` — where the unit is active for exactly as long as the
    command runs and nothing in the agent's process tree can reach it. Wrapping the *launcher* in that
    unit is the trap: the launcher spawns a child and exits, so the unit finishes in seconds and its
    default `KillMode=control-group` SIGTERMs the child it just detached. Prove a new dispatch path with a
    one-line job that reaches a recorded success, never with the real stage — two stages were lost that
    way. Then park a watcher (`while systemctl --user is-active --quiet <unit>; do sleep 60; done` under
    `notify_on_complete=true`) so the end of the unit, not the operator's next question, tells you it is
    over.
    **Kill a job through its launcher, never with `pkill -f <slug>`.** Your own shell's command line
    contains the slug, so the pattern matches the command doing the killing: the tool call dies of SIGTERM
    and the job is never restarted. The OMP launcher carries the unit backend as `--backend systemd`
    (`~/claw/tools/omp-run.sh`, which records `backend: systemd:<unit>` in its `lock`/`state.json` so
    `status`/`kill` read it). Its skill is a symlinked library package, so text edits to that skill land
    through the skills repo, not through `skill_manage` (rule 24a).
    **Dispatching into another profile is the same shape with one extra failure mode.**
    `hermes -p <profile> chat --query-file <file> --oneshot -Q` under a transient unit runs that profile's
    turn, but the turn is served through the gateway: a platform adapter drop aborts it mid-write while the
    unit still exits `0`, the log holds `Gateway disconnected; turn outcome is unknown`, and no artifact
    exists. The unit's exit code is therefore no evidence at all — require the artifact (exists **and**
    written after the dispatch started), and continue from the `session_id:` printed in that log instead of
    re-sending the task. `~/.hermes/scripts/agent-dispatch.py` automates the whole path (dispatch → detect
    the disconnect marker → bounded `--resume` → artifact+mtime check → one `OK`/`FAIL` line), so use it
    rather than hand-rolling `systemd-run` one-liners; in its verdict vocabulary any ambiguity in the
    evidence is a `FAIL`, never `OK`.

23. **A unit whose target disappeared is a runaway, not a service — read its restart counter first.**
    `systemctl status <unit>` / `systemctl show -p NRestarts` shows a counter; five digits means it has
    been failing every `RestartSec` for days and flooding the journal with the same two lines, so the
    noise is never the finding. Diagnose the FIRST line of the loop (an auth/login failure, a dead
    listener) and either restore that precondition or `systemctl disable --now <unit>` — a unit left over
    from a retired service (an old funnel, a dead gateway port) is retired by stopping it, not by
    restarting it. Before deleting, prove nothing depends on it: grep the agent's config and `.env` for the
    port/service name, list other units that reference it, and confirm that port has no listener — the
    unit can outlive both its product and its target. `systemctl mask` refuses while a real unit file lives in `/etc/systemd/system`
    (`Failed to mask unit: File … already exists`): back the file up, `disable --now`, and leave it
    disabled — masking is optional. Confirm the loop ended by counting that unit's journal lines over the
    next 30 s, then cap the journal (`journalctl --vacuum-size=200M` plus `SystemMaxUse=` in
    `/etc/systemd/journald.conf.d/`) but keep enough window to cover the last real incident, because the
    OOM-kill and unclean-exit verdicts exist nowhere else.

24. **A shared repo can be the skill source; the runtime reads it through symlinks, so an uncommitted
    edit there is live but unpublished.** Point `~/.hermes/skills/<category>/<name>` at the repo package
    (`ln -s <repo>/skills/<name>`), then confirm three things before calling it done: `hermes skills list`
    shows the entry `local/enabled`, `skill_view` resolves the body **and** its linked files (a broken
    second level hides `references/` while the body still loads), and the name is in
    `profile.yaml: allowed_skills`. A capability the owner wants permanently is a durable change — add the
    name, then run `profile-layer-reconcile.py`; a one-off run reads from disk instead (rule 21).
    **That one line is still an owner decision, even when the surrounding work is authorized.** It is easy
    to fold "wire the new skills in" into a batch the owner already approved with "continue"; the derived
    `skills.disabled` list then shows up in `hermes skills list` as part of an unrelated change, and the
    honest follow-up becomes an unpicking round ("which of these did I actually agree to?"). Propose the
    one-line diff — names in, names out — and wait for a yes, the same way the install's other derived
    state is never edited silently. Enabling a name therefore means two files in one edit: the declared
    surface (`profile.yaml: allowed_skills`) and the derived visibility (`config.yaml: skills.disabled`),
    with both backed up first and `hermes skills list` as the verdict — the derived list is not rebuilt
    for you, and an entry left in both reads as "enabled" in one place and gone in the other.
    **When a host dir shadows its catalog skill, classify the lineage before merging anything.**
    `install_host_skills.py --root ~/.hermes/skills --check` lists `drifted: <skill> (changed …, extra …)`.
    A real directory whose frontmatter is hub-shaped (`author:`, `license:`, `metadata.hermes.tags`,
    `version: 1.x`) is a stale install of the same name — retire it to a tarball under the workspace
    backups and let the symlink take over. A real directory carrying the catalog's own frontmatter is the
    *live* copy (it has been edited since the port): merge host body into catalog frontmatter, port its
    host-only `references/`/`scripts/`, then re-link and require `--check` to show zero drift for it. A
    name absent from `allowed_skills` is a leftover whatever its date, and deleting it directly loses the
    only copy — back up first, always. Removing
    an absorbed duplicate means absorbing its unique rules into the canonical skill first, then deleting
    its directory **and** its `allowed_skills` entry in the same edit, or the whitelist check reports a
    name that no longer resolves anywhere. Three residues outlive that edit: each home's
    `skills.disabled` still carries the dead name (reconcile rewrites the complement but never shrinks
    it), the exception channel may declare it, and a live session may still be running it. Retirement
    sequence and verification →
    `references/skill-library-ops.md` → retiring a skill across the fleet.
    Two consequences that cost time. **(a) `skill_manage` cannot see a symlinked package** — it answers
    `Skill '<name>' not found in active profile`, while `skill_view` and the loader work fine; edit the
    repo file and land it through that repo's branch/PR, never conclude the skill is missing (a batch of
    edits touching only symlinked skills aborts whole, so keep real-dir skills in a separate call).
    **(b) An uncommitted edit in that worktree is live but unpublished**, invisible until someone runs
    `git status`: wire a probe (`git -C <repo> status --porcelain <subtree>`, oldest mtime >24 h ⇒ WARN;
    `hoa_skill_drift` is the worked shape — registry entry, probe, findings adapter, `main()`, standalone
    flag per `references/health-check-extension.md`), because a skill the agent runs every day can sit
    unmerged for a week without any visible symptom.
    Tar the local dirs into the task dir before replacing them with symlinks, and prove a reconcile run by
    diffing the rewritten `skills` block against `~/.hermes/backups/config/config.yaml.good.*` — it
    rewrites ten homes and prints "repaired" whether or not anything semantic changed.
    **Before declaring the repo copy canonical, look for a second lineage.** A parallel session that
    needed the same loop may have written its own skill under another name; grep the protocol's
    distinctive tokens across the library and compare section headings (a permutation of the same
    headings is one skill in two places). Merge its unique parts into the canonical one, move
    repo-specific rules into the private project profile, and retire the other **only after its
    in-flight users finish** — a skill a live session is executing cannot be deleted mid-run.
    **The live copy and the repo candidate are two writers on one skill — diff before you write a
    lesson into either.** Divergence is invisible until compared, and the second writer is not always a
    session: the background skill curator edits the live copy in place. So a landing pass opens with
    `diff -r <candidate> <live copy>`, and the live-only hunks are adopted verbatim (apply the diff with
    `patch`, or copy the file) instead of re-authoring the same lesson in fresh words — two hand-written
    versions of one rule are exactly the drift a canonical copy exists to prevent. Attribute an
    unexplained live edit before blaming your own read: the curator leaves
    `~/.hermes/.curator_backups/blobs/<sha>` snapshots whose mtimes give the edit time and whose sizes
    identify them (the blob byte-identical to your candidate is its pre-edit snapshot), and a distinctive
    phrase from the new text grepped across both trees says which copy carries the newer wording. Land
    the merged edit through the landing zone the repo designates, never by patching the curated tree.
    **The dotfiles layer must be told, or it undoes the architecture.** A chezmoi/backup source that still
    holds copies of those packages writes them back **over** the symlinks on the next `apply`, and nothing
    complains until a restore. Blanket-ignore the skills tree and make the generator skip symlinked
    packages; accept that class-4 local-only skills then lose that backup (either port them or narrow the
    ignore). Mechanics: `references/chezmoi-cockpit-backup.md` → vendored class, `add`/`apply` traps.
    The shared repo is also where a pointer-only reference corpus lives; re-pinning those gitlinks without
    cloning the trees → `references/ref-corpus-submodules.md`.
    **Syncing that repo to a newer upstream is a fleet migration, not a pull.** Host links point at the
    repo's *live* layout, so one reorganization of `skills/` dangles every link at once. Measure before
    pulling: `git fetch` first (a stale remote-tracking ref understates the gap — a checkout reading
    `behind 10` was 91 behind), then `git rev-list --count <branch>..origin/<branch>` and a layout diff of
    both trees (`git ls-tree -d --name-only <rev>:skills`). The repo's own rename/retire registry
    (`scripts/retired_skills.toml`, or the CHANGELOG) is the only authoritative old→new map; never infer a
    rename by resemblance. Classify every host link (repoint / rename / retire), note that the write side is
    owner-scope `allowed_skills`/`skills.disabled`, and report before pulling when the sync would retire
    skills the fleet runs. A registry that maps several old names onto one successor leaves duplicate host
    links (one package listed twice) — collapse them, and dedupe a whitelist that gained both. The
    directories a reorg leaves behind are not empty: sweep each for **gitignored host-local content**
    (private profiles, local config, generated fixtures) and move it to the new layout before archiving the
    shells — content git never tracked has no other copy. Procedure → `references/skill-library-ops.md` →
    syncing the skill-source repo upstream.

25. **Fleet drift is cleared in a fixed order, and the materializer gates on the instruction layer.**
    Post-check order: instruction files (`AGENTS.md` model declarations, size) → repo bindings →
    `materialize.py --apply` → both verifiers silent. `materialize.py` now calls the host skill
    materializer itself (gated on `--contract-version`, so a schema change fails closed instead of
    writing a half-migrated home) and the reverse-policy writer is retired — do not look for
    `sync-profile-skill-policy.py --apply` in that chain. Reversed,
    the materializer's own `contract-drift-check.py` post-check fails and it **rolls back the host control
    files** while keeping the profiles it already rewrote, so the next `--check` reports a fresh-looking
    `profile.yaml allowed_skills != binding skills.allowed` for every bot. A renamed skill is deleted, not
    renamed, wherever the new name is already listed. **Back up what each `--apply` writes, not what you
    remember editing** — the policy sync rewrites every `profiles/*/config.yaml`, and the instruction file
    is `~/claw/AGENTS.md` (not `~/.hermes/AGENTS.md`, where `SOUL.md` lives); a copy of a wrong path is a
    silent no-backup, so assert each source exists and print its byte size. **A cleanup restores green; it
    does not spend owner decisions**: derived state that lands a new skill `disabled` in every home, roster
    shape, whitelist membership and cron naming are reported as one numbered decision, never swept.
    Class table, rename mechanics, checker regression test, size-ceiling trim, and the duplicate-cron shape → `references/profile-drift-cleanup.md`.

26. **Repair the state the runtime reads, not the warning the CLI printed — and weigh what the repair
    itself writes.** Some `hermes doctor` verdicts are computed inside the CLI process and lag the
    running gateway: `session_reset.mode … is no longer applied` fires while the policy plugin is
    already installed **and** enabled, and the matching `hermes plugins install <name>` answers
    `already exists`. Read the real state first (`hermes plugins list`, `hermes plugins show <name>`),
    then re-run doctor after the next gateway restart before booking the line as open work — installing
    a second copy of something present is churn, not a fix. The repair side has the same discipline:
    `hermes pm install` rebuilds the venv and native deps and is a **GB-scale write** (a fresh venv plus
    chromium/cua-driver took ~7 GB on this host), so capture `df -h /` before and after and report the
    delta as part of the change, the same way every reclaim gets a before → after number.
    **A GB-scale install is an accumulator, not one write.** `<install>/environments/` keeps one
    content-addressed tree per input combination and nothing prunes them; the only live one is the path
    named in that install's `facts.json` (`packages.venv.environment`), so the reclaimable set is
    "siblings the pointer does not name, older than the retention window". Count before concluding there
    is nothing to clean — one top-level `du` shows a single number, not twenty-three.
    Package-manager caches invert the trap: each tool prunes the tree *it* resolves, not the one you
    measured (`uv` honours `UV_CACHE_DIR`; `pnpm`'s store dir is separate from its cache dir). Export the
    variable for the directory you measured and wrap that one command in a `before/after` byte count — the
    tool's own "freed N bytes" describes its choice, and hardlinked entries (live venv wheels) never come
    back. **Measure top-down before any sweep**: `du -s` combined with `--max-depth=1` prints only a
    conflict warning and exits 0, and one `du -s` over a large array of paths reports sizes that disagree
    with a parent-level listing — a candidate list built on them misses the biggest stale directories and
    the sweep has to be redone. Details → `references/install-disk-hygiene.md`.

27. **A script under `~/.hermes/scripts/` is shared state — another session can rewrite it between your
    read and your run.** The write tool says so (`modified by sibling subagent … after this agent's last
    read`); a patch built from a stale copy reverts their change, and a generator you only *ran* may now
    contain logic you never wrote. So: re-read and `stat` any generator you did not author in this session
    before running it, and verify the **effect surfaces** after it runs (each home's config map, each
    harness catalog, the entry list) instead of trusting your own patch. A generator that rebuilds a list
    from a remote source must compute it as `advertised | curated_spec − retired`; a plain "whatever the
    endpoint returned" deletes live entries fleet-wide the moment the response is partial or flapping.
    Concurrency is normal here, not an incident to report as a fault — report the collision, the effect you
    observed, and the guard you added.

28. **Verifying an edit to generated state: compare parsed data, and take the baseline immediately before
    the run.** A tool that re-renders a file rather than patching it changes bytes while leaving the data
    identical (key order, quoting, indent), so a raw hash against the pre-edit tree reports a cosmetic
    reorder as a change; gate on *parsed data equal* plus byte-stability across two consecutive runs. For a
    rollback or round-trip check, capture the baseline from the state the run is about to change — a
    baseline taken before an intervening run makes a working rollback look broken. And when the verification
    is a script, read its inputs first: a harness with a hard-coded file list rots on its own and either
    fails against a healthy change or passes vacuously over a shrunken set, which is a finding about the
    harness, not about the change. The same discipline covers an ad-hoc audit: confirm the population you
    scanned (the JSON key you parsed, every store in the fleet, a bounded glob) before publishing a count,
    because a number built from the wrong input set reads as a finding and costs a rebuttal round.

29. **A repo gate you run inherits the agent shell's interpreter env — sanitize before believing a red.**
    The shell exports `PYTHONPATH`/`PYTHONHOME` pointing at the runtime's own site-packages, so a child
    `uv run` / `pytest` / plain `python3` in any checkout can import that tree and report failures that
    have nothing to do with the code under test (measured: a vault harness suite reporting 4 errors →
    `OK (skipped=1)` under `env -u PYTHONPATH -u PYTHONHOME`, same command, same tree). Re-run sanitized
    before reporting a regression, before attributing red to a delegated agent's change, and before
    booking a repo or a data path as broken — and say which env you ran in when you quote the result.

30. **A sibling chat session can own the repo you are about to write — probe for it before you take a
    branch, even when the owner just told you to.** Every Discord thread runs its own agent session over
    the same `~/repos/*` trees, so "this branch is stale" and "another agent is mid-edit in it" look
    identical from one snapshot. Take two read-only reads a minute apart in the same session: a HEAD that
    moved (`git rev-parse --short HEAD` / `git reflog` / the merge commit's `%ci`) or a
    `git status --porcelain` count that changed is a live writer, not a stale reading. Attribute it before
    deciding anything: `grep -h <session-id> ~/.hermes/logs/agent.log | tail -1` dates that session's last
    tool call, its `session_reset_policy` lines map the id to
    `agent:<profile>:<platform>:thread:<thread_id>`, the Discord channel lookup names the thread, and a
    sibling dir under `~/claw/tasks/<date>/` written minutes ago names its workspace. `sessions.json` holds
    session metadata only — no messages, so do not dig there for content. Then stop and hand the owner the
    collision: which thread/session owns the path, the evidence with timestamps, and 2–3 options. Never be
    the second writer in one worktree — an uncommitted v2 in progress is destroyed by "resolving" the same
    branch from here. A direct order authorizes the action, not a two-writer collision; on a shared branch
    the useful answer is who owns it. Hand the item over in writing the moment you rule it belongs to
    another lane (a post into that lane's thread), and tell the owner it is **queued, not delivered**: the
    gateway drops events authored by its own bot account before admission, so a peer session does not start
    a turn because you posted — the owner's ping, or a board/task item the owning profile pulls, is what
    starts it. Write the handoff against the state you re-read immediately before posting, and correct it
    if the head moved in between.

31. **A retired id leaves the selection surface, not the capability surfaces — and an id you promise a CLI
    must exist in that CLI's own list.** Fleet model lists are two different things: the Hermes
    `providers.<p>.models` map is what the agent may *pick*, while each harness's own model list
    (`~/.pi/agent/models.json`, `~/.omo/agent/models.json`, `~/.omp/agent/models.yml`, opencode/dsh) is
    what that CLI can *run when named explicitly*. An **upstream deprecation** (the endpoint stopped
    serving it) comes out of every file; a **policy retirement** (off the menu, still answers) comes out
    of the Hermes catalogs only — leaving the harness row in place costs nothing and preserves an explicit
    rollback position, so say which of the two you did. The reverse direction bites harder: adding a
    backup id to the Hermes catalog does not make it selectable in `pi`/`omp`, and a lane that validates
    its model id fails the run instead of degrading to a default — add the registry row in the same pass
    and prove it offline (`pi --offline --list-models`) rather than by spending a call. Report the two
    surfaces separately, or a later session reads the surviving row as an unfinished retirement.

32. **The unattended updater is a wrapper around a tree the update replaces — re-resolve its pins, gate
    its restart on live truth, and read its run history, not one exit code.** A wrapper that upgrades and
    then rolls back leaves `hermes --version` frozen for weeks while the timer still reads enabled and
    active, so count consecutive failed runs from the update receipts (`latest.json` can belong to a
    newer run) before reporting the install as current.
    - **Anything resolved at import time dies with the tree.** The updater rebuilds the dependency
      environment under a new content-addressed path and deletes the old one, so a pinned
      interpreter/venv path fails on the wrapper's first step after the update — and the rollback path
      runs against the same replaced tree, turning a revertable failure into a truncated one. Re-resolve
      the interpreter after the updater returns *and* at the start of rollback.
    - **Gate the post-update restart check on live process truth.** Compare the service manager's current
      main pid, and require the platform state file to postdate this run's start; a pid captured before
      launch, or a state file read without a freshness check, reports a platform-verification failure
      while every platform is connected, and that false failure then reads as the cause.
    - **A probe that shells out to the agent CLI must use a creation source the gateway accepts**
      (`cli`, `tui`, `gui`, `acp`, `tool`, `oneshot`). An invented label is rejected as an
      invalid-parameter error that the wrapper surfaces as a model failure — an invented provider outage
      that sends you back to diagnose the model. Use `oneshot` for unattended probes and keep the stored
      session label so an owner-activity gate still resolves; prove the layer with the same probe under a
      bogus source and an accepted one.
    - Back up the wrapper before editing, verify with `py_compile` plus module-level probes (a positive
      case and the failure case), and let the scheduled window apply it — do not restart the gateway by
      hand to make the fix take effect.

33. **Instruction files (SOUL / operating protocol / MEMORY / USER / bot contracts) are written for the
    model reader, not a human.** Optimize precision and brevity: no prose, narrative or step-by-step
    teaching, and do not restate what the reading agent can obtain by calling a tool (environment,
    rosters, ids, history, file contents) — a written copy only rots. One canonical layer per rule;
    per-instance identifiers (roster, models, channels, scheduled jobs) belong in a **generated
    inventory** the contract points at, because an id kept in the contract turns every infrastructure
    change into a contract edit. When you move them out, retarget every checker that asserted those
    facts in the contract, and prove freshness read-only (render the generator in-process, compare to
    disk) rather than regenerating. Placement table, allocation test and the marker-coverage trap →
    `references/instruction-layer-authoring.md`.

34. **A dispatcher-owned worker always carries the board's tools; the only board-blind worker is one you
    launch yourself.** The runtime injects `kanban_*` into any worker it spawns (env `HERMES_KANBAN_TASK`
    set) *before* the profile toolset is consulted, so a profile's `toolsets`/`disabled_toolsets` cannot
    remove them, and patching the runtime to try is off-limits. For an independent verifier that must not
    read the board (or the producer's identity), launch it outside the dispatcher with that env unset and
    own its lifecycle yourself (pid, deadline, retries in your own state file) — the board gets a read-only
    status marker only after the verdict lands. Strip shared memory read/write and session persistence from
    that profile too: injected long-term memory or prior-session context is precisely the leak that makes
    blindness theater. On any board you want deterministic, turn off the LLM back-doors
    (`kanban.auto_decompose` fans triage cards out via a model; `kanban.auto_subscribe_on_create` resumes
    the creating session on terminal events → routing loops) and check for LLM review-gate / retry-triager
    hooks. Board status is a **work-item** lifecycle (`triage|todo|ready|running|scheduled|blocked|review|
    done|archived`) — never map a cyclic domain state machine onto the columns: keep the domain FSM in your
    own file and make one card = one immutable stage-attempt (link a revision to the attempt it supersedes).
    Host sandbox for that worker — bwrap, the Ubuntu AppArmor userns fix, and the minimal mount surface →
    `references/worker-sandboxing.md`.

## Self-healing mechanisms (profile layer)

- `~/.hermes/scripts/skill-rematerialize-trigger.py` runs from `repo-sync.sh` (every 2h) under a lock
  shared with `daily-hygiene.py`, **content-gated** (`--since` + `git diff` over the skill source trees)
  so it repairs upstream drift only and leaves hand edits and writable copies alone; `--dry-run` prints
  the plan without the lock, and silence is the healthy output. A `source drifted from the materialized
  copy` line from `skill-applyback-guard.py check` is therefore a *real* upstream move (a sibling moving
  a source tree looks identical) — a manual trigger run heals it and prints
  `rematerialize: homes=N skills=M`; re-run the guard to confirm `clean`.
- **Pausing one upstream is a file, never a scheduler change.** `state/skill-upstream-pause.json`
  (`{"paused":[{"path":"~/repos/<repo>","label":"<name>","since":"YYYY-MM-DD"}]}`) is read by
  `skill-applyback-guard.py` and `hermes_health.py`. An entry whose recorded `source` **resolves**
  under a paused path (host-library sources are symlinks into the upstream checkout, so resolution is
  what matches) is skipped in the source-drift step: the guard prints a `paused upstream` note instead
  of `source drifted from the materialized copy`. Both healing paths — the 2h `repo-sync.sh` trigger
  and `daily-hygiene.py` — plus the daily `skill_applyback` / `hoa_skill_drift` probes decide from
  those FAIL lines, so one entry stops the propagation *and* its alarm for that repo while every other
  upstream keeps syncing. Hand edits, writable copies and two-tier collisions there still fail.
  Deleting the entry resumes: the next run re-derives the drift from the upstream's recorded head and
  heals it. Use it when a repo mid-refactor must not push half-written skills into the homes; never to
  silence a red that is already true (the file is inert when absent or malformed).
- `hermes_health.py` records `checks_run/checks_expected/duration_s/timed_out` per run and, on its wall
  deadline, writes a `run-timed-out` event listing the checks it never reached before exiting non-zero —
  so a truncated sweep is never read as a clean one. `daily-hygiene.py` carries two **report-only**
  readings: `ghost_profile_homes()` (empty `profiles/drill-*` leftovers after a drill — delete the empty
  dirs, never a registered home) and `state_meta_reading()` (admission tombstones; see rule 6, deletion
  waits for framework GC). Ordinary drift surfaced *while a delegated run is mid-edit* can be a transient
  crash in the probe rather than a real fault: re-run the probe once before reporting it.

## Drift control (why this skill does not rot)

- **Two generated sheets, one rule: change the generator's input, re-run the generator, never patch the
  sheet.** `references/local-install.md` (`snapshot-install-facts.py`) carries providers/models/profiles/cron;
  the workspace's generated live-object inventory (`gen-live-inventory.py`) carries the roster, channels and the
  job list the contract points at. After any config, profile or cron change — a renamed job, a new schedule,
  a new channel — re-run both and read the rendered row back against the live store (`jobs.json`); a stale
  sheet is worse than none. Hand-editing is the worse of the two failure modes: either the daily digest
  reports `install-state sheet is STALE` / `config snapshot stale` (cleared by running the generators —
  `snapshot-install-facts.py`, then `config-snapshot.py` — not by debugging), or the edit happens to match
  live state today and the next render silently reverts it while the row you "fixed" reappears.
- `~/.hermes/scripts/hermes-ops-claims-check.py` asserts this skill family's policies against the live
  install (facts sheet current, bundled skills stock, route resolves, per-profile providers, vision
  pinned, dashboard routing, one-way channel, snapshot current). Cron `hermes ops claims check` runs it
  every 6h and stays silent unless a finding **changed**. If it fires, fix the install or the assertion —
  never the detector.
- Rule of thumb: **policy is hand-written, state is generated, drift is asserted.** Narrative session
  logs belong in references only when a procedure can't be stated as a rule.
- **Skills and harness carry the same software-engineering standard as production code** (owner): one
  responsibility per file, plus a bounded size — when an entry file (SKILL.md, a checker module) stops
  fitting in a single read, move the depth into `references/<topic>.md` and leave the entry as rules plus
  pointers. A thousand-line SKILL.md is the failure shape, not thoroughness: split it. And never restate a
  rule whose home is another layer — extend the existing file instead of adding a second copy.
- **Every check binds an owner decision — consolidation is deletion-led.** Before writing or keeping any
  checker, answer "this finding changes what action, by whom?"; no answer means delete the check, not
  soften it. Never add validation out of caution: git is the byte layer, declaration files are the
  intent layer, checks only align the two. When consolidating checkers, each absorbed one must
  individually survive that question — if every one survives, the audit was theater — and the
  consolidated package ships **net-negative in lines**, because a consolidation that grows the codebase
  is new drift, not less. Domain data pipelines (capture→analyze→report systems) are tenants, not
  gates: they move to their own package, never inside a harness directory.
- After any restructure (split, merge, rename, de-fork) run
  `python3 scripts/verify-skill-links.py <skill-dir>`: it fails on a pointer to a missing support file,
  a `cases.md` anchor that no longer resolves, an over-budget description, or a leftover dated file.
  Eyeballing the index does not catch anchors, because the heading text and the link drift apart.

## Owner cockpit

Deterministic and script-first: gateway status, cron list, DB/WAL sizes, integrity, recent gateway
warnings. For recurring pings where the script already emits final text, use cron `no_agent: true`
(silent when healthy).

`N alert line(s)` counts `- ` lines in a log window — it is not a score. Stale `has no resolvable home`
warnings for deleted profiles and cron `recovered since` lines dominate it while the install is fine, so
categorize the lines before reporting or every quiet day reads as a red.

A health review is verdict-first and read-only: what is provably healthy (with the command that proved
it), what needs an owner decision (numbered, one line each, so it can be answered by number), what is
cosmetic. Queue-changing repairs stay an offer. **But a record-only repair of the install's own generated
state — a stale skill binding rebind, a regenerated facts sheet, a re-derived whitelist — changes no
runtime behavior and is restored by putting back the file you just copied, so fix it inline, keep the
backup, and report it as "刚修掉" with the check output.** The offer line is for edits that change what
runs: prompt text, toolsets, schedule, model, deliver target, retention, deletions.

## Pitfalls

- **An inherited `PYTHONPATH` makes `uv run --project` load a FOREIGN venv's packages.** A session /
  tool context here carries `PYTHONPATH=<other Hermes install>/venv/lib/python3.14/site-packages`;
  the project env (`.harness/.venv`, python 3.12) then resolves that copy of `rpds`/`jsonschema` and
  dies with `ModuleNotFoundError: No module named 'rpds.rpds'` — a false red, not a code defect.
  Cron passes because it has no `PYTHONPATH`. Run project-env commands as
  `env -u PYTHONPATH -u PYTHONHOME -u VIRTUAL_ENV uv run --project <p> python …`; when a scheduled
  wrapper's own gate can be invoked from a session, sanitize inside the wrapper too (done for
  `thoughtscape-sync.sh`, 2026-11-14).
- **A scratch TMPDIR under `~/.hermes/cache/...` breaks AF_UNIX-socket tests.** The session scratch
  path is long, and Unix socket paths cap at ~108 bytes, so `tmux`/socket-based tests fail as if the
  code were broken. Re-run with a short `TMPDIR=/tmp/x` before believing a failure.
- **A Discord adapter disconnect kills in-flight `hermes -p X chat` children.** Symptom:
  `Gateway disconnected; turn outcome is unknown` plus rc≠0 while the unit ran fine. It is the
  adapter (`ack_stale`, `socket_closed`), not the task: the gateway itself stays up. Dispatch long
  profile jobs through `agent-dispatch.py start`, which resumes the printed session id instead of
  resending the work; a run may reach attempt 3 and still finish.
- **Never archive or delete a host script on a literal-name scan alone.** `repo-sync.sh` invokes its
  workers by *computed* name (`script="$SCRIPTS_DIR/${repo}-sync.sh"`), so `thoughtscape-sync.sh` and
  `nana-research-sync.sh` scan as "referenced nowhere" while every 2-hourly sync needs them. Before
  moving a script: (1) build the corpus from `scripts/**`, every cron store's full job JSON, systemd user
  units, `~/claw/tools` + `~/claw/AGENTS.md` + `references/`, and the repos' `.harness`/`.agents` — the
  docs corpus is easy to forget and it is where the sync chain is described; (2) grep for computed-name
  and glob invocations (`$SCRIPTS_DIR/${x}-…`, `*-watchdog.sh`); (3) prove the result by running the
  caller (`repo-sync.sh`) and checking it does not report a missing script. Once a script *is* retired,
  sweep its callers in three layers — root **and** every profile `quick_commands`, cron job payloads, and
  prose/reference docs — and repoint each to the live successor; a dead `quick_commands` entry only fails
  when someone types the command, so it survives months unnoticed (delete the key only when no successor
  exists). Record the retirement as a **new** dated entry in a dated ledger (`LOCAL_OVERRIDES.md`): the
  ledger is append-only, so never rewrite the historical section that names the old path — the correction
  goes where the next reader looks, not in place of what was true then.
- **A `.bak-<ts>` file can be a live run's rollback point.** A delegated run that edits managed scripts
  writes `*.bak-<ts>` seconds before it finishes; sweeping `*.bak*` into a backup dir mid-run removes the
  rollback that run relies on. Check each mtime against in-flight jobs (`systemctl --user is-active`)
  before sweeping, and restore immediately if you already did.
- **A report script reachable only through another tool is never exercised.** A cockpit / health /
  diagnostic script whose output is summarized by a larger checker can raise for months (a missing import,
  a renamed helper) while the caller prints a generic "crash" line, and nobody reads a crash as a failure.
  Run the script itself — its default path *and* its `--full`/deep flag — and read its exit code after any
  edit; the caller's summary is not evidence that the script works.

## Proof

```bash
hermes doctor && hermes config check
hermes gateway status --deep
hermes cron list --all
python3 ~/.hermes/scripts/post-update-check.py        # "all good"
python3 ~/.hermes/scripts/profile-layer-reconcile.py --dry-run
python3 ~/.hermes/scripts/snapshot-install-facts.py --check
cd ~/.hermes/hermes-agent && git status --short       # empty
```

Report: what changed, the artifact path, the verification output, what still hurts.

## References

- `references/memory-write-queue.md` — memory write queue: why background-review proposals are staged, the staleness rule, `memory-queue.py` approve/reject + receipts.
- `references/local-install.md` — **generated** install state (providers, models, profiles, cron,
  channels). Never hand-edit; re-run `snapshot-install-facts.py`. Facts only.
- `references/config-env-editing.md` — `.env`/`config.yaml` guards, safe edit pattern, the
  post-write-backup trap, turn-budget keys (`agent.max_turns` and the sibling limits that do not follow
  it, with liveness per key), secrets outside `.env`, redacted-output trap.
- `references/backups-and-cockpit.md` + `references/chezmoi-cockpit-backup.md` — config-plane extraction,
  `dot_`/`private_` pitfalls, the autosync pipeline and its gates.
- `references/profile-backup-restore.md` — restorable per-profile backups: the scheduled generation
  subsystem (`hermes_recovery.py` produce/verify/weekly + frozen policy + `policy-stale` tripwire),
  include/exclude table, SQLite backup API, the symlink extraction failure, the `--verify` drill, the
  orphan-WAL removal gate, and rotation.
- `references/session-data.md` — WAL truncation, `sessions.auto_prune`, per-platform message counts.
- `references/install-disk-hygiene.md` — where a Hermes install spends its GBs: content-addressed
  `environments/` snapshots and the `facts.json` live pointer, per-tool cache locations and the
  measure-then-prune recipe, what is safe to delete and what only looks reclaimable — plus the top-down
  measurement rule, sweeping host scratch/task trees, the before → after report shape, and the contract
  for an age-based sweep as a standing job (liveness beats age, newest-mtime-not-entry-mtime, cadence ≥
  retention window).
- `references/skill-library-ops.md` — bundled/hub/local updates, installs, de-forking a bundled skill,
  cleaning local residue of upstream-dropped bundled skills, case-note merging, and the
  policy/state/assertion split that keeps this family from rotting.
- `references/ref-corpus-submodules.md` — the pointer-only reference corpus in the shared skills repo:
  `ls-remote` + `update-index --cacheinfo` re-pinning, adding a submodule without cloning it, and the
  `.gitmodules` quoting trap — plus diagnosing a materialised worktree that stranded and deadlocked a
  publish loop.
- `references/pr-merge-ref-and-version-race.md` — why a pull-request check evaluates `refs/pull/N/merge`
  (green head, red CI), what `no checks reported` really means, rebuilding instead of resolving generated
  conflicts, and which side should own the version bump.
- `references/upstream-pr-workflow.md` — fixing Hermes itself: separate clone, clone-local test env,
  duplicate check, commit/PR/fork commands, and what to verify before claiming success.
- `references/capability-verification.md` + `references/acp-vs-kanban.md` — prove a claim against source
  and a live probe.
- `references/worker-sandboxing.md` — isolating an agent worker that must be blind to the board and the
  producer (run it off-dispatcher, what to strip), and the bwrap + AppArmor recipe on an Ubuntu host: the
  `uid map: Permission denied` userns symptom, the scoped `/etc/apparmor.d/bwrap` profile, the minimal
  mount surface, and the residual risk.
- `references/release-diff-brief.md` — answering "are we up to date / what changed": which endpoint and
  which git ranges give the window, reading files that only exist in the newer tag, and the reporting
  shape for the owner.
- `references/profile-drift-cleanup.md` — clearing a red `contract-drift-check.py` / reconcile across the
  fleet: classify → fix order → verify, skill renames, the checker's own false positives, the AGENTS.md
  byte ceiling, and duplicate cron jobs.
- `references/retiring-platforms.md` — purge or rename a retired platform with a verified rollback set.
- `references/instruction-layer-authoring.md` — writing instruction files for the model reader: the
  layer-placement table and allocation test, extracting live identifiers into a generated inventory
  (plus retargeting the checker that asserted them and proving freshness read-only), the
  coverage-marker trap when proving a compression lossless, and the recipe for de-bloating a monolithic
  entry file into a router plus `references/` (name reservation, byte-exact move proof, the
  concurrent-writer and reverted-by-materialize traps).
- `references/config-review-checklist.md`, `references/feature-adoption-audit.md`,
  `references/config-efficiency-review.md` — review passes.
- `references/host-resource-review.md` — host/VM layer: headroom vs averages, OOM history, RSS
  attribution across gateway vs UI sessions, duplicated disk weight, listener exposure, resource budget.
- `references/source-ip-attribution.md` — naming an unknown source IP: ipinfo → RDAP → Microsoft
  ServiceTags (live-URL discovery, longest-prefix match), pool-vs-host block shape, and the
  time-correlation test that finds the actual machine (a probe match is not one).
- `references/incident-triage.md` — "everything disappeared" triage: process tree → install state → data,
  the `state.db` query that reconstructs what the agent ran, and how to report an incident you caused.
- `references/live-run-triage.md` — deciding running vs waiting vs hung for a detached lane (`omp -p`,
  `pi -p`, `hermes … -Q`, `systemd-run` units): the two-sample probe set (mtime vs ring buffer, serving
  socket, sub-agent `lastIntent`/`contextTokens`) and the output-file traps (block-buffered one-shots,
  `-Q` writes at completion, mid-run `pid` absent from the state file), plus reading a board-dispatched
  worker's progress out of the assignee home's `state.db` when its card log stays empty.
- `references/health-signal-triage.md` — reading the live health signals of a working install: the ordered
  read-only sweep, finding → cause → action table, and which warnings are cosmetic noise.
- `references/health-check-extension.md` — writing one: registry entry, probe, findings adapter, daily
  wiring, standalone flag, and the threshold/dedupe rules that keep a new check from becoming noise.
- `references/host-remediation.md` — the write side of that review: swap sizing and the evidence that
  settles it, journald / filesystem / cgroup caps, systemd-oomd, the supervision map for app-spawned
  backends and their reaper, OOM-protection drop-ins, python-venv
  slimming, packaging a cache-launched service, and the periodic job that stops a reclaim regressing.
- `references/memory-provider-stack.md`, `references/memory-file-migration.md` — holographic memory and
  MEMORY.md/USER.md migration, provider selection (a switch replaces, never adds to, the fact store);
  `memory-provider-stack.md` also carries the read-only audit of a **running**
  dream install (job liveness vs. actual writes, snapshot-noise alerts, stale skill bindings), plus the
  opt-in `experience` journal for measuring whether recall was actually used — its per-turn token cost,
  TTL, why to sample by hand before paying for it, and the bounded-experiment recipe (boolean flags,
  per-agent rollout, report script + one-shot cron reading) once the owner says yes.
- `references/local-search-proxies.md` — ghc-proxy preflight, the model-id pin and `--max-tokens`
  failures that read as "the search tool is broken", the sequential-sweep-to-files shape, and where a
  local note goes when the vendored skill itself is not patchable.
- `references/cases.md` — historical cases: config review + OpenClaw migration cleanup, skill update
  lifecycle, third-party GitHub skill install.
- `scripts/classify-skills.py` (builtin/hub/local), `scripts/session-source-stats.py` (message stats),
  `scripts/state-db-holders.py` (who holds `state.db`, plus `--reap-backends` for the maintenance window),
  `scripts/verify-skill-links.py` (frontmatter/description/pointer/anchor audit after a restructure).
