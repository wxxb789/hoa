# Index — 按 area 与 target 索引

> [English](./index.md) · **简体中文**

仓库**按类型**组织（就是那些目录）。每个逻辑 artifact 在这里也占**一行**，用
`areas` 和 `targets` 打标签——因为一个 artifact 常同时服务多个 area 或 runtime，
而目录表达不了这一点。

> 由 `uv run scripts/generate_index.py` 生成——目录表不要手改。skill 请修改 YAML
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
| contract-bound-deliverables | skill | work-management,software-development | runtime-agnostic | `skills/contract-bound-deliverables/` | 满足可度量契约：冻结证据包、并行起草、按字数装配、用契约自身的度量脚本验收 |
| cross-agent-repair-routing | skill | software-development,work-management | runtime-agnostic | `skills/cross-agent-repair-routing/` | 把他人写入面内的缺陷送修：权限地图、复现、一次定界的落地决策 |
| define-goal | skill | self-management,software-development,work-management | runtime-agnostic | `skills/define-goal/` | 把雄心转化为编号 goal 文件，近期清晰、远期可细化，不制定实现步骤 |
| delegated-work-acceptance | skill | work-management,software-development | runtime-agnostic | `skills/delegated-work-acceptance/` | 验收被委派的交付：核对 artifact、重算关键数字、检查写入边界 |
| discord-rich-message | skill | software-development,work-management | runtime-agnostic | `skills/discord-rich-message/` | 在平台限制内发送结构化 Discord 消息：Components V2、等宽对齐表格、附件兜底 |
| dotnet-repo-workflow | skill | software-development | runtime-agnostic | `skills/dotnet-repo-workflow/` | 走仓库自带 .NET gate 而非手搓 `dotnet test`；lock 文件、Roslyn 编译陷阱、merge-ready 清单 |
| evidence-backed-analytical-writing | skill | work-management | runtime-agnostic | `skills/evidence-backed-analytical-writing/` | 中文分析报告：证据地图与「主张 → 证据 → 机制 → 局限」骨架；时效边界、状态阶梯、否定性结论 |
| evidence-boundary-discipline | skill | work-management | runtime-agnostic | `skills/evidence-boundary-discipline/` | 只陈述有日期的来源所能支持的事实：时态对齐日期、来源标签全链路一致、缺失不升级为不存在 |
| gdd | skill | software-development,work-management | runtime-agnostic | `skills/gdd/` | 目标契约 → agent 分阶段产出 → operator 验收 → 脚本化合并门禁 → 可续跑账本；随附 `gdd.py`、`delivery-state.py`、`pr-merge-check.py` |
| gdd-route-cc | skill | software-development,work-management | runtime-agnostic | `skills/gdd-route-cc/` | Claude Code stream-JSON 路由，支持会话恢复和原生 JSON schema |
| gdd-route-codex | skill | software-development,work-management | runtime-agnostic | `skills/gdd-route-codex/` | Codex exec 与 resume 路由，支持原生 JSON schema，默认关闭集成 |
| gdd-route-dsh | skill | software-development,work-management | runtime-agnostic | `skills/gdd-route-dsh/` | 把 GDD 阶段派发给 dsh headless 并监督：会话/worktree 规则、完成判定、恢复、harness 陷阱（需要 skill `gdd`） |
| gdd-route-omp | skill | software-development,work-management | pi | `skills/gdd-route-omp/` | 脱离会话的 runner 跑 `omp -p` 长任务；轮询完成、按 session id 恢复（需要 skill `gdd`） |
| gdd-route-opencode | skill | software-development,work-management | runtime-agnostic | `skills/gdd-route-opencode/` | OpenCode 独立服务器路由，支持会话恢复和模型变体选择 |
| gdd-route-pi | skill | software-development,work-management | runtime-agnostic | `skills/gdd-route-pi/` | Pi stdin 与 JSON 事件路由，支持会话恢复 |
| ghc-decisions | skill | software-development,work-management | runtime-agnostic | `skills/ghc-decisions/` | 按需启用（opt-in）的 `/v1/decisions` 与 `/v1/chat/completions` 结构化 Rubric 分类器，内置 9 大日常预设 |
| ghc-search | skill | software-development | runtime-agnostic | `skills/ghc-search/` | 经本机 `ghc-proxy` Responses API 做 web 与 X/Twitter 搜索；返回答案加去重来源 |
| git-auto-sync-pipelines | skill | software-development,work-management | runtime-agnostic | `skills/git-auto-sync-pipelines/` | 手改仓库的定时提交推送：固定门序、白名单与体积上限、暂存区密钥扫描、心跳与去重告警 |
| harness-engineering | skill | software-development | runtime-agnostic | `skills/harness-engineering/` | 重构与设计 harness 脚本：自包含、检查绑定 owner 决策、纯函数检查加薄 runner、净减行数 |
| hermes-context-file-loading | skill | software-development | hermes | `skills/hermes-context-file-loading/` | Hermes 指令文件各自从何处加载、哪个项目文件生效，以及规则该放进哪个 prompt 层 |
| hermes-kanban | skill | work-management,software-development | hermes | `skills/hermes-kanban/` | 多卡片看板工作：拆解、并行派发、评审门禁、卡住任务恢复 |
| hermes-models | skill | software-development | hermes | `skills/hermes-models/` | 配置 Hermes provider、传输与路由；用实时信号证明路由，而非 `config get` |
| hermes-models-cutover | skill | software-development | hermes | `skills/hermes-models-cutover/` | 跨 Hermes home 与 harness 切换供应商路由，实时验证并保留回滚 |
| hermes-ops-claim-verification | skill | software-development,work-management | hermes | `skills/hermes-ops-claim-verification/` | 验证 Hermes 定时任务、修复或部署的说法：找准记录面、区分手动与调度运行、审查审计者 |
| hermes-runtime-repairs | skill | software-development,work-management | hermes | `skills/hermes-runtime-repairs/` | 修模板/生成器、验证暂存产物，再部署并回读线上运行时 |
| hermes-updates | skill | software-development | hermes | `skills/hermes-updates/` | 升级运行中的 Hermes 并诊断漂移：快照、官方更新器、更新后检查、故障索引 |
| hoa-practice-retro | skill | self-management,work-management | runtime-agnostic | `skills/hoa-practice-retro/` | 定期复盘负责人跨仓库、会话与记忆的工程实践：应停止的习惯、未执行的决定、未知的未知，每条都有两个独立来源 |
| hoa-repo-reckoning | skill | software-development,work-management | runtime-agnostic | `skills/hoa-repo-reckoning/` | 仅显式调用的只读仓库审查提示词：哪些事该停止，哪些未知会改变工作 |
| hoa-skill-create | skill | software-development,work-management,self-management | runtime-agnostic | `skills/hoa-skill-create/` | 直接创建、演进或组合已定义的 skill，并按风险聚焦验证 |
| hoa-skill-curate | skill | software-development,self-management | runtime-agnostic | `skills/hoa-skill-curate/` | 追溯已安装技能的来源与上游新鲜度，执行上游退役规则，仅在所有者确认后变更技能库 |
| hoa-skill-port | skill | software-development,work-management | runtime-agnostic | `skills/hoa-skill-port/` | 把私有 skill 解耦到可发布仓库：确定权威副本、五轴改造、配置解析、目录与 CI 校验、走分支与 PR 发布 |
| hoa-skill-review | skill | software-development,work-management,self-management | runtime-agnostic | `skills/hoa-skill-review/` | 依据消费者证据审计 skill 行为与修改，不改动被审查对象 |
| hoa-skill-set-audit | skill | software-development,self-management | runtime-agnostic | `skills/hoa-skill-set-audit/` | 审计会话实际提供的整套技能：单项质量、重叠、遮蔽、指令冲突、同名漂移、可见性、../ 闭包、清单预算；只出报告 |
| measurement-campaign-evidence | skill | software-development,work-management | runtime-agnostic | `skills/measurement-campaign-evidence/` | 测量运动：先钉候选身份、串行跑、一致报告集，不让基线伪造延迟对比 |
| official-document-verification | skill | work-management | runtime-agnostic | `skills/official-document-verification/` | 用文档的确切版本核验结论，含只能用真浏览器取到的被封来源 |
| package-release-verification | skill | software-development | runtime-agnostic | `skills/package-release-verification/` | 发版：先补 changelog、同一 commit 的门禁、分派、按版本号核 registry、单独获批的清理 |
| project-phase-closeout | skill | software-development,work-management | runtime-agnostic | `skills/project-phase-closeout/` | 清点任务面，对账记录/索引/发布/生产四层，输出带唯一决策点的收尾清单 |
| report-claim-audit | skill | work-management,software-development | runtime-agnostic | `skills/report-claim-audit/` | 从各自的权威 artifact 重算每条报告声明、对账交付集合，并给待决事项定价 |
| research-stream-consolidation | skill | work-management | runtime-agnostic | `skills/research-stream-consolidation/` | 把重复的研究流并成一个项目，并修好绑定旧路径的记录 |
| review-revision-candidates | skill | work-management | runtime-agnostic | `skills/review-revision-candidates/` | 被驳回候选的返修轮：编号清单就是全部变更集，交的是字节不是辩解 |
| spec-convergence | skill | software-development | runtime-agnostic | `skills/spec-convergence/` | 把模糊需求收敛为已确认 spec：每轮一个根问题、每轮问题数有上限、每问附事实、写前显式确认共同理解 |
| structural-validity-gates | skill | software-development | runtime-agnostic | `skills/structural-validity-gates/` | 两面完整性门禁：拒掉坏的，接受格式合法的一切；上线前两侧都要探针 |
| tmux-agent-control | skill | software-development,work-management | runtime-agnostic | `skills/tmux-agent-control/` | 在 tmux 中驱动运行中的 TUI agent：定位 pane、证明空闲、一次发出完整指令 |
| writing | skill | work-management,self-management | runtime-agnostic | `skills/writing/` | 一套内容优先的共同层加分渠道契约：博客、论文、X、Reddit、小红书、公众号、教程、changelog；附可量化的 AI 味自查 |
| skill-scout | agent | software-development,work-management | repo-only | `agents/skill-scout.md` | 按请求先搜索已有 skill，再决定是否编写；只报告，不代写 |
| typed-verification-gates | orchestration | software-development | repo-only | `orchestration/typed-verification-gates.md` | 循环每次迭代止于一道事先定型的验证门：programmatic / judge / human |
| ado-commit-push-pr | prompt | software-development | repo-only | `prompts/ado-commit-push-pr.md` | 一次性 commit → push → PR 请求模板（Azure DevOps 或 GitHub），附提交约定与 az/gh 易错点 |
| cross-agent-history-retrieval | prompt | self-management,software-development | repo-only | `prompts/cross-agent-history-retrieval.md` | 一次性检索/导出本机各 agent 历史，按来源报告覆盖、去重并打码 |
| fresh-context-grader | prompt | software-development,work-management | repo-only | `prompts/fresh-context-grader.md` | 一次性评审 prompt：用先于回答写好的 rubric 在全新上下文里评分 |
| hermes-skill-naming | prompt | software-development,self-management | hermes | `prompts/hermes-skill-naming.md` | 交给 Hermes 的创建/演化 skill 须知：判定耦合、耦合 skill 加 hermes- 前缀、不分叉内置 skill、可移植 skill 走 hoa 的移植评审 |
| parallel-agent-worktrees | prompt | software-development,work-management | repo-only | `prompts/parallel-agent-worktrees.md` | 一次性为每个 agent CLI 建独立 git worktree：布局、env/端口隔离、fail-closed 初始化、安全清理 |
| cross-platform-skills | rule | software-development | repo-only | `rules/cross-platform-skills.md` | 技能在 Windows、Linux、macOS 上原样可跑：安装完整 ../ 依赖闭包、正斜杠相对路径、标准库 Python 显式 UTF-8、技能脚本用 uv run 且带 PEP 723 块 |
| generalization-rubric | rule | software-development,work-management | repo-only | `rules/generalization-rubric.md` | 技能进入公开目录的唯一标准：陌生人在全新机器上能跑通——六道门槛、硬性失败项、回灌不变量 |
| generated-means-generated | rule | software-development,work-management,self-management | repo-only | `rules/generated-means-generated.md` | 生成文件绝不手改；再生成随同一提交，漂移即 CI 失败 |
| skill-composition | rule | software-development | repo-only | `rules/skill-composition.md` | 隐藏子技能：一个可见性标记加 Codex 旁路文件，以 Read 链接串联扁平同级目录且只下一层，必守规则留在父技能，隐藏不等于授权 |
| skill-naming | rule | software-development | repo-only | `rules/skill-naming.md` | 技能名是稳定 ID 和兜底路由信号：kebab-case 且与目录同名、族内按“族-对象-动词”排列、动词全库一义、禁用泛词、hoa- 只给技能库元技能族、改名走退役登记 |
| adopt-a-pattern | workflow | software-development | repo-only | `workflows/adopt-a-pattern.md` | 把 ref 地图里的 what-to-steal 笔记变成落地、归类、带署名 artifact 的有限步骤 |

## 安装

`npx skills` 只安装你点名的 skill，不跟随它们之间的 `../` 链接。
整库安装用 `npx skills add wxxb789/hoa -g -s '*' -y`；单装某个 skill 用下表该行的命令。
表中没有的 skill 没有依赖：`npx skills add wxxb789/hoa -g -s <skill> -y`。
`gdd` 通过单独安装的 route 运行 agent：请用某个 `gdd-route-*` 行安装（默认 agent 是
`gdd-route-omp`），不要只用 `gdd` 那一行。

| Skill | 依赖（`../` 传递闭包） | 安装命令 |
|---|---|---|
| gdd | delegated-work-acceptance | `npx skills add wxxb789/hoa -g -s gdd -s delegated-work-acceptance -y` |
| gdd-route-cc | delegated-work-acceptance, gdd | `npx skills add wxxb789/hoa -g -s gdd-route-cc -s delegated-work-acceptance -s gdd -y` |
| gdd-route-codex | delegated-work-acceptance, gdd | `npx skills add wxxb789/hoa -g -s gdd-route-codex -s delegated-work-acceptance -s gdd -y` |
| gdd-route-dsh | delegated-work-acceptance, gdd | `npx skills add wxxb789/hoa -g -s gdd-route-dsh -s delegated-work-acceptance -s gdd -y` |
| gdd-route-omp | delegated-work-acceptance, gdd | `npx skills add wxxb789/hoa -g -s gdd-route-omp -s delegated-work-acceptance -s gdd -y` |
| gdd-route-opencode | delegated-work-acceptance, gdd | `npx skills add wxxb789/hoa -g -s gdd-route-opencode -s delegated-work-acceptance -s gdd -y` |
| gdd-route-pi | delegated-work-acceptance, gdd | `npx skills add wxxb789/hoa -g -s gdd-route-pi -s delegated-work-acceptance -s gdd -y` |
| hermes-models | hermes-models-cutover | `npx skills add wxxb789/hoa -g -s hermes-models -s hermes-models-cutover -y` |
| hoa-skill-set-audit | hoa-skill-create | `npx skills add wxxb789/hoa -g -s hoa-skill-set-audit -s hoa-skill-create -y` |

不使用 Hermes 时，不要安装 `hermes-*` skill：它们只用于操作 Hermes，其他 skill 也不链接它们。
安装其余全部 skill：

```bash
npx skills add wxxb789/hoa -g -s agent-harness-settings-parity -s agent-operating-contract-evolution -s ai-coding-agent-delegation -s contract-bound-deliverables -s cross-agent-repair-routing -s define-goal -s delegated-work-acceptance -s discord-rich-message -s dotnet-repo-workflow -s evidence-backed-analytical-writing -s evidence-boundary-discipline -s gdd -s gdd-route-cc -s gdd-route-codex -s gdd-route-dsh -s gdd-route-omp -s gdd-route-opencode -s gdd-route-pi -s ghc-decisions -s ghc-search -s git-auto-sync-pipelines -s harness-engineering -s hoa-practice-retro -s hoa-repo-reckoning -s hoa-skill-create -s hoa-skill-curate -s hoa-skill-port -s hoa-skill-review -s hoa-skill-set-audit -s measurement-campaign-evidence -s official-document-verification -s package-release-verification -s project-phase-closeout -s report-claim-audit -s research-stream-consolidation -s review-revision-candidates -s spec-convergence -s structural-validity-gates -s tmux-agent-control -s writing -y
```

某次发布改名或退役了 skill 时：移除本仓库已不再提供的名称（由 `scripts/retired_skills.toml`
生成，其中写明每个名称的替代者），再重新运行整库安装命令或上表中该 skill 的当前行（之前保存的命令可能仍含旧名称）——
`npx skills update` 从不安装新名称。
移除从未安装的名称不会有任何影响；但移除按名称匹配所有来源，所以先看 `npx skills ls -g`，
把你从其它来源安装的同名 skill 从命令中去掉：

```bash
npx skills remove -g arch-improvement-plan design-an-interface design-md dsh-headless-gdd find-nearby generated-runtime-repairs git-worktree-workflow github-code-review github-repo-management grounded-citations hoa-agent-retrieve hoa-introspect hoa-introspect-distill hoa-skill-work html-artifact jupyter-live-kernel kanban-workflows m365-copilot-cdp microsoft-office my-ado-cppr notes-to-prd ocr-and-documents omp-headless-orchestration ops-claim-verification plan-to-issues rss-feeds skill-library-curation skill-porting-and-publishing subagent-driven-development systematic-debugging teams-cdp to-issues to-prd whisper writing-plans
```

> reflections 与 eval 结果属于文章 / 知识类，不在此索引。
