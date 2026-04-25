#!/usr/bin/env bash
# lib/packages.sh — Capability → requirements file resolution.
#
# Sourced by install.sh; do not execute directly.
# shellcheck shell=bash

_PKG_CAP_KEYS=(   "scheduler" "pdf_import" "calendar" "screenshot" "media" "desktop"        "browser"        )

_PKG_ENV_VARS=(   "RESTRICT_SCHEDULER" "RESTRICT_PDF_IMPORT" "RESTRICT_CALENDAR" "RESTRICT_SCREENSHOT" "RESTRICT_MEDIA" "DESKTOP_ENABLED" "BROWSER_ENABLED" )

_PKG_ACTIVE_VAL=( "false"     "false"      "false"    "false"      "false"  "true"           "true"           )


_resolve_requirements() {
  local env_file="$BACKEND_DIR/.env"
  local req_dir="$BACKEND_DIR/requirements"

  # core + dev her zaman yüklenir
  printf '%s\n' "$req_dir/core.txt"
  printf '%s\n' "$req_dir/dev.txt"

  # Capability flag'leri mevcut değilse: tümünü yükle
  if ! grep -qE "^(RESTRICT_|DESKTOP_ENABLED|BROWSER_ENABLED)" "$env_file" 2>/dev/null; then
    log "$_S_STEP_PKG_ALL"
    for f in "$req_dir"/*.txt; do
      [[ "$(basename "$f")" == "core.txt" ]] && continue
      [[ "$(basename "$f")" == "dev.txt"  ]] && continue
      printf '%s\n' "$f"
    done
    return
  fi

  # Seçili yeteneklere göre dosya ekle
  local i
  for (( i=0; i<${#_PKG_CAP_KEYS[@]}; i++ )); do
    local val
    val="$(_read_env_var "${_PKG_ENV_VARS[$i]}" "$env_file")"
    val="${val,,}"  # küçük harfe çevir
    # Eksik değer için runtime default uygula:
    #   RESTRICT_* → default "false" (kısıtlama yok = etkin)
    #   *_ENABLED  → default "false" (etkinleştirilmedi)
    if [[ -z "$val" ]]; then val="false"; fi
    if [[ "$val" == "${_PKG_ACTIVE_VAL[$i]}" ]]; then
      printf '%s\n' "$req_dir/${_PKG_CAP_KEYS[$i]}.txt"
    fi
  done
}

