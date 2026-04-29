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
  if [[ -n "${PY:-}" ]]; then
    printf '%s' "$_json" | "$PY" -c "
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
  if [[ -n "${PY:-}" ]]; then
    printf '%s' "$_json" | "$PY" -c "
import sys,json
try: print(json.load(sys.stdin).get('$_field',''))
except: pass" 2>/dev/null || true
  else
    printf '%s' "$_json" | grep -oE "\"${_field}\":\"[^\"]*\"" | head -1 | cut -d'"' -f4 || true
  fi
}


_sed_i() {
  # Portable in-place sed: GNU sed (Linux) and BSD sed (macOS) have
  # incompatible -i syntax; temp-file approach works on both.
  # Usage: _sed_i FILE EXPR
  local _file="$1" _expr="$2" _tmp
  _tmp="$(mktemp "${_file}.XXXXXX")"
  sed "$_expr" "$_file" > "$_tmp" && mv "$_tmp" "$_file" || { rm -f "$_tmp"; return 1; }
}


_env_comment_out() {
  local key="$1" file="$2"
  if grep -q "^${key}=" "$file" 2>/dev/null; then
    _sed_i "$file" "s@^${key}=@# ${key}=@"
  fi
}


_env_uncomment() {
  local key="$1" file="$2"
  if grep -q "^# ${key}=" "$file" 2>/dev/null; then
    _sed_i "$file" "s@^# ${key}=@${key}=@"
  fi
}


_read_env_var() {
  grep "^${1}=" "${2}" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"\r' || true
}


_parse_wiz() {
  local _json="$1" _key="$2" _def="${3:-}"
  echo "$_json" | "$PY" -c \
    "import sys,json; d=json.load(sys.stdin); print(d.get(sys.argv[1],sys.argv[2]))" \
    "$_key" "$_def" \
    2>/dev/null || echo "$_def"
}


_env_get() {
  # Bash/grep-only — avoids Git Bash + native Windows Python path-conversion
  # quirks where open(sys.argv[N]) on /c/Users/... silently fails inside
  # try/except: pass and returns empty (this skipped the Telegram wizard).
  # Behavior matches _read_env_var: strips surrounding "/' and trailing CR.
  local _key="$1" _file="$2" _line _val
  _line="$(grep "^${_key}=" "$_file" 2>/dev/null | head -1)"
  [[ -z "$_line" ]] && return 0
  _val="${_line#${_key}=}"
  _val="${_val%$'\r'}"
  # Strip a single layer of surrounding double or single quotes
  if [[ "$_val" == \"*\" ]]; then _val="${_val#\"}"; _val="${_val%\"}"
  elif [[ "$_val" == \'*\' ]]; then _val="${_val#\'}"; _val="${_val%\'}"
  fi
  printf '%s' "$_val"
}

