# 测量每轮真实 prompt，再动优化

instruction 文件只是每轮成本的一部分，通常还不是最大的一块。别靠读文件猜，取实测：

## 取 ground truth

- 真实 prompt 存在运行时的持久化记录里（常见是 SQLite 的 `system_prompts` 表：
  `select length(prompt), prompt from system_prompts order by rowid desc limit 1`，只读 URI 打开）。
- 单位要统一：**字符**与**字节**别混进同一份报告（CJK 1 字符 ≈ 1 token；`wc -c` 的字节数对 CJK 会放大 3 倍）。
- 用 marker 找分段边界（项目上下文块 / available-skills 块 / memory 段 / user-profile 段 / 运行时环境段），对分段做差。
- 先量一份自己的样本（例如 preamble+identity、protocol、skills 清单、memory+user 四项），把占比写下来，再决定砍哪块。

## skills 清单通常是最大可削减块

- 当前注入集合通常有快照文件（skills prompt snapshot）；每个技能的使用计数在 usage ledger。零使用 = 候选。
- 剪枝走运行时的 disabled-skill 列表（按 name 或 load_name 匹配），**root 与每个 profile 的 config 都要设**（profiles 不继承）。
- 实测效果举例：126 → 52 个技能，skills 块 −57%，整份 prompt −35.5%，行为零变化（eval 全过）。你自己的数字以实测为准。
- 只从 prompt 摘除，文件保留，恢复 = 从 disabled 列表里删名字。把恢复命令写进 owner 的状态文档，否则三个月后没人知道怎么加回来。

## 验证

- 跑一次无意义 one-shot（`<runtime> -z '只回复 ok'`），再量最新 prompt 记录：剪掉的名字消失、保留的名字还在。
- 限制工具集的会话（例如只给 web 工具）会得到另一份 prompt 变体（可能没有 skills 块）。**只和同 hash 家族比**，否则会把工具集差异误报成回归。

## 追加式文档的陷阱

- 按时间追加的长文档（overrides / changelog 式笔记），顶部一定过期（旧模型名、旧 profile 数），agent 从上往下读就先拿到错事实。
- 重构为：顶部 `当前状态（唯一事实源）` 表 → 历史在下 → 被覆盖行标 SUPERSEDED。

## 双写规则要漂移守卫

跨层重复的规则不能靠自觉。一个脚本每日检查：profile 数量、protocol 里写的模型名 vs 实际 config、
disabled 列表各 profile 是否一致、identity 文件双写关键词是否还在、workspace 下有没有会抢占的
overlay 文件。健康静默，漂移才出声（no-agent 定时任务 + 投递）。
