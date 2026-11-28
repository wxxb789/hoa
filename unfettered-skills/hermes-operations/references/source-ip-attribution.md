# Source IP attribution (who is connecting to this host)

Use when sshd or another daemon names an IP the owner does not recognize — "这几个不停重试的 IP 是什么"、
"我看一下我的哪台机器有这个 IP" — or when a login storm's client must be named before deciding whether it
is the owner's own tooling or a credential problem. Read-only: attribution first, no firewall edits here.

## Order: geo/ASN → registration record → cloud service tag

1. **Coarse identity** — works for any IP, no cloud account needed:

```bash
curl -s "https://ipinfo.io/<ip>/json" | tr ',' '\n' | grep -E '"(ip|city|region|country|org)"'
```

   Gives city/country + AS number and holder org. Enough to separate a residential scanner from a cloud
   egress address, and enough to kill a wrong guess early (an IP remembered as "Hong Kong" is routinely
   Dhaka or Frankfurt).

2. **Registration record** — block holder and boundaries:

```bash
curl -s "https://rdap.arin.net/registry/ip/<ip>" | tr '{' '\n' | grep -iE '"(handle|name|startAddress|endAddress)"'
```

   RIPE-space addresses answer through ARIN as an upstream pointer; `startAddress`/`endAddress` still
   bound the block and confirm the holder is a cloud provider rather than an ISP customer.

3. **Cloud service tag** — authoritative, no geo-guessing (Azure/Microsoft):

```bash
curl -s -L "https://www.microsoft.com/en-us/download/details.aspx?id=56519" -o st.html
grep -oE 'https://download\.microsoft\.com[^"]*\.json' st.html | head -1   # live filename
curl -s -L -o ServiceTags.json "<that url>"
```

   Then match every IP to its **longest matching prefix** and report `name` + `region` (python: load
   `values[]`, walk `properties.addressPrefixes`, keep the highest `prefixlen` hit).

   Reading: `AzureCloud.<region>` alone means ordinary compute egress in that region. Presence under a
   service-specific tag (`AzureBastion.*`, `AzureFrontDoor.*`, …) means that service specifically; absence
   there is a **decisive negative** and is often the most useful fact in the answer.

Hardcoding a dated `ServiceTags_Public_YYYYMMDD.json` URL 404s as soon as the list rolls — always discover
it from the landing page. The file is ~5 MB; download it once and match all IPs in a single pass.

## Interpretation rules

- **One key fingerprint + several IPs + several of them in the same second = one client behind an egress
  pool** (corporate VPN exit, cloud NAT/LB pool, PaaS shared egress). Owner-side, not attackers — but say
  it as inference, not fact, until the owner confirms the device.
- **Block shape tells you the pool type.** Contiguous addresses (a /28, a public IP prefix) = one customer
  NAT gateway or LB frontend. Scattered hits across different /16s in the same metro = shared platform
  egress. Do not reason "one IP = one machine" after seeing the scattered shape.
- **No PTR + a cloud provider as holder = a platform address**, not a host someone provisioned and named.
  State that explicitly, because the owner will otherwise go looking for a VM that has it as a static IP.
- **Split traffic into auth classes before quoting counts** — the class is the finding. Merging them into one
  per-IP table manufactures an attack out of a health check and buries the client that actually
  authenticated.

## Auth class decides the verdict

| log evidence | what it means | what to do |
|---|---|---|
| `Accepted publickey … SHA256:X` | the private-key holder logged in | prove ownership; not an attack |
| `Invalid user <name>` / `Failed publickey` / `Failed password` | guessing, no credentials | scanner noise unless one succeeds |
| `Connection closed by authenticating user <known-user> … [preauth]` **and no `Failed publickey`** | handshake plus username query, nothing submitted | probe / health check; near-zero cost, do not harden sshd for it |

- **Match `Accepted publickey`, never the bare word `Accepted`.**
  `userauth_pubkey: signature algorithm ssh-rsa not in PubkeyAcceptedAlgorithms [preauth]` contains it,
  so `grep Accepted | tail -1` answers with a rejected scanner and misdates the storm's last event.
- **Fingerprint first, machine second**: `grep 'Accepted publickey' | grep -oP 'SHA256:[^ ]+' | sort |
  uniq -c`, then `ssh-keygen -lf ~/.ssh/authorized_keys`. Same fingerprint ⇒ the legitimate key holder
  (client bug, key lives on that machine). A successful login the owner cannot account for ⇒ **leaked
  private key**, and the remedy is rotation, not throttling.
- **Zero failed-key lines on a known-username probe is decisive**: with `PasswordAuthentication no` in
  force nothing was even offered, so it is not credential stuffing — say that instead of quoting the
  attempt count as a threat. A username being known is not a leak (the cloud image default username is public).
- **Count processes with `grep -v grep` or `pgrep -fc`**: `ps -eo args | grep -c -- '--ssh-owner-nonce'`
  counts its own command line and reports orphan backends that do not exist.

## "Is it still happening?" — observation window, not a snapshot

1. Read the last successful event first, then compare it with **when the owner acted**: quiet that began
   before they closed the client is not evidence the close fixed anything.
2. Run a bounded watcher in the background and report its artifact path: poll every 20s
   (`journalctl -u ssh --since "50 seconds ago"`), dedupe each line with `md5sum` into a `.seen` file so
   overlapping windows do not double-count, append `timestamp | raw line` to `events.log` under
   `~/claw/tasks/<date>/<task>/`.
3. Report the window as bounds plus numbers ("12:02–12:37, 0 accepted logins, 3 probes"), then offer the
   next step: a silent cron that alerts only on a new `Accepted publickey`, or a `tcpdump` banner capture
   (root) when the probe's owner must be named.
4. **Verify the watcher by its output file, not the notification text** — a completion notice can carry
   wrapper noise (`open terminal failed: not a terminal`) while the script ran to the end and logged its
   events; reading `events.log` settles it, re-running blind does not.

## Identifying WHICH machine — the easy thing to get wrong

A probe from the candidate machine (`curl ifconfig.me`, `ipify`) is **not** a test when the egress is a
pool: SNAT selects an address per connection, so one probe matches or misses by luck. Do not offer it as
proof, and do not read a miss as "not this machine".

The reliable test is **time correlation**:

1. owner opens the client on candidate machine N and says so;
2. read `journalctl -u ssh --since "-2 min" | grep Accepted` and report the source IPs that *just*
   appeared;
3. repeat per candidate; the set that tracks the open/close action is the machine.

Supporting checks, in order of cost: loop the probe on the machine (20 hits, to see whether the pool shows
up at all); on the cloud side query the subscription's public IP / NAT gateway / LB frontend for the
address — **finding nothing there is itself evidence** of a shared platform pool.

## Reporting shape

One line per address: `ip → ASN/org → region → service tag → hits today → first/last seen`. Then one verdict
sentence (one client behind an egress pool / scanner noise / unknown credential ⇒ rotate the key), then the
single next action that would settle it. Never end on the IP table: an unattributed IP list is data, not an
answer.
