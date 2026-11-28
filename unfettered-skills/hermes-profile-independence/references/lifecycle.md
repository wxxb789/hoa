# Profile lifecycle — create, rename, retire

The ordered procedure, the rename sweep list and the bootstrap steps.

## Lifecycle

Use the CLI, not hand-assembly: `hermes profile rename <old> <new>` migrates session/routing
identity; `hermes profile create <name> --clone [--clone-from <src>]` seeds a home from a live one and
writes a `~/.local/bin/<name>` wrapper. A rename done with `mv` works on disk but leaves every
reference and the routing identity behind — if you must `mv` (multi-reference sweep already scripted),
follow with `hermes profile migrate-identity` and treat the sweep list below as mandatory.

Bootstrap a new home (all five, then restart):

1. `hermes profile create <n> --clone` (or `--clone-all` when state matters).
2. Write the home's own `SOUL.md`: contract head block byte-identical at byte 0, then role-first body
   (`templates/role-soul-minimal.md`). A clone carries the source home's identity — overwrite it.
3. `profile.yaml`: `description`, `allowed_skills`, `paused: false`, `ui_meta.hermes-bots.title`.
4. `HERMES_HOME=~/.hermes/profiles/<n> hermes config set model.provider <p>` then `model.default`,
   `memory.provider`; `terminal.cwd`. Then fix `fallback_providers` — a clone keeps the source chain
   and can end up naming its own default provider first.
5. `profile-skill-materialize.py --apply --profile <n>` → `--check`; add the bot to `~/claw/AGENTS.md`
   (measure bytes: CJK is 3 B/char and the file has a hard 25 000 B gate — compress elsewhere in the
   same edit).

Rename sweep (each is a real failure, not paranoia):

- `contract-drift-check.py` `CORE_PROFILES`, `hermes_health.py` home lists, `setup-dreaming.py`
  schedule dict, prose lists in `profile-soul-deinherit.py`.
- `~/claw/backups/profiles/recovery-policy-*.json`, `~/.hermes/gateway_state.json`, and the bot matrix
  in `~/claw/AGENTS.md`.
- Cron job **ownership tags inside the moved home**: `cron/jobs.json` carries `[bot:<old>]` labels;
  the drift check reports them as "存在别人的 store 里" until renamed.
- Restart the gateway, then delete the old home directory. A live gateway recreates a stale skeleton
  (cache / cron / logs / state.db, a few hundred KB) for a profile it still serves, so removing it
  before the restart is undone.

## Restore drill（验证备份真能跑，而不只是能解开）

脚本化，不要手敲：`~/.hermes/scripts/restore-drill.sh [generation-dir] [home ...]`（默认最新一代、全部
home），配合 `lib/drill_check.py` 对比 `SOUL.md`/`.env` 与 `manifest.json` 的 hash，报告落
`~/.hermes/logs/recovery/drill-<ts>.md`。月度 producer 之后由 `hermes-recovery-drill.sh` 抽验 3 个
（`default` + `nana-nrs` + 按月轮换的一个核心 home），结果搭乘 producer 自己的通知。

三条硬规则（每条都真的踩过）：

- **profile 名每次必须唯一**（脚本用 `drill-<home>-<stamp>`，且 stamp 必须小写——CLI 会把 profile id
  转小写，目录名带大写 `T` 会报 `does not exist`）。残留 phantom 用同名启动会报 "already serves"，
  看起来像备份坏了。
- **恢复出的 `default` home 带着线上 cron**：开跑前必须把 `cron/jobs.json` 改名，否则演练会真的执行
  生产任务。
- **收尾用 `hermes profile delete <name> --yes`，不是 `rm -rf`**：删目录不够——gateway 仍把该 profile
  留在 `served_profiles`，还会重建骨架目录，而且**重启不会清**。只有 CLI 会移除登记。

单条排障（手动）：把备份解到 `~/.hermes/profiles/<name>`（身份来自目录位置，放别处会报
`one gateway per host`）→ 启动一次 one-shot → comp 完整性 → `hermes profile delete`。

## Backup retention (owner decision 2026-11-13)

Two different jobs, two different artifacts — never conflate them:

| Need | Artifact | Retention |
|---|---|---|
| Roll back to a known-good running state | `~/claw/backups/profiles/generation-*` (monthly producer, rotate=2) | newest 2 |
| Reproduce *what the files looked like before a change* | `<file>.bak-<what>` kept **inside that change's own** `cleanup-<YYYYMMDD>/` batch | with the batch (30 days) |
| Ad-hoc cleanup rollback | `~/claw/backups/cleanup-<YYYYMMDD>/` (`daily-hygiene.py` expires it) | 30 days |

Rule: **before a structural change, copy the file you are about to rewrite next to the batch that the
change belongs to** (`cleanup-<date>/<file>.bak-<what>`). One directory per change, so rollback is "the
batch from that day", not a hunt across three naming schemes.

A separate `pre-change-*/` tree was retired on 2026-11-13: the rule had accumulated **zero instances**
(the practice was already "back up the file into the day's batch" — e.g. `nana-nrs.SOUL.md.bak-pre-align`),
and a documented track nothing writes to is worse than no rule, because the next reader assumes it is
live. The original motivation stands: a cleanup pass once deleted both the ad-hoc 11-01 home snapshots
and the pre-refactor tarballs, leaving no way to reproduce the state between two generations.

Deleting anything else: keep only if it is (a) a unique copy of non-reproducible data
(`state.db`, `memories/`, raw evidence, credentials), or (b) the single rollback copy of a live tree.
Reproducible content (`skills/`, `plugins/`, caches, browser profiles, packaged `.tgz` of a source tree
that still exists) goes; a retired home is kept **stripped** — identity, memory and session core only
(~8 MB), not its 95 MB of re-materializable skills and plugins.
