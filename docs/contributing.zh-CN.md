# 贡献与 skill 开发

> [English](contributing.md) · **简体中文** · [仓库首页](../README.zh-CN.md)

## 克隆仓库

```sh
git clone https://github.com/wxxb789/hoa
```

使用 skill 和运行仓库测试只需普通克隆。[外部参考地图](../ref/README.zh-CN.md)供研究
上游项目、复用模式并保留归属。所有子模块设为 `update = none`，普通克隆和
`npx skills add` 都会跳过它们。按需以 depth 1 获取（省略路径则获取全部）：

```sh
git submodule update --init --checkout --depth 1 ref/<name>
```

[ref 同步 workflow](../.github/workflows/ref-sync.yml) 每日把所有指针推进到上游
默认分支最新提交，直接推送到 `main`。
[Dependabot 配置](../.github/dependabot.yml)按组每周更新 Actions 和 GDD Observer 的
npm 依赖。仓库已启用 Dependabot alerts 和 security updates。

## 安装、更新和开发 skill

仓库没有自带安装器。请用生成的[安装一节](../index.zh-CN.md#安装)：有同级依赖的
skill 会有一条将整个闭包装入同一个 skills 根目录的命令。没有此类安装行的 skill
没有同级依赖。除非要运维 Hermes，否则请用**不使用 Hermes 时**；非 Hermes skill
不链接 Hermes 家族。源码树中每个 skill 位于 `skills/<category>/<name>/`；分类只属于
源码树——安装仍为扁平的 `<skills-root>/<name>/`，所有命令都按名称执行。
若要安装全部 skill、列举或更新：

```sh
npx skills add wxxb789/hoa -g -s '*' -y
npx skills add wxxb789/hoa --list
npx skills update -g -y
```

- 全局安装到选定 runtime 的 skills 根目录（例如 `~/.claude/skills`、
  `~/.config/opencode/skills` 或 `~/.agents/skills`）。省略 `-g` 可安装到当前项目。
  `-a <agent>` 指定 runtime，`-a '*'` 选择所有 agent。默认用链接指向同一权威副本；
  不能或不想用链接时可用 `--copy`。
- 本地 checkout 使用 `npx skills add <local-checkout> -g -s <skill> -y`，
  并按生成的命令带上同级依赖。修改后重跑 `add`：`update` 会跳过本地来源。
  改动进入默认分支后，从 `wxxb789/hoa` 重新安装，恢复上游跟踪。
- 改名或移除后，`update` 会警告，但会保留旧名且不安装新名。先检查
  `npx skills ls -g`，再使用生成的移除命令，去掉从其他来源安装的同名 skill。
  移除按名称匹配，未安装的名称不受影响。复装时使用当前生成的命令，不用旧副本。
  替代项记录在[退役 skill 注册表](../scripts/retired_skills.toml)。
- 用 [hoa-skill-set-audit](../skills/skill-authoring/hoa-skill-set-audit/SKILL.md) 诊断同级依赖闭包
  缺失或分裂、重复和遮蔽。根目录与链接细节见[跨平台规则](../rules/cross-platform-skills.md)。

对于 Hermes 模型路由，用父 skill 生成的命令一起安装
[hermes-models](../skills/hermes/hermes-models/SKILL.md) 和
[hermes-models-cutover](../skills/hermes/hermes-models-cutover/SKILL.md)。
子 skill 支持可回滚的全量切换和同 provider 的 ID 替换，并逐一提供受影响运行面的在线证据。
Hermes 不识别 `disable-model-invocation`，仍会列出子 skill。
在其他 runtime 手动调用时，按[各 host 的调用语法](../rules/skill-composition.md#visibility)操作。

## 选择 skill 维护流程

| 需求 | Skill | 结果 |
|---|---|---|
| 评审行为或拟议改动 | [hoa-skill-review](../skills/skill-authoring/hoa-skill-review/SKILL.md) | 带证据的发现，不修改被评审的 skill |
| 创建、演进或组合一项已定义的能力 | [hoa-skill-create](../skills/skill-authoring/hoa-skill-create/SKILL.md) | 改动、验证结果及未验证路径 |
| 复盘跨仓库和 agent 会话的实践 | [hoa-practice-retro](../skills/skill-authoring/hoa-practice-retro/SKILL.md)（仅显式调用） | 带证据的发现和重复工作候选，不自动创建 |
| 审查单个仓库的实践与运作机制 | [hoa-repo-reckoning](../skills/skill-authoring/hoa-repo-reckoning/SKILL.md)（仅显式调用的提示词） | 自由格式报告，按严重程度排列发现并附证据 |
| 审计会话实际可用的 skill 集合 | [hoa-skill-set-audit](../skills/skill-authoring/hoa-skill-set-audit/SKILL.md)（仅显式调用） | 集合级发现和必要性结论，不做改动 |
| 根据近期工作推荐 skill | [hoa-skill-curate](../skills/skill-authoring/hoa-skill-curate/SKILL.md) | 带证据的建议，不做改动 |

先做聚焦的行为检查；覆盖范围、风险或证据冲突有需要时，再扩展到多个变体、model
或 runtime。复盘候选须经负责人逐项批准后才能创建；直接请求明确定义的 skill 不用走
该提名流程。见[公开目录准入标准](../rules/generalization-rubric.md)。

Claude Code 原生的 `plugin eval` 测试 plugin 形态的包；Anthropic 的 `skill-creator`
是独立的官方插件。早期 `define-goal` 评审使用了 CE 指南与会话内编写的 runner。
这些都不是 runtime-agnostic skill 的必要依赖。
[Claude Code 源码研究](../reflections/2026-09-25-claude-code-skill-source.md)区分了
各自的实现和证据边界。

## Revision 与双语政策

没有项目版本或发布包：`npx skills` 直接从 GitHub 默认分支安装。每个 skill 用
整数字符串 `metadata.revision` 记录自己的迭代；PR 改了哪个 skill 目录，就将其加一。
新名称（包括改名）从 `"1"` 开始，改名须登记到
[退役 skill 注册表](../scripts/retired_skills.toml)。纯分类平移不算变更：保留原 revision，
也不需要退役登记；平移并改动包内任何文件则必须加一。
运行 `uv run --script scripts/version.py check-revisions`。
[变更日志](../CHANGELOG.md)按日期编排，可选；早期条目保留历史项目和单 skill 版本。

对于双语文档，英文是权威版本；简体中文镜像在同一次 commit 更新，保持章节顺序、事实和
链接目标等效。技术术语和命令保持一致。[索引](../index.zh-CN.md)从一个来源生成两种语言。

## 笔记与项目历史

hoa 最初是个人使用但公开的可移植 agent 组件库：集中版本管理，避免副本分散；部署 skill；
并复盘哪些配置有效。名字取自 Tony Stark 的 *Hall of Armor*：为不同任务打造、比较和改进
装备的工坊。可以 fork 或按需复用。只跟踪模板和脱敏产物，不将凭证和个人数据放入 Git
（见[忽略规则](../.gitignore)），敏感信息也可放入 secret manager。

负责人的机器专属 provider、model、插件注册、runtime 设置文件和密钥模板由 chezmoi
管理，用 `chezmoi apply` 单独下发。hoa 不要求 chezmoi。除了 skill 目录和手动安装的
Paseo 插件，这里的内容供参考或仓库维护，不自动部署。

- 初始骨架与标签分类用 Oracle 做了压力测试。[Skills-first 改造](../reflections/2026-09-23-skills-first-split.md)
  拆开安装与设置，并移除了 `runtimes/`。随后加入目录生成、路由案例和书面复盘。
- [最早一批上游模式改编](../reflections/2026-09-23-first-steals.md)包括 ECC 的 skill scout
  和 looper 的 typed verification gates。[复盘](../reflections/)、
  [目标契约](goals/README.md)与[计划](plans/)是工作和历史记录，不是功能路线图。
- 每月运行一次 `hoa-practice-retro`，它只读取自身以往的运行记录。
  产物写入配置的私有审计状态目录，不提交到 Git。

## 请求一个 skill

如果缺少某个能力或只覆盖了一部分场景，请提交
[bug report 或 skill 请求](https://github.com/wxxb789/hoa/issues/new/choose)。
外部请求有助于安排后续工作优先级。
