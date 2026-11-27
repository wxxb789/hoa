# Channel topology research — channel vs thread vs forum

用来回答"我该开几个频道"。结论先行，然后是可引用的事实，最后是什么时候该换另一套。

## 一句话原则

> **Channels represent stable contexts. Forum posts represent durable work items.
> Threads represent temporary execution.**

任务对象与容器分开：容器（channel）少而稳定，工作项（thread / forum post）多而短命。

## 什么时候一个项目"配"一个频道

只有满足下列之一才单开频道，否则就是 channel sprawl：

1. 权限 / 可见性不同（人不同、能看的范围不同）
2. 持续高噪声，会淹没共享频道
3. 内部有多条同时推进的工作流
4. 需要专属集成（webhook、语音、外部 bot）
5. 独立的团队或节奏（有自己的人、自己的例会）

频道多起来后的典型熵增：`#todo` `#doing` `#done` 三个频道、一个项目拆出 `-alerts` `-voice`、
名字用了一段时间就与内容脱节。状态用标签/改名表达，不用新频道。

## 命名法（最容易落地的一条）

```
[WIP]     auth-token-refresh      | claude
[BLOCKED] stripe-webhook-retry    | codex
[REVIEW]  migrate-users-table
[DONE]    fix-null-avatar
```

- 状态前缀放最前（扫读/排序都靠它），第二个是短 slug（与分支、PR、ticket 同名），最后才是执行者。
- **改状态就改名字**——这一个习惯做掉大部分跟踪工作。
- 首行写进 thread 正文，与分支/PR 标题一致，两个方向都能跳。

## 索引要外置

一条 pinned 消息或一张看板，只留四列：`任务 / 状态 / thread 链接 / 最后更新`。改写时机：开始、阻塞、结束。
链接而不是描述；索引与 thread 名冲突时以索引为准并修名字。

不需要独立 dashboard：论坛频道自己的排序/筛选就是控制面。需要机器可读的精确状态时（SLAs、租约、负责人），
状态放数据库/仓库，不要只靠标题和标签。

## 反面清单

- agent 不得自动建频道；允许它建 thread / 论坛帖。
- 不把 agent 的原始 tool 输出、思考流灌进 Discord——一条有用的更新是"结论 + 数字 + 产物链接"。
- 完成后归档/锁定，不删除（日志还有用）。
- 不试图用频道层级表达 项目→任务→子任务；层级要一层（项目帖）或零层（thread + 标签）。

## 另一套形态（何时该换）

**外部系统做 SSOT（Linear / GitHub Issues / 自建 task 表），Discord 只是输入输出面。**
判据是数量级：月任务几十个以内，thread/post + 一个索引就够；上百个、多人协作、要依赖关系与验收门禁时，
任务对象必须住在外部系统，否则聊天记录就是唯一真相，而这从来撑不住。

## 出处

- Discord Threads FAQ — https://support.discord.com/hc/en-us/articles/4403205878423-Threads-FAQ
- Discord Forum Channels FAQ — https://support.discord.com/hc/en-us/articles/6208479917079-Forum-Channels-FAQ
- Discord Threads Moderation FAQ — https://support.discord.com/hc/en-us/articles/4404809613847-Threads-Moderation-FAQ
- X/Twitter 实践面（多 agent 并行、状态前缀命名、单一索引、forum 当队列）——用 `ghc-search` 的
  `x` 引擎按 "thread per task / forum as task queue" 类查询取当时样本，结论比具体帖子稳定。
