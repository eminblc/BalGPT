#!/usr/bin/env bash
# lib/capabilities.sh — FEAT-3 capability flag selection + .env application.
#
# Sourced by install.sh; do not execute directly.
# shellcheck shell=bash

declare -A _CAP_ASSOC_PARAMS=(
  ["desktop"]="DESKTOP_RECORDING DESKTOP_RECORDING_MAX_MB"
  ["browser"]="BROWSER_HEADLESS BROWSER_SESSIONS_DIR"
)


_apply_cap_visibility() {
  local cap="$1" enabled="$2" file="$3"
  local params="${_CAP_ASSOC_PARAMS[$cap]:-}"
  [[ -z "$params" ]] && return
  local param
  for param in $params; do
    if [[ "$enabled" == "true" ]]; then
      _env_uncomment "$param" "$file"
    else
      _env_comment_out "$param" "$file"
    fi
  done
}


_write_capabilities() {
  # $1 = seçili etiketler (whiptail checklist çıktısı: '"fs" "media"' formatında, ya da text mode: ' "fs" "media"')
  local selected="$1"
  local env_dst="$BACKEND_DIR/.env"
  # key:ENV_VAR eşlemeleri
  # RESTRICT_* → seçili=false (kısıtlama yok), seçilmemiş=true (kısıtlı)
  # Senkronizasyon: bu diziler config.py restrict_* / *_enabled field'ları ve
  #   capability_guard.py _RULES listesiyle eşleşmeli (bkz. register_capability_rule)
  local -a cap_keys=( "fs" "network" "shell" "service_mgmt" "media" "calendar" "project_wizard" "screenshot" "scheduler" "pdf_import" "conv_history" "plans" "intent_classifier" "wizard_llm_scaffold" )
  local -a cap_envs=(
    "RESTRICT_FS_OUTSIDE_ROOT" "RESTRICT_NETWORK" "RESTRICT_SHELL" "RESTRICT_SERVICE_MGMT"
    "RESTRICT_MEDIA" "RESTRICT_CALENDAR" "RESTRICT_PROJECT_WIZARD" "RESTRICT_SCREENSHOT"
    "RESTRICT_SCHEDULER" "RESTRICT_PDF_IMPORT" "RESTRICT_CONV_HISTORY" "RESTRICT_PLANS" "RESTRICT_INTENT_CLASSIFIER"
    "RESTRICT_WIZARD_LLM_SCAFFOLD"
  )
  [[ ${#cap_keys[@]} -ne ${#cap_envs[@]} ]] && die "cap_keys/cap_envs length mismatch (${#cap_keys[@]} vs ${#cap_envs[@]})"
  local i
  for (( i=0; i<${#cap_keys[@]}; i++ )); do
    local key="${cap_keys[$i]}"
    local env_var="${cap_envs[$i]}"
    if [[ "$selected" == *"\"$key\""* ]]; then
      # Seçili = aktif = kısıtlama yok
      _env_set "$env_var" "false" "$env_dst"
      _apply_cap_visibility "$key" "true" "$env_dst"
    else
      # Seçilmedi = devre dışı = kısıtlı
      _env_set "$env_var" "true" "$env_dst"
      _apply_cap_visibility "$key" "false" "$env_dst"
    fi
  done

  # *_ENABLED → ters mantık: seçili=true (aktif), seçilmemiş=false (devre dışı)
  # Senkronizasyon: config.py *_enabled field'ları ile eşleşmeli
  local -a enabled_keys=( "desktop" "browser" )
  local -a enabled_envs=( "DESKTOP_ENABLED" "BROWSER_ENABLED" )
  for (( i=0; i<${#enabled_keys[@]}; i++ )); do
    local key="${enabled_keys[$i]}"
    local env_var="${enabled_envs[$i]}"
    if [[ "$selected" == *"\"$key\""* ]]; then
      _env_set "$env_var" "true" "$env_dst"
      _apply_cap_visibility "$key" "true" "$env_dst"
    else
      _env_set "$env_var" "false" "$env_dst"
      _apply_cap_visibility "$key" "false" "$env_dst"
    fi
  done
}


_capabilities_whiptail() {
  local selected
  # Tüm yetenekler varsayılan ON — kullanıcı istemediğini işareti kaldırır
  selected=$(whiptail --title "$_S_CAP_TITLE" --checklist \
    "$_S_CAP_DESC" 30 76 15 \
    "fs"               "$_S_CAP_FS"      ON \
    "network"          "$_S_CAP_NET"     ON \
    "shell"            "$_S_CAP_SHELL"   ON \
    "service_mgmt"     "$_S_CAP_SVC"     ON \
    "media"            "$_S_CAP_MEDIA"   ON \
    "calendar"         "$_S_CAP_CAL"     ON \
    "project_wizard"   "$_S_CAP_WIZ"     ON \
    "screenshot"       "$_S_CAP_SS"      ON \
    "scheduler"        "$_S_CAP_SCHED"   ON \
    "pdf_import"       "$_S_CAP_PDF"     ON \
    "conv_history"     "$_S_CAP_HIST"    ON \
    "plans"            "$_S_CAP_PLANS"   ON \
    "intent_classifier" "$_S_CAP_IC"     ON \
    "wizard_llm_scaffold" "$_S_CAP_WIZ_LLM" ON \
    "desktop"          "$_S_CAP_DESKTOP" OFF \
    "browser"          "$_S_CAP_BROWSER" OFF \
    3>&1 1>&2 2>&3) || return 0   # ESC veya Cancel = değişiklik yapma
  _write_capabilities "$selected"
}


_capabilities_telegram() {
  local env_dst="$1"
  local _tok _cid _offset _cb _cb_uid _cb_id _cb_data
  _tok="$(_env_get "TELEGRAM_BOT_TOKEN" "$env_dst" 2>/dev/null || true)"
  _cid="$(_env_get "TELEGRAM_CHAT_ID"   "$env_dst" 2>/dev/null || true)"
  if [[ -z "$_tok" || -z "$_cid" ]]; then
    warn "  ↳ Telegram credentials not in .env — falling back to text mode"
    _capabilities_text
    return
  fi

  local -a keys=( "fs" "network" "shell" "service_mgmt" "media" "calendar" "project_wizard" "screenshot" "scheduler" "pdf_import" "conv_history" "plans" "intent_classifier" "wizard_llm_scaffold" "desktop" "browser" )
  local -a labels=( "$_S_CAP_FS" "$_S_CAP_NET" "$_S_CAP_SHELL" "$_S_CAP_SVC"
                    "$_S_CAP_MEDIA" "$_S_CAP_CAL" "$_S_CAP_WIZ" "$_S_CAP_SS"
                    "$_S_CAP_SCHED" "$_S_CAP_PDF" "$_S_CAP_HIST" "$_S_CAP_PLANS" "$_S_CAP_IC" "$_S_CAP_WIZ_LLM"
                    "$_S_CAP_DESKTOP" "$_S_CAP_BROWSER" )
  local -a defaults=( "Y" "Y" "Y" "Y" "Y" "Y" "Y" "Y" "Y" "Y" "Y" "Y" "Y" "Y" "N" "N" )

  _offset="$(_tg_get_offset "$_tok")"

  # Phase 1: defaults vs customize gateway
  log "  $_S_TXT_TG_WAIT"
  _tg_send_buttons "$_tok" "$_cid" "$_S_CAP_TG_INTRO" \
    "$_S_CAP_TG_DEFAULTS_BTN:defaults"  "|" \
    "$_S_CAP_TG_CUSTOM_BTN:customize" >/dev/null

  local _gate_attempt=0
  while (( _gate_attempt < 3 )); do
    _cb="$(_tg_poll_callback "$_tok" "$_cid" "$_offset" 300)" || _cb="0 0 defaults"
    _cb_uid="$(echo "$_cb" | cut -d' ' -f1)"
    _cb_id="$(echo  "$_cb" | cut -d' ' -f2)"
    _cb_data="$(echo "$_cb" | cut -d' ' -f3)"
    _tg_answer_callback "$_tok" "$_cb_id"
    [[ "$_cb_uid" =~ ^[0-9]+$ && "$_cb_uid" -gt 0 ]] && _offset=$(( _cb_uid + 1 ))
    [[ "$_cb_data" == "defaults" || "$_cb_data" == "customize" ]] && break
    _gate_attempt=$(( _gate_attempt + 1 ))
  done
  [[ "$_cb_data" != "defaults" && "$_cb_data" != "customize" ]] && _cb_data="defaults"

  if [[ "$_cb_data" == "defaults" ]]; then
    _tg_notify "$_tok" "$_cid" "$_S_CAP_TG_DEFAULTS_APPLIED"
    ok "  $_S_CAP_TG_DEFAULTS_APPLIED"
    _write_capabilities "$(_caps_basic_str)"
    return
  fi

  # Phase 2: per-capability Y/N. After each click, send confirmation.
  local selected="" i
  for (( i=0; i<${#keys[@]}; i++ )); do
    local def="${defaults[$i]}" label="${labels[$i]}" key="${keys[$i]}"
    local _intro_label="*${label}*"
    [[ "$def" == "Y" ]] && _intro_label+="  _(önerilen: aktif)_" || _intro_label+="  _(önerilen: pasif)_"
    log "  $_S_TXT_TG_WAIT"
    _tg_send_buttons "$_tok" "$_cid" "$_intro_label" \
      "$_S_CAP_TG_BTN_ENABLE:y"  "$_S_CAP_TG_BTN_DISABLE:n" >/dev/null

    local _yn_attempt=0 _ans=""
    while (( _yn_attempt < 3 )); do
      _cb="$(_tg_poll_callback "$_tok" "$_cid" "$_offset" 300)" || _cb="0 0 ${def,,}"
      _cb_uid="$(echo "$_cb" | cut -d' ' -f1)"
      _cb_id="$(echo  "$_cb" | cut -d' ' -f2)"
      _cb_data="$(echo "$_cb" | cut -d' ' -f3)"
      _tg_answer_callback "$_tok" "$_cb_id"
      [[ "$_cb_uid" =~ ^[0-9]+$ && "$_cb_uid" -gt 0 ]] && _offset=$(( _cb_uid + 1 ))
      if [[ "$_cb_data" == "y" || "$_cb_data" == "n" ]]; then _ans="$_cb_data"; break; fi
      _yn_attempt=$(( _yn_attempt + 1 ))
    done
    [[ -z "$_ans" ]] && _ans="${def,,}"

    if [[ "$_ans" == "y" ]]; then
      selected+=" \"${key}\""
      # shellcheck disable=SC2059
      _tg_notify "$_tok" "$_cid" "$(printf "$_S_CAP_TG_CONF_ENABLED" "$label")"
    else
      # shellcheck disable=SC2059
      _tg_notify "$_tok" "$_cid" "$(printf "$_S_CAP_TG_CONF_DISABLED" "$label")"
    fi
  done

  _tg_notify "$_tok" "$_cid" "$_S_CAP_TG_DONE"
  ok "  $_S_CAP_TG_DONE"
  _write_capabilities "$selected"
}


_capabilities_text() {
  local selected=""
  local -a keys=( "fs" "network" "shell" "service_mgmt" "media" "calendar" "project_wizard" "screenshot" "scheduler" "pdf_import" "conv_history" "plans" "intent_classifier" "wizard_llm_scaffold" "desktop" "browser" )
  local -a labels=( "$_S_CAP_FS" "$_S_CAP_NET" "$_S_CAP_SHELL" "$_S_CAP_SVC"
                    "$_S_CAP_MEDIA" "$_S_CAP_CAL" "$_S_CAP_WIZ" "$_S_CAP_SS"
                    "$_S_CAP_SCHED" "$_S_CAP_PDF" "$_S_CAP_HIST" "$_S_CAP_PLANS" "$_S_CAP_IC" "$_S_CAP_WIZ_LLM"
                    "$_S_CAP_DESKTOP" "$_S_CAP_BROWSER" )
  # desktop ve browser varsayılan N (ek paket gerektirir)
  local -a defaults=( "Y" "Y" "Y" "Y" "Y" "Y" "Y" "Y" "Y" "Y" "Y" "Y" "Y" "Y" "N" "N" )
  local i ans
  for (( i=0; i<${#keys[@]}; i++ )); do
    local def="${defaults[$i]}"
    if [[ "$def" == "Y" ]]; then
      _ask_inline "  ${labels[$i]} [Y/n]:" ans
      ans="${ans:-Y}"
    else
      _ask_inline "  ${labels[$i]} [y/N]:" ans
      ans="${ans:-N}"
    fi
    [[ "${ans,,}" =~ ^y ]] && selected+=" \"${keys[$i]}\""
  done
  _write_capabilities "$selected"
}


_caps_already_set() {
  # CRLF-safe check via Python — works on Windows Git Bash .env files too
  local _f="$1"
  "$PY" -c "
import sys
try:
    txt = open(sys.argv[1]).read()
    prefixes = ('RESTRICT_', 'DESKTOP_ENABLED=', 'BROWSER_ENABLED=')
    sys.exit(0 if any(l.startswith(prefixes) for l in txt.splitlines()) else 1)
except Exception:
    sys.exit(1)
" "$_f" 2>/dev/null
}


_caps_basic_str() {
  echo '"fs" "network" "shell" "service_mgmt" "media" "calendar" "project_wizard" "screenshot" "scheduler" "pdf_import" "conv_history" "plans" "intent_classifier" "wizard_llm_scaffold"'
}


step_capabilities() {
  local env_dst="$BACKEND_DIR/.env"
  log "🔧 $_S_CAP_TITLE..."

  # .env yoksa henüz wizard çalışmamış demektir — atla
  [ ! -f "$env_dst" ] && { warn "  ↳ .env not found, skipping capabilities"; return 0; }

  # İdempotent: RESTRICT_* veya *_ENABLED zaten tanımlıysa atla (--reconfigure-capabilities olmadığı sürece)
  if ! $RECONFIGURE_CAPS && _caps_already_set "$env_dst"; then
    ok "  ↳ $_S_CAP_SKIP"
    return 0
  fi

  # --reconfigure-capabilities: mevcut capability satırlarını sil ve yeniden sor
  if $RECONFIGURE_CAPS && _caps_already_set "$env_dst"; then
    log "  ↳ $_S_CAP_RECONFIG"
    # CRLF-safe removal via Python
    "$PY" -c "
import sys, re
with open(sys.argv[1]) as f: txt = f.read()
lines = [l for l in txt.splitlines(keepends=True)
         if not re.match(r'^(RESTRICT_|DESKTOP_ENABLED|BROWSER_ENABLED)', l)]
with open(sys.argv[1], 'w') as f: f.write(''.join(lines))
" "$env_dst" 2>/dev/null || sed -i '/^RESTRICT_/d;/^DESKTOP_ENABLED/d;/^BROWSER_ENABLED/d' "$env_dst"
  fi

  # Non-interactive mode: apply Basic preset silently (no prompts).
  # Only trigger when stdin is not a TTY (true CI/CD: piped input, no pty).
  # Do NOT check stdout — it's always a pipe when tee logging is active.
  if [ ! -t 0 ]; then
    warn "  $_S_CAP_NONINTERACTIVE"
    _write_capabilities "$(_caps_basic_str)"
    return 0
  fi

  # Route to Telegram inline buttons when MESSENGER_TYPE=telegram so the user
  # can complete capability selection from their phone instead of the desktop
  # terminal. Falls back to text mode if credentials are missing.
  local _messenger
  _messenger="$(_env_get "MESSENGER_TYPE" "$env_dst" 2>/dev/null || true)"
  if [[ "$_messenger" == "telegram" ]]; then
    _capabilities_telegram "$env_dst"
  elif _wt_available; then
    _capabilities_whiptail
  else
    _capabilities_text
  fi
}

