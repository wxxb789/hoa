# 对话「卡住了」：先分清暂停 / 长 turn / 写锁争用

同一个抱怨（“很多 thread 的对话停掉了”、“全都卡住了”）有四种完全不同的因，处理方式相反。
**先定性，再动手**：把某个真的暂停的会话 discard 掉之前，先确认它是暂停，而不是正在跑一个长 turn。

## 四分法（全部只读）

```sql
-- 1) 有没有被暂停的会话
select target_session_id, status, outcome, generation from session_admissions
where status in ('unknown','queued');
-- 2) 谁在跑、租约是不是活的
select conversation_id, holder, datetime(acquired_at,'unixepoch','localtime'),
       datetime(expires_at,'unixepoch','localtime') from session_turn_leases;
```

```bash
# 3) 每个会话最后在干什么（API 轮次 / 工具耗时）
grep -oE '\[[0-9]{8}_[0-9]{6}_[a-z0-9]{6}\]' ~/.hermes/logs/agent.log | tail -200 | sort | uniq -c
awk '$0 >= "<HH:MM>"' ~/.hermes/logs/agent.log | grep <session-id> | tail -5
# 4) 争用与上游信号
grep -E 'write lock unavailable|lease refresh|Clean EOF|prefetch timed out' ~/.hermes/logs/errors.log | tail
```

| 观测 | 定性 | 处置 |
|---|---|---|
| `session_admissions.status='unknown'` 存在 | **真的暂停**（网关被 SIGKILL 时在跑的 turn 丢了） | `/discard` 或 `hermes sessions discard <id> --yes` |
| `unknown` 为空，`started` 有行，lease 的 holder 是**当前 MainPID** 且 `acquired_at` 很近 | **长 turn**，不是卡死 | 什么都不做；看工具耗时与排队消息数，向 owner 报“在跑第 N 轮、这轮已 M 分钟” |
| 同一时段出现 `state.db write lock unavailable for 20s`、`lease refresh hit a SQLite lock`、`lease refresh stayed locked through its lifetime` | **写锁争用**：多个重 turn 同时写一个库 | 减并发；库维护排到空闲窗口 |
| `Clean EOF, no finish_reason`、`holographic prefetch timed out after 8.0s` | 上游流截断 / 记忆预取超时 | 单次无动作；成片出现才当故障 |
| thread 有消息但**没有对应 session 行**，标题还是网关占位名或原始 URL | **从未开过会话**：被并发上限拒收（那条 thread 收到 `at the active session limit (N/M)`）或建 session 前就被杀 | 不在暂停之列；按 `references/paused-conversations.md` → *Batch repair* 从零重建 |

## 长 turn 才是最常见的“全都卡住”

一个 turn 里跑一次全量测试（前端 e2e、浏览器测试常常 200–300 秒）时，这个会话在 Discord 里表现和卡死完全一样：
不回复、你后面发的消息全部排队。判别只看两行日志：`API call #n` 与 `tool terminal completed (308.02s, …)`。

- 报给 owner 的应当是进度而不是“卡了”：第几轮 API、这轮哪个工具、已耗时多久、队列里还有几条。
- 真正的修法在写 turn 的一侧：分钟级的测试/构建丢后台并轮询，不要在前台阻塞（见 `hermes-operations`
  与 goal 流水线里的同名规则）。
- `session_turn_leases.expires_at` 只是租约上限，不代表业务进度；不要因为它接近到期就判死。

## 为什么被杀之后会话会暂停

被杀那一刻在跑的 turn 变成 `session_admissions.status='unknown'`（丢失、未重放），
它的后继消息是 `status='queued'`。Hermes 故意暂停这类会话，避免重放一个可能已经执行过的 turn。
用户看到的是：`⏸️ This conversation is paused: a previous turn did not finish when Hermes restarted`。

`handoff_state` 是空的不代表没卡；`session_turn_leases` 里 holder 的 pid 是**旧网关 pid** 才是特征。

`gateway.log` 里 `gateway.session_authority: Session <id> paused: <reason>` 直接给了原因，不要从现象猜：

| reason | 含义 | 处置 |
|---|---|---|
| `unknown_execution` | 崩溃时正在跑的 turn 丢了 — 真暂停，有 `unknown` admission | `/discard` 或 `hermes sessions discard <id> --yes` |
| `runtime_draining` | 计划内停网关/重启时那个 turn 被 drain | 什么都不用做，重发即可；不会留 admission |
| `not_found` | 运行时 store 里已没有这个会话 | 看同一秒的 adapter 日志，多半是平台断连 |

`paused: not_found` 常和平台抖动同秒出现：`[Discord] Discord Gateway WebSocket … socket_closed` →
`transport closed; forcing reconnect` → agent 的回复两次 `send_path_degraded` 失败，那条回复就永久丢了。
这类会话本身没坏，是「回复没送到」，所以 `discard` 会回 `Nothing to discard`——别把它当命令失败。

## 恢复

- 在对应聊天里发 `/discard`：丢弃丢失那一轮（不重跑），排队消息继续执行。
- 等价的非交互形式：`hermes sessions discard <session_id> --yes`（`--admission <id>` 可只丢指定一条）。
- `/reset` 只在新会话可接受时用，会丢上下文。
- 放行前先想清楚：如果那个会话是 goal-driven 开发任务，`/discard` 会让它立刻继续动手。
- **`discard` 只认 `unknown`。** 只剩一条 `queued` 的会话会回 `Nothing to discard … no unknown admission`，
  而这条排队项只能被**来自该 chat 的新输入** fence 掉（`run_inbound` 会 fence route 并 cancel 排队中的
  messaging admission）。也就是说这类会话必须由 owner 在那个 thread 里发一句话或 `/new` —— bot 自己发的
  消息不算，也没有 CLI 子命令能替他做。报给 owner 时给这一步动作，不要声称「我已经 resume 了」。
- `hermes sessions repair-routing` 是只读报告；`N orphaned session(s) found, none unambiguously
  repairable` 是正常结论（要求同 key 的前驱在 900s 内静默才敢改判），不要为了「修好」加 `--apply`。

## 防护（系统层，不动硬件）

`ManagedOOMPreference=omit` **不保证**免杀：实测 cgroup 上 `user.oomd_omit=1` 已写入，
`systemctl --user show -p ManagedOOMPreference` 也回 `omit`，oomd 仍然选了网关。不要把它当护栏。

有效的是两条一起上：

1. **抬高 slice 压力阈值**（立刻生效，无需重启网关）：
   ```bash
   sudo systemctl set-property user-1000.slice ManagedOOMMemoryPressureLimit=90%
   # 持久化：/etc/systemd/system/user-1000.slice.d/50-oomd-pressure.conf
   ```
   该属性在 `systemctl show` 里显示成字节（90% → 3865470566），别按百分比去读。
2. **收紧 worker 上限**（下次网关启动生效）：worker scope 由
   `tools/process_registry.py` 用 `systemd-run --user --scope --property MemoryMax=…` 创建，
   取值 `min(TERMINAL_LOCAL_MEMORY_MAX_MB, 网关 memory.max, 物理内存一半, 4GiB)`。
   把 `Environment=TERMINAL_LOCAL_MEMORY_MAX_MB=2048` 写进
   `~/.config/systemd/user/hermes-gateway.service.d/30-worker-memory.conf`，让吃内存的 executor
   在自己的 cgroup 里先 OOM，而不是拖垮网关。
   **不要为了让它生效立刻重启网关**：正在跑的 turn 会再死一次，问题原地复现。等空闲再重启。

## 写锁争用的善后（只排进空闲窗口）

`state.db` 到几百 MB、`-wal` 涨到几十 MB 时，`synchronous=FULL` 下每次提交都要落盘，
三四个重 turn 并发时它会互相把写锁拿到 20 秒。两个命令都会卡住：`hermes sessions optimize` 在网关
持有库时直接拒绝，`--force` 又会在重写期间让所有 agent 拒绝接活；真正的空间杠杆是
`hermes sessions optimize-storage`（把 FTS 重建为紧凑布局再 VACUUM，可中断重跑，不动会话数据）。
所以这是**停网关的维护窗口**，不是后台任务：停网关 → `optimize-storage` →（可选）prune → 起网关 → 验证。
从网关自己服务的会话里停网关会杀掉当前 turn，要用 `systemd-run --user --on-active` 起一个带
`trap` 恢复网关的脚本；完整步骤与判据见 `hermes-operations` → `references/session-data.md`。
干净 `systemctl --user stop` 不会产生 `unknown`，只有 SIGKILL 才会——计划内重启不会暂停任何会话。

## 验证

```bash
systemctl show user-1000.slice -p ManagedOOMMemoryPressureLimit   # 90% 应显示成 ~3.86e9
systemctl --user show -p Environment hermes-gateway.service | tr ' ' '\n' | grep MEMORY
# unknown 计数应为 0；started 有值说明在正常工作，不是卡死
```
