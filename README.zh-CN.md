# hoa — Hall of Armor（战甲陈列室）

> [English](./README.md) · **简体中文**

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
├── index.md · index.zh-CN.md   # 全部 artifact，按 area + target 打标签
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
└── scripts/       # 仓库自身的 validation / index 工具
```

`skills/` 遵循 `npx skills` 的布局：`skills/<name>/SKILL.md`（扁平）或
`skills/<category>/<name>/SKILL.md`（catalog）；`skills/.curated/`、
`skills/.experimental/`、`skills/.system/` 也会被识别。

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

## 标签

area 与 target 作为标签记录在 [`index.md`](./index.md) 里，而不是建目录（一个
artifact 常同时服务多个）：

- `areas`：`software-development` · `work-management` · `self-management`
- `targets`：`runtime-agnostic` · `repo-only` · `claude-code` · `codex` ·
  `opencode` · `hermes` · `pi` · `kimi-code`（即这个 skill 面向的
  `npx skills --agent`）

type 从目录推导。两个轴都可多值。

## 路线图

- **Phase 1：** 骨架 + 定义 + 按 area/target 打标签的 index（taxonomy 已经 Oracle
  压力测试）。✓
- **Phase 2：** skills-first 下发——`skills/` 走 `npx skills`，设置走 chezmoi；
  去掉 `runtimes/`。✓
- **Phase 3：** 在 `skills/` 里长出真实 skill；从 per-artifact metadata 生成
  `index.md`；建 `evals/` + `reflections/`。

## 如何使用

- **任何人：** `npx skills add wxxb789/hoa` 装上这些 skill，或 fork 拿走对你有用的
  部件。
- **我：** 在这里写 skill → `npx skills add wxxb789/hoa -g` → 落到每个 runtime；
  设置随 chezmoi 一起走。
