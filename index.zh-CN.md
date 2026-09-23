# Index — 按 area 与 target 索引

> [English](./index.md) · **简体中文**

仓库**按类型**组织（就是那些目录）。每个逻辑 artifact 在这里也占**一行**，用
`areas` 和 `targets` 打标签——因为一个 artifact 常同时服务多个 area 或 runtime，
而目录表达不了这一点。

> 由 `python scripts/generate_index.py` 生成——目录表不要手改；改每个 skill 里的
> `<!-- index: ... -->` 注释即可。

## 标签词表

```text
areas:    software-development | work-management | self-management
targets:  runtime-agnostic | repo-only |
          claude-code | codex | opencode | hermes | pi | kimi-code
```

- 两个轴都**可多值**（逗号分隔）。
- **type** 从顶层目录推导——不要重复打标。
- 一行对应一个**逻辑** artifact（不为双语文件分别建行）。
- 暂不设 `status` 轴，等实验 / 废弃状态真的出现再加。

## 编目

| Artifact | Type | Areas | Targets | Path | Notes |
|---|---|---|---|---|---|
| define-goal | skill | self-management,software-development,work-management | runtime-agnostic | `skills/define-goal/` | 把意图定义为一个完整、可验证的目标或最小充分目标集，不制定实现方案 |
| ghc-search | skill | software-development | runtime-agnostic | `skills/ghc-search/` | 经本机 `ghc-proxy` Responses API 做 web 与 X/Twitter 搜索；返回答案加去重来源 |
| git-worktree-workflow | skill | software-development,work-management | runtime-agnostic | `skills/git-worktree-workflow/` | 用隔离的 worktree 在同一仓库并行运行多个 agent CLI；随附 `gitwt` 助手 |
| hoa-agent-retrieve | skill | self-management,software-development | runtime-agnostic | `skills/hoa-agent-retrieve/` | 跨 agent 历史 → 带 coverage manifest、已去重的 Retrieval Bundle |
| hoa-introspect | skill | self-management,work-management | runtime-agnostic | `skills/hoa-introspect/` | 分层自省报告：确定性使用 facets（L1）+ 带证据的盲点审计（L2） |
| hoa-introspect-distill | skill | self-management,software-development | runtime-agnostic | `skills/hoa-introspect-distill/` | 把已批准的可复用工作提炼成 skill（或 opt-in 的 rule/config），经 runtime 原生 skill-creator 或内联产出 |
| my-ado-cppr | skill | software-development | runtime-agnostic | `skills/my-ado-cppr/` | commit → push → 在 Azure DevOps 或 GitHub 创建/更新 PR；probe/plan/apply 三段式，状态可 resume |
| skill-scout | agent | software-development,work-management | repo-only | `agents/skill-scout.md` | 写新 skill 前先在本地/marketplace/上游搜索已有实现；只报告，不代写 |
| ghc-proxy | mcp | software-development | repo-only | `mcps/ghc-proxy.md` | 本地 ghc-proxy 搜索服务的可移植定义；注册留在 chezmoi |
| typed-verification-gates | orchestration | software-development | repo-only | `orchestration/typed-verification-gates.md` | 循环每次迭代止于一道事先定型的验证门：programmatic / judge / human |
| fresh-context-grader | prompt | software-development,work-management | repo-only | `prompts/fresh-context-grader.md` | 一次性评审 prompt：用先于回答写好的 rubric 在全新上下文里评分 |
| generated-means-generated | rule | software-development,work-management,self-management | repo-only | `rules/generated-means-generated.md` | 生成文件绝不手改；再生成随同一提交，漂移即 CI 失败 |
| adopt-a-pattern | workflow | software-development | repo-only | `workflows/adopt-a-pattern.md` | 把 ref 地图里的 what-to-steal 笔记变成落地、归类、带署名 artifact 的有限步骤 |

> reflections 与 eval 结果属于文章 / 知识类，不在此索引。
