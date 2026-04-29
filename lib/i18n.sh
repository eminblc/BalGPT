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
  if [[ -z "${PY:-}" ]]; then
    echo "[install] FATAL: Python 3 bulunamadı / Python 3 not found (\$PY unset)" >&2
    exit 1
  fi
  local _generated _rc
  # PYTHONIOENCODING=utf-8  — prevents UnicodeEncodeError for Turkish/non-ASCII
  #   chars on Windows (default code page e.g. CP1254 cannot encode them).
  # < "$_file" — bash/MSYS2 opens the file; Python reads sys.stdin, never
  #   sees the /c/Users/... POSIX path, eliminating all path-conversion issues.
  # shellcheck disable=SC2016
  _generated="$(PYTHONIOENCODING=utf-8 "$PY" -c 'import json,shlex,sys; data=json.load(sys.stdin); [print("_S_"+k+"="+shlex.quote(v)) for k,v in data.items()]' < "$_file")"
  _rc=$?
  if [ $_rc -ne 0 ] || [ -z "$_generated" ]; then
    echo "[install] FATAL: locale load failed" >&2; exit 1
  fi
  eval "$_generated"
}
