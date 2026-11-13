#!/usr/bin/env bash
# Route + auth triage for an OpenAI-style provider gateway (Kong / Tencent API-gw shapes).
#
# Secret-safe: the key is loaded from .env into a shell variable and EVERY printed line is
# redacted; only a fingerprint is shown, never the value.
#
# Usage:
#   probe-provider-endpoint.sh <KEY_ENV_VAR> <base-url> [<base-url> ...]
#   probe-provider-endpoint.sh TENCENT_GLM_API_KEY http://10.0.0.1/v1 http://10.0.0.1:8000/v1
#
# Env knobs: MODEL_ID (default MODEL - auth triage answers before model validation, so a
# placeholder is fine), HERMES_ENV_FILE (default ~/.hermes/.env).
#
# Reading the output:
#   404 "no Route matched with those values" -> wrong host/path
#   401 "No API key found in request"        -> gateway does not read that header name
#   401 "Unauthorized"                       -> key read but rejected: the key VALUE is the problem
#   connection failure on a port            -> that scheme/port is not served
#
# Rule: once you see 401 Unauthorized, stop. No header variant can fix it - the owner must
# confirm the key. See references/providers-and-models.md -> "Rotating a provider endpoint".
set -u

ENVVAR="${1:?usage: $0 <KEY_ENV_VAR> <base-url> [...]}"; shift
[ "$#" -ge 1 ] || { echo "usage: $0 <KEY_ENV_VAR> <base-url> [...]" >&2; exit 2; }
ENVFILE="${HERMES_ENV_FILE:-$HOME/.hermes/.env}"
MODEL_ID="${MODEL_ID:-MODEL}"

KEY=$(grep -E "^${ENVVAR}=" "$ENVFILE" | head -1 | cut -d= -f2- | tr -d '"' | tr -d '\r' | tr -d ' ' | tr -d "'")
if [ -z "${KEY:-}" ]; then echo "!! ${ENVVAR} not found in ${ENVFILE}" >&2; exit 1; fi

redact() { sed -e "s/${KEY}/<KEY>/g"; }
python3 - "$KEY" <<'PY'
import sys, hashlib, re
k = sys.argv[1]
print("key fingerprint: %d chars | %s...%s | sha256[:12]=%s | clean_shape=%s" % (
    len(k), k[:6], k[-4:], hashlib.sha256(k.encode()).hexdigest()[:12],
    bool(re.fullmatch(r'[A-Za-z0-9_\-]{16,}', k))))
PY

TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT
BODY="{\"model\":\"${MODEL_ID}\",\"messages\":[{\"role\":\"user\",\"content\":\"ping\"}],\"max_tokens\":5}"

for base in "$@"; do
  echo "=== ${base}"
  for path in /models /chat/completions /messages; do
    if [ "$path" = /models ]; then
      code=$(curl -s -k -m 15 -o "$TMP" -w '%{http_code}' -H "Authorization: Bearer ${KEY}" "${base}${path}")
      label="GET "
    else
      code=$(curl -s -k -m 20 -o "$TMP" -w '%{http_code}' -X POST \
        -H "Authorization: Bearer ${KEY}" -H 'Content-Type: application/json' \
        -H 'anthropic-version: 2023-06-01' -d "$BODY" "${base}${path}")
      label="POST"
    fi
    printf '  %s %-20s -> %-4s ' "$label" "$path" "$code"
    head -c 200 "$TMP" | tr -d '\n' | tr -s ' ' | redact
    echo
  done
done
