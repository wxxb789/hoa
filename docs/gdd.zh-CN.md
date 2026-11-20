# gdd：Goal-driven delivery 与 agent route

> [English](gdd.md) · **简体中文** · [仓库首页](../README.zh-CN.md)

当书面目标定义了一项可机器检查的仓库增量时，使用 [gdd 协议](../skills/gdd/SKILL.md)。
它协调每阶段独立的 authoring run、由操作者运行的 gate、脚本化的合并检查和可恢复的
ledger。[目标契约目录](goals/README.md)是本仓库存放活跃契约的地方。

## Headless route

默认 launcher 是随附的 `agent_run.py` headless runner；`GDD_AGENT`
选择 CLI（默认 `omp`）。将选中的 route skill 单独装入同一个 skills 根目录。
当前 route 设计中，共享 runner 负责进程、发现已安装的同级 route；选中的 route
缺失时，会报错并列出已安装的 route。默认 agent 名称不会自动安装 route。

| Agent | `GDD_AGENT` | Route skill | 可见性 |
|---|---|---|---|
| OMP | `omp` | `gdd-route-omp` | 可见 |
| DeepSeek Harness | `dsh` | `gdd-route-dsh` | 隐藏 |
| Codex | `codex` | `gdd-route-codex` | 隐藏 |
| Claude Code | `claude` | `gdd-route-cc` | 隐藏 |
| Pi | `pi` | `gdd-route-pi` | 隐藏 |
| OpenCode | `opencode` | `gdd-route-opencode` | 隐藏 |
| Omo | `omo` | `gdd-route-omo` | 隐藏 |
| GitHub Copilot | `copilot` | `gdd-route-copilot` | 隐藏 |

上表描述独立 route 的设计。请从[生成的安装指南](../index.zh-CN.md#安装)
查看当前 checkout 可用的包。隐藏 route 不向模型公布以供路由；隐藏不授予权限。
配置、答案读取、完成规则和平台证据见 [transport 契约](../skills/gdd/references/transport.md)。

## 原生 Paseo transport

显式把 `GDD_LAUNCHER` 指向随附的 `paseo-run.py`，以原生 Paseo agent 运行
各阶段。这要求 daemon 可达。可达性从不自动改变所选 launcher。
Transport 契约分别记录原生与 headless 的平台证据。

## 可选 Paseo GDD Observer

[GDD Observer](../paseo-plugins/gdd-observer/README.md) 是只读插件，不启动 run，
也不改变所选 transport。`npx skills` 不会安装它。侧栏底部的 **GDD runs**
行打开全局 `runs` 屏幕；插件另有独立的设置屏幕。

安装、设置、读取的产物、信任边界、开发检查及移除见插件指南。
[集成指南](../paseo-plugins/gdd-observer/HOA-INTEGRATION.md)说明共享的
`GDD_RUN_ROOT` 与 route 集成。安装前请评审源码：插件会在 Paseo daemon 和 client
中执行受信任、无沙箱的代码。注册与 runtime 设置保留在本机。
