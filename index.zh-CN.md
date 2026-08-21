# Index — 按 area 与 target 索引

> [English](./index.md) · **简体中文**

仓库**按类型**组织（就是那些目录）。每个逻辑 artifact 在这里也占**一行**，用
`areas` 和 `targets` 打标签——因为一个 artifact 常同时服务多个 area 或 runtime，
而目录表达不了这一点。

## 标签词表

```text
areas:    software-development | work-management | self-management
targets:  runtime-agnostic | repo-only |
          claude-code | codex | opencode | hermes | pi | kimi-code
```

- 两个轴都**可多值**（逗号分隔）。
- **type** 从顶层目录推导——不要重复打标。
- `targets` = 这个 skill 用 `npx skills --agent` 装到哪些 runtime
  （`runtime-agnostic` = 任意；`repo-only` = 永不下发，如库 / 知识类）。
- 一行对应一个**逻辑** artifact（不为双语文件分别建行）。
- 暂不设 `status` 轴，等实验 / 废弃状态真的出现再加。

## 编目

目前手工维护；Phase 3 可从 per-artifact metadata 生成。

| Artifact | Type | Areas | Targets | Path | Notes |
|---|---|---|---|---|---|
| define-goal | skill | self-management, software-development, work-management | codex | `skills/define-goal/` | 把模糊意图转成可衡量目标，并通过 Codex goal tools 创建 |
| ghc-search | skill | software-development | runtime-agnostic | `skills/ghc-search/` | 经本机 `ghc-proxy` Responses API 做 web 与 X/Twitter 搜索；返回答案加去重来源 |
| hoa-agent-retrieve | skill | self-management, software-development | runtime-agnostic | `skills/hoa-agent-retrieve/` | 跨 agent 历史 → 带 coverage manifest、已去重的 Retrieval Bundle |
| hoa-introspect | skill | self-management, work-management | runtime-agnostic | `skills/hoa-introspect/` | 分层自省报告:确定性使用 facets（L1）+ 带证据的盲点审计（L2） |
| hoa-introspect-distill | skill | self-management, software-development | runtime-agnostic | `skills/hoa-introspect-distill/` | 把已批准的可复用工作提炼成 skill（或 opt-in 的 rule/config），经 runtime 原生 skill-creator 或内联产出 |
| my-ado-cppr | skill | software-development | runtime-agnostic | `skills/my-ado-cppr/` | commit → push → 在 Azure DevOps 或 GitHub 创建/更新 PR；probe/plan/apply 三段式，状态可 resume |

> 非 skill 类型（orchestration · agent · workflow · mcp · prompt · rule · eval · reflection）会在真实 artifact 落地时补充。
