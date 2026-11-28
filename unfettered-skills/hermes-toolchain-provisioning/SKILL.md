---
name: hermes-toolchain-provisioning
version: 1.0.0
description: "Use when CLIs are missing, shadowed, or need one manager."
author: Zoe
license: MIT
metadata:
  hermes:
    tags: [toolchain, path, mise, version-manager, environments, provisioning]
---

# Toolchain Provisioning

Host-level question: which install channel provides each CLI, what wins on PATH, and how to move
everything onto one version manager without turning working commands into `not found`.

## When to Use

| You hear / see | Do |
|---|---|
| "找不到 X"、`command not found`、某个 agent 里能用、另一个不能 | Step 3 diagnostics + `references/provisioning-channels.md` |
| "mise 里没有 X"、版本落后、想把 toolchain 统一管理 | full audit (Steps 1-6) |
| 要把 nvm / pipx / corepack / 手工二进制收掉 | Steps 5-6 — 顺序就是风险 |
| repo 要求的 runtime 版本与全局默认不同 | per-repo `mise.toml` 钉版本 |

**Not for**: Hermes config/data/skills → `hermes-operations`; providers/models/routing → `hermes-models`.

## Rules

1. **`not found` 先按 PATH 上下文诊断，不要当安装缺失。** 这台机器上同名命令有五个可能的提供者：版本管理器 shims、产品私有运行时、npm global prefix、`~/.local/bin`（手工二进制 + pipx/uv 符号链接）、apt。结论前先在三种上下文里各探一次 —— 当前 session、`env -i HOME=$HOME bash -lc 'command -v X'`、`env -i HOME=$HOME bash -c 'command -v X'` —— 它们读不同的激活源，经常互相打脸。
2. **受管 agent 继承的是 unit 里写死的 PATH，不是你的 rc 文件。** `systemctl --user cat <unit> | grep Environment=` 才是「每个 session / cron / 子进程能看到什么」的权威答案。不在那串里的 CLI 装得再好也不可见，修法是 drop-in + `daemon-reload` + 重启，不是重装。
3. **激活点有三个家。** 交互 rc（`.bashrc`/`.zshrc`）、登录/非交互（`.profile`）、服务 unit 的环境。只接在 rc 里的版本管理器对 cron、systemd、被 spawn 的子进程完全隐形 —— 这是「我终端里好好的」最常见的成因。非交互上下文里，一个 shims **目录**挂在 PATH 上比 shell hook 更可靠。
4. **先安装，再暴露。** shims 目录是一组指向「必须已经存在」的版本的硬链接：在它提供的每个名字都装好之前把目录挂上 PATH，会把本来能用的命令变成 `not found`。顺序是 (a) 把其他通道当前提供的名字逐个装进管理器 → (b) 三种上下文各 `command -v` 一遍 → (c) 才把 shims 加到 PATH。顺序颠倒，故障现象会伪装成「版本管理器坏了」。
5. **shims 位置：产品私有运行时之后、`/usr/bin` 之前。** 让 agent 自己的 `~/.hermes/{node,tools/*}/bin` 保持在前面，supervisor 的内部运行时才不会在它脚下移动。
6. **PATH 更靠前的 stub 会遮蔽一个健康的受管安装。** 残留的 toolchain 代理（rustup、旧 corepack wrapper、指向已删版本的 corepack 符号链接）排在前面时，`--version` 报错或报旧版本，而受管副本完好。同时解析两边：胜出的路径（`readlink -f`、`stat -c %y`）与管理器的版本，比对后文件年龄会暴露没人记得装过的手工副本。
7. **漂移才是迁移的理由，所以要量化。** 每个手工副本都把「已装 vs 可用」并排列出（`mise ls-remote <name> | tail -1`）。几个月前手装的工具普遍落后好几个 minor；是这张表、不是「整齐」这个说法，支撑迁移的必要性。
8. **不要用 registry 表判断可装性。** `mise registry` 会漏掉仍然可解析的常用名（`node`、`gh`、`jq` 是 core/aqua 的短名）。用 `mise ls-remote <name> | tail -1` 探；没有短名的用显式后端 —— `aqua:owner/repo`、`npm:<pkg>`、`pypi:<pkg>`、`pipx:<pkg>`、`github:owner/repo`。
9. **移动一个 CLI 之前先 grep 它的消费者。** 旧前缀的绝对路径藏在 agent 配置（`config.yaml`）、辅助脚本（`~/.hermes/scripts/*.py` 里自建候选目录列表）、unit 文件、repo 脚本里：`grep -rn "<old bin dir>" ~/.hermes ~/claw ~/.config/systemd`。最后一个硬编码消费者在同一次改动里更新完，才算迁移完成；否则它恰好对最需要它的代码消失。
10. **产品自己拥有的东西不要纳管。** agent 的私有运行时树、服务会链接的发行版基础包（`git`、`curl`、`build-essential`，以及任何已在 unit PATH 里出现的路径）、生成的启动器脚本，全部划出范围，并写进明确的「不迁移」清单 —— 悄悄把它们算进去，会让整份审计读起来像一份搞坏安装的计划。
11. **一个语言生态只留一个管理器。** pipx + `uv tool` + `pip --user` 并存是同一个问题的三种形态；收敛到一个（uv tool：单一缓存、快一个数量级），并在同一阶段删掉其余，逐个按名重装，确保没有 CLI 静默消失。
12. **每个阶段自带回滚与一条验收探针。** 先备份 unit 文件 / rc 文件，写明恢复用的确切命令，并给出证明该阶段成立的探针（`env -i HOME=$HOME bash -c 'command -v a b c'`）。阶段以编号决策行呈现 —— 迁移改的是整机状态，深度由 owner 定。

13. **shim 靠 `HOME` 找状态库：给子进程换过 `HOME` 的环境必须把状态目录按绝对路径带进去。** mise 的信任库与 state 在 `$HOME/.local/state/mise` 下，任何给子进程设 task-local `HOME`/`XDG_*` 的隔离（测试 runner、sandbox、CI 夹具）都会让 shim 直接拒绝执行：`mise ERROR Config files in ... are not trusted.`，看起来像「工具没装好」。探针：`env -i HOME=/tmp/fake PATH=<shims>:/usr/bin bun --version`（not trusted）对比 `env -i HOME=$HOME ...`（正常版本号）。修法是把 `MISE_STATE_DIR`（有则加 `MISE_DATA_DIR`）作为绝对路径传进子进程环境——不是放宽 `HOME` 隔离，也不是放宽那个 gate。同一个 gate 有两个旋钮，报错点名的那个才管用：状态库找不到 → `MISE_STATE_DIR`；**config 文件不受信** → `MISE_TRUSTED_CONFIG_PATHS=<config 绝对路径>`。症状长在别处是这个 gate 的常态：repo 自带的 selftest 里有几步会换掉 `XDG_*`，其余与 mise 无关的检查跟着一起红（91 条错 3 条），看起来像被测代码坏了 —— 先怀疑被隔离的 `HOME`/`XDG_*`，再怀疑代码。修法写进 dispatch prompt 或测试调用方，不进 repo：把宿主的环境事实编译进被测仓，等于让每个下游平台继承一个只有本机成立的假设。

14. **shim 目录是生成物，丢了重建、不要重装；临时 unit 拿不到 rc 的 PATH。** `~/.local/share/mise/shims` 被删或被清空时，工具本身没坏：`mise reshim` 按已装版本一次性重建全部 shim（探针：`ls ~/.local/share/mise/shims | wc -l` 从 0 回到正常条数，再逐名 `command -v` 一遍），不要逐个重装、也不要怀疑 installs/。反向的坑：`systemd-run --user` 起的临时 unit 只有 manager 的最小环境，既没有 rc 也没有 shims，在里面跑 shim 提供的 CLI 一律 `command not found` —— 必须显式 `--setenv=HOME=$HOME --setenv=PATH=$HOME/.local/share/mise/shims:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin`。"`command not found` 在 unit 里 = 环境没带进去，不是没装。" 另：破坏性命令（`rm -rf` 等）先把路径变量 `echo` 展开确认目标 —— shim/installs/toolchain 目录不在任何删除范围内。

## Procedure

1. **盘点装了什么、怎么装的。** 一批只读：`mise ls --global`、`mise --version`、`cat ~/.config/mise/config.toml`、`echo $PATH | tr ':' '\n'`、逐目录 `ls -1`、`npm ls -g --depth=0`、`uv tool list`、`pipx list`。
2. **逐个二进制查来源。** 循环打印 `command -v`、`readlink -f`、`stat -c %y` 加一行 shebang 嗅探 —— 符号链接指向包管理器，裸 ELF 是手工投放，`#!/bin/sh` 是生成物（不算依赖）。
3. **诊断可见性**（规则 1-3）：三上下文探针 + unit `Environment=`。
4. **分类**：已纳管 / 重复运行时（数份数，5 份 node 就是结论）/ 用户 bin 里的手工二进制 / 包管理器全局包 / python CLI / 不迁移。同时交叉核对 repo 需求（`.nvmrc`、`package.json engines`、lockfile 名、`global.json`、逐仓 `mise.toml`）：全局默认要满足最严的 repo，其余逐仓钉。
5. **按规则 4 排阶段**：可见性 → 运行时 → 手工二进制 → 包管理器全局包 → python CLI。先 `df -h /`：包管理器树动辄数 GB，重装期两份副本要空间。
6. **审计落 `~/claw/tasks/<YYYY-MM-DD>/<task>/audit.md`**，聊天只给：一行根因、并行通道计数、漂移表要点、不迁移清单、带回滚的分阶段计划、每个真分叉一条编号决策（深度 / 全局默认版本 / 有争议根目录的归属）。

通道清单、后端映射、值得 grep 的耦合点：`references/provisioning-channels.md`。

## Script runners the host must always have (owner 2026-11-14)

Harness/growth scripts and skill scripts are written in one of three cross-platform runners. That is the
*reason* they exist, not a style preference: the operator moves between Windows, macOS and Linux, and skills
are ported into the public catalog, so anything `sh`/PowerShell-only breaks for the next platform.

| 用途 | Runner | 探针 |
|---|---|---|
| Python 脚本 | `uv` / `uvx`（依赖走 PEP 723 内联，不装进系统 python） | `uv --version` |
| F# script | `dotnet fsi`（`.fsx`） | `dotnet fsi --version` |
| TypeScript | `bun` / `bunx`（不写 JavaScript；例外：agent 自己的 Code Mode 草稿） | `bun --version` |
| 大 CLI（需求明确 + 高重复） | Go，单一静态二进制 | `go version` |

All four come through mise (`mise use -g <name>@latest`). Two traps learned the hard way:

- **`dotnet fsi` is not a separate binary** — it ships inside the SDK, so `command -v fsi` fails while
  `dotnet fsi --version` works. Probe the invocation, not the name.
- **A managed entry whose install was pruned warns on every command.** `mise WARN missing: X@latest` appears
  in every shell, cron run and agent subprocess, and looks like a broken toolchain. Fix the manager's
  config, not the shims: `mise unuse -g X` (or reinstall it).

## Routine: updating a whole host on mise

`mise --version` → `mise self-update --yes` → `mise upgrade --dry-run` → `mise upgrade --yes` → `mise reshim` → verify.

- **Non-interactive runs of `self-update` and `upgrade` cancel without `--yes`** — they print the selected
  version and then `cancelled; use --yes`, exit non-zero, and leave the old binary in place. A CI/cron/agent
  caller must pass it.
- **`self-update` only applies to a standalone binary** (`~/.local/bin/mise`); if `readlink -f $(which mise)`
  lands in a package manager's prefix, update via that manager instead.
- **`upgrade` without `--bump` stays inside the config's range** (`dotnet = "10.0"` → newest 10.x) — this is
  what keeps LTS/STS banding intact. `--bump` rewrites `config.toml`; only use it when the band should move.
- **`minimum_release_age` (default 24h) marks releases younger than the gate ineligible and WARNs about them.**
  That is the gate working, not a failed upgrade: report it as "held back by release age, eligible <date>", and
  re-run the next day. Never defeat it to grab a same-day release.
- **`--version` passing is not a working tool.** After `reshim`, run one functional probe per moved major/tool
  (`bun -e`, `uvx --version`, `rg -c`, `ruff check <tmp file>`) — a broken install shows up there, not in `-v`.
- **No service restart is needed for a version bump.** Shims resolve the active version at exec time, so a
  running gateway/cron picks the new tool up in its next subprocess. Restarting is a separate, riskier change.
- **Old versions survive `upgrade.prune_after` (grace period)**, so rollback is per tool
  `mise use -g <name>@<old version>`; check `df -h /` before and after (some tools are hundreds of MB).

`mise doctor` reporting `mise shims are shadowed by executables earlier in PATH` is **expected** when a
product-owned runtime deliberately precedes the shims dir (rule 10) — read it as confirmation the ordering is
intact, not as a defect to fix.

## Pitfalls

- 对未知名字跑 `mise ls-remote` 只吐一句 `mise ERROR`，没有任何提示；含义是「没有短名」而不是「装不了」，换显式后端重试（规则 8）。
- 把 bin 目录的条目数当成「装了哪些工具」会高估：启动器脚本、python console-script、`npm link` 的本地包都躺在里面，一个都不算依赖。
- `command -v -a <name>` 是查遮蔽最快的单条命令：它按 PATH 顺序列出所有命中，重复安装一眼可见。
