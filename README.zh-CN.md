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
`npx skills add wxxb789/hoa`、拿走任何喜欢的部分。正因为公开，**任何 secret 和
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
| Skills（`SKILL.md` 包） | **hoa** | `npx skills add wxxb789/hoa` → `~/<agent>/skills/` |
| agent 角色、orchestration、prompt、rule、mcp、workflow、eval | **hoa** | 版本控制的库 / 知识（拼进 skill 或手动取用） |
| reflections 与外部参考 | **hoa** | 知识，永不下发 |
| runtime **设置**——LLM provider、models、plugins、`settings.json` / `config.toml` / `opencode.json` | **chezmoi** | `chezmoi apply` |

分工是刻意的：chezmoi 本就处理机器专属设置与 secret 模板化；`hoa` 只管可移植、
可共享的部件。零重叠，不自建下发工具。

## 目录结构

```text
hoa/
├── index.md · index.zh-CN.md   # 全部 artifact，按 area + target 打标签（自动生成——见 scripts/）
├── VERSION        # 全部自定义 skill 共用的权威版本
├── CHANGELOG.md   # 重要变更；旧条目保留历史上的各 skill 版本
├── skills/        # 唯一部署面 —— 用 `npx skills` 安装的 SKILL.md 包
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
链接错误或存在两个条目的 skill；`--link` 在 `<category>/<name>` 创建缺失的符号链接，
category 取该 skill 的第一个 `metadata.areas` 值，可用 `--category` 覆盖（`.` 表示平铺）。
它不会替换真实目录，也不会为同一个 skill 添加第二个条目。

## 这个仓库的形状

两条轴描述这里的一切：**artifact 是什么**（surface）与 **skill 如何与其他 skill 组合**（layer）。
`index.md` 是清单；本节是地图。

### 四个组合层

每个 `skills/<name>/SKILL.md` 都声明 `metadata.kind`。CI 拒绝缺失或未知的值，因此层是树上的
事实，而不是靠人记得添加的标签。

| `kind` | 用途 | 当前树上 |
|---|---|---|
| `entry` | 可由用户请求直接路由。它可以消费/生产 artifact，但不需要 controller 来调用。 | 37 个 skill，例如 `ghc-search`、`hoa-skill-work`、`spec-convergence` |
| `controller` | 路由一条链：决定哪个 stage 运行，且只生产 `chain-plan`。 | `goal-driven-delivery` |
| `stage` | 链中的一个阶段，由它的 controller 调用。声明它消费和生产什么。 | `subagent-driven-development`（`plan` → `implementation`） |
| `mechanism` | 只由另一个 skill 调用，永远不是路由目标。CI 拒绝把它列为 trigger case 的 `must_pick`。 | `delegated-work-acceptance` |

### 面（Surfaces）

| 目录 | 内容 | 是否下发 |
|---|---|---|
| `skills/` | 40 个 `SKILL.md` 包：唯一自动下发的 artifact。`npx skills add wxxb789/hoa` 安装它们。 | 是 |
| `agents/` | 1 个 role / authority / I-O 契约（`skill-scout`）。 | 否——库 |
| `mcps/` | 1 个可移植 MCP 定义（`ghc-proxy`）。 | 否——库 |
| `orchestration/` | 1 个调度/handoff/termination 模式（`typed-verification-gates`）。 | 否——库 |
| `prompts/` | 4 个按任务调用的 prompt 模板。 | 否——库 |
| `rules/` | 1 条常驻约束（`generated-means-generated`）。 | 否——库 |
| `workflows/` | 1 个面向结果的有限 recipe（`adopt-a-pattern`）。 | 否——库 |
| `evals/` | 两个 case suite（`trigger-cases.json`、`skill-method-cases.json`）及其离线校验器。 | 否——仅仓库 |
| `reflections/`、`ref/` | 人写的复盘与外部参考子模块；研究材料，从不下发。 | 否 |
| `scripts/` | 仓库维护：目录、主机一致性、版本/发布、契约图、配置解析器。 | 否 |

skill 的 frontmatter 同时携带目录字段与组合字段：`version`、`kind`、可选的逗号分隔
`consumes` / `produces`、`areas`、`targets`、`summary`、`summary_zh`。库 artifact 把元数据
放在 `<!-- index: ... -->` 注释里。`index.md` 与 `index.zh-CN.md` 从这两个来源生成，覆盖 49 个
artifact；CI 对漂移报错。runtime **设置**（provider、模型、插件）归 chezmoi，不归本仓库。

### 契约图

`scripts/check_contract_graph.py` 读取每个 skill 的 `kind` / `consumes` / `produces`，构建
artifact 图并离线检查（`--list` 打印图）。`scripts/contract_graph_registry.yaml` 登记三个
豁免口：`external:` 是 skill 图之外生产的 artifact（request、work-report、git-commit、
ci-result）；`shared:` 是两个 skill 都可以生产的 artifact（当前为空）；`terminal:` 是没有任何
skill 消费的 artifact，每个都带一行理由（chain-plan、implementation、acceptance-verdict、
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

### CI 跑什么

`test` job 在每次 push 到 `main`、每个 pull request 与 `workflow_dispatch` 时运行；`release`
job 只在 `main` 上、`test` 成功之后运行，并为 CI 验证过的提交打 tag。

| 检查命令（CI step） | 保护什么 |
|---|---|
| 在 `scripts/shared`、`skills/teams-cdp/scripts`、`skills/m365-copilot-cdp/scripts` 中运行 `bun install --frozen-lockfile && bun run check && bun test` | 共享代码与两个桌面 skill 的 CDP 类型和行为。 |
| `python scripts/vendor_shared.py --check` | 分发到 skill 内的共享脚本副本与权威文件一致。 |
| `python scripts/generate_index.py --check` | `index.md` / `index.zh-CN.md` 与 artifact 元数据一致。 |
| `python scripts/check_contract_graph.py` | 上面的 R1–R9。 |
| `python scripts/test_check_contract_graph.py` | 契约图检查器自身的规则测试。 |
| `python -m unittest scripts.test_skill_config` | 配置解析顺序与畸形配置行为。 |
| `python scripts/test_generate_index.py` | 目录收集、summary、中文回退、漂移。 |
| `python -m unittest scripts.test_install_host_skills` | 主机安装一致性（`--check` / `--link`）。 |
| `python -m unittest scripts.test_check_changelog` | changelog 规则自身的测试。 |
| `python scripts/check_frontmatter.py` | 每个 `SKILL.md` 的 frontmatter 与目录字段。 |
| `python -m unittest scripts.test_check_frontmatter` | frontmatter 检查器自身的测试。 |
| `python scripts/version.py check` | `VERSION` 被每个 skill 与两个索引镜像。 |
| `python scripts/version.py check-bump`（pull request） | `VERSION` 恰好是 `origin/main` 的 patch + 1。 |
| `python scripts/check_changelog.py --base origin/main`（pull request） | `VERSION` 变化时 `CHANGELOG.md` 也变化。 |
| `python scripts/version.py check-merge`（pull request） | 合并前版本声明在远端仍然可用。 |
| `python scripts/test_version.py` | 版本、同步与发布守卫行为。 |
| `python scripts/test_release.py` | 针对隔离本地 Git remote 的自动发布。 |
| `python skills/ghc-search/scripts/test_ghc_search.py` | 搜索客户端的请求/解析/错误行为。 |
| `python skills/hoa-introspect/evals/run.py` | `hoa-introspect` eval fixtures。 |
| `python skills/hoa-introspect-distill/evals/run_evals.py` | `hoa-introspect-distill` eval fixtures。 |
| `python skills/define-goal/evals/validate_fixtures.py` | `define-goal` eval fixtures。 |
| `python evals/run_trigger_evals.py` | trigger case 结构、目录交叉引用与 baseline 算术（离线）。 |
| `python -m unittest evals.test_judge_trigger_evals` | judge 配置优先级、退出码、逐 case 失败、baseline 写入；对本地 stub 运行。 |
| `python evals/validate_skill_method_cases.py` | `skill-method-cases.json` 结构与隔离路径。 |
| `python -m unittest evals.test_validate_skill_method_cases` | skill-method case 的 setup 文件隔离。 |
| `python scripts/release.py`（release job，`main` 上 `test` 之后） | 发布 CI 刚验证过的版本；从不升版。 |

依赖安装（`python -m pip install -r scripts/requirements.txt`）先于这些检查。judge 的 HTTP
客户端只用标准库；它导入的目录生成器使用仓库的 PyYAML 工具。

### eval case 如何评分——以及它能证明什么

`evals/trigger-cases.json` 有 25 个路由 case：`id`、用户 `request`、恰好一个 `must_pick`
artifact，以及不得被选中的 `distractors`。评分者是 fresh context 中的 LLM，它只看到一个新贡献者
会看到的东西：

1. 从 `scripts/generate_index.py collect()` 构建目录：49 个 artifact 的 name、type 与英文 summary。
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
`per_case`），且只记录完整 case set；已有记录只有加 `--force` 才会被替换。CI 从不调用模型：
`run_trigger_evals.py` 离线校验 baseline 的 id、通过数与 case 数，在第一次记录之前报告
`no baseline recorded yet`。

诚实边界：一个模型、一个 prompt、一个 effort 级别、一套人工挑选的 case。通过率说明的是这个
judge 在这一天这样理解了这些描述；它不证明用户会同样路由、不证明描述本身好、也不证明另一个
模型会同意。baseline 固定 model、effort、endpoint host 与日期，正是因为改动其中任何一项都会
破坏可比性。这个 suite 证明的是在人工挑选的近义 case 上有区分度，而不是真实世界的路由质量。

## 统一 skill 版本

`VERSION` 是 `skills/` 下所有自定义包共用的发布版本，从 `0.1.0` 开始。
每个 SKILL.md 通过标准 YAML `metadata.version` 同步版本，独立安装后也保留该信息。
目录标签也放在同一个 metadata mapping 中；自定义 skill 的旧 HTML index 注释
会报错，不作为兼容回退。第三方/参考目录及非 skill 的库 artifact 保持原有元数据。

```bash
python -m pip install -r scripts/requirements.txt  # 仓库工具依赖；建议使用 venv
python scripts/version.py check       # 只读检查版本一致性和索引
python scripts/version.py sync        # 同步 VERSION 并重新生成索引
python scripts/version.py bump        # 默认 patch：0.1.0 -> 0.1.1
python scripts/version.py bump minor  # 显式 minor；也支持 major
```

每个 PR 自行递增 patch：CI 要求 `VERSION` 恰好等于 `origin/main` 的版本且 patch 加 1，
因此在他人的合并之后才建立或落后的分支必须 rebase 并再次运行
`python scripts/version.py bump`。`main` 的 CI 成功后，发布 job 只为已合并 PR 提交的
版本打 tag（首次的 `v0.1.0` 原样发布）；它从不递增版本，也不创建版本提交。
发布保留 desktop CDP 测试及现有仓库检查，串行执行，拒绝过期 CI 对应的提交，
并以原子 push 发布 tag，不使用 force。

本地版本命令不会 commit 或 push。仅供 CI 的发布 helper 需要 `contents: write`，
分支保护也必须允许正常 push；它不会绕过仓库策略。重跑已发布的 push 不会再次升版。


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

**Skills**——唯一自动下发的 artifact——用 Vercel 的
[`skills`](https://github.com/vercel-labs/skills) CLI 安装：

```bash
# 把 hoa 所有 skill 装进每个检测到的 runtime(全局)
npx skills add wxxb789/hoa -g

# 只装某些 skill,到指定 runtime
npx skills add wxxb789/hoa -g -s <skill> -a claude-code -a opencode

# 安装前先列 / 更新 / 移除
npx skills add wxxb789/hoa --list
npx skills update
npx skills remove <skill>
```

- 全局（`-g`）装到 `~/<agent>/skills/`（`~/.claude/skills`、
  `~/.config/opencode/skills`、`~/.agents/skills` …）；默认 scope 装到当前项目。
- 默认 **symlink**（单一权威副本，好更新）或 `--copy`（Windows / 不支持 symlink 时）。
- `hoa` 里其它东西都是**库 / 知识**——不自动下发。拼进某个 skill，或手动取用。
- runtime **设置**由 `chezmoi apply` 另行下发。

## 处理 skill

按要完成的工作选择能力，而不是按当前运行的模型选择：

| 需求 | Skill | 结果 |
|---|---|---|
| 审计已有 skill、评审拟议修改，或判断其行为 | `hoa-skill-review` | 带证据的发现项；不修改被审查的 skill |
| 根据明确能力创建 skill，或改进已有 skill | `hoa-skill-work` | 完整的 skill 修改，以及验证结果与未验证路径 |
| 从 agent 历史中发现重复工作 | `hoa-introspect` | 带证据的工作模式发现；不会自动创建资产 |
| 在选择资产前评估给定的重复工作发现 | `hoa-introspect-distill` | 逐项批准的候选，以及获批后创建的资产 |

对行为变更，`hoa-skill-work` 默认使用聚焦检查；只有覆盖面、风险或相互矛盾的证据需要时，
才扩大到多版本、多模型或多 runtime。`hoa-introspect-distill` 保留逐候选批准门槛；
直接请求创建或改进一个明确的 skill，不需要走该提名流程。
`evals/skill-method-cases.json` 保存聚焦行为场景；CI 只校验结构与隔离路径，
模型和 runtime 行为须在全新运行中判断，不能把 fixture 检查当成行为证明。
Claude Code 内置的 `plugin eval` 测试 plugin 形态的包；Anthropic 的
`skill-creator` 是另外安装的官方 plugin，先前的 `define-goal` 审查则使用 CE
指导和会话自写 runner。它们都不是这些可移植 hoa skill 的必需依赖。
[源码归属研究](./reflections/2026-09-25-claude-code-skill-source.md)
区分了实现及各自的证据边界。

## 桌面消息自动化

- [`teams-cdp`](./skills/teams-cdp/SKILL.md) 查找准确的联系人和现有群聊，
  发送已授权的纯文本消息，并检查新消息的 **Sent** 回执。
- [`m365-copilot-cdp`](./skills/m365-copilot-cdp/SKILL.md) 通过本机 CDP 操作
  桌面 Copilot 的 Chat 与 Code，包括模型选择和回复读取。

两个包使用 strict TypeScript、Bun 和 `playwright-core`，连接已登录的应用，
不额外下载浏览器。每个 skill 均包含独立的依赖清单和 lockfile。
必须为实际工作界面启用本机 CDP；Code 还依赖已就绪的 native host。
使用真实账号前，先阅读各 skill 的启动方式和授权边界。

## 标签

area 与 target 作为标签记录在 [`index.md`](./index.md) 里，而不是建目录
（一个 artifact 常同时服务多个）。自定义 skill 将标签保存为标准 YAML
`metadata` 下的逗号分隔字符串，与版本放在一起：

```yaml
metadata:
  version: "0.1.0"
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

- **任何人：** `npx skills add wxxb789/hoa` 装上这些 skill，或 fork 拿走对你有用的
  部件。
- **我：** 在这里写 skill → `npx skills add wxxb789/hoa -g` → 落到每个 runtime；
  设置随 chezmoi 一起走。
