#!/usr/bin/env bash
# lib/security.sh — Random key + TOTP secret generation.
#
# Sourced by install.sh; do not execute directly.
# shellcheck shell=bash

_gen_api_key() {
  if command -v openssl &>/dev/null; then openssl rand -hex 32
  else { date +%s%N 2>/dev/null || date +%s; echo "$RANDOM$RANDOM"; } | sha256sum | head -c 64; fi
}


_gen_totp() {
  local _py=""
  # Detect venv python — Windows uses Scripts/python.exe, Linux/macOS uses bin/python
  if   [[ -x "$BACKEND_DIR/venv/Scripts/python.exe" ]]; then _py="$BACKEND_DIR/venv/Scripts/python.exe"
  elif [[ -x "$BACKEND_DIR/venv/bin/python"         ]]; then _py="$BACKEND_DIR/venv/bin/python"
  fi
  # Fallback to globally picked Python (set by install.sh _pick_python)
  [[ -z "$_py" && -n "${PY:-}" ]] && _py="$PY"
  # Use pyotp if available; otherwise generate a valid base32 secret via openssl/date
  if [[ -n "$_py" ]] && "$_py" -c "import pyotp" 2>/dev/null; then
    "$_py" -c 'import pyotp; print(pyotp.random_base32())'
  else
    local raw=""
    if command -v openssl &>/dev/null; then
      while [[ ${#raw} -lt 32 ]]; do
        raw+="$(openssl rand -base64 64 | tr -dc 'A-Z2-7')"
      done
    else
      while [[ ${#raw} -lt 32 ]]; do
        raw+="$({ date +%s%N 2>/dev/null || date +%s; echo "$RANDOM"; } | sha256sum | tr -dc 'A-Z2-7')"
      done
    fi
    echo "${raw:0:32}"
  fi
}

