---
name: hermes-ssh-access-forensics
description: "Use when SSH access, source IPs, or open ports need triage."
version: 1.0.0
author: Zoe
license: MIT
metadata:
  hermes:
    tags: [ssh, forensics, security, journalctl, incident, ops]
    category: devops
---

# SSH access forensics

## When to Use

- 有人在问「这些 IP 是什么 / 是不是被爆破 / 有没有被登录」
- 出现登录风暴、连接数异常、或某客户端把主机资源拉高（每条 SSH 登录可能拉起一个 backend 进程）
- 怀疑私钥外泄，需要在动 key 之前先定性

不用于：加固 sshd 本身、审计应用层认证、与主机远程访问面无关的网络排障。监听端口是否真的对外可达、以及退役不再使用的远程访问通道（Tailscale 一类）**在**范围内，见第 7 节。

Answers three questions **in this order**, because each answer changes the next step:

1. **谁在连** — 频率、源 IP、时间分布
2. **是不是有凭证** — 认证成功 / 凭证尝试 / 空探测
3. **进来过没有** — 账号、密钥、cron、监听的完整性

Read-only by default. 换 key、改 sshd 配置是**另外的、要批准的**动作，不在调查里顺手做。

## 1. 先量速率，再下结论

```bash
journalctl -u ssh -o short-iso --no-pager \
  | grep -E "Accepted (publickey|certificate) for" \
  | sed -E 's/^([0-9-]+)T[0-9:+-]+ .*from ([0-9.]+) port.*/\1 \2/' \
  | sort | uniq -c | sort -k2,2
```

- 逐日 → 逐小时 → 逐 10 分钟分桶。日计数在中午读会低估整夜风暴。
- 永远给**最后一条**的时间戳：「10:21:35 之后 0 次」比「现在不高」强一个量级。
- 采样窗口先于指标：journal 起点晚于事件就明说，别用不覆盖的日志下「从未发生」的判断。
- 累计趋势比单点有用：`264 → 3468 → 4053 → 5102` 才能说明这是升级中的问题，不是噪声。

## 2. 按日志行类型分类（决定表）

| journald 行 | 含义 |
|---|---|
| `Accepted publickey for U from IP` | 认证成功 —— 对方**持有私钥** |
| `Failed publickey` / `Failed password` / `Invalid user` | 凭证尝试（爆破或爆破式枚举） |
| `Connection closed by authenticating user U IP port N [preauth]`，且该 IP **没有任何** `Failed publickey` 行 | **空探测**：握手完成后按用户名断开，从未提交凭证 |
| `userauth_pubkey: signature algorithm ssh-rsa not in PubkeyAcceptedAlgorithms` | 客户端用旧 SHA-1 RSA 签名，被算法策略拒绝 |

空探测 ≠ 爆破。前者零凭证、代价是一次 TCP+KEX；后者会留下成片的 `Failed publickey`/`Invalid user`。
**不要为空探测改 sshd**：`MaxStartups`/iptables 限流会把正常客户端的重连一起打死，而对方一次都没试过 key。

## 3. 指纹关联 —— 判断「同一个人」的决定性证据

```bash
ssh-keygen -lf ~/.ssh/authorized_keys
journalctl -u ssh --no-pager | grep -E "Accepted (publickey|certificate) for" | grep -oP 'SHA256:[A-Za-z0-9+/=]+' | sort | uniq -c
```

- 不同源 IP 用**同一个指纹** = 同一个持钥者换了出口，不是「陌生人拿到另一把 key」。这把「是不是外人」的问题从「谁有这个 IP」变成「这把私钥在哪台机器上」。
- 指纹与服务端 `authorized_keys` 一致，说明是合法登录；不一致却出现 `Accepted` 才是真正的异常。
- 逐个 IP 单独取指纹（`grep '<ip>' | grep -oP 'SHA256:...'`），能区分「同一客户端多出口」和「两拨人各用一把 key」。

## 4. 归属判定（地理/ASN/服务 tag）

`dig -x` 对 Azure/Microsoft 段基本返回空，别用 PTR 下结论。走 `references/azure-ip-attribution.md` 的 ipinfo + 微软 ServiceTag 两段式，能区分「普通计算出口」和「Bastion/FrontDoor 等专属服务」。

关键判断：**同一秒内多个不同 /16 段 IP 并发连入 = 共享出网池**（企业代理 / PaaS / NAT 池），不是单机固定公网 IP。反过来，客户端自称的「我的 IP」不出现在服务端日志里，也不等于它不是那台机器 —— 代理把源地址 NAT 掉了。

## 5. 完整性检查（有没有人真的做了什么）

```bash
awk -F: '$3>=1000 && $3<65534 {print $1, $3, $7}' /etc/passwd   # 人类账号
ls -la --time-style=long-iso ~/.ssh/                             # authorized_keys / known_hosts 时间戳
crontab -l; ls -la /etc/cron.d/                                  # 有无新增计划任务
find ~/.config/systemd /etc/systemd/system -newermt '<窗口起点>' \( -name '*.service' -o -name '*.timer' \)
ss -tulnp | awk 'NR==1 || $5 !~ /^(127\.|\[::1\])/'               # 非 loopback 监听
ss -tnp state established                                        # 出站对端
```

- `session opened` 远多于 `session closed` 是**隧道被 kill 而非正常退出**的正常表现，不是「有 shell 残留」；用 `who` / `last` / `ps` 复核，别按差值报警。
- `who` 和 `last` 对经代理/中间层的会话常显示 `0.0.0.0`，不能用于源地址归因 —— 归因只信 sshd 日志。
- 报告里把「无入侵痕迹」写成可复核的清单（账号数、密钥 mtime、cron 数、监听端口），不要写成结论形容词。

### 反证「连接其实来自本机 loopback」

被质疑源地址是否伪造、或其实是本机自连时，四条只读证据即可闭环：

```bash
loginctl list-sessions --no-legend | awk '{print $1}' | while read s; do
  echo "$s remote=$(loginctl show-session "$s" -p Remote --value) host=$(loginctl show-session "$s" -p RemoteHost --value)"
done                                   # systemd 自己记录的 peer IP，独立于 sshd 日志
ss -tnp | awk '$5 ~ /:22$/'            # 本机是否有到 22 的出站连接
curl -s https://api.ipify.org          # 本机自己的公网出口 IP
journalctl -u ssh --no-pager | grep -cE 'from (127\.0\.0\.1|::1) port'
```

- `RemoteHost` 是公网地址 = 不是 loopback；日志里 loopback 源地址计数为 0 = 没有任何本地自连。
- 本机公网出口 IP **不在**源 IP 列表里 → 连 hairpin 自连（经自己的公网 IP 绕回）也排除。
- 客户端日志里的 `peer=127.0.0.1` 是 SSH 隧道的**服务端出口**，天然不含来源地址；既不能当来源证据，也不能当清白证据。
- `/proc/net/nf_conntrack` 一般需要 root，不要把它写进只读取证流程。
- 会话若显示 `remote=yes`，说明 systemd 认定这是远程登录来源，可直接引用为反证。

## 6. 报告形状

- 先回答被问的那个二选一（「是合法凭证，不是爆破」），再证据，再标注 Fact / Inference，最后 ≤3 个带成本的动作并给出推荐。
- IP 按**行为**分组（认证成功 / 空探测 / 已排除的扫描器），不要按地理分组；每个 IP 给「次数 + 最后出现时间」。
- 同一次调查里出现过的 IP 要不要清单一并给全并标类别，避免对方只拿到「5 个」而不知道是哪 5 个。
- 服务端证明不了「是哪台机器」时，直说证明不了，并给出唯一能证明的动作（让对方打开客户端，30 秒内报源 IP）；不要用 GEO/ASN 反推机器身份。

## 7. 别只查 22 端口 —— 监听面的真实暴露

`ss -tlnp` 里看到 `*:PORT` **不等于**公网可达，也不等于“已暴露”。四步走完再下结论：

```bash
ss -tlnp | grep -E ":PORT\b"                    # 1. bind 地址 / socket 家族
sudo iptables -S INPUT | grep "PORT"            # 2. v4 规则
sudo ip6tables -S INPUT | grep "PORT"           # 3. v6 规则（最常漏）
systemctl is-enabled netfilter-persistent       # 4. 重启后还在不在
sudo grep -n "PORT" /etc/iptables/rules.v4 /etc/iptables/rules.v6
```

- 只有 `-A INPUT -i lo ... ACCEPT` + `-A INPUT ... DROP` 这一对（且 ACCEPT 在前）才算“仅本机”；改完 `sudo netfilter-persistent save` 固化（同时写 v4/v6）。
- `*:PORT` 是 v6 socket 且接受 v4-mapped：v4 封了、v6 空着是典型缺口。
- 进程能自己绑 `127.0.0.1` 就不要只靠防火墙；只有程序确实没有 `--host/--bind`（本机 `ghc-proxy` 就只有 `--port`）才退到规则层，并在报告里写清这一点。
- 报告里不要把 bind 地址当暴露结论：先查规则再说话。

未使用访问通道的退役流程与坑（apt 源残留、状态备份、五项验证）→ `references/host-access-surface.md`。

## Pitfalls

- **`grep "Accepted"` 会命中 `PubkeyAcceptedAlgorithms`**，凭空造出不存在的登录记录。只用 `Accepted (publickey|certificate) for`；同一个坑也会让「非本用户成功登录」这类统计失真。
- **默认 journalctl 输出在中文 locale 下按列 `awk` 会错位**（`11月 09 12:07:18`），时间分桶和 IP 聚合都会静默出错。解析前加 `-o short-iso` 或 `LC_ALL=C`。
- **systemd unit 的默认值会骗人**：报节奏前读 `*.service.d/*.conf` 的 drop-in（`Environment=` 覆盖），别拿 unit 文件里的 `Environment=` 当真。
- **周期约 10 分钟、间隔缓慢漂移、零凭证** = 健康探测/监控，不是爆破也不是你的客户端；把它和认证成功的客户端分开报，否则会误判成「还有人在高频连」。
- 观察窗脚本用 `write_file` 落盘再 `terminal(background=true)` 启动；在 shell 里现写 heredoc 是审批最慢的路径。现成模板：`scripts/ssh-watch.sh`。后台完成通知里的噪声行（如 `open terminal failed: not a terminal`）不代表脚本失败 —— 回报前先读 `events.log` 尾部和 `WATCH_DONE` 行。
- 只读调查被要求「继续查」时，不等于授权换 key 或改 sshd —— 这两件事各自要一次明确批准，并附回滚。

## 附带文件

- `references/azure-ip-attribution.md` — 微软/Azure 段 IP 的归属判定recipe（ipinfo + ServiceTag JSON）。
- `scripts/ssh-watch.sh` — 去重 + 落盘的 journalctl 轮询观察窗。
- `references/host-access-surface.md` — 监听端口可达性判定（bind / v4 / v6 / 持久化）+ 退役未使用访问通道（Tailscale 类）的流程与坑。
