# 仓库架构

> [English](architecture.md) · **简体中文** · [仓库首页](../README.zh-CN.md)

[生成的索引](../index.zh-CN.md)是清单。本指南回答两个不同的问题：artifact 该放在哪里，
以及 skill 如何与其他 skill 组合。

## Surface：该放哪儿？

按 artifact 的主要消费接口分类，而不是按其内部实现。

| Surface | 属于这里 | 不属于这里 |
|---|---|---|
| [`skills/`](../skills/) | 通过 skill 或 command 名调用的完整能力，用 `npx skills` 安装 | 仅供其他 artifact 组装的 prompt 或 role |
| [`paseo-plugins/`](../paseo-plugins/) | 显式安装的可移植 Paseo 插件源码 | 机器专属的注册或 runtime 设置 |
| [`agents/`](../agents/) | 单 agent 的 role、权限与 I/O 契约 | Vendor 设置或多 agent 调度 |
| [`orchestration/`](../orchestration/) | 调度、交接、重试、继续、终止或聚合模式 | 具体、有限步骤的 recipe |
| [`prompts/`](../prompts/) | 一次性任务模板 | 常驻规则或 agent persona |
| [`rules/`](../rules/) | “必须”“禁止”等常驻约束 | 一次性任务说明 |
| [`workflows/`](../workflows/) | 达成结果的有限步骤 | 控制重试、继续运行或 agent 调度的机制 |
| [`evals/`](../evals/README.md) | 可重复评分的案例、fixture 和 rubric | 对结果的文章式分析 |
| [`reflections/`](../reflections/) | 观察、决策、对比及复盘 | Runtime 使用的 fixture、配置或数据集 |
| [`ref/`](../ref/README.zh-CN.md) | 供研究的外部子模块 | Runtime 代码或安装依赖 |
| [`scripts/`](../scripts/) | 目录生成、vendoring、验证及配置解析等共享工具 | 机器专属的设置和 hook |
| [`docs/goals/`](goals/README.md)、[`docs/plans/`](plans/) | 交付契约及规划记录 | Runtime 输入 |

Runtime 专用的 stop hook 属于 runtime 设置；通用的继续或终止模式归入 `orchestration/`。
以 skill 方式调用的多 agent 能力归入 `skills/`，即使内部用了 orchestration。
`npx skills` 只安装 skill；Paseo 插件需要手动安装。其他 surface 供参考或仓库维护。

## 组合层

每个 skill 在 `SKILL.md` 中声明 `metadata.kind`。这个角色与可见性无关：

| Kind | 角色 | 示例 |
|---|---|---|
| `entry` | 可直接从用户请求路由，无需 controller | `ghc-search`、`hoa-skill-create`、`spec-convergence` |
| `controller` | 为 chain 做路由，只产出 `chain-plan` | `gdd` |
| `stage` | 由 controller 调用的阶段，声明输入和输出 | 目前无示例 |
| `mechanism` | 由其他 skill 调用，不是路由目标 | `gdd-route-dsh` |

隐藏 skill 仍能手动调用。可见性、Codex sidecar 以及指向扁平同级 skill 的单层
Read 链接，见[组合规则](../rules/skill-composition.md)。

## 契约图

`uv run --script scripts/check_contract_graph.py --list` 打印基于 `kind`、
`consumes` 和 `produces` 构建的图。[注册表](../scripts/contract_graph_registry.yaml)
定义 `external:` 输入（如 `request`、`ci-result`）、可有多个生产者的
`shared:` 输出（目前没有），以及无需消费者的 `terminal:` 输出
（如 `chain-plan`、`spec`）。检查器拒绝：

| 规则 | 拒绝 |
|---|---|
| R1、R2、R7 | 未知或缺失的 kind，包括声明契约却未声明 kind |
| R3 | 没有 skill 生产者且未注册为 external 的输入 |
| R4、R10 | 触发案例的 `must_pick` 中出现 mechanism 或隐藏 skill |
| R5、R8 | controller 的唯一输出不是 `chain-plan`，或其 `SKILL.md` 超过 120 行 |
| R6 | 未注册为 shared 的输出有多个生产者 |
| R9 | 输出无消费者且未注册为附理由的 terminal；external 输出例外 |
| R11 | 可见的 mechanism 未被其他 skill 的 `SKILL.md` 或 references 点名或链接 |

## 目录 metadata 与标签

Skill 位于 `skills/<category>/<name>/SKILL.md`，属于五个仅存在于源码树的分类之一：
`engineering`、`productivity`、`research-writing`、`skill-authoring`、`hermes`；
安装后的包仍保持扁平 `<skills-root>/<name>/`。`npx skills` 也识别带点号的布局，
如 `skills/.curated/`、`skills/.experimental/` 和 `skills/.system/`。
Skill frontmatter 存放 `revision`、`kind`、可选的
`consumes` 和 `produces`，以及目录字段：

```yaml
metadata:
  revision: "1"
  kind: entry
  areas: "software-development,work-management"
  targets: "runtime-agnostic"
  summary: "One line for the English catalog"
  summary_zh: "中文目录用一行"
```

- `areas`：`software-development`、`work-management`、`self-management`。
- `targets`：`runtime-agnostic`、`repo-only`、`claude-code`、`codex`、
  `opencode`、`hermes`、`pi`、`kimi-code`。Runtime 名称表示预期的
  `npx skills --agent` 目标。

两类标签均可用逗号分隔多个值；artifact 类型由所属目录决定。
`agents/`、`orchestration/`、`prompts/`、`rules/` 和 `workflows/` 的参考库
artifact 在 `<name>.md` 或 `<name>/README.md` 中使用 `<!-- index: ... -->` 注释。
每个目录条目名称必须唯一，每个参考库目录必须有 artifact。说明取自 `summary` 和
`summary_zh`；英文 skill 说明缺失时使用 description 首句，中文说明缺失时使用英文。

编辑 metadata 后，运行 `uv run --script scripts/generate_index.py` 重新生成
[两个索引](../index.zh-CN.md)。不要手改索引或其他[生成文件](../rules/generated-means-generated.md)。

## CI 跑什么

[CI](../.github/workflows/ci.yml) 在 push 到 `main`、pull request 或手动触发时运行。
同一个 PR 有新 push 时取消上次运行。Main ruleset 要求通过 PR 和七项检查
（`test`，以及 Linux、macOS 和 Windows 各自的 `gdd-runner` 和 `gdd-observer`），
禁止 force-push 和删除，并允许管理员 bypass。仓库使用 squash merge、auto-merge 和合并后删除分支。
[每晚及手动运行的 Windows 生命周期压测](../.github/workflows/gdd-windows-stress.yml)
不是必需检查。没有 release job。

本地运行的 Python 最低版本为 3.13，脚本入口使用 uv 和 PEP 723 metadata。
CI 固定用 3.13，安装测试依赖与 uv，并在 job 内直接调用 Python。下表给出本地等效方式。

| Job 或 step | 本地命令或范围 | 检查内容 |
|---|---|---|
| Frontmatter | `uv run --script scripts/check_frontmatter.py` | Skill metadata 与布局（分类白名单、名称唯一）；可见 description 最长 350 字符，隐藏的最长 1024；可见性标记与 Codex sidecar 一致 |
| Contract graph | `uv run --script scripts/check_contract_graph.py` | R1 至 R11 |
| Skill links | `uv run --script scripts/check_skill_links.py` | 同级引用解析且不跨分类；skill 脚本命令使用 uv 和 PEP 723，内联 Python 使用 `--no-project` |
| Catalog drift | `uv run --script scripts/generate_index.py --check` | 两份索引与源 metadata 一致 |
| Vendoring drift | `uv run --script scripts/vendor_shared.py --check` | Vendored 文件与权威来源一致 |
| Revisions（PR） | `uv run --script scripts/version.py check-revisions` | 发生变更的 skill 目录提高各自的 revision；仅分类平移不计变更 |
| Ruff | `uvx ruff@0.17.5 check --config ruff.toml --force-exclude scripts evals skills` | `scripts/`、`evals/`、`skills/` 下的 Python 正确性与清理发现；Windows 上在现有终端直接运行 |
| pytest | `uv run --no-project --python 3.13 --with-requirements scripts/requirements.txt python -m pytest -n auto --dist load` | 收集 `scripts/`、`evals/` 和 `skills/` 中的 `test_*.py`；单项超时 120 秒 |
| 独立检查 | 分别用 `uv run --script` 运行：触发案例、define-goal fixture、Hermes 路由清单与 provider metadata、GDD verdict matrix 与 merge-gate mutation harness | 每个命名步骤以退出码为契约；具体路径见 workflow |
| `gdd-runner` | Runner、detach supervisor、dispatch、no-window、Paseo adapter 和 PR watcher 测试 | 跨平台原生行为，按平台跳过不适用案例；Linux 有私有 tmux 集成测试 |
| `gdd-observer` | 在 `paseo-plugins/gdd-observer` 中运行 `npm ci`、`npm run typecheck`、`npm test` | 三个平台上的插件 typecheck 和 Vitest |

收集范围内的新 `test_*.py` 文件无需注册。pytest 之外的独立检查需要单独的命名 CI 步骤。

## 路由 eval 的评分与局限

每个[路由案例](../evals/trigger-cases.json)都有 `id`、`request`、唯一的
`must_pick`（artifact 名称或 `none`），以及不能选择的 `distractors`。
[在线 judge](../evals/judge_trigger_evals.py)为每个案例使用新上下文：

1. 用索引生成器的 `collect()` 构建列表：给出可见 skill 的名称、类型和完整
   frontmatter description，以及参考库 artifact 的英文索引说明；省略隐藏 skill。
2. 发送列表和请求，不发送 `must_pick` 或 `distractors`。
3. 只有去掉首尾空白后与 `must_pick` 完全相同才通过。其他回复保留为 pick；
   transport 或 endpoint 错误只导致该案例失败。

```sh
uv run --script evals/judge_trigger_evals.py --json \
  --base-url <openai-compatible-base> --model <judge-model> --effort low
```

配置按 CLI flag、环境变量、`$XDG_CONFIG_HOME/evals/config.yaml`
（回退到 `~/.config/evals/config.yaml`）、默认值的次序解析。键为 `base_url`、
`model`、`effort` 和可选的 `api_key`，环境变量为 `EVALS_BASE_URL`、
`EVALS_MODEL`、`EVALS_EFFORT` 和 `EVALS_API_KEY`。Endpoint 和 model 必填
（缺失时退出码为 2）；effort 默认为 `low`，作为 OpenAI 兼容的
`POST /chat/completions` 的 `reasoning_effort` 字段发送。

`--record` 只接受完整运行；替换 baseline 需要 `--force`。
[Baseline](../evals/baseline.json)记录案例数量、model、effort、endpoint host、
时间戳、总计和各案例结果。Transport 错误、或 pick 既不在目录内也不是 `none`，
会阻止记录（退出码为 2）；合法但错误的 pick 作为失败记录。
[离线 gate](../evals/run_trigger_evals.py)检查案例 ID、允许的 pick、重算的通过标记和总计；
没有 baseline 也能验证案例。CI 从不调用在线 judge。

这衡量特定 judge、prompt 和 effort 对精选案例的区分能力，不能证明真实场景的路由质量
或跨模型一致性。结果应保留 model、effort、endpoint 和日期。若要评估任务结果而非路由，
请用独立的 [skill 必要性 runner](../evals/README.md#run-a-necessity-comparison)：
强制激活用加载证据验证内容；自然激活检查 skill 在正常发现机制下是否有益。
无 skill 和精简指令是对照组。
