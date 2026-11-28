---
name: hermes-read-later-pipeline
description: "Use when a saved link must reach the <notes-vault> vault."
version: 1.0.0
author: Zoe
license: MIT
metadata:
  hermes:
    tags: [pkm, <notes-vault>, capture, reading]
---

# Read-Later Pipeline（收藏 → <notes-vault>）

## When to Use

- owner 丢来一个 URL / 说「稍后读」「收藏这篇」「存进知识库」。
- 要回答「稍后读积压多少」「draft 里还有什么没处理」。

## 三段（各段只有一个正本）

| 段 | 正本 | 动作 |
| --- | --- | --- |
| 采集 | `~/claw/tools/read-later/read-later.py` | URL → `<notes-vault>/sources/clippings/draft/<slug>.md`（`status: captured`） |
| 提炼 | vault `.agents/skills/process-clips`、`deep-reading` | draft → `sources/references` 或 `sources/research/<category>/`，`status: distilled` 或 `archived` |
| 收敛 | cron `d26e66eba2c8`（周日 10:00，`no_agent`）+ `~/.hermes/scripts/read-later-nudge.py` | 积压 ≥7 天才发一条 ZH-CN 提醒，否则静默 |

支持文件：`scripts/verify-quotes.py`（引文逐字核验）、`references/extraction-recipes.md`（capture 失败后按平台取正文的配方：小红书/xhslink、YouTube、X thread、图片型线程、厂商文档站正文丢结构时取官方 markdown 出口、站点按 Accept-Language 返回机器翻译版时的重抽）、`references/thread-sweep-and-resume.md`（批量 thread 盘点/改名与中断续跑：读回核对、archived 帖改名、channel 改名限速、`--resume` 续跑 prompt 四件事、报告回投去重、lane 队列生命周期）。

## 命令

```
cd ~/claw/tools/read-later
.venv/bin/python read-later.py capture <url> [--kind article|video|paper|x-thread|book] [--category CAT]
.venv/bin/python read-later.py queue [--json] [--alert-days N]
.venv/bin/python read-later.py status <slug|path> captured|distilled|archived [--compiled-into vault/path]
.venv/bin/python read-later.py move <slug|path> <vault-relative-dest>
.venv/bin/python read-later.py doctor [--verbose]
```

- `EXISTS <path>` = 该 URL 已采集过，幂等跳过；要重采先删/移走旧笔记。
- 账本 `~/claw/tools/read-later/ledger.jsonl` 是 append-only 事件流；`doctor` 按 slug 链取最新路径，`--verbose` 才展开被取代的历史行。
- 环境覆盖：`OBFLOW_VAULT`（vault 根）、`READ_LATER_LEDGER`（账本路径），测试必须两个都指到 `/tmp`，否则污染真 vault/账本。

## 硬规则

- **帖里丢来的链接默认全量 distill，不停下来问**（owner 2026-11-22）：read-it-later 帖（`#tasks` 的 read-later 流水线）里收到的每个 URL 一律走完 `capture → 提炼 → 落 <notes-vault> → 闸门 → 回报`，包括「帖 → 正本」的拆分（二手帖进 `clippings/<year>/`，正本进 `references|research/`）。只有 Red 动作（公开发布、凭证/生产、付费、他人系统）才停下等确认；「要不要落库」本身不是问题，不需要问 —— 但**「不打断」不等于「一律入库」**。
- **入口先过价值三档**：① 有独特价值 / 一手证据 → 按全量流程严肃提炼（认真对待它的内容，别平均用力）；② 平庸但确有可搬点 → 轻量收进 `sources/clippings/<year>/`；③ 平庸且无可搬点 → **直接跳过、不落库**，回报里写一行「跳过 + 理由」。档位由自己判、不回头问 owner；但 vault 不是垃圾场，「一律入库」是这套流水线最省事的退化。**档位与证据绑定**：拿不出原文原话或关键数据（含位置）的素材，一律不进 A/B 档，压回 C 档走一行卷宗。
- 工具只写 draft 目录与账本；**从不 commit / push / 改别人的笔记**。vault 提交交给 `[ops] repo auto-sync`。
- 提炼时正文逐字保真，只动 frontmatter 与 `status:` / `compiled_into:` 行；旧式 Web Clipper 笔记没有 `status:` 也要能寻址（按文件名，大小写不敏感）。
- **写提炼内容时按 `## Extracted Text` 切两半**：只重写前半（frontmatter + Why / Summary / Key Ideas / Evidence / Tensions / Destinations），后半原样拼回——不要用 `write_file` 重打全文，也不要手改 extracted 区块。脚本形式：`head, tail = text.split("## Extracted Text", 1)`，写完再核对后半字符数未变。
- 正文里混进站点噪声（文档站把 API tooltip 内联进 HTML）时**不清洗字节**，在 frontmatter 记一行 `extraction_noise: "..."` 说明噪声占比与位置，引文仍按真正文取。
- **一条笔记一个归宿**：`sources/references/`（查得到的资料）或 `sources/research/`（带论证的调研），别两边都放。
- **回报形状**：每条素材一条消息 —— 「我的判断（含素材性质：一手 / 推广稿 / 二手汇总）/ 能直接搬的点 / 折价处 / 落点路径」；批状态（闸门 + commit）先发，过程与原始输出只落 `status.md`，不回灌聊天。素材性质决定后续引用时信几分，所以它必须显式写出来，而不是留给读者猜。
- **回报只给结果，工具调用/过程噪声在 gateway 层关掉，不要在 prompt 里叮嘱模型别汇报。** 素材 thread 的交付面 = 判断 / 可搬点 / 折价 / 落点，工具调用与闸门过程一律不出现。若 bot 还在推 tool-call 气泡，根因是那个 home 的 `display.tool_progress: "off"`（机制见 `hermes-gateway`）——改配置，不要靠「禁止过程元话语」这类句子去对抗。
- **失败与残缺本身是一个状态，必须显性化，严禁用标题脑补摘要**：抓取结果只要不是干净正文（`extraction: failed`、付费墙、只剩导航骨架、反爬验证页），就把该素材标成待补救并保留 stub —— 回报写清「未抓到正文（原因）/ 未入库 / 把正文或截图贴回本 thread 即可续跑」，绝不允许拿标题或平台名编一段摘要充当提炼结果。补正文走另一条通道，stub 不删、capture 不重跑。
- **静默回执用 emoji，不用消息**：处理完成后在 owner 的**原消息**上补一个状态 reaction（按档位各一个 emoji），不要再发一条「已完成」——他扫一眼就知道结果，不会被多余的 ping 打断；处理中不发进度消息。bot 自带的过程标记（👀/✅/❌）保留不动。
- **owner 在链接同一条消息里多写的话属于素材的一部分**：他把 URL 和「这个像我 Q3 要做的 X」写在一起时，把那句作为 `user_note` 落进笔记 frontmatter，并在回报里回显一句「当时为什么存」——丢了这句，几个月后的自己只看得见标题，看不见意图。
- **入库前先保证能检索**：素材进了 vault 但对不上关键词等于不存在。给已捕获语料维护一份本地全文索引（重建走 CLI，不靠 LLM 逐条扫）；owner 发一句 `? <关键词>` 时**不建 thread**：宽召回 → 自己精排 Top3 → 每条给「标题 + 一句话结论 + 原文铁证一行 + 原链接 + vault 路径」。
- **交付要能只看标题/首行就认出素材**：自动 thread 标题只看得到用户那条消息（URL），默认会产出 `Analyze <url>`、平台名、作者 handle 这类零信息标题；交付完成后标题（或首条回报首行）必须同时给出**主题 + 素材性质**，否则 owner 扫标题时根本不知道这条收藏讲的是什么。这是 owner 的目录，不是装饰。**交付完成后由 bot 自己改这个 thread 的名字**（thread 就是 channel：`PATCH /channels/<thread_id> {"name": …}`，需 `MANAGE_THREADS`）——自动标题只看得到那条 URL，光改首行不够，标题必须是下次扫一眼就能认出「这是什么 + 讲什么」的那句话；渠道与权限探针见 `hermes-gateway`。
- **笔记本身也要带一句能被下游直接引用的话**：模板的首节固定 `## 一句话`（≤120 字、脱离上下文可读：是什么 + 为什么值得 / 或为什么只值一行卷宗），晨报摘要**引用这一节**，不从标题或正文首行现编。模板不给这一节，下游就只能在标题上脑补摘要——把「给下游引用的一句」写进模板，别指望每条素材都恰好有一句现成话。
- **中断的素材帖靠「复用原 session」接上，不靠发消息催**：bot 往自己 thread 发消息唤醒不了它（只有 owner 的真人消息会）；用 `hermes -p <profile> chat --resume <session_id> --query-file <续跑 prompt> --oneshot -Q` 跑一条「只做剩余步骤」的 prompt。批量时串行 + 队列落盘 + 先单条验证，收尾与报告去重见 `references/thread-sweep-and-resume.md`。
- **补救（停在 `captured` 的素材）也必须在素材自己负责的 thread 里做**（owner 规则：不在讨论/晨报 thread 里做）：按**负责 thread 分组**（一组可含多条，一组一次 `--resume`），报告由该 turn 的最终回复自动投进那个 thread。已落库、只差账本终态的，prompt 明确要求**只对账、不重写笔记**。盘点、分组与无归属清单见 `references/thread-sweep-and-resume.md`。
- **一条链接一个 thread；晨报单独一个只读频道**：素材不能挤在一个长 session 里串行处理（拦收藏速度、压缩吃掉中间），每条链接开自己的 thread、处理完改名。每日晨报（前一天全部素材按价值排序）投到一个**只读单向**频道 —— 该频道不进 `allowed_channels`，靠 `deliver` 定点投递，当天无素材则静默不发。
  - **一天一个 thread**：晨报投进当天的 thread（`YYYY-MM-DD · 晨报`），频道于是变成日期列表，而不是每天一条裸消息。换结构时**把旧的裸消息删掉**，同一个频道里并排两份同一天的简报，owner 无法判断哪份算数。
  - **日期是交付的一部分，要自检**：日期/时间一律按**显式时区**算（`Asia/Shanghai`），不依赖机器 TZ（`date` 跟 UTC 跑过就会发出一份日期错的简报）。发之前断言「标题里含当天日期」且「覆盖窗口串等于预期区间」，不一致就**非零退出走失败告警** —— 宁可不发，也不发一份日期错的。
  - **脚本自己投递 ⇒ cron `deliver: local`**：简报由脚本调 REST 发帖（stdout 留空），所以 cron 不能再投一次 stdout；失败路径另配 `deliver` 告警（失败与空闲必须可区分）。同日幂等（marker 文件 + `--force` 才重发）：重试、补跑、手工发都不会出第二份。
  - 正文同时落 vault（`sources/digests/<date>.md`，带 frontmatter），并过 vault 闸门（`markdownlint-cli2` + `vault.status` 的 `blocking_count: 0`）。
- **晨报每条素材要能点进它自己的 thread —— 用入口帖的 `compiled_into` 连边，别拿正本 URL 当 thread 键**：账本行记的是**正本** URL（github / arxiv / 官方页），thread 是按**入口帖**（clipping）建的，两者不同源，按 URL 直接找 thread 必然落空（常见症状：链接栏印出 vault 路径，看着像坏链）。做法：正本 frontmatter 的 `compiled_into` → 入口帖路径 → 入口帖 URL → thread。连不上时**不要**把 vault 路径放在链接的位置：显式标 `↳ 落点：<path>`，让它自己说明「东西在、只是没有 thread」。
- **耗时/轮次失控先怀疑「确定性工作被交给了 LLM」**：采集校验、查重、frontmatter 拼装、引文核验、落库提交都应有脚本正本；让模型多轮 tool call 去手工完成它们，是单条素材十几分钟、撞轮次上限被截断的主因。模型只该做语义判断与模板填空，确定性步骤留在 CLI 里。
- **汇总/推荐帖是入口，不是素材：帖内的 deep link 各自成一个 asset**。owner 丢来「这 N 篇值得读」这类帖子时，批 = N 个正本（`sources/references/` 或 `sources/research/`，各自完整提炼）+ 1 条帖本身（`sources/clippings/<year>/`，逐字保真 capture + `status: archived`）。帖本身**不重复提炼正本已覆盖的事实**——它的价值是清单、排序与逐条转述差异，把这个差异按正本一条条列出来：推荐帖的一句话概括常把正本的性质都说错（把已 301 成产品文档的文章称作旧栏目文、漏掉原文自己写的过时/边界声明、只提原文三条要点里的一条），写「概括有出入」而不列条目等于没核。
- **素材指向一件可执行的事时，别停在「已落库」**：提炼出的判断常自带动作（该准备的问题、该补的验证、该改的流程）。给它一个归宿 —— 落进对应项目的 tracking surface（vault 项目笔记的 backlog / 待办行），而不是留在笔记里当建议；owner 一句同意就照做并回报，不留悬空提案。**规则类素材（别人家的 agent / 流程制度）走「差额 → 逐条确认」**：先与自己现有的 `~/claw/AGENTS.md` 与 skills 逐条比，只把真缺口递给他（逐条 approve，一次一条）；**未采纳的必须把理由写回笔记的 Destinations**（「已有 X，不重复写」）并同步进对应 `references/agents/*.md` —— 不记录的不采纳会被下一个 session 重新提案，等于让他读第二遍同样的规则。
- **往 `~/claw/AGENTS.md` 写规则前先量准字节差**：该文件受 5–25 KB 体检上限约束（`contract-drift-check.py` 报 `AGENTS.md 体积异常`），估算会低估。做法：把待写入/待替换的原文与新版各自 `len(s.encode('utf-8'))` 量一次，装不下就把细则下沉到 `references/agents/<topic>.md`、AGENTS.md 只留一行指针 —— 该文件写入是审批门禁，返工要多花一次 owner 点击，所以第一版就要是终版。
- 微信链接走 `~/claw/tools/wechat-article-to-markdown` 后端，失败回退 trafilatura；抽不出正文也要落 stub（`extraction: failed`，exit 3），不静默丢。**但反爬验证页会让 `capture` 报假的 `extraction: ok`** —— 拿到的是「环境异常，完成验证后即可继续访问」那类验证页（标题会是「环境异常」，正文只有「Video / Mini Program / Like」几行）。判断法：正文极短且含验证/点赞字样就是墙。这时：① 真跑一次 `wechat-article-to-markdown`（Camoufox，首次会下载 ~1.3G 浏览器）确认；② 无论它成败，自己把桩里的 `extraction:` 改成 `failed` 并在 `extraction_backend` / `extraction_noise` 写清通道与失败证据，别留 `ok`；③ 正文走**正本另采**（例：微信传的 PG 19 发布文 → postgresql.org 官方公告），桩 `move` 到 `sources/clippings/<year>/` + `status archived` 并链回正本。
- **短链先解出真实 URL 再判断，登录墙后的正文另找通道**：手机分享出的 `xhslink.cn` / `b23.tv` / 微博短链，`capture` 只会抓到跳转页（trafilatura 无文本）。先 `curl -sS -o /dev/null -w '%{http_code} %{redirect_url}' <url>` 拿真实地址；真实地址落在登录墙后（小红书 discovery → `rednote.com/login`）时，拿到 stub + `extraction: failed` 就是预期结果（笔记与账本都落了、不会丢）——正文另走浏览器通道（配方：`references/extraction-recipes.md`），别把它当「链接坏了」、别反复重跑 capture、也别删 stub。分享链 URL 里的 `xsec_token` 在**无登录态**浏览器里就能取到正文——`rednote.com/login` 不等于「必须登录」，别据此放弃。
- **小红书分享链自带 `xsec_token` 就能过网页端**：用真实浏览器打开 `https://www.xiaohongshu.com/discovery/item/<id>?xsec_token=…&xsec_source=app_share`，会落到 `rednote.com` 镜像并渲染 SSR；正文在 `window.__INITIAL_STATE__.note.noteDetailMap[<id>].note.desc`（`title` / `time` / `user.nickname` / `tagList` 同处），逐字取出即得正文，**不需要登录**。`curl` 直接取只会 302 到登录页 —— 别据此判定「抓不到」、也别去找登录态。
- **YouTube 从本机 IP 拿不到字幕，走 `web_extract`**：`yt-dlp`、`youtube-transcript-api`、`youtubetotranscript.com` / notegpt / kome 等公开转写站全部被拦（innertube 报 `LOGIN_REQUIRED`「确认你不是机器人」、其余是 Cloudflare / datacenter IP 封禁）。可行路径是 `web_extract` 直接传 watch URL —— 返回里带整段自动字幕（页面的 `## Transcript`），全文落 `~/.hermes/cache/web/`。别在 yt-dlp / 转写站上反复试。
- **从网络素材取的正文常带制表符，维护笔记要清**：JSON `desc` 之类字段用「只有 tab 的分隔行」，直接拼进 `## Extracted Text` 会让 `markdownlint` 报 MD010（`sources/clippings/**` 在排除名单里，`sources/research|references/` 不在）。把这些纯 tab 行改写成空行即可 —— 只差空白，`verify-quotes.py` 仍 0 失配；同时在 Provenance 注明这处规范化。脚本形式：`paras = [l.strip() for l in tail.split('\n') if l.strip()]` 再用空行 join；别加 `markdownlint-disable` 掩盖、也别改字。
- **别在后台 job 退出前删它要写的 scratch 目录**：一次 `rm -rf …/scratch/yt` 发生在 `ghc-search` 后台 job 仍在写同一目录时，产物被清掉；后台 job 的产物路径在 scratch 时，先等它退出再清。
- **自己重建 extracted text 的笔记必须原样带上 marker 行**：`scripts/verify-quotes.py` 靠 `<!-- machine-extracted by read-later.py; do not hand-edit this section -->` 定位正文；从 README / 资产 / 别处取正本时若省了这行，脚本报 `no extracted-text marker — refusing to guess`（看着像引文失配，其实是缺标记）。
- **锚点匹配要容忍硬折行**：README、长文的短语常被折行拆成两行（`Apply backs up` / `every profile first`），`text.count(anchor)` 会得 0 而误判「锚点不存在」。改用空白折叠的正则（`re.compile(r"\\s+".join(re.escape(w) for w in anchor.split()))`）找 span 并断言全文唯一，切片仍从原文取字节。
- **重建笔记的脚本要幂等**：draft 已 `move` 走后重跑会把「找不到 draft」当失败。做法：`src = draft if draft.exists() else vault/dest`，重写 head + extracted text 后，draft 不在就跳过 move/status（原地重建），保证脚本可重复跑、不产生第二份笔记。

## 坑

- **站点会按 `Accept-Language` 返回机器翻译版，`capture` 照样报 `extraction: ok`**：个人博客 / 文档站常把 AI 翻译页当默认出口，trafilatura 拿回的是**译文而不是作者正本**（译文会改掉帽句、抹掉作者自称与限定语，引用它等于引用二手转述）。正文语言与站点语言不符、或页面有翻译声明就是它。修法：`curl -sS -H 'Accept-Language: <原文语言>' <url>` 抓同页 HTML → trafilatura 重抽，用正本版当 `## Extracted Text`，两份都留证 —— 别改 `extraction: failed`（内容确实拿到了），也别就地翻译回去。配方：`references/extraction-recipes.md`。
- **`status --compiled-into` 是追加不是覆盖**：若 frontmatter 里已手写 wikilink 形式的 `compiled_into`，再跑 `status … --compiled-into <path>` 会多出一条纯路径，两条并存（同一归宿写两遍）。收尾读回 frontmatter，删掉纯路径那条，只留 `- "[[vault-root-qualified]]"`（vault 现有笔记的约定形式）。
- **同帖回复要单独抓、单独核验**：主帖抓取只含主帖正文，而作者的 self-reply 常是立场所在，值得连回复一起提炼。做法：把 `OBFLOW_VAULT` + `READ_LATER_LEDGER` 指到 scratch 目录（避开真 vault/真账本），逐条 `capture` 每个 reply URL，再按空白折叠逐字比对。`verify-quotes.py` 只校验笔记自己的 `> ` 行对本笔记的 extracted text，所以回复引文写成**行首带 status URL 的 bullet**，别写成 `> `（否则误报失配）。trafilatura 会把 `~` 转义成 `\~`，这类差异在引用处写明，别悄悄改字。
- **引文用 `scripts/verify-quotes.py` 逐字核验，不靠眼看**：原文里的 `**加粗**`（如列表项 `- **宽泛口径：…**`）、`“ ”`（不是「」）、以及源文件的换行折行都是判定的一部分。脚本按空白折叠比对，0 失配才算过；手抄后改了引号类型或省掉 `**` 是最常见的失配源。**extracted text 也必须机器落地**：浏览器里让 JS 返回 JSON 字符串、Python 侧 `json.loads` 后直接写文件，绝不手打——引文与本笔记的 extracted text 都由你手抄时，同一个错字会同时落在两边，脚本会**假通过**。这条对所有素材成立、不只 PDF/浏览器：文章、X 长帖也一样 —— 引文由脚本在 extracted text 里按锚点切片（`body.count(anchor) == 1` 后取 index 切片、断言结果无换行）再拼成 `> ` 行，比手抄省事且零失配。**但锚点要容忍撇号漂移**：同一篇里 `’`（U+2019）与 `'` 会混用（"I’d like to share…" vs "That's just a step"），锚点匹配不上时先按两种撇号各试一遍再断言，别改字去迁就。
- **提升进 `garden/` 需要 `goal_id`**（`structure-policy.json` 的 `garden_admission_policy`，白名单：content-brand / financial-independence / promo-senior / system-reliability）；没有合适 goal 就留在 `sources/` 并给 `status: archived`。该准入只管**新提升**——更新既有 `garden/` 笔记（补一节、加反例）不重跑准入、不需要 goal_id。
- **`garden/` 顶层域只有 6 个**（`structure-policy.json` 的 `states.<state>.garden_domains`）：`ai` / `dev` / `fin` / `interview-prep` / `life` / `research-methods`；`learning` / `lifestyle` / `people` 是**已退役的顶级域**，只能在 `life/` 下当子目录用。职场 / 生涯 / 影响力这类内容没有 `garden/career` 可放 → 落 `garden/life/lifestyle/`（同域已有 `self-help-advice-evidence-strength` 这类证据分层笔记）并在该 `_index.md` 的 Key Entry Points 加一行；别凭感觉新建顶级域。相对的，`sources/research/<category>/` 的 category 可以新开（如 `career-performance`），目录随 category 建、不需要 `_index.md`。
- **观点 / 叙事类素材（第一人称长文、无一手可核事实）的提炼重点是证据强度，不是复述**：先把它拆成动作清单，再逐条挂外部证据（同行评审 / 大样本实验），把与文献的张力、以及不可证伪的归因（族裔、性格）写进 Tensions；Garden 侧做成 `type: framework` + `goal_id` 的对照表笔记（动作 / 证据 / 强度分层），来源侧引文照样过 `verify-quotes.py`（0 失配）。这类素材的杀伤点是它自洽但不自证 —— 内部矛盾（时间线对不上、叙述者姓名不一致）要当场写出来。**推广稿与二手汇总稿同理，且必须当场点名性质**：产品软文（零量化效果、零失败案例、「能做人能做的任何事」式营销口径）与二手汇总（转述数字随产品运营变、法律部分只到「未定」）都只提炼可搬的方法，写清折价理由，别把营销口径或二手转述当结论引用。
- **素材引用的论文 / 官方报告要逐条核到来源页，核不到的在笔记里标「未核实」**：综述型帖子（引 N 篇论文 + 官方博客）的价值就等于它的引用能不能落地。做法：每个数字去 arXiv **abs 页**（不是只看帖子正文的转述）或厂商官方页各取一次，笔记里分「完全核实 / 部分核实 / 未核实」三档并列出核到的原文数字；**核不到的数字（常是帖子作者自己算的比例、放大倍数）必须点名不能转引**，否则未核数字会以「已核」身份继续流传。核验页缓存路径写进笔记，供回源。
- **同一天的多条链接按「批」处理，批批各自跑闸门**：一个 `~/claw/tasks/<date>/<task>/status.md` 按批分节（输入 / 归类 / 来源笔记 / Garden / sha256 / 备份），每批独立跑 `queue` + `doctor` + `markdownlint-cli2` + `vault.status`，把 receipt id 与 `blocking_count` / `warning_count` 写进表里 —— 混成一次总闸门后，出问题就指认不出是哪批引入的。收尾先看 `git status --porcelain`（在 `~/repos/<notes-repo>` 跑）再看 `git log -1 --stat`：上一批的文件从 status 里消失 = 已被 `[ops] repo auto-sync` 提交，把 commit sha + diffstat 当「已落库」的证据回报，别报成「还没提交」。
- **收尾闸门用仓库自己的命令**：`markdownlint-cli2 '<file>'`（vault 根有 `.markdownlint-cli2.jsonc`）+ `/usr/bin/python3 .harness/harness.py run vault.status`；`blocking_count` 必须为 0，既有的 `generic_maintained_name` 等 warning 不是自己引入的就不用管；**终端输出很长且被截断，数字去 `.harness/receipts/<id>.json` 的 `result.data.structure` 里读**（`blocking_count` / `warning_count`），并跑前先记下上一轮 warning 数，才能说「持平」。
- **vault 闸门要用 `/usr/bin/python3`**：mise shim 的 `python3` 没有 PyYAML，`harness.py` 会以 `No module named 'yaml'` FAILED（旧 pid 的 receipt 里看不到，只看 exit code 会漏）。
- 验证命令别在同一个 shell 里 `export OBFLOW_VAULT=...`：变量会跨调用存活，后续真 vault 操作会指向 /tmp。用 `env -u` 或 `unset`。
- gateway 的 lifecycle 守卫会整条拒绝「引用了非普通文件」的 `terminal` 命令（`/dev/null`、进程替换 `<(cat f)`），并对被执行脚本做粗粒度扫描，报 `could not scan this command or referenced script`。把探测输出写到 scratch 真文件再比较，命令拆成单用途小调用；heredoc 写脚本本身可用（`python3 - <<'PY'` 实测能跑），别把它误读成「heredoc 一定被拦」。
