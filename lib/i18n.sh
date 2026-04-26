#!/usr/bin/env bash
# lib/i18n.sh — Language selection + JSON locale loader.
#
# Sourced by install.sh; do not execute directly.
# shellcheck shell=bash

_select_language() {
  # Already set via env var
  if [[ "$INSTALL_LANG" == "tr" || "$INSTALL_LANG" == "en" ]]; then return; fi

  # Non-interactive: default Turkish / Etkileşimsiz: Türkçe varsayılan
  if [ ! -t 0 ]; then INSTALL_LANG="tr"; return; fi

  if command -v whiptail &>/dev/null && [ -t 2 ]; then
    local choice
    choice=$(whiptail --title "Language / Dil" \
      --radiolist "Select language / Dil seçin:" 12 50 2 \
      "tr" "Türkçe" ON \
      "en" "English" OFF \
      3>&1 1>&2 2>&3) || choice="tr"
    INSTALL_LANG="${choice:-tr}"
  else
    echo ""
    echo "  Language / Dil:"
    echo "  1) Türkçe (varsayılan / default)"
    echo "  2) English"
    _ask_inline "  [1]:" _lang_choice
    case "${_lang_choice:-1}" in
      2|en|EN) INSTALL_LANG="en" ;;
      *)        INSTALL_LANG="tr" ;;
    esac
  fi
}


_load_strings() {
  local _file="$ROOT_DIR/locales/install_${INSTALL_LANG:-tr}.json"
  [ ! -f "$_file" ] && _file="$ROOT_DIR/locales/install_tr.json"
  if [ ! -f "$_file" ]; then
    echo "[install] FATAL: locale file missing under $ROOT_DIR/locales/" >&2
    exit 1
  fi
  if ! command -v python3 &>/dev/null; then
    echo "[install] FATAL: python3 required to load install locales" >&2
    exit 1
  fi
  local _generated _rc
  # python3 -c avoids both temp-file path issues (Windows) and stdin/heredoc
  # pipe issues (Git Bash + native Windows Python combination).
  _generated="$(python3 -c "
import json, shlex, sys
with open(sys.argv[1], encoding='utf-8') as f:
    data = json.load(f)
for k, v in data.items():
    print('_S_' + k + '=' + shlex.quote(v))
" "$_file")"
  _rc=$?
  if [ $_rc -ne 0 ] || [ -z "$_generated" ]; then
    echo "[install] FATAL: locale load failed" >&2; exit 1
  fi
  eval "$_generated"
}
