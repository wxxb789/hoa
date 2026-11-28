# Decision execution prompt (one file per approved decision)

Handed to `agent-dispatch.py start --prompt <this file>` for the bot that owns the work. Fill every
<angle> slot; keep the approved wording verbatim so the landed diff is comparable to the decision.

```
你是 <线>（profile `<bot>`）。owner <date> 已批准下面这些，本任务 = **执行**，不要再问 owner。

## 硬边界（越界即停手，只写报告）
- <禁止的资金 / 生产 / 发布 / 删除 / 下单动作>
- 不改 <不在本次批准内的文件、状态字面量、schema>
- 需要超出本范围的改动（新 cron 条目、config、schema 升版）→ **不要自己加**，写进报告「待批」段并附精确 diff
- 不 commit / 不 push（除非该仓的同步规则明确如此）

## 批准原文（逐字；执行范围以它为准）
> <owner 选定的选项文本，含他看到的「优 / 劣 / 回滚」>

## 任务
1. <可自证的动作：读什么、改什么、写什么文件>
2. <同上>

## 交付物（必须落盘，禁只写聊天）
- 报告：`<task dir>/exec/<decision>-report.md`
  段：① 做了什么（文件路径 + 命令 + 输出）② gate / 测试的真实输出 ③ 未做 / 失败项（禁美化）
  ④ 待批项（精确 diff）⑤ 残留风险
- 每个新增 / 修改文件的路径 + `sha256sum`

## 自证（必须真跑，不是描述）
- `ls -l` + `sha256sum` 新文件；`git -C <repo> status --short`；相关 gate 命令的真实退出码
- 失败即停：恢复原状态，把候选留在任务目录，报告写明卡在哪

跑完只输出一行结论 + 报告路径。
```

Then: `--expect <task dir>/exec/<decision>-report.md`, a unique `--unit`, background + notify, and
confirm the unit is live before reporting the delegation to the owner.
