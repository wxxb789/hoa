# hoa 库重构：扫描结果、技术选型、计划 v1

日期：2026-11-14 · 基线：`3131458` / VERSION 0.1.56 · 扫描脚本：`~/claw/tasks/2026-11-13/gdd-family-refactor/hoa-scan.py`（只读，输出 `scan.json`）

本文是**待审计的计划**，不是结论。审计方：GPT-6.1-sol（codex）与 gemini-4-carbon（pi），各自独立、只读、互不可见。

---

## 1 扫描结果（全部为本机实测数字，非估计）

| 指标 | 值 |
|---|---|
| skills | **59**（+ evals/ 触发评测、artifacts 契约注册表） |
| 总行数 | 10,116（SKILL.md 正文，不含 references） |
| 行数分布 | 中位 143 / p90 323 / 最大 516（`github-repo-management`） |
| >120 行 | **38 / 59** |
| 结构 | 31 有 `references/`、22 有 `scripts/`、**仅 6 有 tests**、18 纯散文（只有 SKILL.md） |
| 带脚本但零测试 | **16** |
| areas | software-development 46 / work-management 38 / self-management 10 |
| targets | runtime-agnostic 55、**hermes 3、pi 1**（枚举外） |
| kind | **entry 46**、mechanism 11、controller 1、stage 1 |
| 完全重复的正文/描述 | **0**（今天清掉的 `to-prd` 一类已消失） |
| CI | `.github/workflows/ci.yml` **33 个手写步骤**，逐条硬编码测试路径 |
| 契约注册表 | `external` 4 / `terminal` 5 / `shared` **0** |
| 仓内文档 | AGENTS.md、README(±zh)、docs/{evidence,goals,plans}/、agents/skill-scout.md；无 CONTRIBUTING、无 catalog spec |

### 1.1 从数字里读出的五个结构问题

1. **CI 靠手写清单，新测试默认隐身。** 33 步里每一步都写死路径（`skills/gdd/scripts/tests/run-gdd-selftest.sh`…）。今天新增的 `test-routing-inventory.py`、`test-provider-metadata.py` 都是我手动加进 ci.yml 才跑起来的；没人加就永远不跑。这是"机制依赖记忆"的典型形态。
2. **`kind` 字段事实上是死字段。** 46/59 是 `entry`，等于没分类。要么给它真实语义并让 CI 校验，要么删掉它——现在的状态是"看起来有分层，实际没有"。
3. **`targets` 枚举已经漏了。** `hermes 3 / pi 1` 出现在正式 catalog 里，说明有人（很可能是我）在不受校验的位置写了枚举外的值。要么扩枚举，要么归一。
4. **16 个技能发脚本但无测试；6 个技能有测试。** 这不是"测试不够"的道德问题，而是**契约问题**：技能对外承诺的能力里有可执行部分，但没有任何东西证明它在发布版本下仍能跑。
5. **重叠簇已成形，但没有裁决机制**：
   - `github-code-review` 481 + `github-repo-management` 516（同域两座大山）
   - `hermes-models` 278 / `hermes-updates` 127 / `hermes-context-file-loading` 168
   - CDP 三件：`m365-copilot-cdp`、`teams-cdp` + `scripts/shared/cdp.ts`
   - 写作-证据簇：`writing`、`evidence-backed-analytical-writing`、`grounded-citations`、`report-claim-audit`、`measurement-campaign-evidence`
   - 委派簇：`ai-coding-agent-delegation`、`delegated-work-acceptance`、`subagent-driven-development`、`omp-headless-orchestration`、`kanban-*`
   - hoa 自省簇：`hoa-introspect`、`hoa-introspect-distill`、`hoa-skill-review`、`hoa-skill-work`、`skill-library-curation`、`skill-porting-and-publishing`

---

## 2 技术选型：三条路，与建议的排序

### 方案 A（机械卫生）：让"忘了做"不再可能
新增 `scripts/run_all_tests.py`：自动发现 `scripts/test_*.py`、`skills/*/scripts/tests/*`、`skills/*/evals/*`、`evals/*`，逐条跑并汇总；`ci.yml` 从 33 步压到 ~10 步，其余交给发现器。同时：`targets` 枚举归一（`hermes`/`pi` → 合法值或扩枚举并写进 checker）；`kind` 要么给出 3 个有定义的取值并在 `check_frontmatter` 里校验，要么整个字段删除。

- 成本：1 个 PR，~300 行新代码（含测试）。
- 收益：新技能/新测试第二天自动进 CI；两个枚举字段不再漂移。
- 风险：发现器跑错东西（必须带超时、白名单、失败可诊断）。

### 方案 B（形态重构）：大技能拆成 controller + references
把最重的 6 个（`github-repo-management` 516、`github-code-review` 481、`subagent-driven-development` 447、`systematic-debugging` 429、`writing-plans` 345、`whisper` 323）+ 重叠簇，按今天 `gdd` 已验证的形态重写：入口 ≤120 行、阶段/主题进 `references/`、契约边（produces/consumes）在 registry 里闭合。

- 成本：6–12 个 PR，逐个都要 codex review（今天实测每轮 1–4 条真 findings）。
- 收益：入口可读、可组合、契约可检。
- 风险：**这是行为改动**，每个拆分都要重新验证技能仍可独立使用；重叠簇的合并需要 owner 判"哪个名字活着"。

### 方案 C（契约先行）：把 catalog 变成可机器校验的图
把"能测的都测、能检的都检"做成仓库能力：每个发脚本的技能必须在 `scripts/tests/` 里有夹具测试（或显式标 `untested: <理由>`），`check_contract_graph` 校验 artifacts 的生产者/消费者与终端豁免，`kind`/`targets` 枚举校验，`index` 双语一致，`references/` 里的相对链接必须可解析。

- 成本：1–2 个 PR 打底 + 每个技能的补齐工作（16 个无测试技能）。
- 收益：漂移在 CI 被抓，而不是在 21 轮 review 里被抓。
- 风险：一次性补齐 16 个测试的量不小；必须先立规矩再补，否则规矩会被绕过。

### 建议：**A → C → B**（此刻只做 A）
理由：今天 21 轮 review 的教训是"**没有被机械校验的东西一定会漂**"。C 是 B 的前置——先把校验器造出来，B 的每一次拆分才有机器判据（而不是又靠 codex 人工挑）。A 是 C 的前置，因为 C 要新增的检查若还靠手写 ci.yml 步骤挂上去，就重蹈覆辙。

**本轮先做 A**，C 在 A 合并后立刻接（同一批设计，分成两个 PR 让 review 面变小），B 等 C 的体检报告出来再排期——B 的清单应该由扫描器输出，而不是我现在拍脑袋列。

### 2.1 明确不做的
- 不合并 `hermes-*` 三件：它们对应三个不同的运维面（模型/升级/上下文加载），合并只会造一个 573 行的巨石。
- 不动 `gdd`（今天刚重构完，形态已经是目标形态）。
- 不为了压行数而删规则（AGENTS.md 的教训：拆文件，不删内容）。
- 不引入新依赖：全部 stdlib + 现有 `scripts/requirements.txt`。

---

## 3 请审计方回答的问题（两家相同，便于对照）

1. **A → C → B 的排序对不对？** 如果 C 应该在 A 之前／B 应该先做一块，请指出哪一步会卡住，以及证据。
2. **A 的发现器设计有什么坑？** 具体：并发与超时、失败隔离、哪些目录不该被发现（`scripts/shared/` 是 bun/vitest 而非 python 步骤）、如何避免"发现了但跑不动"的假绿。
3. **C 的校验清单里，哪一条最可能变成形式主义**（即：增加了 CI 时间却不改变行为）？请点名并给替代方案。
4. **B 的拆分判据应该是什么？** 给一条可机械判定的规则（例如"入口 >120 行且 references ≥3 段主题时拆"），而不是"感觉太大就拆"。
5. **`kind` 与 `targets` 两个字段：保留并赋语义，还是删除？** 给出决断与代价。
6. **本机的 `scripts/install_host_skills.py` 与宿主 59 链接的关系**：catalog 重构后，宿主侧要跟着动的最小集合是什么？（宿主每天 05:00 有 `daily-hygiene.py` 自动补链接 / 只在"上游更新型漂移"时重物化。）
7. **最危险的一步是什么**，以及用什么证据能在合并前发现它。

## 4 已定的约束（不需要审计）
- 每个 PR 必须 bump patch、加 CHANGELOG、过 `check_frontmatter` / `check_contract_graph` / `generate_index --check` / `version.py check`。
- 不写死本机路径、bot/频道 id、个人数据（公开仓）。
- `/usr/bin/python3`（mise shim 的 python3 无 PyYAML）。

---

## 5 追加扫描：超大文件与冗余（owner 2026-11-14 追加提问）

**结论先说：本仓没有任何 SQL。** `git ls-files` 里 0 个 `.sql` / `.db` / `.sqlite`；工作树里唯一的
"sqlite" 字样出现在 `skills/teams-cdp/scripts/node_modules/@types/node/sqlite.d.ts`（第三方类型定义，
且 `node_modules/` 已在 `.gitignore`，未被跟踪）。所以"超大 SQL 冗余"这一项无对象。

但同一类问题（体积大、重复、可重构）在别处真实存在，实测如下：

| 类别 | 实测 | 说明 |
|---|---|---|
| 单文件超大（>600 行） | **9 个** | `run-gdd-selftest.sh` 1139、`omp-run.sh` 960、`gdd.py` 917、`pr-merge-check.py` 838、`test_version.py` 704、`grounded-citations/scripts/sources.py` 676、`m365-copilot-cdp/scripts/copilot.ts` 642、`delivery-state.py` 621、`teams-cdp/scripts/teams.ts` 591 |
| SKILL.md 超大（>480 行） | 2 个 | `github-repo-management` 516、`github-code-review` 481 |
| 参考区 | `ref/` = **38 个 git submodule**（8.3MB 检出，只跟踪指针） | 不是入库冗余，但**同主题重复**：`humanizer`/`Humanizer-zh`/`say-it-human`/`shuorenhua`（四个"去 AI 味"）、`yao-open-skills`/`yao-open-prompts`/`yao-meta-skill`（三个同作者） |
| 并行目录文档 | 4 份 | `README.md` 458 + `README.zh-CN.md` + `index.md` + `index.zh-CN.md`（后两者自动生成；前两者手写，内容重叠） |
| 工作树体积 | 166MB（`.git` 17MB，`node_modules` 未跟踪） | 体积主要由 submodule 检出贡献 |

**因此重构优先级里新增两项**：
- **A′（并入方案 A）**：把 9 个 >600 行文件按"一个职责一个文件"拆开——判据是机械的：单文件 >400 行且包含 ≥2 个顶层职责（函数组/子命令）即拆。
- **A″（并入方案 A）**：`ref/` 参考区瘦身——同一主题保留一个上游，其余移出（submodule 删除是可逆的：`.gitmodules` 里有 URL）；4 份目录文档收敛为"生成 2 份 + 手写 1 份英文，中文 README 只留入口指针"。
