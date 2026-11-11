#!/usr/bin/env bash
# Fill in .env on the server, one question at a time. Secrets are typed hidden,
# so the screen (and any screenshot of it) never shows them.
# Run from the repository folder:  bash scripts/configure.sh
# Run it again any time; press Enter at a question to keep what's already there.
set -euo pipefail
cd "$(dirname "$0")/.."

ENV_FILE=.env
[ -f "$ENV_FILE" ] || cp .env.example "$ENV_FILE"
chmod 600 "$ENV_FILE"
[ -f config/roster.yaml ] || cp config/roster.example.yaml config/roster.yaml

get_kv() {
  grep -E "^$1=" "$ENV_FILE" | head -1 | cut -d= -f2- | sed -E 's/[[:space:]]+#.*$//; s/[[:space:]]+$//' || true
}

set_kv() {
  KEY="$1" VAL="$2" python3 - "$ENV_FILE" <<'PY'
import os, re, sys
path, key, val = sys.argv[1], os.environ["KEY"], os.environ["VAL"]
lines = open(path).read().splitlines()
pattern = re.compile(rf"^{re.escape(key)}=")
out, done = [], False
for line in lines:
    if pattern.match(line):
        out.append(f"{key}={val}")
        done = True
    else:
        out.append(line)
if not done:
    out.append(f"{key}={val}")
open(path, "w").write("\n".join(out) + "\n")
PY
}

is_unset() {
  case "$1" in ""|change-me*|purchases.example.com|https://purchases.example.com) return 0 ;; *) return 1 ;; esac
}

ask() {  # ask KEY "question" default
  local cur; cur="$(get_kv "$1")"
  is_unset "$cur" && cur="$3"
  read -rp "$2 [$cur]: " v
  set_kv "$1" "${v:-$cur}"
}

ask_secret() {  # ask_secret KEY "question"
  local cur state; cur="$(get_kv "$1")"
  if is_unset "$cur"; then state="not set"; else state="set, Enter keeps it"; fi
  read -rsp "$2 ($state, typing is hidden): " v
  echo
  [ -n "$v" ] && set_kv "$1" "$v"
  return 0
}

generate() {  # generate KEY command...: fill only if empty
  local key="$1"; shift
  is_unset "$(get_kv "$key")" && set_kv "$key" "$("$@")"
  return 0
}

echo "Purchase Desk settings. Press Enter to keep the value in [brackets]."
echo
ask DOMAIN "Web address" "kec-purchase.duckdns.org"
set_kv PUBLIC_BASE_URL "https://$(get_kv DOMAIN)"
ask PRIVACY_CONTACT "Contact email shown on the privacy page" ""
echo
ask_secret WA_ACCESS_TOKEN "Meta permanent token (System user)"
ask_secret WA_APP_SECRET "Meta App secret (App settings > Basic)"
ask WA_PHONE_NUMBER_ID "WhatsApp Phone number ID (leave empty if you don't have it yet)" ""
echo
ask_secret ANTHROPIC_API_KEY "Claude API key (Enter to skip for now)"
ask_secret SARVAM_API_KEY "Sarvam API key (Enter to skip for now)"

generate ADMIN_TOKEN openssl rand -hex 24
generate WA_VERIFY_TOKEN openssl rand -hex 16
generate SIGNING_KEY openssl rand -base64 32

echo
echo "Saved to .env (only you can read it)."
echo "Type this into Meta's webhook form as the Verify token:"
echo "    $(get_kv WA_VERIFY_TOKEN)"
