#!/usr/bin/env bash
# 去重 + 落盘的 sshd 日志观察窗（只读，无需 root）。
#
# 用法： ssh-watch.sh <outdir> [minutes=35] [grep-regex='Accepted publickey|Invalid user']
# 产物： <outdir>/events.log  （时间戳 | 原始日志行），<outdir>/.seen 去重键
#
# 设计要点：
#   - 轮询窗口（50s）必须大于轮询间隔（20s），否则会漏事件
#   - 用 md5 去重，重复读同一时间窗不会重复写入
#   - 结束时写 WATCH_DONE，方便后台任务事后判断是否跑完（而不是被杀）
set -uo pipefail

DIR=${1:?usage: ssh-watch.sh <outdir> [minutes] [regex]}
MIN=${2:-35}
PAT=${3:-'Accepted publickey|Invalid user'}

mkdir -p "$DIR"
OUT="$DIR/events.log"
SEEN="$DIR/.seen"
touch "$OUT" "$SEEN"
echo "START $(date '+%F %T') pattern=$PAT minutes=$MIN" >> "$OUT"

END=$(( $(date +%s) + MIN * 60 ))
while [ "$(date +%s)" -lt "$END" ]; do
  journalctl -u ssh --since "50 seconds ago" --no-pager 2>/dev/null \
    | grep -E "$PAT" \
    | grep -vE "session (opened|closed)" \
    | while IFS= read -r line; do
        key=$(printf '%s' "$line" | md5sum | cut -d' ' -f1)
        if ! grep -qx "$key" "$SEEN"; then
          printf '%s | %s\n' "$(date '+%F %T')" "$line" >> "$OUT"
          echo "$key" >> "$SEEN"
        fi
      done
  sleep 20
done

echo "WATCH_DONE $(date '+%F %T')" >> "$OUT"
