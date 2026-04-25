#!/usr/bin/env bash
# lib/env.sh — .env mutation + JSON extraction helpers.
#
# Sourced by install.sh; do not execute directly.
# shellcheck shell=bash

_env_set() {
  local key="$1" val="$2" file="$3"
  if grep -q "^${key}=" "$file" 2>/dev/null; then
    # Use awk instead of sed to avoid breakage when val contains sed delimiters (@ / \)
    local tmp; tmp="$(mktemp "${file}.XXXXXX")"
    awk -v k="$key" -v v="$val" 'BEGIN{OFS=""} $0 ~ "^"k"=" {print k"="v; next} {print}' "$file" > "$tmp"
    mv "$tmp" "$file"
  else
    printf '%s=%s\n' "$key" "$val" >> "$file"
  fi
}


_tg_extract_next_offset() {
  local _json="$1"
  if command -v python3 &>/dev/null; then
    printf '%s' "$_json" | python3 -c "
import sys,json
try:
    r=json.load(sys.stdin)['result']
    print(r[-1]['update_id']+1 if r else 0)
except: print(0)" 2>/dev/null || echo 0
  else
    # awk: "update_id":12345 pattern'lerinden sonuncusunu bul, +1 yaz
    local _last
    _last="$(printf '%s' "$_json" | grep -oE '"update_id":[0-9]+' | tail -1 | grep -oE '[0-9]+' || true)"
    if [[ -n "$_last" ]]; then echo $((_last + 1)); else echo 0; fi
  fi
}


_extract_json_field() {
  local _json="$1" _field="$2"
  if command -v python3 &>/dev/null; then
    printf '%s' "$_json" | python3 -c "
import sys,json
try: print(json.load(sys.stdin).get('$_field',''))
except: pass" 2>/dev/null || true
  else
    printf '%s' "$_json" | grep -oE "\"${_field}\":\"[^\"]*\"" | head -1 | cut -d'"' -f4 || true
  fi
}


_env_comment_out() {
  local key="$1" file="$2"
  if grep -q "^${key}=" "$file" 2>/dev/null; then
    sed -i "s@^${key}=@# ${key}=@" "$file"
  fi
}


_env_uncomment() {
  local key="$1" file="$2"
  if grep -q "^# ${key}=" "$file" 2>/dev/null; then
    sed -i "s@^# ${key}=@${key}=@" "$file"
  fi
}


_read_env_var() {
  grep "^${1}=" "${2}" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"\r' || true
}


_parse_wiz() {
  local _json="$1" _key="$2" _def="${3:-}"
  echo "$_json" | python3 -c \
    "import sys,json; d=json.load(sys.stdin); print(d.get(sys.argv[1],sys.argv[2]))" \
    "$_key" "$_def" \
    2>/dev/null || echo "$_def"
}


_env_get() {
  local _key="$1" _file="$2"
  python3 -c "
import sys
key = sys.argv[1]
try:
    for line in open(sys.argv[2]).read().splitlines():
        if line.startswith(key + '='):
            val = line[len(key)+1:].strip('\"').strip(\"'\")
            print(val)
            break
except Exception:
    pass
" "$_key" "$_file" 2>/dev/null || true
}

