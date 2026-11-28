# 主机远程访问面：可达性判定与通道退役

## A. 「这个端口对外开放吗」

判定必须四步走完，只看 bind 地址一定出错：

```bash
ss -tlnp | grep -E ":PORT\b"                       # 1. bind 地址 / socket 家族
sudo iptables -S INPUT | grep "PORT"               # 2. v4 规则
sudo ip6tables -S INPUT | grep "PORT"              # 3. v6 规则（最常漏）
systemctl is-enabled netfilter-persistent           # 4. 重启后还在不在
sudo grep -n "PORT" /etc/iptables/rules.v4 /etc/iptables/rules.v6
```

- Linux 的 `*:PORT` 是 v6 socket 且接受 v4-mapped：v4 封了、v6 空着是典型缺口，两边要对称。
- 「仅本机」的规则形状（顺序不能反）：

```
-A INPUT -i lo -p tcp --dport PORT -j ACCEPT
-A INPUT -p tcp --dport PORT -j DROP
```

- 改完 `sudo netfilter-persistent save`，它会同时写 `/etc/iptables/rules.v4` 与 `rules.v6`。
- 进程层优先：先确认程序能不能自己绑 `127.0.0.1`（扫二进制 `grep -aoE "--(host|bind|listen)" <bin>` 或 `--help`），不能才退到规则层。用防火墙兜底时要在报告里写清「程序不支持绑定，只能靠规则」，不要让人误以为已从进程层收口。

### 同机验证的陷阱

| 测试 | 结果 | 含义 |
|---|---|---|
| `curl 127.0.0.1:PORT` | 200 | 本机访问正常（需求满足） |
| `curl <本机 eth0 IP>:PORT` | 200 / 421 | 走 `lo`，命中 `-i lo ACCEPT` —— **不能**用来证明封禁生效 |
| `iptables -L INPUT -n -v` 的 DROP 计数 | 0 pkts | 至今没有外部尝试；持续为 0 才说明没被扫到 |

真封禁证据只有两种：外部探针，或 DROP 规则的命中计数。同机自测无论如何都是放行的。

## B. 退役未使用的远程访问通道（Tailscale 为例）

先确认它真的没用：

```bash
command -v tailscale && tailscale status     # Logged out 但仍 active = 空壳进程
systemctl is-enabled tailscaled; systemctl is-active tailscaled
ip link show | grep -i tailscale; ss -ulnp | grep 41641
dpkg -l | grep -i tailscale; snap list | grep -i tailscale
```

步骤：

1. 备份（state 含节点私钥，落盘后立刻 `chmod 600`）：

```bash
sudo tar czf backup/<pkg>-state-and-config.tgz -C / \
  var/lib/<pkg> etc/default/<pkg> etc/apt/sources.list.d/<pkg>.list \
  usr/share/keyrings/<pkg>-archive-keyring.gpg
```

2. `sudo systemctl stop <svc>` → `sudo systemctl disable <svc>`
3. `sudo DEBIAN_FRONTEND=noninteractive apt-get purge -y <pkg> <pkg>-archive-keyring`
4. 删残留：`/etc/apt/sources.list.d/<pkg>.list`、`/run/<pkg>`、`/var/lib/<pkg>`，再 `apt-get update`
5. 验证五项：dpkg 无、二进制无、接口无、端口无、systemd 单元无；再查配置引用（`~/.hermes/config.yaml`、`scripts/`、`skills/`、`cron/`、`/etc/hosts`、`~/.ssh/config`）
6. 任务目录写 `record.md`：清理前状态、动作、验证结果、回滚命令

坑：

- **`apt purge` 不删手动添加的 apt 源文件**，残留会让 `apt-get update` 继续去打已弃用的仓库 → 必须单独删 + 重新 update。
- 状态目录 `/var/lib/<pkg>` 含私钥：备份别放进 git 同步的仓库，权限 600。
- 只 grep `~/.hermes` 整棵树会超时（几分钟都不够）；限定 `config.yaml scripts skills contracts *.md` 这些路径。
