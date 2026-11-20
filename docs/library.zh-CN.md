# 小型参考库

> [English](library.md) · **简体中文** · [仓库首页](../README.zh-CN.md)

这些是组装 agent 工作流时可手动改编的独立示例，不是可安装的 skill 或 runtime 设置。

| Surface | 入口 |
|---|---|
| Agent role 与权限 | [Skill scout](../agents/skill-scout.md) |
| Orchestration 模式 | [Typed verification gates](../orchestration/typed-verification-gates.md) |
| 一次性任务模板 | [Prompts](../prompts/) |
| 面向结果的有限步骤 recipe | [Adopt a pattern](../workflows/adopt-a-pattern.md) |

Harness engineering 将能力视为 model × harness：上下文、工具、控制循环、记忆、权限和
输出处理都很重要。hoa 提供可移植组件，不提供完整 harness。Orchestration 涵盖重试、
继续、终止、交接、fan-out/fan-in 和 best-of-N；循环只是 orchestration 的一种形式，
没有单独的参考库目录。归类方式见[仓库架构](architecture.zh-CN.md)。
