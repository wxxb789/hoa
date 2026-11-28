# Provisioning channels（本机通道图）

> 结构稳定、内容会漂。任何一次使用前用文末探针重新确认，不要引用这里的版本号当事实。

## 通道与优先级

受管 session 的 PATH 通常按此顺序注入（高者胜）：

1. `<repo>/node_modules/.bin` —— 项目本地 dev bin
2. agent 私有运行时：`~/.hermes/node/bin`、`~/.hermes/tools/node-*/bin`、`npm-*/bin`、`python-*/bin`、`ffmpeg-*/bin`
3. 用户 bin：`~/.local/bin` —— 手工 ELF、pipx 符号链接、uv tool 符号链接、生成的启动器
4. `~/.cargo/bin` —— rustup 代理（常是坏的/旧的）
5. npm global prefix：`~/.npm-global/bin`
6. 版本管理器 shims：`~/.local/share/mise/shims` —— 默认**不在** unit PATH 里
7. 发行版：`/usr/local/*`、`/usr/bin`、`/bin`

推论：同一个名字在不同上下文里有 5 种解析结果。「哪个上下文」是每次都要先问的问题。

## 来源签名（provenance）

| 看到 | 来自 |
|---|---|
| 符号链接 → `~/.local/share/uv/tools/…` | `uv tool` |
| 符号链接 → `~/.local/share/pipx/venvs/…` | `pipx` |
| 符号链接 → `~/.local/gh/<ver>/`，或几个月前日期的裸 ELF | 手工投放 |
| `#!/usr/bin/python3` console-script | `pip --user`（对系统解释器） |
| `#!/bin/sh`，内容是 profile/launcher | Hermes 生成的启动器，不是依赖 |
| 符号链接 → `/usr/lib/node_modules/corepack/dist/…` | corepack（常指向已删的 node 版本） |

## 后端映射（短名 → 必要时写全）

| 工具 | mise 后端 |
|---|---|
| node / python / go / rust / dotnet / bun / deno | core（`node@24` 这种写法即可） |
| pnpm | `aqua:pnpm/pnpm`；yarn → `npm:@yarnpkg/cli-dist` |
| uv / ruff | `aqua:astral-sh/uv`、`aqua:astral-sh/ruff` |
| gh | `aqua:cli/cli` |
| jq / ripgrep / fd / fzf / bat / just | 短名可解析（aqua 背后） |
| gitleaks / trufflehog | `aqua:gitleaks/gitleaks`、`aqua:trufflesecurity/trufflehog` |
| chezmoi / tmux | `aqua:twpayne/chezmoi`、`aqua:tmux/tmux-builds` |
| pre-commit | `pipx:pre-commit`（或 `aqua:pre-commit/pre-commit`） |
| yt-dlp | `github:yt-dlp/yt-dlp` |
| playwright / markdownlint-cli2 / opencode / puppeteer 等 npm 包 | `npm:<pkg>` |
| agent-browser | `aqua:vercel-labs/agent-browser`（或 `npm:`） |
| 任意 pypi 包 | `pypi:<pkg>` |

aqua 的 owner/repo 会改名，落盘前用 `mise ls-remote` 验一遍。

## 迁移前必须 grep 的耦合点

- `~/.hermes/config.yaml` —— 浏览器/CLI 集成的绝对 bin 路径
- `~/.hermes/scripts/*.py` —— 自建候选目录列表（`Path.home()/".npm-global/bin"`、`.nvm/versions/node/*/bin` 这类）
- `~/.config/systemd/user/*.service` —— `Environment=PATH`
- `~/.bashrc` / `~/.zshrc` / `~/.profile` —— 激活块，`DOTNET_ROOT`、`NVM_DIR`、`PNPM_HOME`、`BUN_INSTALL`
- repo `package.json` 的 `packageManager` + lockfile —— repo 期待哪个 pnpm/yarn

```bash
grep -rn -E "npm-global|\.local/node|DOTNET_ROOT|cargo/bin|nvm|PNPM_HOME" \
  ~/.hermes/config.yaml ~/.bashrc ~/.profile ~/.zshrc ~/.hermes/scripts
```

## 体量 / 余量

```bash
du -sh ~/.local/share/mise ~/.npm-global ~/.local/share/pipx ~/.local/share/uv \
       ~/.nvm ~/.local/node ~/.cargo ~/.hermes/tools
df -h /
```

包管理器树常是 GB 级；重装期新旧两份并存，先看余量再定批次。

## 探针

```bash
# 三种上下文可见性
env -i HOME=$HOME bash -c 'command -v node python3 pi omp dotnet go bun'
env -i HOME=$HOME bash -lc 'command -v node python3'
command -v -a node          # 全部命中，按 PATH 顺序，查遮蔽最快

# unit 权威 PATH
systemctl --user show <unit> -p Environment

# shims 覆盖
ls ~/.local/share/mise/shims

# 漂移
mise ls-remote <name> | tail -1
```
