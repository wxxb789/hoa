# hoa — Hall of Armor（战甲陈列室）

> [English](./README.md) · **简体中文**

[![CI](https://github.com/wxxb789/hoa/actions/workflows/ci.yml/badge.svg)](https://github.com/wxxb789/hoa/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

我运行 AI agent 的**可移植部件**的个人家目录，覆盖我的整体运作——软件开发、
公司 / 项目管理、个人内省 / 自我管理。skill、agent 角色、orchestration 模式、
prompt、rule、MCP 配置、workflow、eval 都在这里纳入版本控制。其中可下发的那部分
——**skills**——用 [`npx skills`](https://github.com/vercel-labs/skills) 装进每个
runtime；runtime 的**设置**（LLM provider、models、plugins）留在 chezmoi。

名字取自 Tony Stark 的 *Hall of Armor*：打造、存放、对比、迭代每一套战甲的
库房——面向每一种任务的全套装备，而非单一聚焦。

## 两门工程学科

这个仓库是两门手艺的练武场：

- **Harness engineering（战甲工程）**——*capability = model × harness*。harness
  是包裹在模型外的一切：context、tools、control loop、memory、permissions、
  output handling。`hoa` 不存整套 harness——一套 harness 是**组装**出来的：runtime
  自己的**设置**（chezmoi 管）加上这里的**可移植部件**（`skills/` 用 `npx skills`
  装，`agents/` `prompts/` `rules/` `mcps/` 作它取用的库）。
- **Orchestration & loop engineering（编排 / 循环工程）**——驱动迭代式、多 agent
  工作的控制结构：continuation、termination、retry、handoff、fan-out / fan-in、
  best-of-N。循环只是编排的一种形态，所以归 `orchestration/`，不设 `loops/`。

## 个人用途，公开仓库

给我**个人**用，但仓库是**公开的**——你可以直接 clone、fork、
用 `npx skills` 安装你需要的 skill、拿走任何喜欢的部分。正因为公开，**任何 secret 和
个人信息都绝不纳入 git**（见 [`.gitignore`](./.gitignore)）：只提交模板和脱敏
资产；真实凭据与私密内容保持未跟踪（`.env`、`*.key`、`*.token`、`*.local.*`、
`private/`）或放进 secret manager。

## 用来做什么

1. **管理（Manage）**——给可移植的 agent 部件一个带版本控制的统一家目录，而不是
   散落在 `~/.claude`、`~/.codex`、`~/.config/opencode` … 的副本。
2. **下发（Deploy）**——`skills/` 用 `npx skills` 装进每个 runtime；runtime
   **设置**由 chezmoi 下发。`hoa` 两样都不重复造。
3. **复盘（Reflect）**——分析 / 评审 / 回顾自己怎么用 AI agent：哪套配置擅长哪类
   任务、什么有效、什么翻车、为什么这么选。

## 覆盖的 runtime

Hermes · Claude Code · Codex · pi · OpenCode · Kimi Code · *(`npx skills` 支持的
70+ agent 都行)*

## `hoa` ↔ chezmoi（谁管什么）

| 关注点 | 归属 | 机制 |
|---|---|---|
| Skills（`SKILL.md` 包） | **hoa** | `npx skills add wxxb789/hoa -s <skill>` → `~/<agent>/skills/` |
| agent 角色、orchestration、prompt、rule、mcp、workflow、eval | **hoa** | 版本控制的库 / 知识（拼进 skill 或手动取用） |
| reflections 与外部参考 | **hoa** | 知识，永不下发 |
| runtime **设置**——LLM provider、models、plugins、`settings.json` / `config.toml` / `opencode.json` | **chezmoi** | `chezmoi apply` |

分工是刻意的：chezmoi 本就处理机器专属设置与 secret 模板化；`hoa` 只管可移植、
可共享的部件。零重叠，不自建下发工具。

## 目录结构

```text
hoa/
├── index.md · index.zh-CN.md   # 全部 artifact，按 area + target 打标签（自动生成——见 scripts/）
├── VERSION        # 唯一的项目版本；skill 各自携带 metadata.revision
├── CHANGELOG.md   # 重要变更；旧条目保留历史上的各 skill 版本
├── skills/        # 唯一部署面 —— 用 `npx skills` 安装的 SKILL.md 包
├── paseo-plugins/ # 可选 Paseo 插件源码；显式安装，不自动下发
├── agents/        # 可移植、runtime 无关的 role / persona / authority / I-O 契约
├── orchestration/ # 调度、handoff、retry、continuation、termination、聚合(循环、crew、fan-out/in、best-of-N)
├── mcps/          # 可移植的 MCP server 定义与清单
├── prompts/       # 按任务调用的 prompt 模板
├── rules/         # 常驻的规范性约束 / 可复用 ruleset
├── workflows/     # 面向结果的有限步骤 recipe(不含 retry / termination 控制器)
├── evals/         # 可重复的 benchmark、cases、fixtures、rubrics、脱敏 datasets
├── reflections/   # 人写的比较、决策、retro、post-mortem
├── ref/           # 外部参考
└── scripts/       # 仓库工具：generate_index.py（索引）、install_host_skills.py（主机一致性）、vendor_shared.py（共享 skill 脚本分发）
```

`skills/` 遵循 `npx skills` 的布局：`skills/<name>/SKILL.md`（扁平）或
`skills/<category>/<name>/SKILL.md`（catalog）；`skills/.curated/`、
`skills/.experimental/`、`skills/.system/` 也会被识别。

`index.md` / `index.zh-CN.md` 是**生成文件**——修改目录元数据后运行
`python scripts/generate_index.py`：自定义 skill 使用 YAML 的 `metadata.areas` /
`metadata.targets`，库 artifact 使用 `<!-- index: ... -->` 注释（CI 会对漂移报错）。
Artifact 包括 skill（`skills/<name>/SKILL.md`）与库文件
（`agents/`、`mcps/`、`orchestration/`、`prompts/`、`rules/`、`workflows/`
下的 `<folder>/<name>.md` 或 `<folder>/<name>/README.md`）。目录名全局唯一，
每个配置的库目录至少要有一个 artifact,索引备注取 artifact 自身的元数据：
skill 用 `metadata.summary` / `metadata.summary_zh`，库 artifact 用索引注释里的
`summary` / `summary_zh`；缺失时回退到 description 首句,中文缺失时回退到英文备注。

主机安装一致性独立于目录：
`python scripts/install_host_skills.py --root <host-skills-dir> --check`
会搜索 `<root>/<name>` 与 `<root>/<category>/<name>`，逐条列出缺失、内容漂移、
链接错误或存在两个条目的 skill；`--link` 默认在 `<root>/<name>` 平铺创建缺失的符号链接，
传 `--category` 时放在 `<root>/<category>/<name>`，因此父 skill 与它通过 `../` 链接的兄弟 skill
位于同一目录。它不会替换真实目录，也不会为同一个 skill 添加第二个条目。

## 这个仓库的形状

两条轴描述这里的一切：**artifact 是什么**（surface）与 **skill 如何与其他 skill 组合**（layer）。
`index.md` 是清单；本节是地图。

### 四个组合层

每个 `skills/<name>/SKILL.md` 都声明 `metadata.kind`。CI 拒绝缺失或未知的值，因此层是树上的
事实，而不是靠人记得添加的标签。

| `kind` | 用途 | 当前树上 |
|---|---|---|
| `entry` | 可由用户请求直接路由。它可以消费/生产 artifact，但不需要 controller 来调用。 | 例如 `ghc-search`、`hoa-skill-create`、`spec-convergence` |
| `controller` | 路由一条链：决定哪个 stage 运行，且只生产 `chain-plan`。 | `gdd` |
| `stage` | 链中的一个阶段，由它的 controller 调用。声明它消费和生产什么。 | 目前没有 |
| `mechanism` | 只由另一个 skill 调用，永远不是路由目标。CI 拒绝把它列为 trigger case 的 `must_pick`。 | `delegated-work-acceptance` |

### 面（Surfaces）

| 目录 | 内容 | 是否下发 |
|---|---|---|
| `skills/` | `SKILL.md` 包：唯一可下发的 artifact。`npx skills add wxxb789/hoa -s <skill>` 安装你选中的那些。 | 是 |
| `paseo-plugins/` | 可选 Paseo 插件源码，包括只读的 GDD run observer。 | 仅手动选择安装 |
| `agents/` | 1 个 role / authority / I-O 契约（`skill-scout`）。 | 否——库 |
| `mcps/` | 1 个可移植 MCP 定义（`ghc-proxy`）。 | 否——库 |
| `orchestration/` | 1 个调度/handoff/termination 模式（`typed-verification-gates`）。 | 否——库 |
| `prompts/` | 5 个按任务调用的 prompt 模板。 | 否——库 |
| `rules/` | 1 条常驻约束（`generated-means-generated`）。 | 否——库 |
| `workflows/` | 1 个面向结果的有限 recipe（`adopt-a-pattern`）。 | 否——库 |
| `evals/` | 两个 case suite（`trigger-cases.json`、`skill-method-cases.json`）及其离线校验器。 | 否——仅仓库 |
| `reflections/`、`ref/` | 人写的复盘与外部参考子模块；研究材料，从不下发。 | 否 |
| `scripts/` | 仓库维护：目录、主机一致性、版本/revision 检查、契约图、配置解析器。 | 否 |

skill 的 frontmatter 同时携带目录字段与组合字段：`revision`、`kind`、可选的逗号分隔
`consumes` / `produces`、`areas`、`targets`、`summary`、`summary_zh`。库 artifact 把元数据
放在 `<!-- index: ... -->` 注释里。`index.md` 与 `index.zh-CN.md` 从这两个来源生成，覆盖目录里的全部
artifact；CI 对漂移报错。runtime **设置**（provider、模型、插件）归 chezmoi，不归本仓库。

### 契约图

`scripts/check_contract_graph.py` 读取每个 skill 的 `kind` / `consumes` / `produces`，构建
artifact 图并离线检查（`--list` 打印图）。`scripts/contract_graph_registry.yaml` 登记三个
豁免口：`external:` 是 skill 图之外生产的 artifact（request、work-report、git-commit、
ci-result）；`shared:` 是两个 skill 都可以生产的 artifact（当前为空）；`terminal:` 是没有任何
skill 消费的 artifact，每个都带一行理由（chain-plan、spec、acceptance-verdict、
scope-seal）。每条规则都由该命令执行：

| 规则 | 拒绝什么 |
|---|---|
| R1 | `kind` 不在 `entry`、`controller`、`stage`、`mechanism` 之内。 |
| R2 | 没有 `kind` 却声明了 `consumes` / `produces`。 |
| R3 | 消费的 artifact 没有 skill 生产，也未登记为 `external:`。 |
| R4 | `mechanism` 出现在任何 trigger case 的 `must_pick` 中——mechanism 永远不是路由目标。 |
| R5 | controller 不生产 `chain-plan`，或生产了任何别的 artifact。 |
| R6 | 同一个 artifact 由多个 skill 生产，且未登记为 `shared:`。 |
| R7 | skill 完全没有声明 `kind`。 |
| R8 | controller 的 `SKILL.md` 超过 120 行。 |
| R9 | 生产的 artifact 没有 skill 消费，也未登记为 `terminal:` 并带一行理由；`external:` artifact 豁免。 |
| R10 | 隐藏 skill（`disable-model-invocation: true`）出现在任一 trigger case 的 `must_pick` 中。 |

### CI 跑什么

`test` job 在每次 push 到 `main`、每个 pull request 与 `workflow_dispatch` 时运行。没有 release
job：`npx skills` 直接从 GitHub 安装，因此不打 tag、不发布。

`test` job 先装好运行时与依赖，然后运行 `python scripts/run_all_tests.py`。该 discoverer 将下表
中的每一条命令作为 `scripts/test_manifest.toml` 里的 manifest 条目来调度，而非独立的 CI
step（该表将在本系列的后续步骤中与 manifest 收敛）。它同时调度此前从未接入 CI 的 Python 测试套件——
`skills/delegated-work-acceptance/scripts/tests/test_worktree_scope.py` 与
`skills/gdd/scripts/tests/test_paseo_run_python.py`——以及 `paseo-plugins/gdd-run-observer`
这个 Vitest 包。

结算是防假绿的：零执行检查永远不是 PASS，counter 必须交代每一个未通过的检查——包括通过
`covered_by` 依据父套件日志结算的子套件。每个套件在自己的进程组与任务级 scratch 目录中运行；
未能按自身流程收尾的套件（被 runner 超时终止，或被信号杀死）只会终止**本运行 spawn 的那一个
进程**，其余一切都只**报告、不碰**：该命令所领导组的成员，以及仍持有该套件任务级 scratch 的进程
（按启动时的 cwd 或环境中的 scratch 路径识别，读 `/proc`）。规则刻意收窄——**runner 只对本运行
spawn 的进程发信号**——因为只有那个进程的身份是本运行自己记下的；同组成员、scratch 持有者、任何
后代都只会在记录里被点名并继续运行，而且只要发现这类进程，该套件的 teardown 就是 `unverified`，
让这条限制出现在结果里，而不是被悄悄吸收。绝不向进程组广播，也绝不通过裸 pid 或组号发信号。
被 spawn 进程的身份（pid 与 spawn 时读到的 `/proc/<pid>/stat` 第 22 字段：起始时间）是**投递时**
钉住的，而不是之前采样来的：为该 pid 打开 pidfd（`os.pidfd_open`），重读起始时间并要求等于记下的
那个，然后才经 `signal.pidfd_send_signal` 发信号。pidfd 钉住的是那个进程实例，所以被别人的 reap
释放、又被内核复用的 pid 收不到本运行的信号；已经消失的目标记为消失；已经终止的进程根本不会收到
信号；升级（TERM → 有界宽限 → KILL）每一轮都重新钉住目标，绝不复用上一轮的授权。spawn 之前本运行
还会把自己的 `SIGCHLD` 处置置为 `SIG_DFL`，并以不 reap 的方式观察命令退出（`waitid` + `WNOWAIT`），
这才让 pid 在 teardown 还需要它时不会被回收复用；组在命令被 reap 之前读取，所以干净退出留下的成员
会在组号仍属于该命令时被如实报告。证明拿不到时——处置没能建立或已不再存活、没有内核探针、没有
pidfd、没有 `/proc` 可读身份、起始时间复核失败、目标被别人 reap——一律不发信号，teardown 记为
unverified；既不退回 `Popen` 缓存的 `returncode`（它看不见 reap），也不退回裸 pid 或组号（用时它
可能已经指向别的什么）。每条退出路径——干净退出、超时、被信号杀死——都把 teardown 记录（含它证明
不了的部分）写进结果里的套件条目，让看记录的人看得到而不止产生它的那个 helper；再也无法等待其退出
的命令按错误结算，而不是把整轮运行拖下水。**残留限制写明**：runner 只对 spawn 的进程发信号，所以
套件留下的其他进程——同组成员、detached 持有者、任何后代——都会活过本轮运行，记录会点名它们并写明
未被触碰。这些门槛也决定了 teardown 在各平台上的上限：macOS 与 Windows 没有 pidfd（也没有
`/proc`），那里永远不发信号——每次 teardown 都拒绝并如实记录——Linux 上则按上面的方式逐次把关。

| 检查命令（CI step） | 保护什么 |
|---|---|
| `python scripts/vendor_shared.py --check` | 分发到 skill 内的共享脚本副本与权威文件一致。 |
| `python scripts/generate_index.py --check` | `index.md` / `index.zh-CN.md` 与 artifact 元数据一致。 |
| `python scripts/check_contract_graph.py` | 上面的 R1–R10。 |
| `python scripts/check_skill_links.py` | skill 中每个 `../<name>/` 引用都指向存在的同级 skill 与路径（相对所在文件解析）；skill Markdown 里每个 `uv run <path>.py` 指向带 PEP 723 块的脚本，`uv run python` 带 `--no-project`，且不用裸 `python`/`python3` 运行 skill 脚本。 |
| `python -m unittest scripts.test_check_skill_links` | 链接检查器自身的测试。 |
| `python scripts/test_check_contract_graph.py` | 契约图检查器自身的规则测试。 |
| `python -m unittest scripts.test_skill_config` | 配置解析顺序与畸形配置行为。 |
| `python scripts/test_generate_index.py` | 目录收集、summary、中文回退、漂移。 |
| `python -m unittest scripts.test_install_host_skills` | 主机安装一致性（`--check` / `--link`）、`../` 闭包、退役名称。 |
| `python -m unittest scripts.test_check_changelog` | changelog 规则自身的测试。 |
| `python scripts/check_frontmatter.py` | 每个 `SKILL.md` 的 frontmatter 与目录字段；description 上限 1024 字符；隐藏标记与 `agents/openai.yaml` 一致。 |
| `python -m unittest scripts.test_check_frontmatter` | frontmatter 检查器自身的测试。 |
| `python scripts/version.py check-bump`（pull request） | `VERSION` 恰好是 `origin/main` 的 patch + 1。 |
| `python scripts/version.py check-revisions`（pull request） | 自 merge base 以来改动过的每个 skill 目录都提高了 `metadata.revision`。 |
| `python scripts/check_changelog.py --base origin/main`（pull request） | `VERSION` 变化时 `CHANGELOG.md` 也变化。 |
| `python scripts/test_version.py` | 在临时 Git 仓库中检验 `bump`、`check-bump`、`check-revisions` CLI。 |
| `python skills/ghc-search/scripts/test_ghc_search.py` | 搜索客户端的请求/解析/错误行为。 |
| `python skills/hoa-introspect/evals/run.py` | `hoa-introspect` eval fixtures。 |
| `python skills/hoa-introspect-distill/evals/run_evals.py` | `hoa-introspect-distill` eval fixtures。 |
| `python skills/define-goal/evals/validate_fixtures.py` | `define-goal` eval fixtures。 |
| `python evals/run_trigger_evals.py` | trigger case 结构、目录交叉引用与 baseline 算术（离线）。 |
| `python -m unittest evals.test_judge_trigger_evals` | judge 配置优先级、退出码、逐 case 失败、baseline 写入；对本地 stub 运行。 |
| `python evals/validate_skill_method_cases.py` | `skill-method-cases.json` 结构与隔离路径。 |
| `python -m unittest evals.test_validate_skill_method_cases` | skill-method case 的 setup 文件隔离。 |

依赖安装（`python -m pip install -r scripts/requirements.txt`）先于这些检查。judge 的 HTTP
客户端只用标准库；它导入的目录生成器使用仓库的 PyYAML 工具。

### eval case 如何评分——以及它能证明什么

`evals/trigger-cases.json` 存路由 case：`id`、用户 `request`、恰好一个 `must_pick`
artifact，以及不得被选中的 `distractors`。评分者是 fresh context 中的 LLM，它只看到一个新贡献者
会看到的东西：

1. 从 `scripts/generate_index.py collect()` 构建目录：目录里全部 artifact 的 name、type 与英文 summary。
2. 对一个 case，发送目录与请求，要求只回复一个 artifact 名。
3. 只有去掉首尾空白后的回复恰好等于该 case 的 `must_pick` 才算通过。回复没有命中任何目录条目
   即该 case 失败，pick 原样保留。网络或 endpoint 错误只让该 case 失败，批次其余 case 继续完成。
4. `must_pick` 与 `distractors` 从不展示给 judge。

judge 靠配置运行，绝不写死。endpoint、model、effort 按 CLI flag → 环境变量 →
`$XDG_CONFIG_HOME/evals/config.yaml`（回退 `~/.config/evals/config.yaml`）→ 文档化默认值解析：

```bash
python evals/judge_trigger_evals.py --json \
  --base-url <openai-compatible-base> --model <judge-model> --effort low
```

配置键是 `base_url`、`model`、`effort` 与可选的 `api_key`；环境变量名是
`EVALS_BASE_URL`、`EVALS_MODEL`、`EVALS_EFFORT` 与 `EVALS_API_KEY`。请求是普通的
`POST <base_url>/chat/completions`；effort 通过 `reasoning_effort` 字段发送。全都没提供时脚本
以 2 退出，打印所需键与配置文件路径，绝不猜一个模型。`--record` 写入 `evals/baseline.json`
（`case_count`、`model`、`effort`、`passed`、`total`、`judge_endpoint_host`、`generated_at`、
`per_case`），且只记录完整 case set；已有记录只有加 `--force` 才会被替换。写入前会用离线
gate 自身的规则校验待写入记录：包含传输错误或非目录回答的运行无法用接受的 schema 表示，因此
文件保持原样、脚本以 2 退出并点名出错的 case（重跑而不是丢掉上一次测量）；答成目录内但错误的
artifact 则如实记录为失败。CI 从不调用模型：
`run_trigger_evals.py` 离线校验 baseline 的 id、目录内 pick、重算后的通过标志与 case 总数，
在第一次记录之前报告 `no baseline recorded yet`。

诚实边界：一个模型、一个 prompt、一个 effort 级别、一套人工挑选的 case。通过率说明的是这个
judge 在这一天这样理解了这些描述；它不证明用户会同样路由、不证明描述本身好、也不证明另一个
模型会同意。baseline 固定 model、effort、endpoint host 与日期，正是因为改动其中任何一项都会
破坏可比性。这个 suite 证明的是在人工挑选的近义 case 上有区分度，而不是真实世界的路由质量。

## 版本与 revision

两个计数器，各管一件事：

- `VERSION` 是唯一的项目版本（semver）。每个 PR 递增它的 patch：CI 要求恰好等于
  `origin/main` 的 patch + 1，所以落后于他人合并的分支要 rebase 后重新 bump。
- 每个 `SKILL.md` 里的 `metadata.revision` 是整数字符串，记录该 skill 自身的迭代次数。
  PR 只为它改动过的 skill 目录提高 revision；新 skill 从 `"1"` 开始。项目版本不会复制进 skill。

```bash
python -m pip install -r scripts/requirements.txt  # 仓库工具依赖；建议使用 venv
python scripts/version.py bump             # 默认 patch：0.1.0 -> 0.1.1
python scripts/version.py check-bump       # VERSION 是 origin/main 的 patch + 1
python scripts/version.py check-revisions  # 每个改动过的 skill 都提高了 revision
```

没有 release、tag 或二进制产物：`npx skills` 直接从 GitHub 默认分支安装。
本地版本命令不会 commit 或 push。


## 双语政策

文档同时维护英文与简体中文。**英文是权威来源**；中文镜像随同一次提交跟进。
生成文件（索引）从单一来源产出双语，只有手写文档付翻译成本。

## 克隆

```bash
git clone https://github.com/wxxb789/hoa   # 用 skill / 跑测试都不需要子模块
```

`ref/` 下的 35 个参考仓库是子模块——很重，只在研究上游时才需要。普通克隆
（不加 `--recursive`）使用和测试其余一切完全够用。需要时刷新参考：
`git submodule update --init --remote --merge`。

## 该放哪儿？（分类）

按 artifact 的**主要消费接口**分类，而不是按它内部用了什么。

| 目录 | 属于这里 | 不属于这里 |
|---|---|---|
| `skills/` | 通过 skill / command 名直接调用的完整能力，可用 `npx skills` 下发 | 仅供别的 artifact 拼装的 prompt 或 role |
| `paseo-plugins/` | 显式安装为 Paseo 插件的可移植源码包 | 机器专属插件注册或 runtime 设置（→ chezmoi） |
| `agents/` | 多个 runtime 都能实现的单 agent role 契约 | vendor 专属 runtime 设置(→ chezmoi);crew 调度(→ `orchestration/`) |
| `orchestration/` | 决定谁何时运行、结果如何流转、是否 retry / 停止 | 具体业务 recipe(→ `workflows/`) |
| `mcps/` | 可移植的 MCP endpoint / tool 定义 | `settings.json` 里的 vendor 专属注册(→ chezmoi) |
| `prompts/` | 一次任务的请求模板 | 常驻行为约束(→ `rules/`);persona(→ `agents/`) |
| `rules/` | “始终 / 禁止 / 必须”式常驻约束 | 一次性任务说明(→ `prompts/`) |
| `workflows/` | 以结果为中心的有限步骤 | 任何拥有 retry / continuation / agent 调度的东西(→ `orchestration/`) |
| `evals/` | 可机器执行 / 可重复评分的输入 + rubric | 对结果的文章式分析(→ `reflections/`) |
| `reflections/` | 观察、结论、决策、retro | 运行期用到的 fixture / config / dataset |
| `scripts/` | 维护 `hoa` 仓库自身 | runtime 设置或 hook(→ chezmoi) |

> 边界例子：改 runtime 的 stop-hook 属于**设置** → chezmoi；通用的 continuation /
> termination 模式 → `orchestration/`。像 `/security-review` 这样的多 agent skill
> 归 `skill/`（它的外部接口），即使内部用了 orchestration。

## 下发

**Skills**——唯一可下发的 artifact——用 Vercel 的
[`skills`](https://github.com/vercel-labs/skills) CLI 安装：

```bash
# 默认：装全部 skill（用 -a <agent> 选择 runtime）
npx skills add wxxb789/hoa -g -s '*'

# 看有哪些
npx skills add wxxb789/hoa --list

# 更新 / 移除
npx skills update
npx skills remove -g <skill>
```

**默认整库安装。** `npx skills` 只安装你点名的 skill，不跟随它们之间的 `../` 链接，所以单写
`-s <skill>` 可能缺少它串联的同级 skill。要单装，从 [`index.zh-CN.md`](./index.zh-CN.md#安装) 的
“安装”一节复制该 skill 的命令：它由链接生成，列出该 skill 的整个闭包。表中没有的 skill 没有依赖。

**升级已有安装。** 在本仓库改名或退役的 skill 仍以旧名留在安装目录里。用同一节里生成的
`npx skills remove -g …` 命令移除旧名；该名单的来源是 `scripts/retired_skills.toml`，其中写明每个
替代者。先把你从其它来源安装的同名 skill 从命令中去掉，否则它也会被移除。

- 全局（`-g`）装到 `~/<agent>/skills/`（`~/.claude/skills`、
  `~/.config/opencode/skills`、`~/.agents/skills` …）；默认 scope 装到当前项目。
- 默认 **symlink**（单一权威副本，好更新）或 `--copy`（Windows / 不支持 symlink 时）。
- 部分 skill 通过 `../<child>/SKILL.md` 串联同级 skill。copy 安装（`--copy`、Codex 的
  skill-installer）必须把整个 `../` 依赖闭包装进同一个 skills 根目录，否则链路断开。Windows 上
  仓库安装器（`python scripts/install_host_skills.py --root <host-skills-dir> --link`，再跑
  `--check`；默认平铺，传一个 `--category` 也会让父 skill 与其子 skill 同处一处）以绝对目标 symlink
  链接整个目录，需要开发者模式或管理员权限；`--check` 报告缺失或分裂的闭包，以及仍安装着的退役名称。
  详见 [`rules/cross-platform-skills.md`](./rules/cross-platform-skills.md)。
- `hoa` 里其它东西都是**库 / 知识**——不自动下发。拼进某个 skill，或手动取用。
- runtime **设置**由 `chezmoi apply` 另行下发。

### GDD transport 与可选 Paseo observer

[`gdd`](./skills/gdd/SKILL.md) 默认仍使用随附的 `omp-run.py` headless launcher。
显式把 `GDD_LAUNCHER` 指向随附的 `paseo-run.py`，才会让 stage 成为原生 Paseo agent；
这条路要求 daemon 可达。可达性绝不触发 launcher 自动替换。
[Transport 契约](./skills/gdd/references/transport.md) 说明配置、答案读取、完成判定，
以及相互独立的 headless / native 平台证据。

[`paseo-plugins/gdd-run-observer`](./paseo-plugins/gdd-run-observer/README.md) 是可选的
只读 observer 源码，**不是 launcher**。`npx skills` 不会自动安装它，它也不会改变
所选 transport。[README](./paseo-plugins/gdd-run-observer/README.md) 提供从干净克隆
安装依赖、typecheck / 测试、信任边界、禁用和移除说明；
[HOA-INTEGRATION.md](./paseo-plugins/gdd-run-observer/HOA-INTEGRATION.md) 说明共享
`GDD_RUN_ROOT` 与两条路径的集成。安装前先审查：插件会在 Paseo daemon / client 中
执行受信任、无沙箱的代码。Runtime 注册与设置仍由本机管理。

## 处理 skill

按要完成的工作选择能力，而不是按当前运行的模型选择：

| 需求 | Skill | 结果 |
|---|---|---|
| 审计已有 skill、评审拟议修改，或判断其行为 | `hoa-skill-review` | 带证据的发现项；不修改被审查的 skill |
| 根据明确能力创建 skill，或演进、组合已有 skill | `hoa-skill-create` | 完整的 skill 修改，以及验证结果与未验证路径 |
| 从 agent 历史中发现重复工作 | `hoa-introspect` | 带证据的工作模式发现；不会自动创建资产 |
| 在选择资产前评估给定的重复工作发现 | `hoa-introspect-distill` | 逐项批准的候选，以及获批后创建的资产 |
| 审计会话实际提供的整套 skill：重叠、遮蔽、漂移、可见性与清单预算（隐藏 skill：手动运行 `/hoa-skill-set-audit`，Codex 用 `$hoa-skill-set-audit`） | `hoa-skill-set-audit` | 按危害排序、带证据的整体发现项；不做任何修改 |

对行为变更，`hoa-skill-create` 默认使用聚焦检查；只有覆盖面、风险或相互矛盾的证据需要时，
才扩大到多版本、多模型或多 runtime。`hoa-introspect-distill` 保留逐候选批准门槛；
直接请求创建或改进一个明确的 skill，不需要走该提名流程。
`evals/skill-method-cases.json` 保存聚焦行为场景；CI 只校验结构与隔离路径，
模型和 runtime 行为须在全新运行中判断，不能把 fixture 检查当成行为证明。
Claude Code 内置的 `plugin eval` 测试 plugin 形态的包；Anthropic 的
`skill-creator` 是另外安装的官方 plugin，先前的 `define-goal` 审查则使用 CE
指导和会话自写 runner。它们都不是这些可移植 hoa skill 的必需依赖。
[源码归属研究](./reflections/2026-09-25-claude-code-skill-source.md)
区分了实现及各自的证据边界。

## 标签

area 与 target 作为标签记录在 [`index.md`](./index.md) 里，而不是建目录
（一个 artifact 常同时服务多个）。自定义 skill 将标签保存为标准 YAML
`metadata` 下的逗号分隔字符串，与 revision 放在一起：

```yaml
metadata:
  revision: "1"
  areas: "software-development,work-management"
  targets: "runtime-agnostic"
```

库 artifact 保留 HTML index 注释。允许的标签值：

- `areas`：`software-development` · `work-management` · `self-management`
- `targets`：`runtime-agnostic` · `repo-only` · `claude-code` · `codex` ·
  `opencode` · `hermes` · `pi` · `kimi-code`（即这个 skill 面向的
  `npx skills --agent`）

type 从目录推导。两个轴都可多值。

## 参考地图

[`ref/README.md`](./ref/README.md) 把 **35 个外部 agent/skill/harness 仓库**逐一
映射到"它是什么 + 值得偷什么具体模式"——如果你想设计自己的 agent 体系，这是
本仓库信息密度最高的一页。

## 路线图

- **Phase 1：** 骨架 + 定义 + 按 area/target 打标签的 index（taxonomy 已经 Oracle
  压力测试）。✓
- **Phase 2：** skills-first 下发——`skills/` 走 `npx skills`，设置走 chezmoi；
  去掉 `runtimes/`。✓
- **Phase 3：** 在 `skills/` 里长出真实 skill；从 per-artifact metadata 生成
  `index.md`（✓ `scripts/generate_index.py`，现已覆盖库目录）；建 `evals/` +
  `reflections/`（第一篇复盘：`reflections/2026-09-23-skills-first-split.md`；
  trigger evals：`evals/trigger-cases.json`）。✓
- **Phase 4（当前）：** 让库真正活起来——每个库目录现在至少有一个改编自
  `ref/` 的样例（第一批偷师：ECC 的 skill-scout → `agents/`、looper 的
  typed gates → `orchestration/`）；下一步：distill 循环产出的第一个
  自产 skill，第一个外部消费者 issue。

## 复盘节奏

复盘是排期的，不是随缘的：每月跑一次 **hoa-introspect** 自我复盘，产出写入
`reflections/`。distill 循环（introspect → retrieve → distill）应在下一个
phase 收尾前产出第一个自产 skill。

## 请求一个 skill

公开仓库，开放接收：如果这里缺某个能力、或某个 skill 只覆盖了你场景的一半，
请开 issue（bug 或 skill request）——issue 模板两种都有。外部请求也是决定
下一步建什么的最好信号。

## 如何使用

- **任何人：** `npx skills add wxxb789/hoa -g -s '*'`，或用
  [`index.zh-CN.md`](./index.zh-CN.md#安装) 里的命令单装某个 skill，或 fork 拿走对你有用的部件。
- **我：** 在这里写 skill → `npx skills add wxxb789/hoa -g -s <skill> -a '*'` → 落到每个 runtime；
  设置随 chezmoi 一起走。
