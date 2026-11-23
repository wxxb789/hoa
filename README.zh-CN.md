# hoa：Agent skills 与 goal-driven delivery

> [English](README.md) · **简体中文**

[![hoa CI 状态](https://github.com/wxxb789/hoa/actions/workflows/ci.yml/badge.svg)](https://github.com/wxxb789/hoa/actions/workflows/ci.yml)
[![许可证：MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

hoa 是一套面向 AI coding agent 的开放 skill 集合：可直接获取 Claude Code skills，
或用 [`npx skills`](https://github.com/vercel-labs/skills) 将它们安装到 Codex、OpenCode、
Pi 等 runtime，也可使用 [gdd 做 goal-driven delivery](docs/gdd.zh-CN.md)。

## 安装 agent skills

从[目录](index.zh-CN.md#编目)挑选 skill，然后使用[安装指南](index.zh-CN.md#安装)
生成的命令。以一个独立 skill 为例：

```sh
npx skills add wxxb789/hoa -g -s official-document-verification
```

`-g` 表示全局安装；省略则安装到当前项目。用 `-a <agent>` 选择 runtime。
如果 skill 依赖同级 skill，请用生成的命令把它们装到同一个 skills 根目录：
`npx skills` 不会自动安装依赖。想安装整个集合时，除非也需要 Hermes 专用 skill，
否则请用生成的**不使用 Hermes 时**命令。

源码树中每个 skill 位于 `skills/<category>/<name>/`；分类只是 checkout 的组织方式，
安装仍保持扁平的 `<skills-root>/<name>/` 布局，所有命令都按名称执行。

## 仓库内容

这是一个由独立部分组成的 monorepo，不需要把整套内容作为一个 harness 安装。
按需取用即可；单个 skill 可能有文档注明的依赖。

### Agent skill 目录

可安装的 [`skills/`](skills/) 目录面向需要可复用 agent 能力的用户，
覆盖软件开发、工作管理和自我管理。请从[生成的 skill 目录](index.zh-CN.md#编目)开始。

- **证据与验证：**审计主张、核查官方文档，以及验证委派工作或测量活动的结果。
- **Skill 生命周期：**`hoa-skill-*` 用于创建、评审、移植、整理和审计 skill，
  另有仅显式调用的实践复盘与仓库复盘。
- **写作：**撰写和修订可发布的文稿，包括以证据支撑的分析论证。
- **交付：**定义交付产物、检查软件包发布以及收尾项目阶段。
- **其他能力：**收敛 spec、整合研究，以及使用 Discord 等具体工具。
- **Hermes 运维（按需安装）：**`hermes-*` 只供 Hermes 运维人员使用，
  涵盖模型路由、Kanban、更新和 runtime 修复。

### gdd：Goal-driven delivery

面向需要交接一项书面、可机器检查的增量工作的仓库负责人，[`gdd`](skills/engineering/gdd/SKILL.md)
定义交付协议：目标、分阶段 agent run、由操作者运行的 gate，以及脚本化的合并检查。
单次外部 CLI 交接可用轻量委派，在独立验收后停止，无需阶段 ledger 或合并。
Agent route 单独安装。只有 OMP（`gdd-route-omp`）对模型可见；DeepSeek Harness、
Codex、Claude Code、Pi、OpenCode、Omo 和 GitHub Copilot route 均隐藏。
可选的 [Paseo GDD Observer](paseo-plugins/gdd-observer/README.md) 是只读插件，
不随 skill 安装。

请从 [gdd 交付与 transport 指南](docs/gdd.zh-CN.md)开始。

### 路由与 skill 必要性 eval

面向维护者和评估者：路由案例检查某个请求应选哪个 skill；必要性 runner 对比同一任务在
无 skill、精简指令和完整 skill 下的结果。CI 离线验证路由案例和已记录的 baseline；
真实模型对照实验另行运行。

请从[评估 runner 指南](evals/README.md)开始。

### 仓库工具与 CI gate

面向维护 hoa 的贡献者：[`scripts/`](scripts/) 生成索引，检查 vendored 文件，
并验证 metadata、链接、组合和 revision。[`rules/`](rules/) 定义仓库的常驻约束。
这些是仓库内部的工具和规则，不是已安装的 runtime。

请从 [CI gate 一览](docs/architecture.zh-CN.md#ci-跑什么)开始。

### 小型 role、模式、prompt 和 recipe 库

面向自行组装 agent 工作流的用户：[`agents/`](agents/) 存放一个 role 契约，
[`orchestration/`](orchestration/) 存放一个验证 gate 模式，[`prompts/`](prompts/)
存放任务模板，[`workflows/`](workflows/) 存放一个有限步骤的 recipe。
这是供手动复用的小型参考库，不是安装包。

请从[参考库指南](docs/library.zh-CN.md)开始。

### 外部参考子模块

面向研究上游 agent、skill 和 harness 项目的读者：[`ref/`](ref/README.zh-CN.md)
将外部仓库与值得学习的模式对应起来。所有子模块设为 `update = none`，任何克隆和安装都不会拉取它们；
每日 workflow 把指针推进到上游默认分支最新提交。只在研究时以 depth 1 检出。

### 复盘、目标与计划

面向想了解 hoa 如何演进的读者：[`reflections/`](reflections/) 存放对比、决策与复盘；
[`docs/goals/`](docs/goals/README.md) 和 [`docs/plans/`](docs/plans/) 记录工作契约和计划。
它们是工作与历史记录，不是 runtime 输入。

请从[笔记与项目历史](docs/contributing.zh-CN.md#笔记与项目历史)开始。

## 支持的 runtime

目录可用于 Claude Code、Codex、OpenCode、Pi、Kimi Code，或其他
[`npx skills` 支持的 runtime](https://github.com/vercel-labs/skills)。
各 skill 的先决条件和 runtime 相关行为请查阅其文档；Hermes 运维需要 Hermes，
gdd route 则有各自的 CLI 要求。运行 Python 脚本的 skill 需要 uv 和 Python 3.13 或更新版本。

## 许可证与项目链接

[MIT 许可证](LICENSE) · [变更日志](CHANGELOG.md) ·
[架构](docs/architecture.zh-CN.md) · [贡献与 skill 请求](docs/contributing.zh-CN.md)
