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
  # PYTHONIOENCODING=utf-8  — forces UTF-8 stdout on Windows (default code page
  #   e.g. CP1254 causes UnicodeEncodeError for Turkish chars → exit 1).
  # < "$_file" (shell redirection, not a Python argument) — bash/MSYS2 opens
  #   the file using its own POSIX path layer, so Python never sees /c/Users/...
  #   and path-conversion issues are eliminated entirely.
  # sys.stdin (json.load) — reads the file content Python receives via stdin.
  # shellcheck disable=SC2016
  _generated="$(PYTHONIOENCODING=utf-8 python3 -c 'import json,shlex,sys; data=json.load(sys.stdin); [print("_S_"+k+"="+shlex.quote(v)) for k,v in data.items()]' < "$_file")"
  _rc=$?
  if [ $_rc -ne 0 ] || [ -z "$_generated" ]; then
    echo "[install] FATAL: locale load failed" >&2; exit 1
  fi
  eval "$_generated"
}
