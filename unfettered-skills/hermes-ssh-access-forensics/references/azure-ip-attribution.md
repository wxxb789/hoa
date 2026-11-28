# 微软 / Azure 段源 IP 的归属判定

目标不是「查到一个城市」，而是判断这三件事：
1. 是不是 Microsoft/Azure（AS8075 之外还可能是 Microsoft 自有段）
2. 是**普通计算出口**还是**专属服务**（Bastion / Front Door / 其他）
3. 这个 IP 是客户自己的资源，还是平台共享池

## 第一步：ipinfo（不要用 PTR）

```bash
curl -s --max-time 10 "https://ipinfo.io/<IP>/json" | tr ',' '\n' | grep -E '"(city|region|country|org)"'
```

- Azure 段基本**没有 PTR**，`dig -x` 返回空是常态，不代表 IP 无效。
- `org` 里的 `AS8075 Microsoft Corporation` 是判定的起点；`city` 是**数据中心区域**，不是用户所在城市 —— 不要把「阿姆斯特丹」当成「人在荷兰」。

## 第二步：微软 ServiceTag（判断服务类型）

下载页会给出当天有效的 JSON 文件名（文件名带日期，猜日期会 404）：

```bash
curl -s -L "https://www.microsoft.com/en-us/download/details.aspx?id=56519" -o /tmp/st.html
grep -oE 'https://download\.microsoft\.com[^"'\'']*\.json' /tmp/st.html | head -1
curl -s -L -o /tmp/ServiceTags.json "<上一步的 URL>"     # 约 4.5 MB
```

匹配时取**最长前缀**，并同时看是否有非 `AzureCloud` 的专属 tag：

```python
import json, ipaddress
d = json.load(open("/tmp/ServiceTags.json"))
targets = ["<IP1>", "<IP2>"]
for v in d["values"]:
    for cidr in v["properties"].get("addressPrefixes", []):
        net = ipaddress.ip_network(cidr)
        for t in targets:
            if ipaddress.ip_address(t) in net:
                print(t, v["name"], v["properties"].get("region"), cidr)
```

## 怎么读结果

| 命中 | 结论 |
|---|---|
| 只有 `AzureCloud` + `AzureCloud.<region>` | 该区域的**普通计算出口**（VM / LB outbound / NAT 池），最常见 |
| `AzureBastion.<region>` | 经 Bastion 转发 |
| `AzureFrontDoor.*` | 经 Front Door |
| 完全查不到 | 不是 Azure 公网段：Microsoft 自有 / 合作方 / 已回收段，按普通 ASN 处理 |

## 归属推断的边界

- 4 个 IP 分布在 3 个不同 /16、又能在同一秒并发连入 → **共享出网池**（企业代理、PaaS、NAT 池），不是单机固定公网 IP；单机 SNAT 通常固定一个地址。
- 客户在机器上 `curl ifconfig.me` 得到的地址**可能完全不出现**在服务端日志里 —— 企业代理会把源地址 NAT 成自己区域的出口。因此「日志里没有你说的那个 IP」不能推出「不是那台机器」。
- 反过来，城市/ASN 也不能证明机器身份。要钉死是哪台机器，只有一条可靠路径：让对方现在发起一次连接，实时抓源 IP 做时间关联。
