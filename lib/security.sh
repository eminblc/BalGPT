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
  # venv python (systemd/PM2 modu)
  if "$BACKEND_DIR/venv/bin/python" -c "import pyotp" 2>/dev/null; then
    "$BACKEND_DIR/venv/bin/python" -c 'import pyotp; print(pyotp.random_base32())'
  # system python3 (Docker modu / Git Bash)
  elif python3 -c "import pyotp" 2>/dev/null; then
    python3 -c 'import pyotp; print(pyotp.random_base32())'
  elif python -c "import pyotp" 2>/dev/null; then
    python -c 'import pyotp; print(pyotp.random_base32())'
  # pyotp yoksa base32 uyumlu rastgele string üret
  else
    local raw=""
    if command -v openssl &>/dev/null; then
      # Generate enough bytes so after filtering we get at least 32 chars
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

