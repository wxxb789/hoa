# ref — 外部参考

> [English](./README.md) · **简体中文**

一份精选的 agent / skill / harness 仓库地图，值得借鉴学习。这里**不 vendor
代码**——只是我寻找灵感、可借鉴模式的去处。某个参考被验证有用后，就把它吸收进
对应的顶层目录——[`../skills/`](../skills/)、[`../orchestration/`](../orchestration/)、[`../agents/`](../agents/) …（保留署名）。

## Vendor 的参考（submodule）

下表所有条目都作为 git submodule 克隆到本地 `ref/<name>/` 下，各自
**分支跟踪**其上游默认分支。一条命令把全部刷新到最新：

```sh
git submodule update --remote --merge   # 把所有跟踪分支拉到各自最新
```

| 仓库 | 类别 | 是什么 | 可借鉴什么 |
|---|---|---|---|
| [EveryInc/compound-engineering-plugin](https://github.com/EveryInc/compound-engineering-plugin)<br>`ref/compound-engineering-plugin` | 工程 skills | 一个跨 harness 的 AI 编码 agent 插件，包含 31 个串联的工作流 skills，覆盖 brainstorm、plan、work、review、debug 与复利式学习循环。 | 复利循环：ce-compound 写入 docs/solutions 的学习记录，之后 ce-brainstorm/ce-plan 会把它们作为基底读取。 |
| [obra/superpowers](https://github.com/obra/superpowers)<br>`ref/superpowers` | 工程 skills | 一个 Claude Code 插件，包含 14 个可组合、可自动触发的 skills，编码了 TDD 优先的 agent 开发工作流：brainstorm、plan、worktree、subagent 驱动的实现、review。 | “writing-skills 就是流程文档的 TDD”这一 meta-skill，加上以 RED-GREEN-REFACTOR 为门槛的 subagent 驱动开发，以及先规范后代码的两阶段 review。 |
| [mattpocock/skills](https://github.com/mattpocock/skills)<br>`ref/mattpocock-skills` | 工程 skills | Matt Pocock 收集的约 41 个可组合 Claude Code agent skills，面向真实工程：grilling、spec/ticket 流程、TDD、代码 review 与领域建模。 | “grilling”模式：一场不留情面的构建前访谈，同时产出 CONTEXT.md 通用语言词汇表与 ADR（grill-with-docs）。 |
| [juliusbrussee/caveman](https://github.com/juliusbrussee/caveman)<br>`ref/caveman` | prompts | 一个 Claude Code / 多 agent 插件，强制以简短的“穴居人腔”回复，在保留代码与技术准确性的同时削减约 65% 的输出 token。 | SessionStart + UserPromptSubmit hooks 持久化一个模式标志，并通过 decision:"block" 注入统计信息，而非靠模型计算。 |
| [JimLiu/baoyu-skills](https://github.com/JimLiu/baoyu-skills)<br>`ref/baoyu-skills` | 内容生成 | 一个 Claude Code marketplace 插件，打包了 21 个 baoyu-* AI 内容 skills：图片卡片、信息图、SVG 图表、封面、幻灯片、漫画、发布（WeChat/Weibo/X）、翻译以及转录/markdown 工具。 | 组合式维度系统（Style x Layout x Palette，或 Type x Palette x Rendering x Text x Mood），把一个 skill 变成上百种样式。 |
| [JimLiu/baoyu-design](https://github.com/JimLiu/baoyu-design)<br>`ref/baoyu-design` | 设计 | 一个可移植的 Agent Skill，重新封装了 Anthropic 的 Claude Design 引擎，让本地 agent（Cursor、Claude Code、Codex）产出自包含的 HTML mockup、原型与幻灯片。 | 与 harness 无关的 SKILL.md：检测运行时并加载对应 harness 的 references/*.md 工具映射，让工艺规则保持可移植。 |
| [lijigang/ljg-skills](https://github.com/lijigang/ljg-skills)<br>`ref/ljg-skills` | 思维工具 | 一个个人收藏的 21 个中文认知 skills，把概念、书籍、论文与领域拆解为结构化思维框架，以 org-mode/markdown 或 PNG 卡片输出。 | 可复用的“框架即 skill”模式：固定维度的拆解（8 轴概念解剖、书籍的 x→f→f(x) 归约）压缩成一句顿悟式的话。 |
| [zjp1997720/zhijian-skills](https://github.com/zjp1997720/zhijian-skills)<br>`ref/zhijian-skills` | agent skills | 一个单仓库作品集，包含 11 个聚焦、独立版本化的 Agent Skills，涵盖 Codex 运维、工作流编排、模型路由、知识系统、研究与 WeChat 发布。 | registry/skills.json 清单，加上 `skills/<name>/` 载荷与 `docs/skills/<name>/` 双语文档的拆分，让每个 skill 拥有自己的版本。 |
| [dontbesilent2025/dbskill](https://github.com/dontbesilent2025/dbskill)<br>`ref/dbskill` | skills | 一个中文 Claude Code 插件/marketplace，包含 28 个商业与内容创作诊断 Skills，外加一个从推文挖掘出的 4,176 条原子知识库。 | `/dbs` 路由 skill：单一入口读取对话上下文并自动派发到合适的专用 skill。 |
| [tw93/Waza](https://github.com/tw93/Waza)<br>`ref/Waza` | 工程 skills | Waza 是一个跨 agent（Claude Code/Codex/Cursor）插件，包含八个工程工作流 skills：think、ui、check、hunt、write、learn、read、health。 | 双语的 `when_to_use`/`dispatch_intent` frontmatter，加上 RESOLVER.md 路由表，让一个 skill 能跨 agent/语言触发。 |
| [tw93/Kami](https://github.com/tw93/Kami)<br>`ref/Kami` | 设计 | 一个 Claude Code skill 与基于约束的设计系统，通过 WeasyPrint 把专业文档与落地页排版成带品牌的 PDF/PPTX/PNG 交付物。 | 确定性交付门：发布前的按类型内容 schema + 事实覆盖检查 + 页面图像视觉 QA 清单。 |
| [lyra81604/zhengxi-views](https://github.com/lyra81604/zhengxi-views)<br>`ref/zhengxi-views` | 研究 | 一个 Claude Agent Skill，用可溯源的语料、提炼的方法与真实基金数据回答关于基金经理 Zheng Xi 的问题。 | 反幻觉溯源规则：有语料则引用，否则把首句加粗标记为基于方法的推断，绝不捏造。 |
| [ksimback/looper](https://github.com/ksimback/looper)<br>`ref/looper` | agent skills | 一个 Claude Code 斜杠命令 skill，通过访谈帮你设计一个良好成形的 agent 循环（目标、类型化验证、跨模型 review 门、终止守卫），并产出可移植、可 lint 的循环规范。 | 类型化验证分类法（programmatic/judge/human），加上静态的 `looper lint`，用来标记诸如全凭感觉的检查和同厂商 judge 等循环反模式。 |
| [kunchenguid/no-mistakes](https://github.com/kunchenguid/no-mistakes)<br>`ref/no-mistakes` | 工程 skills | 一个 Go CLI，在你的远端之前放置一道本地 git-push 门，在开出干净 PR 之前运行一条 AI 验证流水线（review、test、docs、lint、push、PR、CI）。 | SKILL.md 的门循环契约：驱动一次 TOON 机器可读的运行，在每个 `gate:` 上响应，循环直至 `outcome:`，并把 `ask-user` 的发现逐字上报给人类。 |
| [kunchenguid/gnhf](https://github.com/kunchenguid/gnhf)<br>`ref/gnhf` | 编排 | 一个跨平台 npm CLI，在 git 仓库中整夜循环运行任意编码 agent CLI，每次迭代提交一个经过验证的小改动，直到满足停止条件。 | SKILL.md 的 Hands-Off 与 Companion 拆分，加上信号到行动的引导表，以及“满足停止条件不等于用户验收”这条规则。 |
| [kunchenguid/lavish-axi](https://github.com/kunchenguid/lavish-axi)<br>`ref/lavish-axi` | agent 工具 | 一个“AXI” CLI（lavish-axi）加安装 skill，在本地浏览器打开 agent 生成的 HTML 制品，供人做元素/文本/Mermaid 标注，并把长轮询反馈回传给 agent。 | 通过 build:skill 从 CLI 运行时指南单源生成 SKILL.md，并设一道在漂移时失败的 check 门。 |
| [petergyang/no-ai-slop](https://github.com/petergyang/no-ai-slop)<br>`ref/no-ai-slop` | 文风 | 一个 AI-harness 写作 skill，有两种模式：默认的编辑模式做最小改动以剥离 20+ 个命名的 slop 模式（冒号揭示、重要性吹嘘、破折号堆叠），同时保留作者声音，并对照 eval.md 自检；检测模式则逐一引用每个模式，不改写也不臆测是否为 AI 撰写。 | 成对的 eval.md 通过/失败清单，由同一个 agent 对自己的编辑自跑——一个无需单独评估者 agent 的自我批评循环。 |
| [mvanhorn/last30days-skill](https://github.com/mvanhorn/last30days-skill)<br>`ref/last30days-skill` | 研究 | 一个多主机 Agent Skills 插件（/last30days），并行搜索约 20 个社交平台，按互动量给结果打分，再由一个 AI judge 综合出一份带引用的简报。 | `doctor` 健康检查命令：探测每个来源并开出精确修复方案：缺失的 key、不在 PATH 的 CLI、过期的 cookie。 |
| [titanwings/colleague-skill](https://github.com/titanwings/colleague-skill)<br>`ref/colleague-skill` | meta-skill | 一个双语 meta-skill 引擎（dot-skill），从素材中把同事、关系或名人提炼为可复用的 persona+work Agent Skill。 | 分阶段的 prompt 链流水线：intake 到 persona_analyzer 到 persona_builder 到 work_builder 到 merger 到 correction_handler。 |
| [alchaincyf/nuwa-skill](https://github.com/alchaincyf/nuwa-skill)<br>`ref/nuwa-skill` | meta-skill | 一个 meta-skill（女娲/Nuwa），自动研究一个指定人物或模糊需求，并把其思维提炼为可运行的 Agent-Skill 视角。 | 5 部分的“认知 OS”模板：心智模型 + 决策启发法 + 表达 DNA + 反模式 + 每个 skill 一份 FIDELITY.md 诚实边界文件。 |
| [alchaincyf/huashu-design](https://github.com/alchaincyf/huashu-design)<br>`ref/huashu-design` | 设计 | 一个与 agent 无关的 Claude skill，把一句 prompt 变成可交付的 HTML 原型、幻灯片、MP4/GIF 动画、可编辑 PPTX、信息图与专家设计评审。 | Brand Asset Protocol：询问、搜索官方品牌页、下载、从真实素材 grep 出 hex 颜色（绝不猜测），并冻结进 brand-spec.md。 |
| [yaojingang/yao-open-skills](https://github.com/yaojingang/yao-open-skills)<br>`ref/yao-open-skills` | 研究 | 一个精选的公开中文 Claude Skills 合集，把决策、商业、安全与学习问题转化为结构化的多格式分析报告。 | registry/skills.json 作为单一事实来源，通过一个 render 脚本自动生成 README 目录 + HTML 导航。 |
| [yaojingang/yao-open-prompts](https://github.com/yaojingang/yao-open-prompts)<br>`ref/yao-open-prompts` | prompts | 一个开源库，含 118 个按场景分类的中文 AI prompts（工作、学习、内容、营销），配有完整的英文镜像与目录生成脚本。 | 严格的每 prompt YAML frontmatter + 三段式正文（title/intro/Prompt），喂给一个自动生成的 CATALOG.md 索引。 |
| [yaojingang/yao-meta-skill](https://github.com/yaojingang/yao-meta-skill)<br>`ref/yao-meta-skill` | meta-skill | 一个 Python 驱动的“Skill OS”，通过语义化的 Skill IR、多目标编译器、触发/输出 evals 与发布治理门，把工作流变成可安装的 agent skills。 | Skill IR：一份与平台无关的语义契约，编译到 OpenAI/Claude/generic/VS Code 适配器，加上 train/dev/holdout 触发 eval 套件。 |
| [virattt/dexter](https://github.com/virattt/dexter)<br>`ref/dexter` | agent | 一个 Bun/TypeScript 自主金融研究 agent，会做计划、执行工具、对照实时市场数据自我验证，并交付 DCF/memo/sentiment skills。 | SKILL.md frontmatter 里带明确的自然语言“Triggers when user asks...”短语，加上一份可复制并跟踪的 Workflow Checklist 正文。 |
| [taxueseek/say-it-human](https://github.com/taxueseek/say-it-human)<br>`ref/say-it-human` | 文风 | 一个中文写作 skills 工具箱，通过 19 维来源图谱与五个串联 skills（voice、humanize、edit、check、package）检测并去除“AI味”。 | 19 维“AI味来源图谱”表：每一行把一个检测信号与一个具体修法配对，加上“按密度而非出现次数判定”的规则。 |
| [blader/humanizer](https://github.com/blader/humanizer)<br>`ref/humanizer` | 文风 | 一个单 SKILL.md 的 Claude Code 插件，依据 Wikipedia 的“Signs of AI writing”指南改写文本，去除 33 个 AI 写作痕迹。 | 33 模式的前后对照检测表，加上最后一遍“明显是 AI”的审查并改写，以及不捏造规则。 |
| [op7418/Humanizer-zh](https://github.com/op7418/Humanizer-zh)<br>`ref/Humanizer-zh` | 文风 | 一个单一 Claude Code skill（中文），检测并改写 24 个 AI 写作痕迹，让文本听起来更像人写的。 | 24 模式的 AI 痕迹分类法（4 大类），加上一份作为可复用编辑清单的“AI 词汇”观察表。 |
| [MrGeDiao/shuorenhua](https://github.com/MrGeDiao/shuorenhua)<br>`ref/shuorenhua` | 文风 | 一个中文优先的 AI 写作去痕 skill/插件，运行固定的六步流水线（场景、保护片段、Tier、改写级别、编辑范围、两遍复读），并由一个 82 例假阳性基准把关。 | `bounded` 编辑范围：整句填充词进入一份用户确认的删除列表而非自动删除，让长度控制保持人性化。 |
| [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill)<br>`ref/taste-skill` | 设计 | 一个可移植的 Agent Skills 库（也是 Claude 插件），包含反 slop 的前端设计与图像生成 skills，把 AI 搭出的 UI 推向高级的布局、排版与动效。 | “反 slop”模式：每个 SKILL.md 把要打破的具体 AI 默认（6 行标题、卡中卡、左右重复）作为硬性负向约束点名。 |
| [affaan-m/ECC](https://github.com/affaan-m/ECC)<br>`ref/ECC` | agent harness | ECC 是一个 harness 原生的 agentic 操作者插件（v2.0.0），在 Claude Code、Codex、Cursor 及其他 harness 上交付 278 个 skills、67 个 agents、hooks、rules 与 MCP 约定。 | skill-scout：在编写新 skill 前先在本地/marketplace/GitHub/web 搜索已有 skill，以避免重复。 |
| [garrytan/gstack](https://github.com/garrytan/gstack)<br>`ref/gstack` | 工程 skills | 一套 59 个 Claude Code 斜杠命令 skills 加一个 headless 浏览器 CLI，运行一场从 plan 到 review、QA 与 ship 的 AI 工程冲刺。 | 通过一个配置驱动的 gen-skill-docs 生成器从 .tmpl 模板生成 SKILL.md，并共享 resolver 模块（preamble/jargon），让众多 skills 共用一条 prompt 脊梁。 |
| [anthropics/skills](https://github.com/anthropics/skills)<br>`ref/anthropics-skills` | skills | Anthropic 官方的示例 Agent Skills 仓库：17 个自包含的 SKILL.md skills（docs、design、MCP、web testing），外加一个模板与 Claude Code 插件 marketplace。 | SKILL.md 模式：两字段 YAML frontmatter（name + when-to-use description）领衔一个自包含的指令文件夹。 |
| [victorchen96/victorchen96.github.io](https://victorchen96.github.io/auto_research/framework.html) (`auto_research/`)<br>`ref/auto_research-site` | 编排 | HTML 展示页加综述 PDF，记录 Deli_AutoResearch：一个长时程自主 agent 协议，以及一条产出 ICLR 风格综述的 5 子 skill 论文写作流水线。 | 三层心跳看门狗（常驻 shell 守卫 / 持久 cron / 会话内 last_seen），加上由 stale_count 驱动的强制结构性转向。 |
| [anthropics/knowledge-work-plugins](https://github.com/anthropics/knowledge-work-plugins) (`finance/`)<br>`ref/knowledge-work-plugins` | plugins | Anthropic 的 Claude Cowork/Code 插件 marketplace：基于文件的角色专家插件（finance、sales、legal、data、HR……），打包了 skills、MCP connectors 与斜杠命令。 | Finance skills 的每 skill“由合格专业人士审阅”信任边界免责声明，加上 `"Use when <枚举触发条件>"` 的 description 格式。 |

> 仓库单元格显示上游仓库（带链接），下方是其本地 submodule 路径。有两行是某个
> 更大 vendor 仓库的子目录——见括号里的路径（`auto_research/`、`finance/`）。

## 仅链接的参考

| 仓库 | 是什么 | 可借鉴什么 |
|---|---|---|
| [multica-ai/andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills) | 一份 SKILL.md 提炼 Karpathy 的四条反 slop 编码原则：先思考后编码、简洁优先、外科手术式改动、目标驱动执行。 | "把命令式任务转化为可验证目标"的表（"Fix the bug" → "先写一个失败的测试"）——一页纸，无需 vendor。 |

> 单薄的单一 skill 仓库：在这里留链接，不用付 submodule 的成本。只有真的要研究
> 上游时才值得加 submodule。

## 如何添加更多

把一个参考作为分支跟踪的 submodule 加入，以便刷新到最新：

```sh
git submodule add -b <默认分支> <url> ref/<name>
git submodule set-branch --branch <默认分支> ref/<name>   # 若省略了 -b
```

仅需借鉴想法时优先用链接——submodule 会撑大仓库、拖进别人的历史。绝不复制带
secret 或个人路径的代码。
