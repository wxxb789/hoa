# 批量 thread 扫尾与中断续跑

素材帖攒成一批后有两类活：把一批 thread 的标题/状态补正（扫尾），以及把中途断掉的帖接上（续跑）。两者都是**确定性为主**的批量作业，靠脚本 + 队列，不靠模型逐条手工操作。

## 1 盘点与改名

- 盘点正本 = 平台 REST + 本地 `state.db`：逐 thread 读回真实 `name`，与本地 thread→session→素材笔记的映射一起写成 `rename_plan.json`（old → new + 笔记路径），逐条执行并把每条的 rc 写进 `rename_log.json`。
- **改完再读回全量核对**：默认名（`Analyze <url>` / 平台名 / 作者 handle）剩余数必须为 0。「命令没报错」不等于改成功。
- 标题格式：`[<档|主题>] <20–60 字中文，主题 + 素材性质>`。同一素材落进两个 thread（兄弟 thread）时，第二条加 ` #2`。
- **archived thread 改名会被拒**（`50083 Thread is archived`）：`PATCH {"archived": false}` → 改名 → `PATCH {"archived": true}`，三步单独记一份日志便于失败重跑。
- **channel 改名走 channel-PATCH 路由桶限速**：批量串行也照样吃 `429 retry_after 100~400s`。失败条目进重试清单、限速窗口过后补——别当失败丢掉，也别并发硬撞。
- frontmatter 解析别用 `\s*` 做键值分隔（`\s` 含换行）：`category:` 这类空值键会把下一行 `tags: [...]` 吃成值，产出的标题直接是错的。用 `[ \t]*`；已经改错的标题要改回真标题并重新读回。
- 确定性部分（盘点 / 改名 / 重试）应沉进该 pipeline 的 CLI 子命令，别让模型逐条手工调 REST——轮次与限速都耗不起。

## 2 中断续跑：复用原 session，不发消息催

- **bot 往自己的 thread 发消息唤醒不了该 thread 的 session**（全舰队同一个 bot user，只有 owner 的真人消息会触发）。测试期发的探针消息要删掉，别留在 owner 的目录里。
- 可行路径是复用原 session（上下文与工具历史都在）：
  `hermes -p <profile> chat --resume <session_id> --query-file <续跑-prompt.md> --oneshot -Q`
  （`--max-turns` 不许给——resume 继承网关会话策略，给了会被拒）。
- 续跑 prompt 必须自带四件事：
  1. **重建时间线**：`state.db` 按 `thread_id` 查该帖的 session 与素材，读上一次回报里「未完成 / 续跑锚点」那一节——那就是剩余清单。
  2. **只做剩余步骤**：已完成且已过闸门的部分不重做（不重复 capture、不重写已落库笔记）。断点常落在「产物已落盘、收尾未做」之间，重跑全文等于白烧一轮。
  3. **闸门在本次 session 现场重跑**（引文核验 / 笔记审计 / vault 结构 / markdownlint），不引用上一轮的结论。
  4. **收尾**（下两条 + 改标题 + 补档位 reaction）。
- 首行固定 `THREAD <id> DONE` 或 `THREAD <id> PARTIAL: <还差什么>`，便于批量收集；**不许编造未做的步骤**，做不动就如实写缺口。
- **本次 turn 的最终回复网关会自己发进 thread**（resume 保留着 origin chat 的投递绑定）→ 再 `hermes send -t discord:<thread_id> "<报告>"` 就是重复一条。所以：把报告**直接写成最终回复**，再读回 `messages?limit=2` 确认最新一条就是它；只有读回里没有才补 `hermes send`。
- **在 profile home 起的 session shell 里 `hermes send` 要先清 `HERMES_HOME`**：那个 shell 的 `HERMES_HOME` 指向 profile home，其 `.env` 没有平台 token → 裸跑报 `Platform 'discord' is not configured … scoped to profile home …`（看着像 Discord 没接上，其实凭据在根 home）。用 `env -u HERMES_HOME hermes send …`；读回消息用带 `dotenv` 的解释器（裸 `python3` 会 `ModuleNotFoundError: dotenv`）。
- **串行**，且进每条之前检查：该 thread 近 30 分钟没有别的 turn 在跑（owner 可能在同一帖自己扫尾 → 双写同一个 session）、同时在跑的 session ≤2。

## 3 待补救（停在 `captured`）按「负责 thread」收口

同一批素材的第二类断点：产物落了 draft、账本停在 `captured`，素材自己的 thread 里什么都没发生。收口方式与续跑同源（复用原 session），差别在**分组**：

- **先盘点成表再动手**：每条停在 `captured` 的素材挂两个键 —— 入口帖 URL 与**负责的 thread**（有独立 thread 的按 thread；无 thread 但属于某个整站批的，归到那个批 thread）。输出 `recon.json`（素材 / 负责 thread / 依据），后面每一步都从这张表取。
- **按负责 thread 分组，不按素材**：一个 thread 一次 `--resume`，组内多条素材一起交。按素材派会把同一个 thread 派出 N 次，N 个 session 互相踩同一个会话。
- **在被补救素材自己的 thread 里做**（owner 规则）：报告由该 turn 的最终回复自动投进那个 thread，不要发到讨论 thread 或晨报频道。
- **已落库、只差账本终态的：prompt 明确要求只做对账**（补 `status` / `compiled_into` / 收尾），不重写笔记、不重跑 capture —— 否则每条素材都要重新烧一轮。
- **账本停在 `captured` 有两种真相，先分再动**：① thread 里已有 DONE 报告、笔记也已落库 = 只是账本没终态 → 只做对账；② 那个批本身就只做了一半（整站批常见：capture/extract 全完、distill 未做）→ 是继续干活，不是对账。混为一谈会把 ② 报成「已完成」，或把 ① 白烧一整轮。分别盘一遍 thread 报告与账本行再分组。
- **与续跑 lane 去重**：已被续跑队列覆盖的 thread 从补救队列剔除；一条 thread 同时只能有一个在跑的 turn。
- **查不到归属 thread 的（早期分享链、被归并的批）先攒成清单交给 owner**，别擅自开花；处置是选项题（各自开新 thread / 只做账本终态 / 归入某批），不是默认动作。

## 4 批量 lane 的生命周期

- **队列落盘才有重启能力**：`queue.json`（每条 `done` / `rc` / `skip`）+ 每条一份 `logs/<thread_id>.log`；驱动幂等（只跑 `done=false`）。**先单条跑通再放全队列**。
- 驱动本身是 gateway 的子进程，且每条 resume 的 turn 也经网关传输 → gateway 重启只打断**当前那条**，不是全队列。重启后重跑驱动即可续（幂等 → 不重复劳动）。
- 断点核对三件：驱动 exit code、`ps` 里有没有 `chat --resume` 进程、`queue.json` 里最后一条的完成时间戳。
- 产物与日志全落盘，别只留在终端 stdout——终端会被 gateway 重启或超时截断，队列在文件里才捡得回来。
- **supervisor 的「剩余」口径必须和 lane 自己的过滤一致**：lane 会跳过 `in_other_lane` / `skip` / `attempts>=N` 的条目，supervisor 若按「`done=false` 计数」判剩余，就会把 lane 永远不会碰的条目算成待做 → 空转满 N 轮再退出（看着像「跑完了但什么都没做」）。两处共用同一个 todo 表达式。
- **队列去重键是 `(thread_id, url)`，不是 `thread_id`**：同一个 thread 里后来才暴露问题的单条 URL（典型：账本行停在 `captured`），按 thread 去重会被「这条 thread 已在队列里」挡掉，永远补不到。重开一条已 `done` 的条目要同时重置 `done=false, attempts=0` 并写 `reason`（如 `ledger-captured`），日志才能说明它为什么又回来了。**改完队列要重启 supervisor**：lane 在启动时读一次队列，跑着的 supervisor 要到下一轮才看得见新条目。

## 5 网关重启后的续跑：先 `discard`，再 `resume`

网关重启会把正在跑的 turn 打断，留下两件必须处理的残留物：

- **`unknown` admission → session 处于 paused**：`hermes chat --resume <id>` 会打印「This chat is paused … type /discard <id>」并**直接退出**（非交互 = 白跑一条队列项）。先解除：

  ```bash
  hermes -p <profile> sessions discard <session_id> --yes
  ```

  （`hermes sessions discard --help`：崩溃后丢失的 turn 被 fence 成 unknown，挡住整个 session；这是 `/discard` 的非交互形式，不重放丢失的输入。可以 `--admission ID` 指定，默认全清。）
  判据：`select status, count(*) from session_admissions group by status`（state.db，只读）——`unknown` 就是待 discard 的，`target_session_id` 即对应 session。
  驱动里应在 `--resume` 之前无条件跑一次 discard（没东西可 discard 时会打印 "Nothing to discard"，幂等、无副作用）。

- **上报口径**：paused 的 thread，其最后一条可见消息停在 `⏳ 正在处理——N 分钟 — 第 M/90 轮迭代 …` 或中途旁白，**没有收尾报告** → 扫尾盘点的判据就是「最后一条之后没有 ≥350 字符的 bot 报告」（细碎的状态行/改名回显/`💾 自我改进回顾` 通知都不算报告）。

- **并发闸别设得比网关本身低**：网关自己常驻 ~5 个并发 turn，`wait_for_slot(max_active=4)` 会永远等不到槽位（实测驱动空转 20 分钟、一条都没启动）。闸值取网关并发 + 余量（本次 8），或直接读同一时刻的活跃 turn 数。
