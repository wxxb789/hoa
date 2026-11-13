# Index — 按 area 与 target 索引

> [English](./index.md) · **简体中文**

仓库**按类型**组织（就是那些目录）。每个逻辑 artifact 在这里也占**一行**，用
`areas` 和 `targets` 打标签——因为一个 artifact 常同时服务多个 area 或 runtime，
而目录表达不了这一点。

> 由 `python scripts/generate_index.py` 生成——目录表不要手改。skill 请修改 YAML
> frontmatter 中的 `metadata.areas`、`metadata.targets`；库文件仍修改
> `<!-- index: ... -->` 注释。

## 标签词表

```text
areas:    software-development | work-management | self-management
targets:  runtime-agnostic | repo-only |
          claude-code | codex | opencode | hermes | pi | kimi-code
```

- 两个轴都**可多值**（逗号分隔）；skill 中的值是 YAML 字符串，不是列表。
- **type** 从顶层目录推导——不要重复打标。
- 一行对应一个**逻辑** artifact（不为双语文件分别建行）。
- 暂不设 `status` 轴，等实验 / 废弃状态真的出现再加。

## 编目

| Artifact | Type | Areas | Targets | Path | Notes |
|---|---|---|---|---|---|
| agent-harness-settings-parity | skill | software-development | runtime-agnostic | `skills/agent-harness-settings-parity/` | 让同一条策略在每个 coding harness 上生效，尽管配置文件、键名与单位各不相同 |
| agent-operating-contract-evolution | skill | software-development,work-management,self-management | runtime-agnostic | `skills/agent-operating-contract-evolution/` | 按分层演进 agent 身份文件与操作协议：覆盖标记、行为评测、加载范围探测 |
| ai-coding-agent-delegation | skill | software-development,work-management | runtime-agnostic | `skills/ai-coding-agent-delegation/` | 把定界编码任务交给隔离 worktree 中的外部 agent CLI，再自行核验 diff、测试与全部验收声明 |
| arch-improvement-plan | skill | software-development | runtime-agnostic | `skills/arch-improvement-plan/` | 增量架构改进：划边界、给迁移计划、产出 PRD 与任务 |
| contract-bound-deliverables | skill | work-management,software-development | runtime-agnostic | `skills/contract-bound-deliverables/` | 满足可度量契约：冻结证据包、并行起草、按字数装配、用契约自身的度量脚本验收 |
| cross-agent-repair-routing | skill | software-development,work-management | runtime-agnostic | `skills/cross-agent-repair-routing/` | 把他人写入面内的缺陷送修：权限地图、复现、一次定界的落地决策 |
| define-goal | skill | self-management,software-development,work-management | runtime-agnostic | `skills/define-goal/` | 把雄心转化为编号 goal 文件，近期清晰、远期可细化，不制定实现步骤 |
| delegated-work-acceptance | skill | work-management,software-development | runtime-agnostic | `skills/delegated-work-acceptance/` | 验收被委派的交付：核对 artifact、重算关键数字、检查写入边界 |
| design-an-interface | skill | software-development | runtime-agnostic | `skills/design-an-interface/` | 设计软件接口或公开 API：签名草稿、OpenAPI 片段、用法示例 |
| discord-rich-message | skill | software-development,work-management | runtime-agnostic | `skills/discord-rich-message/` | 在平台限制内发送结构化 Discord 消息：Components V2、等宽对齐表格、附件兜底 |
| dotnet-repo-workflow | skill | software-development | runtime-agnostic | `skills/dotnet-repo-workflow/` | 走仓库自带 .NET gate 而非手搓 `dotnet test`；lock 文件、Roslyn 编译陷阱、merge-ready 清单 |
| evidence-backed-analytical-writing | skill | work-management | runtime-agnostic | `skills/evidence-backed-analytical-writing/` | 中文分析报告：证据地图与「主张 → 证据 → 机制 → 局限」骨架；时效边界、状态阶梯、否定性结论 |
| evidence-boundary-discipline | skill | work-management | runtime-agnostic | `skills/evidence-boundary-discipline/` | 只陈述有日期的来源所能支持的事实：时态对齐日期、来源标签全链路一致、缺失不升级为不存在 |
| gdd | skill | software-development,work-management | runtime-agnostic | `skills/gdd/` | 目标契约 → agent 分阶段产出 → operator 验收 → 脚本化合并门禁 → 可续跑账本；随附 `gdd.py`、`delivery-state.py`、`pr-merge-check.py` |
| generated-runtime-repairs | skill | software-development,work-management | runtime-agnostic | `skills/generated-runtime-repairs/` | 修模板/生成器、验证暂存产物，再部署并回读线上运行时 |
| ghc-search | skill | software-development | runtime-agnostic | `skills/ghc-search/` | 经本机 `ghc-proxy` Responses API 做 web 与 X/Twitter 搜索；返回答案加去重来源 |
| git-auto-sync-pipelines | skill | software-development,work-management | runtime-agnostic | `skills/git-auto-sync-pipelines/` | 手改仓库的定时提交推送：固定门序、白名单与体积上限、暂存区密钥扫描、心跳与去重告警 |
| github-code-review | skill | software-development,work-management | runtime-agnostic | `skills/github-code-review/` | 评审 PR：读 diff，用 gh 或 REST 发行内评论 |
| github-repo-management | skill | software-development | runtime-agnostic | `skills/github-repo-management/` | 克隆、创建、fork 仓库；管理 remote 与 release |
| grounded-citations | skill | work-management,software-development | runtime-agnostic | `skills/grounded-citations/` | 脚本持有编号引用账本：检索即登记、逐句引用、机械渲染并可校验；随附 `sources.py` |
| harness-engineering | skill | software-development | runtime-agnostic | `skills/harness-engineering/` | 审计与重构 harness 脚本：自包含、检查绑定 owner 决策、纯函数检查加薄 runner、净减行数 |
| hermes-context-file-loading | skill | software-development | hermes | `skills/hermes-context-file-loading/` | Hermes 指令文件各自从何处加载、哪个项目文件生效，以及规则该放进哪个 prompt 层 |
| hermes-models | skill | software-development | hermes | `skills/hermes-models/` | 配置 Hermes provider、传输与路由；用实时信号证明路由，而非 `config get` |
| hermes-updates | skill | software-development | hermes | `skills/hermes-updates/` | 升级运行中的 Hermes 并诊断漂移：快照、官方更新器、更新后检查、故障索引 |
| hoa-introspect | skill | self-management,work-management | runtime-agnostic | `skills/hoa-introspect/` | 分层自省报告：确定性使用 facets（L1）+ 带证据的盲点审计（L2） |
| hoa-introspect-distill | skill | self-management,software-development | runtime-agnostic | `skills/hoa-introspect-distill/` | 评估给定的重复工作发现为候选；逐项批准后才创建资产 |
| hoa-skill-review | skill | software-development,work-management,self-management | runtime-agnostic | `skills/hoa-skill-review/` | 依据消费者证据审计 skill 行为与修改，不改动被审查对象 |
| hoa-skill-work | skill | software-development,work-management,self-management | runtime-agnostic | `skills/hoa-skill-work/` | 直接创建或演进已定义的 skill，并按风险聚焦验证 |
| html-artifact | skill | software-development,work-management | runtime-agnostic | `skills/html-artifact/` | 零依赖单文件 HTML：解释文、计划、报告、图表与一次性编辑器，统一 house style |
| jupyter-live-kernel | skill | software-development | runtime-agnostic | `skills/jupyter-live-kernel/` | 在活的 Jupyter kernel 里迭代 Python，而不是反复重启脚本 |
| kanban-workflows | skill | work-management,software-development | runtime-agnostic | `skills/kanban-workflows/` | 多卡片看板工作：拆解、并行派发、评审门禁、卡住任务恢复 |
| m365-copilot-cdp | skill | software-development,work-management | runtime-agnostic | `skills/m365-copilot-cdp/` | 通过 CDP 操作桌面 Copilot Chat 与 Code，选择模型并读取回复 |
| measurement-campaign-evidence | skill | software-development,work-management | runtime-agnostic | `skills/measurement-campaign-evidence/` | 测量运动：先钉候选身份、串行跑、一致报告集，不让基线伪造延迟对比 |
| microsoft-office | skill | work-management,software-development | runtime-agnostic | `skills/microsoft-office/` | 用 Python CLI 离线创建、读取、编辑与套用 Word、PowerPoint、Excel 文件模板 |
| notes-to-prd | skill | work-management | runtime-agnostic | `skills/notes-to-prd/` | 把笔记或想法转成结构化 PRD 草稿 |
| ocr-and-documents | skill | work-management | runtime-agnostic | `skills/ocr-and-documents/` | 用 pymupdf 或 marker-pdf 从 PDF 与扫描件里抽文本 |
| omp-headless-orchestration | skill | software-development,work-management | pi | `skills/omp-headless-orchestration/` | 脱离会话的 tmux 启动器跑 `omp -p` 长任务；轮询完成、按 session id 恢复 |
| ops-claim-verification | skill | software-development,work-management | runtime-agnostic | `skills/ops-claim-verification/` | 把定时任务、修复或部署的说法变成证据：找准记录面、区分手动与调度运行、审查审计者 |
| package-release-verification | skill | software-development | runtime-agnostic | `skills/package-release-verification/` | 发版：先补 changelog、同一 commit 的门禁、分派、按版本号核 registry、单独获批的清理 |
| plan-to-issues | skill | work-management | runtime-agnostic | `skills/plan-to-issues/` | 把 PRD 或计划拆成 issue 级任务：标题、正文、标签 |
| project-phase-closeout | skill | software-development,work-management | runtime-agnostic | `skills/project-phase-closeout/` | 清点任务面，对账记录/索引/发布/生产四层，输出带唯一决策点的收尾清单 |
| report-claim-audit | skill | work-management,software-development | runtime-agnostic | `skills/report-claim-audit/` | 从各自的权威 artifact 重算每条报告声明、对账交付集合，并给待决事项定价 |
| skill-library-curation | skill | software-development,self-management | runtime-agnostic | `skills/skill-library-curation/` | 按证据审查技能库：清点、重叠分组、安装来源、上游新鲜度；建议不改动状态 |
| skill-porting-and-publishing | skill | software-development,work-management | runtime-agnostic | `skills/skill-porting-and-publishing/` | 把私有 skill 解耦到可发布仓库：确定权威副本、五轴改造、配置解析、目录与 CI 校验、走分支与 PR 发布 |
| spec-convergence | skill | software-development | runtime-agnostic | `skills/spec-convergence/` | 把模糊需求收敛为已确认 spec：每轮一个根问题、每轮问题数有上限、每问附事实、写前显式确认共同理解 |
| structural-validity-gates | skill | software-development | runtime-agnostic | `skills/structural-validity-gates/` | 两面完整性门禁：拒掉坏的，接受格式合法的一切；上线前两侧都要探针 |
| subagent-driven-development | skill | software-development,work-management | runtime-agnostic | `skills/subagent-driven-development/` | 按计划逐任务派发全新 subagent，并做两阶段评审：先规格符合，再代码质量 |
| systematic-debugging | skill | software-development | runtime-agnostic | `skills/systematic-debugging/` | 先定位根因再修：紧致可复现的反馈环、边界证据、可证伪假设排序，然后一次只改一处 |
| teams-cdp | skill | work-management | runtime-agnostic | `skills/teams-cdp/` | 通过本机桌面 CDP 向明确的 Teams 联系人或现有群组发送消息 |
| tmux-agent-control | skill | software-development,work-management | runtime-agnostic | `skills/tmux-agent-control/` | 在 tmux 中驱动运行中的 TUI agent：定位 pane、证明空闲、一次发出完整指令 |
| writing | skill | work-management,self-management | runtime-agnostic | `skills/writing/` | 一套内容优先的共同层加分渠道契约：博客、论文、X、Reddit、小红书、公众号、教程、changelog；附可量化的 AI 味自查 |
| writing-plans | skill | software-development,work-management | runtime-agnostic | `skills/writing-plans/` | 写出零上下文 agent 也能执行的实现计划：小步任务、精确路径、完整代码、带预期输出的命令 |
| skill-scout | agent | software-development,work-management | repo-only | `agents/skill-scout.md` | 按请求先搜索已有 skill，再决定是否编写；只报告，不代写 |
| ghc-proxy | mcp | software-development | repo-only | `mcps/ghc-proxy.md` | 本地 ghc-proxy 搜索服务的可移植定义；注册留在 chezmoi |
| typed-verification-gates | orchestration | software-development | repo-only | `orchestration/typed-verification-gates.md` | 循环每次迭代止于一道事先定型的验证门：programmatic / judge / human |
| ado-commit-push-pr | prompt | software-development | repo-only | `prompts/ado-commit-push-pr.md` | 一次性 commit → push → PR 请求模板（Azure DevOps 或 GitHub），附提交约定与 az/gh 易错点 |
| cross-agent-history-retrieval | prompt | self-management,software-development | repo-only | `prompts/cross-agent-history-retrieval.md` | 一次性检索/导出本机各 agent 历史，按来源报告覆盖、去重并打码 |
| fresh-context-grader | prompt | software-development,work-management | repo-only | `prompts/fresh-context-grader.md` | 一次性评审 prompt：用先于回答写好的 rubric 在全新上下文里评分 |
| parallel-agent-worktrees | prompt | software-development,work-management | repo-only | `prompts/parallel-agent-worktrees.md` | 一次性为每个 agent CLI 建独立 git worktree：布局、env/端口隔离、fail-closed 初始化、安全清理 |
| generalization-rubric | rule | software-development,work-management | repo-only | `rules/generalization-rubric.md` | 技能进入公开目录的唯一标准：陌生人在全新机器上能跑通——六道门槛、硬性失败项、回灌不变量 |
| generated-means-generated | rule | software-development,work-management,self-management | repo-only | `rules/generated-means-generated.md` | 生成文件绝不手改；再生成随同一提交，漂移即 CI 失败 |
| adopt-a-pattern | workflow | software-development | repo-only | `workflows/adopt-a-pattern.md` | 把 ref 地图里的 what-to-steal 笔记变成落地、归类、带署名 artifact 的有限步骤 |

> reflections 与 eval 结果属于文章 / 知识类，不在此索引。
