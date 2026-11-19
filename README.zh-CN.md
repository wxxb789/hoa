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
  装，`agents/` `prompts/` `rules/` 作它取用的库）。
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
| agent 角色、orchestration、prompt、rule、workflow、eval | **hoa** | 版本控制的库 / 知识（拼进 skill 或手动取用） |
| reflections 与外部参考 | **hoa** | 知识，永不下发 |
| runtime **设置**——LLM provider、models、plugins、`settings.json` / `config.toml` / `opencode.json` | **chezmoi** | `chezmoi apply` |

分工是刻意的：chezmoi 本就处理机器专属设置与 secret 模板化；`hoa` 只管可移植、
可共享的部件。零重叠，不自建下发工具。

## 目录结构

```text
hoa/
├── index.md · index.zh-CN.md   # 全部 artifact，按 area + target 打标签（自动生成——见 scripts/）
├── CHANGELOG.md   # 可选的按日期记录；旧条目保留历史上的项目版本与各 skill 版本
├── skills/        # 唯一部署面 —— 用 `npx skills` 安装的 SKILL.md 包
├── paseo-plugins/ # 可选 Paseo 插件源码；显式安装，不自动下发
├── agents/        # 可移植、runtime 无关的 role / persona / authority / I-O 契约
├── orchestration/ # 调度、handoff、retry、continuation、termination、聚合(循环、crew、fan-out/in、best-of-N)
├── prompts/       # 按任务调用的 prompt 模板
├── rules/         # 常驻的规范性约束 / 可复用 ruleset
├── workflows/     # 面向结果的有限步骤 recipe(不含 retry / termination 控制器)
├── evals/         # 可重复的 benchmark、cases、fixtures、rubrics、脱敏 datasets
├── reflections/   # 人写的比较、决策、retro、post-mortem
├── ref/           # 外部参考
└── scripts/       # 仓库工具：generate_index.py（索引与安装命令）、vendor_shared.py（共享 skill 脚本分发）
```

`skills/` 遵循 `npx skills` 的布局：`skills/<name>/SKILL.md`（扁平）或
`skills/<category>/<name>/SKILL.md`（catalog）；`skills/.curated/`、
`skills/.experimental/`、`skills/.system/` 也会被识别。

`index.md` / `index.zh-CN.md` 是**生成文件**——修改目录元数据后运行
`python scripts/generate_index.py`：自定义 skill 使用 YAML 的 `metadata.areas` /
`metadata.targets`，库 artifact 使用 `<!-- index: ... -->` 注释（CI 会对漂移报错）。
Artifact 包括 skill（`skills/<name>/SKILL.md`）与库文件
（`agents/`、`orchestration/`、`prompts/`、`rules/`、`workflows/`
下的 `<folder>/<name>.md` 或 `<folder>/<name>/README.md`）。目录名全局唯一，
每个配置的库目录至少要有一个 artifact,索引备注取 artifact 自身的元数据：
skill 用 `metadata.summary` / `metadata.summary_zh`，库 artifact 用索引注释里的
`summary` / `summary_zh`；缺失时回退到 description 首句,中文缺失时回退到英文备注。

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
| `mechanism` | 只由另一个 skill 调用，永远不是路由目标。CI 拒绝把它列为 trigger case 的 `must_pick`。 | `gdd-route-dsh` |

### 面（Surfaces）

| 目录 | 内容 | 是否下发 |
|---|---|---|
| `skills/` | `SKILL.md` 包：唯一可下发的 artifact。`npx skills add wxxb789/hoa -s <skill>` 安装你选中的那些。 | 是 |
| `paseo-plugins/` | 可选 Paseo 插件源码，包括只读的 GDD run observer。 | 仅手动选择安装 |
| `agents/` | 1 个 role / authority / I-O 契约（`skill-scout`）。 | 否——库 |
| `orchestration/` | 1 个调度/handoff/termination 模式（`typed-verification-gates`）。 | 否——库 |
| `prompts/` | 5 个按任务调用的 prompt 模板。 | 否——库 |
| `rules/` | 1 条常驻约束（`generated-means-generated`）。 | 否——库 |
| `workflows/` | 1 个面向结果的有限 recipe（`adopt-a-pattern`）。 | 否——库 |
| `evals/` | 触发用例与离线校验器。 | 否——仅仓库 |
| `reflections/`、`ref/` | 人写的复盘与外部参考子模块；研究材料，从不下发。 | 否 |
| `scripts/` | 仓库维护：目录与安装命令、版本/revision 检查、契约图、配置解析器。 | 否 |

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

CI（[`ci.yml`](.github/workflows/ci.yml)）在 Ubuntu 上运行 `test`，并在 Ubuntu、macOS 和
Windows 上各运行 `gdd-runner` 和 `gdd-observer`。触发条件是 push 到 `main`、pull request 或
`workflow_dispatch`。`main` 的 ruleset 要求全部七项 job 检查通过。没有 release job：
`npx skills` 直接从 GitHub 安装。每项检查都是具名 step，失败时可在 Actions 界面定位；
同一 pull request 的新 push 会取消旧的运行。

独立的 [`gdd-windows-stress.yml`](.github/workflows/gdd-windows-stress.yml) 每晚及手动触发时运行
带 no-window guard 的 Windows 生命周期测试，不属于必需检查。

| Job / Step | 命令 | 保护什么 |
|---|---|---|
| Frontmatter | `python scripts/check_frontmatter.py` | 每个 `SKILL.md` 的 frontmatter 与目录字段；description 上限：可见 350 字符、隐藏 1024 字符；隐藏标记与 `agents/openai.yaml` 一致。 |
| Contract graph | `python scripts/check_contract_graph.py` | 上面的 R1–R10。 |
| Skill links | `python scripts/check_skill_links.py` | skill 中每个 `../<name>/` 引用都指向存在的同级 skill 与路径（相对所在文件解析）；skill Markdown 里每个 `uv run <path>.py` 指向带 PEP 723 块的脚本，`uv run python` 带 `--no-project`，且不用裸 `python`/`python3` 运行 skill 脚本。 |
| Catalog index drift | `python scripts/generate_index.py --check` | `index.md` / `index.zh-CN.md` 与 artifact 元数据一致。 |
| Vendored shared scripts drift | `python scripts/vendor_shared.py --check` | 分发到 skill 内的共享脚本副本与权威文件一致。 |
| PR bumps changed skills' revision（pull request） | `python scripts/version.py check-revisions` | 自 merge base 以来改动过的每个 skill 目录都提高了 `metadata.revision`。 |
| pytest | `python -m pytest` | `scripts/`、`evals/`、`skills/` 下每个 `test_*.py` unittest/pytest 文件（`pytest.ini`）；每个测试 120 秒上限。 |
| 脚本检查 | `python evals/run_trigger_evals.py`、`skills/define-goal/evals/validate_fixtures.py`、`skills/hermes-models/scripts/tests/test-*.py`、`skills/gdd/scripts/tests/test_verdict_matrix.py`、`mutate_verdict_matrix.py` | 以退出码为契约的独立检查；每个一个 step。 |
| `gdd-observer`（Ubuntu、macOS、Windows） | 在 `paseo-plugins/gdd-observer` 中 `npm ci && npm run typecheck && npm test` | 插件的 typecheck 与 Vitest 套件。 |
| `gdd-runner`（Ubuntu、macOS、Windows） | 对 `skills/gdd/scripts/tests/` 下的 `test_agent_run.py`、`test_detach_supervisors.py`、`test_gdd.py`、`test_no_window.py`、`test_paseo_run_python.py`、`test_watch_pr_checks.py` 运行 `python -m pytest -q` | 跨平台 runner、分离进程 supervisor、阶段派发、控制台抑制、Paseo adapter 和 PR watcher 契约。 |

本地运行 Python 测试：
`uv run --no-project --with-requirements scripts/requirements.txt python -m pytest`（或
`pip install -r scripts/requirements.txt && python -m pytest`）。新的 `test_*.py` 测试文件无需登记即被收集；
不是测试文件的独立检查需要在 `ci.yml` 中有自己的 step。GDD runner 测试也在原生 Windows 和
macOS 上运行；平台专属用例会在不适用的平台跳过。

### eval case 如何评分——以及它能证明什么

`evals/trigger-cases.json` 存路由 case：`id`、用户 `request`、恰好一个 `must_pick`
答案（artifact 名或 `none`），以及不得被选中的 `distractors`。评分者是 fresh context 中的 LLM：

1. 用 `scripts/generate_index.py collect()` 列出 artifact。可见 skill 使用 name、type 和
   `SKILL.md` frontmatter 中的完整 `description`；省略设置了 `disable-model-invocation: true`
   的 skill，其他库内 artifact 仍使用英文索引说明。
2. 发送目录与请求，要求只回复一个 artifact 名；没有合适的 artifact 则回复 `none`。
3. 去掉首尾空白后的回复须匹配 `must_pick` 中唯一的答案；否则该 case 失败，回复保留为 pick。
   网络或 endpoint 错误只让该 case 失败。
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
gate 自身的规则校验待写入记录：包含传输错误或目录名称与 `none` 以外的回答时，文件保持原样，
脚本以 2 退出并点名出错的 case；格式合法但答错的 pick 则如实记录为失败。CI 从不调用模型：
`run_trigger_evals.py` 离线校验 baseline 的 id、pick、重算后的通过标志与 case 总数，
在第一次记录之前报告 `no baseline recorded yet`。

诚实边界：一个模型、一个 prompt、一个 effort 级别、一套人工挑选的 case。通过率说明的是这个
judge 在这一天这样理解了这些描述；它不证明用户会同样路由、不证明描述本身好、也不证明另一个
模型会同意。baseline 固定 model、effort、endpoint host 与日期，正是因为改动其中任何一项都会
破坏可比性。这个 suite 证明的是在人工挑选的近义 case 上有区分度，而不是真实世界的路由质量。

## Revision

没有项目版本。每个 `SKILL.md` 里的 `metadata.revision` 是整数字符串，记录该 skill 自身的迭代次数。
PR 只为它改动过的 skill 目录提高 revision；新 skill 从 `"1"` 开始，Git 识别到的改名在原 revision 上加一。

```bash
python -m pip install -r scripts/requirements.txt  # 仓库工具依赖；建议使用 venv
python scripts/version.py check-revisions  # 每个改动过的 skill 都提高了 revision
```

没有 release、tag 或二进制产物：`npx skills` 直接从 GitHub 默认分支安装。
`CHANGELOG.md` 条目按日期记录且可选，没有 gate 要求必须写。


## 双语政策

文档同时维护英文与简体中文。**英文是权威来源**；中文镜像随同一次提交跟进。
生成文件（索引）从单一来源产出双语，只有手写文档付翻译成本。

## 克隆

```bash
git clone https://github.com/wxxb789/hoa   # 用 skill / 跑测试都不需要子模块
```

`ref/` 下的参考仓库是子模块，只在研究上游时才需要。普通克隆
（不加 `--recursive`）即可使用和测试其余内容。新克隆的子模块默认使用浅克隆。
需要时刷新参考：
`git submodule update --init --remote --merge`。

## 该放哪儿？（分类）

按 artifact 的**主要消费接口**分类，而不是按它内部用了什么。

| 目录 | 属于这里 | 不属于这里 |
|---|---|---|
| `skills/` | 通过 skill / command 名直接调用的完整能力，可用 `npx skills` 下发 | 仅供别的 artifact 拼装的 prompt 或 role |
| `paseo-plugins/` | 显式安装为 Paseo 插件的可移植源码包 | 机器专属插件注册或 runtime 设置（→ chezmoi） |
| `agents/` | 多个 runtime 都能实现的单 agent role 契约 | vendor 专属 runtime 设置(→ chezmoi);crew 调度(→ `orchestration/`) |
| `orchestration/` | 决定谁何时运行、结果如何流转、是否 retry / 停止 | 具体业务 recipe(→ `workflows/`) |
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
[`skills`](https://github.com/vercel-labs/skills) CLI（`npx skills`）安装；本仓库不另带安装器。

```bash
# 装全部 skill（用 -a <agent> 选择 runtime）
npx skills add wxxb789/hoa -g -s '*' -y

# 看有哪些
npx skills add wxxb789/hoa --list

# 重装上游有变化的 skill
npx skills update -g -y
```

**默认整库安装。** `npx skills` 没有依赖概念：只安装你点名的 skill，不跟随它们之间的 `../` 链接，
所以单写 `-s <skill>` 可能缺少它串联的同级 skill。要单装，从 [`index.zh-CN.md`](./index.zh-CN.md#安装)
的“安装”一节复制该 skill 的命令：它由链接生成，列出该 skill 的整个闭包。表中没有的 skill 没有依赖。

**不使用 Hermes？那就不要安装 `hermes-*` skill。** 它们只用于操作 Hermes，而上面的整库安装命令会把它们一起装上。
请改用 [`index.zh-CN.md`](./index.zh-CN.md#安装) “安装”一节里生成的“不使用 Hermes 时”命令；
其他 skill 都不链接它们，所以不会缺依赖。

**Hermes 模型路由。** [`hermes-models`](./skills/hermes-models/SKILL.md) 用于配置和验证 Hermes 模型路由。
请使用父 skill 生成的安装命令，将 [`hermes-models-cutover`](./skills/hermes-models-cutover/SKILL.md)
和父 skill 一起装到同一个 skills 根目录。子 skill 负责可回滚的全量切换和同 provider 的 ID 替换，
并逐一验证受影响的运行面。Hermes 不识别 `disable-model-invocation`，因此仍会列出子 skill。
其他 runtime 的手动入口：Claude Code 和 DeepSeek Harness 用 `/hermes-models-cutover`，
Codex 用 `$hermes-models-cutover`，Pi 和 OMP 用 `/skill:hermes-models-cutover`，
OpenCode 用 `@hermes-models-cutover`。

**某次发布改名或退役了 skill 之后。** `npx skills update` 会把改名或退役的 skill 以旧名保留（只警告
上游已删除），也从不安装新名称。运行 `index.zh-CN.md` 同一节里生成的 `npx skills remove -g …` 命令
（来源是 `scripts/retired_skills.toml`，其中写明每个替代者），再重新运行整库安装命令，
或该节里每个 skill 的当前行（之前保存的单装命令可能仍含旧名称），装上新名称。
移除从未安装的名称不会有任何影响；但移除按名称匹配所有来源，所以先看 `npx skills ls -g`，
把你从其它来源安装的同名 skill 从命令中去掉。

**开发某个 skill。** `npx skills add <本地 checkout> -g -s <skill> -y` 安装工作区中的版本。
`npx skills update` 会跳过本地来源，所以每次修改后重新运行这条 add；推送之后，从 `wxxb789/hoa`
重新安装，让 `update` 重新跟踪它。

- 全局（`-g`）装到 `~/<agent>/skills/`（`~/.claude/skills`、
  `~/.config/opencode/skills`、`~/.agents/skills` …）；默认 scope 装到当前项目。
- 默认 **symlink**（单一权威副本，好更新）或 `--copy`（Windows / 不支持 symlink 时）。
- 部分 skill 通过 `../<child>/SKILL.md` 串联同级 skill，因此父 skill 的整个 `../` 闭包必须位于同一个
  skills 根目录；上面的命令会装齐它。要诊断已安装的集合（闭包缺失或分裂、重复、遮蔽），运行由用户调用的
  [`hoa-skill-set-audit`](./skills/hoa-skill-set-audit/SKILL.md)。详见
  [`rules/cross-platform-skills.md`](./rules/cross-platform-skills.md)。
- `hoa` 里其它东西都是**库 / 知识**——不自动下发。拼进某个 skill，或手动取用。
- runtime **设置**由 `chezmoi apply` 另行下发。

### GDD transport 与可选 Paseo observer

[`gdd`](./skills/gdd/SKILL.md) 默认使用随附的 `agent_run.py` headless runner（`GDD_AGENT` 选择 CLI）。
显式把 `GDD_LAUNCHER` 指向随附的 `paseo-run.py`，才会让 stage 成为原生 Paseo agent；
这条路要求 daemon 可达。可达性绝不触发 launcher 自动替换。
[Transport 契约](./skills/gdd/references/transport.md) 说明配置、答案读取、完成判定，
以及相互独立的 headless / native 平台证据。

[`paseo-plugins/gdd-observer`](./paseo-plugins/gdd-observer/README.md) 是可选的
只读 observer 源码，**不是 launcher**。`npx skills` 不会自动安装它，它也不会改变
所选 transport。它只保留一个入口——侧栏底部的 **GDD runs** 行，用于打开全局 `runs`
屏幕——另有独立的设置屏幕。[README](./paseo-plugins/gdd-observer/README.md) 说明读取的
运行产物、设置、信任边界、开发检查、安装与移除；
[HOA-INTEGRATION.md](./paseo-plugins/gdd-observer/HOA-INTEGRATION.md) 说明共享
`GDD_RUN_ROOT` 与两条路径的集成。安装前先审查：插件会在 Paseo daemon / client 中
执行受信任、无沙箱的代码。Runtime 注册与设置仍由本机管理。

## 处理 skill

按要完成的工作选择能力，而不是按当前运行的模型选择：

| 需求 | Skill | 结果 |
|---|---|---|
| 审计已有 skill、评审拟议修改，或判断其行为 | `hoa-skill-review` | 带证据的发现项；不修改被审查的 skill |
| 根据明确能力创建 skill，或演进、组合已有 skill | `hoa-skill-create` | 完整的 skill 修改，以及验证结果与未验证路径 |
| 复盘跨仓库和 agent 会话的工程实践（隐藏 skill：手动运行 `/hoa-practice-retro`，Codex 用 `$hoa-practice-retro`） | `hoa-practice-retro` | 带证据的发现及符合条件的重复工作候选；不会自动创建资产 |
| 深度审计单个仓库的运作机制（隐藏 skill：手动运行 `/hoa-repo-reckoning`，Codex 用 `$hoa-repo-reckoning`） | `hoa-repo-reckoning` | 验证后的发现、排序的停止事项和上轮跟进 |
| 审计会话实际提供的整套 skill（隐藏 skill：手动运行 `/hoa-skill-set-audit`，Codex 用 `$hoa-skill-set-audit`） | `hoa-skill-set-audit` | 验证后的整套发现、必要性结论或每周推荐；不做任何修改 |

对行为变更，`hoa-skill-create` 默认使用聚焦检查；只有覆盖面、风险或相互矛盾的证据需要时，
才扩大到多版本、多模型或多 runtime。复盘候选须经负责人逐项批准后才能进入创建流程；
直接请求创建或改进一个明确的 skill，不需要走该提名流程。
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

[`ref/README.md`](./ref/README.md) 把外部 agent/skill/harness 仓库逐一
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

每月在仓库审计后运行 **hoa-practice-retro**，以复用审计账本。复盘产出保存在配置的
私有审计状态目录中，不提交到 Git。

## 请求一个 skill

公开仓库，开放接收：如果这里缺某个能力、或某个 skill 只覆盖了你场景的一半，
请开 issue（bug 或 skill request）——issue 模板两种都有。外部请求也是决定
下一步建什么的最好信号。

## 如何使用

- **任何人：** `npx skills add wxxb789/hoa -g -s '*'`，或用
  [`index.zh-CN.md`](./index.zh-CN.md#安装) 里的命令单装某个 skill，或 fork 拿走对你有用的部件。
- **我：** 在这里写 skill → `npx skills add wxxb789/hoa -g -s <skill> -a '*'` → 落到每个 runtime；
  设置随 chezmoi 一起走。
