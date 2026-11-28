# 抓取通道配方（按平台）

`capture` 只负责 trafilatura 能拿到的静态页。本文件是「capture 记下 `extraction: failed` 之后」如何取正文的配方，以及视频类素材的转录取法。

所有配方共守一条硬规则：**正文先机器落到文件，再从文件拼笔记**，绝不凭眼看手抄（理由见 SKILL.md 引文核验那条坑）。

## 通用：正文落地法（浏览器 → 文件）

在浏览器里读到正文时，让 JS 返回 JSON **字符串**，Python 侧 `json.loads` 后直接写盘：

```python
raw = js("""(() => {
  const s = window.__INITIAL_STATE__; const map = s && s.note && s.note.noteDetailMap;
  const k = Object.keys(map)[0]; const n = map[k].note;
  return JSON.stringify({title:n.title, desc:n.desc, time:n.time, nickname:n.user.nickname});
})()""")
meta = json.loads(raw)
Path('<scratch>/note.json').write_text(json.dumps(meta, ensure_ascii=False), encoding='utf-8')
```

拼接时 `head.rstrip('\n') + '\n\n' + text.strip('\n') + '\n'`，前半（frontmatter + 分析）与后半（`## Extracted Text`）分别来自两个文件，不做手抄。

## 小红书 / xhslink（登录墙后）

1. `capture` 落 stub（`extraction: failed`，exit 3）是**预期**：笔记与账本都已落，别删、别反复重跑。
2. 分享链 URL 自带 `xsec_token`；**带 token 的地址在无登录态浏览器里就能拿到正文**，不需要账号、不需要 cookie。别一看到 `rednote.com/login` 就断定要登录态。
3. 用 `new_tab` 打开解析后的 note 地址，把分享链里的 token 参数带上：`https://www.xiaohongshu.com/discovery/item/<note_id>?xsec_token=<token>&xsec_source=app_share`，然后 `wait_for_load()` + 停 2-3 秒。
4. 正文在 SSR 初态里：`window.__INITIAL_STATE__.note.noteDetailMap` → 按 note id 取（`noteDetailMap[<note_id>]`；只渲染了一条时取第一个 key 也行）的 `.note`，字段 `title` / `desc` / `time`（**毫秒** epoch）/ `user.nickname` / `tagList`。
5. `time` 落地前换算成北京日期，写进 frontmatter `published:` 与 Provenance 的「发布时间」。
6. `desc` 段落之间是**只有制表符的行**，不是空行——见 SKILL.md 硬规则里的 MD010 那一条。
7. 二手转述帖（媒体号转发别人的实践）判 `maintenance_kind: reference` + `status: archived`、`compiled_into: []`，并在 Tensions 里点明「无一手链接、细节不可核」。

## YouTube（视频深读）

- `web_extract` 直接吃 watch URL：返回的 markdown 里带 `## Transcript` 段，即自动字幕全文。取法：`text.split('\n## Transcript\n', 1)[1].strip('\n')`。
- 页面文本同时缓存在 `~/.hermes/cache/web/www.youtube.com-<hash>.md`（含 `# Transcript`/`## Transcript` 结构），转录很长时从缓存文件取，别把几万字贴进聊天。
- 采集用 `capture <url> --kind video`；`youtu.be/<id>` 与 `youtube.com/watch?v=<id>` 归一到同一个 `url_sha256`，同一素材采两次会出现两行账本——`doctor` 按 slug 链取最新，不必手工去重。
- 深化流程：先拿到 meta（标题/作者/时长）、再取转录 → 落 frontmatter（`source_kind: video`、`extraction_backend`）+ Provenance（作者/时长/一手链接/发布时间）+ Why / Summary / Key Ideas / Evidence+Quotes / Tensions / Destinations + `## Extracted Text`（带 marker 的转录全文）。
- 讲稿类视频的引文抓「作者原话 + 他自认的边界」（现场没跑通的 demo、承认没人真用的功能），比复述架构更有价值。

## 书 / 长 PDF（免费电子书类正本）

- `capture` **抓不了 PDF**（trafilatura 不解析）；直接 `web_extract` 传 PDF URL —— 返回 head+tail 窗口，**全文落** `~/.hermes/cache/web/<host>-<sha>.md`（几十万字符也不怕，不用贴进聊天）。
- 正本的 `## Extracted Text` = 从该缓存**按行区间择取**的关键节选（序言 / 阅读指引 / 关键章开篇 / 收尾章），行间省略用一条 HTML 注释标出；**不重写任何字**。
- frontmatter 写清 `source_kind: book`、`extraction_backend: "web_extract(PDF) → 全文缓存择段"`、以及一行 `extraction_noise:`（说明节选范围与全文缓存路径），让任何人能回到原书复核。
- 引文照旧用 `> ` 且由脚本从缓存按锚点切片写入（先在归一化文本里 `find(start)`/`find(end)` 断言命中再替换），不手抄。

## Substack

- `capture` 会被 Cloudflare 403（`HTTPError: HTTP Error 403`，落 `extraction: failed` 的 stub，exit 3）。这是预期，别反复重跑。
- 正文走 `web_extract`：整页文本会缓存在 `~/.hermes/cache/web/<host>-<sha>.md`（含订阅框、点赞数、头像、图片与评论）。从缓存里**按行区间择取正文段**，把订阅/计数/头像/图片行（非正文的页面 chrome）去掉，并在 Provenance 里写明「择取了哪段、去掉了几行」——不要就地清洗段内字节。
- 评论段也留在同一缓存里（`#### Discussion about this post` 之后），是天然的「读者反例」来源：按 permalink `/comment/<id>` 引用，写成行首带链接的 bullet。
- 正文里若以 `![]` 开头的图片行留在正文段内会触发 markdownlint（`sources/research|references/` 不在排除名单），择段时一并去掉并在 Provenance 注明。

## 图片型线程（正文在图片不在文字）

- 症状：`capture` 只得到一行 hook（如「N ways to …:」），其余全是时间戳/其它人的回复噪声 → 正文在所附 media 里，`trafilatura` 拿不到。先用 `ghc-search`（x 引擎）确认「作者自己后续没有续帖、内容在图片中」，再去取图。
- 取 media 清单（两条都可，无需登录）：`curl -sS 'https://api.fxtwitter.com/<user>/status/<id>'`（`tweet.media.photos[].url`，`?name=orig` 是原图）或 `curl -sS 'https://cdn.syndication.twimg.com/tweet-result?id=<id>&token=a'`（`entities.media`）。
- 单张**纯文本长截图**（一条 prompt / 一段命令清单铺满整图）可直接 `tesseract --psm 6 -l eng` 转录：比逐图 `vision_analyze` 快、可重跑、产物落文件；代价是 OCR 对连字符、引号、商标符号（`vitest™` 这类）会出错，逐条列进 `extraction_noise`。有排版结构（多栏、表格、代码缩进）的图仍走 vision 逐图转录。
- 下载原图到 scratch → `vision_analyze` 逐图转录（每图一问，要求「只输出逐字转录、保留编号结构、模糊处标 [?]」）→ 写进 `## Extracted Text`，并把**原图 URL 逐条写进 Provenance**（转录是机器产出，必须留回源路径）。
- frontmatter 记 `extraction_backend: "trafilatura（仅首帖一行）+ fxtwitter media → vision 逐图转录"` 与一行 `extraction_noise:`（列出疑似原文拼写错误/裁切处）。这类 note 不写 `> ` 引文（转录不构成逐字核验），引文改用 bullet；**因此 `verify-quotes.py` 报 `0/0 quotes verbatim` 是预期结果，不是失败**。收尾前把转录文本按图分段写进 `## Extracted Text`，并把原帖自己的那行文字（trafilatura 抓到的那句）逐字保留在转录之前；trafilatura 顺手抓来的他人回复/时间戳噪声直接丢弃，并在 `extraction_noise` 里写明。

## X / Twitter thread

- 主帖 URL 用 `capture --kind x-thread`；**同帖 self-reply 要单独 capture、单独核验**（主帖抓取不含回复），引文写成行首带 status URL 的 bullet，不要写成 `> `（`verify-quotes.py` 只认本笔记的 extracted text）。
- **回复的 status URL 怎么找**：x.com 在无登录浏览器里直接 403（`chrome-error://chromewebdata` 页，报「您未获授权」），别在浏览器里反复试。改用 `ghc-search` 的 x 引擎定位：`ghc_search.py x --handle <作者> --from-date <日期> "<线程主题>，这条线程后面还有作者的补充回复吗？给出各帖 status URL 与逐字原文"`。
- **ghc-search 的输出只当线索**：它是模型转述/召回，URL 与原文都必须再用 `capture` 落到 scratch（`OBFLOW_VAULT` + `READ_LATER_LEDGER` 指 scratch）逐字核对后才写进笔记；核不上就丢掉那条，别把转述当引文。
- **读者回复也值得采**：当回复构成实质反例（如指出产品能力边界、与作者自述冲突），一起 capture 下来写进 Tensions —— 只留作者自述会把 vendor 宣传当成结论。
- **二手转述/翻译帖：先找回正本再提炼**。中文 X 圈的摘要或翻译帖经常**不给原文链接**（或只给一句「原文来自…」）。做法：把帖子的主题词 + 站点线索交给 `web_search` 定位一手文章 → `capture` 正本 → 正本进 `sources/research|references/` 并做完整提炼；转述帖只 `move` 到 `sources/clippings/<year>/` 且 `status: archived`，头部写「正本：[[...]]」，把**转述与原文的差异**（被压掉的结论、被强化的数字、省略的方法论章节）写进它的 Tensions。不要把二手帖当正本重复提炼同一事实。帖内自称「原评论」/「我在这篇文章下面写的」时，去**该文章页面**核对（文章页 HTML 的评论区常含评论全文，可直接当证据留档），并把归属写对：评论者是读者、不是文章作者，正本仍是那篇文章。

## 厂商文档站（正文丢结构 / 文章已改版）

- 症状：`capture` 报 `extraction: ok`、正文也在，但**代码块、表格、小标题全没了**（trafilatura 在文档站只留正文段落）。别凭记忆在笔记里补结构，也别因此把 `extraction` 改成 failed。
- 先找该站的 markdown 出口：不少厂商文档站（code.claude.com、Mintlify / Docusaurus 系）支持 `<page_url>.md` 直接返回源 markdown（带 frontmatter 的 `lastModified`），也有 `/llms.txt` 列出全部页面。拿到后落 **`assets/sources/<slug>.md`**（vault 闸门实测 0 新 finding），笔记 Provenance 给路径 + 前 16 位 sha256，让读者能回到带代码块的版本。
- `## Extracted Text` 用哪份取决于要不要引结构内容：只引正文段落时用 capture 文本（引文直接按锚点切片，开箱过 `verify-quotes.py`）；**要引代码块/表格时改用 asset 全文当 extracted text** —— `verify-quotes.py` 只认本笔记自己的 extracted text，两份文本混着引必然失配。
- **正文可能已经不是当初那篇**：`curl -sS -o /dev/null -w '%{http_code} %{redirect_url}' <url>`（同短链解法的探针）能看出文章是否已搬家或被重写进产品文档；页面自己的 `lastModified` 也是证据。与二手帖的推荐描述冲突时，在正本 Provenance 与二手帖 Tensions 各记一处，别只改一边。

## 站点机器翻译版（capture 报 ok，正文却是译文）

- 症状：`capture` 报 `extraction: ok`、正文完整，但**语言/版本不对**——站点按 `Accept-Language` 把 AI 翻译页当默认出口（`/en/posts/…` 这类路径、页面上的机器翻译声明是线索），trafilatura 拿回的是译文。译文不是正本：改帽句、抹掉作者自称与限定语，引用它等于引用二手转述。
- 判断法：正文语言与站点 / URL 语言不符，或页面自带翻译声明。**不要**把它当抓取失败改 `extraction: failed`（内容确实拿到了），也不要自己把译文翻回去当正文。
- 修法：`curl -sS -H 'Accept-Language: <原文语言>' <url> -o page.html` 抓同页 HTML → trafilatura 重抽 → 用这份当 `## Extracted Text`。两份都留档（译文页 / 正本页 HTML / 抽取文本，各自 sha256）。
- frontmatter：`extraction_backend: "trafilatura（capture 拿到站点 EN 机器翻译）→ 同页 zh-CN 正本 curl + trafilatura 重抽"`，`extraction_noise: "本笔记 extracted text 是站点 zh-CN 正本；capture 产出是 AI 英译，仅语言不同、无正文缺漏"`。引文从正本语言版按锚点切片。

## GitHub 仓库（README 正本）

- 症状：`capture <github repo URL>` 拿到的是 **GitHub 渲染页**——页内链接被改写成 `https://github.com#install` 这类断链、代码块与表格丢失。它只能当对照证据，不能当 `## Extracted Text`。
- 正本取法：`curl -sSL https://raw.githubusercontent.com/<owner>/<repo>/<branch>/README.md`（先试 `main` 再试 `master`；404 就换分支，别猜），落 evidence 目录。同时用 `https://api.github.com/repos/<owner>/<repo>` 取元数据（stars / created / pushed / license / **description**）。
- 规范化只去装饰、不动文字：不落行徽章（`^\[!\[`）、图片行（`![`、`<img`）、`<div align=center>` 一类包裹与 `<p>`/`<br>`，`<h1>` → `# `、`<strong>` → `**`；**不做空行折叠**（code fence 内的空行要保真）。落完把规范化文本 `sha256` 记进笔记 Provenance。
- `## Extracted Text` 以 marker 行开头，然后才是 README 正文；引文按锚点从**这份规范化文本**切片（不要从 GitHub 页或 capture 版引）。
- **汇总帖 → N 正本 + 1 条帖本身**（SKILL.md 硬规则）在 GitHub 场景的落地：N 个仓库各 `capture`（记录进 ledger、满足幂等）→ 把 draft 的 head 换成完整提炼、`move` 到 `sources/references/<category>/`，帖本身 `move` 到 `sources/clippings/<year>/` + `status: archived`。帖内逐条对账表用**「仓库 description vs README 的 Limits/证据表」**找差——偏差常出现在仓库自己把定位写成 A、帖里只讲 B，或帖里的「不可否认」被 README 的 Limits 打折。
- **引用帖（quote tweet）**：主帖 URL 的 capture 有时不含被引帖（有时含、但混在正文里）。要判定：`curl -sS https://api.fxtwitter.com/<user>/status/<id>` 看 `tweet.quote`，或 `curl -sS 'https://cdn.syndication.twimg.com/tweet-result?id=<id>&token=a'` 看 `quoted_tweet`。
- **`x.com/i/article/<id>` 长文取不到**：`capture` 报 `ExtractionError: trafilatura produced no text`（exit 3）、`web_extract` 报第三方数据源不服务该 URL。别反复试；在 Provenance 写明「正本在登录墙后、未取到」，并把由此产生的不可核点（例如图内 prompt 的原始作者无法确认）写进 Tensions。
- **图内 prompt 的转录**：带排版/行号栏的卡片走 `vision_analyze` 逐图转录（去行号栏与标题/导航装饰，记在 `extraction_noise`），再用 `tesseract --psm 6 -l eng` 交叉核对——**逐 token 比对两份机器输出**并把差异逐条写进 `extraction_noise`（常见：`paw`→`raw`、项目符号 `+` vs `·`、`Links.` vs `links.`、图标行/品牌区识别失败）。转录不参与 `> ` 逐字引文（引文只取帖文那几条），两份原始输出都进 evidence。
- **读者回复**：用 `ghc-search`（x 引擎）定位 status URL 是线索、必须回 scratch（`OBFLOW_VAULT`+`READ_LATER_LEDGER` 指 /tmp）`capture` 逐字核验；**查下来没有实质反例也要写进 Tensions**（「已查 N 条，无实质反例」比留白有用）。回复页的 capture 会把父帖 + 引帖 + 回复混在一段里，锚点取回复首句、取到段尾即可。
