#!/usr/bin/env bash
# lib/wizard.sh — Phase-1 .env wizards (whiptail + text) + writer.
#
# Sourced by install.sh; do not execute directly.
# shellcheck shell=bash

# Whitelists for inline-button callback values. Telegram occasionally
# redelivers stale callbacks (e.g. the user re-taps an earlier message's
# still-visible keyboard); without validation we'd write the wrong value
# (such as "anthropic" into TIMEZONE) straight into .env.
_TZ_VALID_VALUES="Europe/Istanbul Europe/London Europe/Paris America/New_York America/Los_Angeles Asia/Tokyo UTC __other__"
_LLM_VALID_VALUES="anthropic ollama gemini"
_is_in_whitelist() {  # _is_in_whitelist <value> <space-separated-list>
  local v="$1" list="$2" t
  for t in $list; do [[ "$v" == "$t" ]] && return 0; done
  return 1
}
_is_valid_tz_cb()  { _is_in_whitelist "$1" "$_TZ_VALID_VALUES"; }
_is_valid_llm_cb() { _is_in_whitelist "$1" "$_LLM_VALID_VALUES"; }

_wizard_whiptail() {
  local env_dst="$1"

  _wt_msg "$_S_WIZ_WELCOME_TITLE" "$_S_WIZ_WELCOME_MSG" || { warn "$_S_CANCEL"; return 1; }

  # ── Phase 1: Messenger type + credentials ─────────────────────────────────
  local messenger
  messenger=$(_wt_radio "$_S_WIZ_MSG_TITLE" "$_S_WIZ_MSG_MSG" \
    "whatsapp" "$_S_WIZ_MSG_WA"  ON  \
    "telegram" "$_S_WIZ_MSG_TG"  OFF \
    "cli"      "$_S_WIZ_MSG_CLI" OFF \
  ) || { warn "$_S_CANCEL"; return 1; }

  local wa_token="" wa_phone_id="" wa_secret="" wa_verify="" wa_owner=""
  local tg_token="" tg_chat_id="" tg_webhook_secret=""
  local llm="anthropic" proxy="none" tz_value="Europe/Istanbul"
  local anthropic_key="" ollama_url="" ollama_model="" gemini_key="" gemini_model=""
  local public_url="" ngrok_token="" ngrok_domain=""

  if [[ "$messenger" == "whatsapp" ]]; then
    _wt_msg "$_S_WIZ_WA_INFO_TITLE" "$_S_WIZ_WA_INFO_MSG" || return 1
    while true; do
      wa_token=$(_wt_password "$_S_WIZ_WA_INFO_TITLE" "$_S_WIZ_WA_TOKEN") || return 1
      [[ -n "$wa_token" ]] && break; _wt_msg "$_S_ERROR" "$_S_REQUIRED"
    done
    while true; do
      wa_phone_id=$(_wt_input "$_S_WIZ_WA_INFO_TITLE" "$_S_WIZ_WA_PHONE") || return 1
      [[ -n "$wa_phone_id" ]] && break; _wt_msg "$_S_ERROR" "$_S_REQUIRED"
    done
    while true; do
      wa_secret=$(_wt_password "$_S_WIZ_WA_INFO_TITLE" "$_S_WIZ_WA_SECRET") || return 1
      [[ -n "$wa_secret" ]] && break; _wt_msg "$_S_ERROR" "$_S_REQUIRED"
    done
    wa_verify="$(_gen_api_key)"
    while true; do
      wa_owner=$(_wt_input "$_S_WIZ_WA_INFO_TITLE" "$_S_WIZ_WA_OWNER") || return 1
      [[ -n "$wa_owner" ]] && break; _wt_msg "$_S_ERROR" "$_S_REQUIRED"
    done

  elif [[ "$messenger" == "telegram" ]]; then
    _wt_msg "$_S_WIZ_TG_INFO_TITLE" "$_S_WIZ_TG_INFO_MSG" || return 1
    while true; do
      tg_token=$(_wt_password "$_S_WIZ_TG_INFO_TITLE" "$_S_WIZ_TG_TOKEN") || return 1
      [[ -n "$tg_token" ]] && break; _wt_msg "$_S_ERROR" "$_S_REQUIRED"
    done
    # Drop webhook + all pending updates atomically so getUpdates starts clean
    curl -s --max-time 5 -X POST "https://api.telegram.org/bot${tg_token}/deleteWebhook?drop_pending_updates=true" >/dev/null 2>&1 || true
    # Show instructions AFTER clearing updates so the user's next message is the first one
    _wt_msg "$_S_WIZ_TG_SEND_MSG_TITLE" "$_S_WIZ_TG_SEND_MSG" || return 1
    local _tg_auto_id=""
    _tg_auto_id="$(curl -s --max-time 100 "https://api.telegram.org/bot${tg_token}/getUpdates?timeout=90&limit=1" 2>/dev/null \
      | "$PY" -c "import sys,json
try:
    d=json.load(sys.stdin)
    for u in d.get('result', []):
        if 'message' in u:
            print(u['message']['chat']['id'])
            break
except: pass" 2>/dev/null || true)"
    if [[ -n "$_tg_auto_id" ]]; then
      tg_chat_id="$_tg_auto_id"
    else
      _wt_msg "$_S_WIZ_TG_INFO_TITLE" "$_S_TXT_TG_CHATID_FAIL" || return 1
      while true; do
        tg_chat_id=$(_wt_input "$_S_WIZ_TG_INFO_TITLE" "$_S_WIZ_TG_CHAT") || return 1
        [[ -n "$tg_chat_id" ]] && break; _wt_msg "$_S_ERROR" "$_S_REQUIRED"
      done
    fi
    tg_webhook_secret="$(_gen_api_key)"

    # Connectivity test
    _tg_notify "$tg_token" "$tg_chat_id" "$_S_TXT_TG_TEST_MSG" || true
    ok "  $_S_TXT_TG_TEST_SENT"

    # TG-WIZ-1: Force ngrok + collect creds inline (Telegram needs a public URL).
    proxy="ngrok"
    _wt_msg "$_S_WIZ_TG_INFO_TITLE" "$_S_TXT_TG_MINIMAL_NOTE" || return 1
    _wt_msg "$_S_WIZ_NGROK_INFO_TITLE" "$_S_WIZ_NGROK_INFO_MSG" || return 1
    while true; do
      ngrok_token=$(_wt_password "$_S_WIZ_NGROK_INFO_TITLE" "$_S_WIZ_NGROK_TOKEN") || return 1
      if [[ -z "$ngrok_token" ]]; then _wt_msg "$_S_ERROR" "$_S_REQUIRED"; continue; fi
      if [[ ! "$ngrok_token" =~ ^[A-Za-z0-9_]{16,}$ ]]; then
        _wt_msg "$_S_ERROR" "$_S_NGROK_TOKEN_INVALID"; continue
      fi
      break
    done
    while true; do
      ngrok_domain=$(_wt_input "$_S_WIZ_NGROK_INFO_TITLE" "$_S_WIZ_NGROK_DOMAIN") || return 1
      if [[ -z "$ngrok_domain" ]]; then _wt_msg "$_S_ERROR" "$_S_REQUIRED"; continue; fi
      if [[ "$ngrok_domain" != *.* ]]; then
        _wt_msg "$_S_ERROR" "$_S_NGROK_DOMAIN_INVALID"; continue
      fi
      break
    done

    # Final "ready" notification with the public URL.
    local _public_url=""
    [[ -n "$ngrok_domain" ]] && _public_url="https://${ngrok_domain}"
    if [[ -n "$_public_url" ]]; then
      # shellcheck disable=SC2059
      _tg_notify "$tg_token" "$tg_chat_id" "$(printf "$_S_TXT_TG_TEST_MSG_READY" "$_public_url")" || true
    fi

    # ── Telegram-driven Phase 2: LLM + timezone via inline buttons ────────────
    local _tg_offset _cb _cb_uid _cb_id _cb_data
    _tg_offset="$(_tg_get_offset "$tg_token")"

    # LLM selection (whitelist-validated; see _is_valid_llm_cb).
    local _llm_attempt=0
    while (( _llm_attempt < 3 )); do
      log "  $_S_TXT_TG_WAIT"
      _tg_send_buttons "$tg_token" "$tg_chat_id" "*$_S_WIZ_LLM_TITLE*" \
        "Anthropic:anthropic" \
        "Ollama:ollama" \
        "Gemini:gemini" >/dev/null
      _cb="$(_tg_poll_callback "$tg_token" "$tg_chat_id" "$_tg_offset" 120)" || _cb="0 0 anthropic"
      _cb_uid="$(echo "$_cb" | cut -d' ' -f1)"
      _cb_id="$(echo  "$_cb" | cut -d' ' -f2)"
      _cb_data="$(echo "$_cb" | cut -d' ' -f3)"
      _tg_answer_callback "$tg_token" "$_cb_id"
      [[ "$_cb_uid" =~ ^[0-9]+$ && "$_cb_uid" -gt 0 ]] && _tg_offset=$(( _cb_uid + 1 ))
      if _is_valid_llm_cb "$_cb_data"; then break; fi
      _llm_attempt=$(( _llm_attempt + 1 ))
      warn "  Telegram returned unexpected value '$_cb_data' — re-asking LLM"
    done
    if ! _is_valid_llm_cb "$_cb_data"; then
      _cb_data="anthropic"
      warn "  Falling back to default LLM backend anthropic"
    fi
    llm="$_cb_data"
    ok "  $_S_TXT_TG_LLM_SELECTED: $llm"
    # shellcheck disable=SC2059
    _tg_notify "$tg_token" "$tg_chat_id" "$(printf "$_S_MSG_TG_LLM_CONFIRM" "$llm")" || true
    _tg_notify "$tg_token" "$tg_chat_id" "$_S_MSG_TG_BACK_TO_TERMINAL" || true

    # LLM credentials — sensitive, collected via whiptail
    if [[ "$llm" == "anthropic" ]]; then
      local _an_method
      _an_method=$(_wt_radio "$_S_WIZ_AN_INFO_TITLE" "$_S_WIZ_AN_CHOICE_MSG" \
        "login"  "$_S_WIZ_AN_CHOICE_1" ON  \
        "apikey" "$_S_WIZ_AN_CHOICE_2" OFF \
      ) || { warn "$_S_CANCEL"; return 1; }
      if [[ "$_an_method" == "apikey" ]]; then
        while true; do
          anthropic_key=$(_wt_password "$_S_WIZ_AN_INFO_TITLE" "$_S_WIZ_AN_KEY") || return 1
          [[ -n "$anthropic_key" ]] && break; _wt_msg "$_S_ERROR" "$_S_REQUIRED"
        done
      else
        _wt_msg "$_S_WIZ_AN_INFO_TITLE" "$_S_WIZ_AN_SKIP" || return 1
      fi
    elif [[ "$llm" == "ollama" ]]; then
      _wt_msg "$_S_WIZ_OL_INFO_TITLE" "$_S_WIZ_OL_INFO_MSG" || return 1
      ollama_url=$(_wt_input "$_S_WIZ_OL_INFO_TITLE"   "$_S_WIZ_OL_URL"   "http://localhost:11434") || return 1
      ollama_model=$(_wt_input "$_S_WIZ_OL_INFO_TITLE" "$_S_WIZ_OL_MODEL" "llama3") || return 1
    elif [[ "$llm" == "gemini" ]]; then
      _wt_msg "$_S_WIZ_GE_INFO_TITLE" "$_S_WIZ_GE_INFO_MSG" || return 1
      while true; do
        gemini_key=$(_wt_password "$_S_WIZ_GE_INFO_TITLE" "$_S_WIZ_GE_KEY") || return 1
        [[ -n "$gemini_key" ]] && break; _wt_msg "$_S_ERROR" "$_S_REQUIRED"
      done
      gemini_model=$(_wt_input "$_S_WIZ_GE_INFO_TITLE" "$_S_WIZ_GE_MODEL" "gemini-2.0-flash") || return 1
    fi

    # Timezone selection
    local _tz_attempt=0
    while (( _tz_attempt < 3 )); do
      log "  $_S_TXT_TG_WAIT"
      _tg_send_buttons "$tg_token" "$tg_chat_id" "*$_S_WIZ_TZ_TITLE*" \
        "🇹🇷 Istanbul:Europe/Istanbul"       "🇬🇧 London:Europe/London"      "|" \
        "🇫🇷 Paris:Europe/Paris"             "🇺🇸 NYC:America/New_York"  "|" \
        "🇺🇸 LA:America/Los_Angeles" "🇯🇵 Tokyo:Asia/Tokyo"          "|" \
        "UTC:UTC"                             "✏️ Other:__other__" >/dev/null
      _cb="$(_tg_poll_callback "$tg_token" "$tg_chat_id" "$_tg_offset" 120)" || _cb="0 0 Europe/Istanbul"
      _cb_uid="$(echo "$_cb" | cut -d' ' -f1)"
      _cb_id="$(echo  "$_cb" | cut -d' ' -f2)"
      _cb_data="$(echo "$_cb" | cut -d' ' -f3)"
      _tg_answer_callback "$tg_token" "$_cb_id"
      [[ "$_cb_uid" =~ ^[0-9]+$ && "$_cb_uid" -gt 0 ]] && _tg_offset=$(( _cb_uid + 1 ))
      if _is_valid_tz_cb "$_cb_data"; then break; fi
      _tz_attempt=$(( _tz_attempt + 1 ))
      warn "  Telegram returned unexpected value '$_cb_data' — re-asking timezone"
    done
    if ! _is_valid_tz_cb "$_cb_data"; then
      _cb_data="Europe/Istanbul"
      warn "  Falling back to default timezone Europe/Istanbul"
    fi
    if [[ "$_cb_data" == "__other__" ]]; then
      tz_value=$(_wt_input "$_S_WIZ_TZ_TITLE" "$_S_WIZ_TZ_CUSTOM" "Europe/Istanbul") || return 1
      tz_value="${tz_value:-Europe/Istanbul}"
    else
      tz_value="$_cb_data"
    fi
    ok "  $_S_TXT_TG_TZ_SELECTED: $tz_value"
    # shellcheck disable=SC2059
    _tg_notify "$tg_token" "$tg_chat_id" "$(printf "$_S_MSG_TG_TZ_CONFIRM" "$tz_value")" || true
  fi

  # ── Phase 2: LLM / Proxy / Timezone ─────────────────────────────────────────
  # WhatsApp/CLI: ask LLM + proxy + credentials + timezone.
  # Telegram: already handled above via inline buttons.

  if [[ "$messenger" == "whatsapp" ]]; then
    _wa_notify "$wa_token" "$wa_phone_id" "$wa_owner" "$_S_MSG_WIZ_WA_NOTIFY" || true
  fi

  if [[ "$messenger" != "telegram" ]]; then
    local _tmp_proxy
    _tmp_proxy=$(_wt_radio "$_S_WIZ_PRX_TITLE" "$_S_WIZ_PRX_MSG" \
      "none"        "$_S_WIZ_PRX_NONE"  ON  \
      "ngrok"       "$_S_WIZ_PRX_NGROK" OFF \
      "cloudflared" "$_S_WIZ_PRX_CF"    OFF \
      "external"    "$_S_WIZ_PRX_EXT"   OFF \
    ) || { warn "$_S_CANCEL"; return 1; }
    proxy="$_tmp_proxy"

    local _tmp_llm
    _tmp_llm=$(_wt_radio "$_S_WIZ_LLM_TITLE" "$_S_WIZ_LLM_MSG" \
      "anthropic" "$_S_WIZ_LLM_AN" ON  \
      "ollama"    "$_S_WIZ_LLM_OL" OFF \
      "gemini"    "$_S_WIZ_LLM_GE" OFF \
    ) || { warn "$_S_CANCEL"; return 1; }
    llm="$_tmp_llm"

    if [[ "$llm" == "anthropic" ]]; then
      local _an_method
      _an_method=$(_wt_radio "$_S_WIZ_AN_INFO_TITLE" "$_S_WIZ_AN_CHOICE_MSG" \
        "login"  "$_S_WIZ_AN_CHOICE_1" ON  \
        "apikey" "$_S_WIZ_AN_CHOICE_2" OFF \
      ) || { warn "$_S_CANCEL"; return 1; }
      if [[ "$_an_method" == "apikey" ]]; then
        while true; do
          anthropic_key=$(_wt_password "$_S_WIZ_AN_INFO_TITLE" "$_S_WIZ_AN_KEY") || return 1
          [[ -n "$anthropic_key" ]] && break; _wt_msg "$_S_ERROR" "$_S_REQUIRED"
        done
      else
        _wt_msg "$_S_WIZ_AN_INFO_TITLE" "$_S_WIZ_AN_SKIP" || return 1
      fi
    elif [[ "$llm" == "ollama" ]]; then
      _wt_msg "$_S_WIZ_OL_INFO_TITLE" "$_S_WIZ_OL_INFO_MSG" || return 1
      ollama_url=$(_wt_input "$_S_WIZ_OL_INFO_TITLE"   "$_S_WIZ_OL_URL"   "http://localhost:11434") || return 1
      ollama_model=$(_wt_input "$_S_WIZ_OL_INFO_TITLE" "$_S_WIZ_OL_MODEL" "llama3") || return 1
    elif [[ "$llm" == "gemini" ]]; then
      _wt_msg "$_S_WIZ_GE_INFO_TITLE" "$_S_WIZ_GE_INFO_MSG" || return 1
      while true; do
        gemini_key=$(_wt_password "$_S_WIZ_GE_INFO_TITLE" "$_S_WIZ_GE_KEY") || return 1
        [[ -n "$gemini_key" ]] && break; _wt_msg "$_S_ERROR" "$_S_REQUIRED"
      done
      gemini_model=$(_wt_input "$_S_WIZ_GE_INFO_TITLE" "$_S_WIZ_GE_MODEL" "gemini-2.0-flash") || return 1
    fi

    if [[ "$proxy" == "external" ]]; then
      while true; do
        public_url=$(_wt_input "$_S_WIZ_PRX_TITLE" "$_S_WIZ_EXT_URL") || return 1
        [[ "$public_url" == https://* ]] && break; _wt_msg "$_S_ERROR" "$_S_URL_HTTPS"
      done
    elif [[ "$proxy" == "ngrok" ]]; then
      _wt_msg "$_S_WIZ_NGROK_INFO_TITLE" "$_S_WIZ_NGROK_INFO_MSG" || return 1
      ngrok_token=$(_wt_password "$_S_WIZ_NGROK_INFO_TITLE" "$_S_WIZ_NGROK_TOKEN") || return 1
      ngrok_domain=$(_wt_input "$_S_WIZ_NGROK_INFO_TITLE" "$_S_WIZ_NGROK_DOMAIN") || return 1
    elif [[ "$proxy" == "cloudflared" ]]; then
      _wt_msg "$_S_WIZ_CF_INFO_TITLE" "$_S_WIZ_CF_INFO_MSG" || return 1
      if ! command -v cloudflared &>/dev/null; then warn "$_S_WIZ_CF_MISSING"; fi
    fi

    local tz_choice
    tz_choice=$(_wt_radio "$_S_WIZ_TZ_TITLE" "$_S_WIZ_TZ_MSG" \
      "Europe/Istanbul"    "$_S_WIZ_TZ_TRT" ON  \
      "Europe/London"      "$_S_WIZ_TZ_LON" OFF \
      "Europe/Paris"       "$_S_WIZ_TZ_PAR" OFF \
      "America/New_York"   "$_S_WIZ_TZ_NYC" OFF \
      "America/Los_Angeles" "$_S_WIZ_TZ_LAX" OFF \
      "Asia/Tokyo"         "$_S_WIZ_TZ_TYO" OFF \
      "UTC"                "$_S_WIZ_TZ_UTC" OFF \
      "other"              "$_S_WIZ_TZ_OTH" OFF \
    ) || { warn "$_S_CANCEL"; return 1; }
    if [[ "$tz_choice" == "other" ]]; then
      tz_value=$(_wt_input "$_S_WIZ_TZ_TITLE" "$_S_WIZ_TZ_CUSTOM" "Europe/Istanbul") || return 1
      tz_value="${tz_value:-Europe/Istanbul}"
    else
      tz_value="$tz_choice"
    fi
  fi

  # ── Security keys + summary ────────────────────────────────────────────────
  local api_key totp_secret
  api_key="$(_gen_api_key)"
  totp_secret="$(_gen_totp)"

  local summary="Messenger  : $messenger\nLLM Backend: $llm\nProxy      : $proxy\nTimezone   : $tz_value"
  [[ -n "$public_url" ]] && summary+="\nPublic URL : $public_url"
  [[ -n "$wa_owner"   ]] && summary+="\nWA Owner   : $wa_owner"
  summary+="\n\n$_S_WIZ_SUM_MSG_AUTO\n$_S_WIZ_SUM_MSG_CONF"
  _wt_msg "$_S_WIZ_SUM_TITLE" "$summary" || return 1

  _write_env "$env_dst" "$messenger" "$llm" "$proxy" \
    "$wa_token" "$wa_phone_id" "$wa_secret" "$wa_verify" "$wa_owner" \
    "$tg_token" "$tg_chat_id" "$tg_webhook_secret" \
    "$anthropic_key" "$ollama_url" "$ollama_model" "$gemini_key" "$gemini_model" \
    "$public_url" "$ngrok_token" "$ngrok_domain" \
    "$api_key" "$totp_secret" \
    "$tz_value"

  # For WhatsApp: send a setup-complete summary to the owner's number
  if [[ "$messenger" == "whatsapp" && -n "$wa_token" && -n "$wa_phone_id" && -n "$wa_owner" ]]; then
    local _summary
    _summary="$(printf '%s\n  Messenger : %s\n  LLM       : %s\n  Proxy     : %s\n  Timezone  : %s' \
      "$_S_MSG_WIZ_WA_SUMMARY" "$messenger" "$llm" "$proxy" "$tz_value")"
    [[ -n "$public_url"   ]] && _summary+="$(printf '\n  URL       : %s' "$public_url")"
    _wa_notify "$wa_token" "$wa_phone_id" "$wa_owner" "$_summary" || true
  fi
}


_wizard_text() {
  local env_dst="$1"
  echo ""
  echo "════════════════════════════════════════════"
  echo " $_S_TXT_TITLE"
  echo " $_S_TXT_HINT"
  echo "════════════════════════════════════════════"

  # ── Messenger seçimi ──────────────────────────────────────────────────────
  echo ""
  echo "$_S_TXT_MESSENGER"
  echo "  $_S_TXT_M1"
  echo "  $_S_TXT_M2"
  echo "  $_S_TXT_M3"
  echo ""
  _ask_inline "[1/2/3]:" _m
  local messenger
  case "${_m:-1}" in 2) messenger="telegram";; 3) messenger="cli";; *) messenger="whatsapp";; esac

  _sep
  local wa_token="" wa_phone_id="" wa_secret="" wa_verify="" wa_owner=""
  local tg_token="" tg_chat_id="" tg_webhook_secret=""
  local llm="anthropic" proxy="none" tz_value="Europe/Istanbul"
  local anthropic_key="" ollama_url="" ollama_model="" gemini_key="" gemini_model=""
  local public_url="" ngrok_token="" ngrok_domain=""

  # ── WhatsApp kimlik bilgileri ─────────────────────────────────────────────
  if [[ "$messenger" == "whatsapp" ]]; then
    echo ""
    echo "$_S_TXT_WA"
    printf "  %b\n" "$_S_WIZ_WA_INFO_MSG"
    echo ""
    _ask_req "$_S_WIZ_WA_TOKEN" wa_token
    _ask_req "$_S_WIZ_WA_PHONE" wa_phone_id
    _ask_req "$_S_WIZ_WA_SECRET" wa_secret
    wa_verify="$(_gen_api_key)"
    ok "  $_S_TXT_VERIFY_AUTO: $wa_verify"
    _ask_req "$_S_WIZ_WA_OWNER" wa_owner

  # ── Telegram kimlik bilgileri ─────────────────────────────────────────────
  elif [[ "$messenger" == "telegram" ]]; then
    echo ""
    echo "$_S_TXT_TG"
    echo ""
    printf "  %b\n" "$_S_WIZ_TG_INFO_MSG"
    echo ""
    _ask_req "$_S_WIZ_TG_TOKEN" tg_token

    # Chat ID — auto-detect (90s long-poll). User can press Enter immediately
    # to skip auto-detect and type the chat ID manually.
    # Drop webhook + all pending updates atomically so the user's next message is the first
    curl -s --max-time 5 -X POST "https://api.telegram.org/bot${tg_token}/deleteWebhook?drop_pending_updates=true" >/dev/null 2>&1 || true
    _sep
    echo ""
    echo "  ▶ $_S_WIZ_TG_SEND_MSG_TITLE"
    echo ""
    printf "  %b\n" "$_S_WIZ_TG_SEND_MSG"
    echo ""
    _ask_inline "$_S_TXT_TG_CHATID_TIP" tg_chat_id
    if [[ -z "$tg_chat_id" ]]; then
      log "  Waiting (up to 90s)..."
      local _tg_updates
      _tg_updates="$(curl -s --max-time 100 "https://api.telegram.org/bot${tg_token}/getUpdates?timeout=90&limit=1" 2>/dev/null || true)"
      tg_chat_id="$(echo "$_tg_updates" | "$PY" -c "import sys,json
try:
    d=json.load(sys.stdin)
    for u in d.get('result', []):
        if 'message' in u:
            print(u['message']['chat']['id'])
            break
except: pass" 2>/dev/null || true)"
      if [[ -n "$tg_chat_id" ]]; then
        ok "  $_S_TXT_TG_CHATID_OK: $tg_chat_id"
      else
        warn "  $_S_TXT_TG_CHATID_FAIL"
        _ask_req "$_S_WIZ_TG_CHAT" tg_chat_id
      fi
    fi
    tg_webhook_secret="$(_gen_api_key)"
    ok "  $_S_TXT_WSECRET_AUTO"

    # Interim notification: bot is reachable; user now goes back to the
    # terminal to enter ngrok credentials. After ngrok we'll send the final
    # "ready" message that includes the public URL.
    _tg_notify "$tg_token" "$tg_chat_id" "$_S_TXT_TG_TEST_MSG" || true
    ok "  $_S_TXT_TG_TEST_SENT"

    # TG-WIZ-1: Telegram requires a public URL — force ngrok and collect creds inline.
    # Validation: token alphanumeric + min 16 chars, domain contains a dot.
    proxy="ngrok"
    _sep
    echo ""
    printf "  ℹ️  %b\n" "$_S_TXT_TG_MINIMAL_NOTE"
    echo ""
    echo "▶ $_S_WIZ_NGROK_INFO_TITLE"
    echo ""
    printf "  %b\n" "$_S_WIZ_NGROK_INFO_MSG"
    echo ""
    while true; do
      _ask_inline "$_S_WIZ_NGROK_TOKEN" ngrok_token
      if [[ -z "$ngrok_token" ]]; then
        warn "    $_S_REQUIRED"; continue
      fi
      if [[ ! "$ngrok_token" =~ ^[A-Za-z0-9_]{16,}$ ]]; then
        warn "    $_S_NGROK_TOKEN_INVALID"; continue
      fi
      break
    done
    while true; do
      _ask_inline "$_S_WIZ_NGROK_DOMAIN" ngrok_domain
      if [[ -z "$ngrok_domain" ]]; then
        warn "    $_S_REQUIRED"; continue
      fi
      if [[ "$ngrok_domain" != *.* ]]; then
        warn "    $_S_NGROK_DOMAIN_INVALID"; continue
      fi
      break
    done

    # Final "ready" notification with the public URL — confirms full setup
    # before switching to inline-button Q&A.
    local _public_url=""
    [[ -n "$ngrok_domain" ]] && _public_url="https://${ngrok_domain}"
    if [[ -n "$_public_url" ]]; then
      # shellcheck disable=SC2059
      _tg_notify "$tg_token" "$tg_chat_id" "$(printf "$_S_TXT_TG_TEST_MSG_READY" "$_public_url")" || true
    fi

    # ── Telegram-driven Phase 2: LLM + timezone via inline buttons ────────────
    local _tg_offset _cb _cb_uid _cb_id _cb_data
    _tg_offset="$(_tg_get_offset "$tg_token")"

    # LLM selection (whitelist-validated; see _is_valid_llm_cb).
    _sep
    local _llm_attempt=0
    while (( _llm_attempt < 3 )); do
      log "  $_S_TXT_TG_WAIT"
      _tg_send_buttons "$tg_token" "$tg_chat_id" "*$_S_WIZ_LLM_TITLE*" \
        "Anthropic:anthropic" \
        "Ollama:ollama" \
        "Gemini:gemini" >/dev/null
      _cb="$(_tg_poll_callback "$tg_token" "$tg_chat_id" "$_tg_offset" 120)" || _cb="0 0 anthropic"
      _cb_uid="$(echo "$_cb" | cut -d' ' -f1)"
      _cb_id="$(echo  "$_cb" | cut -d' ' -f2)"
      _cb_data="$(echo "$_cb" | cut -d' ' -f3)"
      _tg_answer_callback "$tg_token" "$_cb_id"
      [[ "$_cb_uid" =~ ^[0-9]+$ && "$_cb_uid" -gt 0 ]] && _tg_offset=$(( _cb_uid + 1 ))
      if _is_valid_llm_cb "$_cb_data"; then break; fi
      _llm_attempt=$(( _llm_attempt + 1 ))
      warn "  Telegram returned unexpected value '$_cb_data' — re-asking LLM"
    done
    if ! _is_valid_llm_cb "$_cb_data"; then
      _cb_data="anthropic"
      warn "  Falling back to default LLM backend anthropic"
    fi
    llm="$_cb_data"
    ok "  $_S_TXT_TG_LLM_SELECTED: $llm"
    # shellcheck disable=SC2059
    _tg_notify "$tg_token" "$tg_chat_id" "$(printf "$_S_MSG_TG_LLM_CONFIRM" "$llm")" || true
    _tg_notify "$tg_token" "$tg_chat_id" "$_S_MSG_TG_BACK_TO_TERMINAL" || true

    # LLM credentials — sensitive, stay in terminal
    _sep
    if [[ "$llm" == "anthropic" ]]; then
      echo ""
      echo "$_S_TXT_AN"
      echo ""
      printf "  %b\n" "$_S_WIZ_AN_CHOICE_MSG"
      echo ""
      _ask_inline "[1/2]:" _an_method_txt
      if [[ "${_an_method_txt:-1}" == "2" ]]; then
        _ask_req "$_S_WIZ_AN_KEY" anthropic_key
      else
        ok "  $_S_WIZ_AN_SKIP"
      fi
    elif [[ "$llm" == "ollama" ]]; then
      echo ""
      echo "$_S_TXT_OL"
      echo ""
      _ask_inline "$_S_WIZ_OL_URL [http://localhost:11434]:" ollama_url
      ollama_url="${ollama_url:-http://localhost:11434}"
      _ask_inline "$_S_WIZ_OL_MODEL [llama3]:" ollama_model
      ollama_model="${ollama_model:-llama3}"
    elif [[ "$llm" == "gemini" ]]; then
      echo ""
      echo "$_S_TXT_GE"
      echo ""
      _ask_req "$_S_WIZ_GE_KEY" gemini_key
      _ask_inline "$_S_WIZ_GE_MODEL [gemini-2.0-flash]:" gemini_model
      gemini_model="${gemini_model:-gemini-2.0-flash}"
    fi

    # Timezone selection
    _sep
    local _tz_attempt=0
    while (( _tz_attempt < 3 )); do
      log "  $_S_TXT_TG_WAIT"
      _tg_send_buttons "$tg_token" "$tg_chat_id" "*$_S_WIZ_TZ_TITLE*" \
        "🇹🇷 Istanbul:Europe/Istanbul"  "🇬🇧 London:Europe/London"    "|" \
        "🇫🇷 Paris:Europe/Paris"        "🇺🇸 NYC:America/New_York" "|" \
        "🇺🇸 LA:America/Los_Angeles" "🇯🇵 Tokyo:Asia/Tokyo"  "|" \
        "UTC:UTC"                        "✏️ Other:__other__" >/dev/null
      _cb="$(_tg_poll_callback "$tg_token" "$tg_chat_id" "$_tg_offset" 120)" || _cb="0 0 Europe/Istanbul"
      _cb_uid="$(echo "$_cb" | cut -d' ' -f1)"
      _cb_id="$(echo  "$_cb" | cut -d' ' -f2)"
      _cb_data="$(echo "$_cb" | cut -d' ' -f3)"
      _tg_answer_callback "$tg_token" "$_cb_id"
      [[ "$_cb_uid" =~ ^[0-9]+$ && "$_cb_uid" -gt 0 ]] && _tg_offset=$(( _cb_uid + 1 ))
      if _is_valid_tz_cb "$_cb_data"; then break; fi
      _tz_attempt=$(( _tz_attempt + 1 ))
      warn "  Telegram returned unexpected value '$_cb_data' — re-asking timezone"
    done
    if ! _is_valid_tz_cb "$_cb_data"; then
      _cb_data="Europe/Istanbul"
      warn "  Falling back to default timezone Europe/Istanbul"
    fi
    if [[ "$_cb_data" == "__other__" ]]; then
      _ask_inline "  $_S_TXT_TG_TZ_OTHER" tz_value
      tz_value="${tz_value:-Europe/Istanbul}"
    else
      tz_value="$_cb_data"
    fi
    ok "  $_S_TXT_TG_TZ_SELECTED: $tz_value"
    # shellcheck disable=SC2059
    _tg_notify "$tg_token" "$tg_chat_id" "$(printf "$_S_MSG_TG_TZ_CONFIRM" "$tz_value")" || true
  fi

  # ── Phase 2: LLM / Proxy / Timezone ─────────────────────────────────────────
  # WhatsApp/CLI: ask LLM + proxy + credentials + timezone.
  # Telegram: already handled above via inline buttons.

  if [[ "$messenger" == "whatsapp" ]]; then
    _wa_notify "$wa_token" "$wa_phone_id" "$wa_owner" "$_S_MSG_WIZ_WA_NOTIFY" || true
  fi

  if [[ "$messenger" != "telegram" ]]; then
    _sep
    echo ""
    echo "$_S_TXT_PROXY"
    echo "  $_S_TXT_P1"
    echo "  $_S_TXT_P2"
    echo "  $_S_TXT_P3"
    echo "  $_S_TXT_P4"
    echo ""
    _ask_inline "[1/2/3/4]:" _p
    case "${_p:-1}" in 2) proxy="ngrok";; 3) proxy="cloudflared";; 4) proxy="external";; *) proxy="none";; esac

    _sep
    echo ""
    echo "$_S_TXT_LLM"
    echo "  $_S_TXT_L1"
    echo "  $_S_TXT_L2"
    echo "  $_S_TXT_L3"
    echo ""
    _ask_inline "[1/2/3]:" _l
    case "${_l:-1}" in 2) llm="ollama";; 3) llm="gemini";; *) llm="anthropic";; esac

    _sep
    if [[ "$llm" == "anthropic" ]]; then
      echo ""
      echo "$_S_TXT_AN"
      echo ""
      printf "  %b\n" "$_S_WIZ_AN_CHOICE_MSG"
      echo ""
      _ask_inline "[1/2]:" _an_method_txt
      if [[ "${_an_method_txt:-1}" == "2" ]]; then
        _ask_req "$_S_WIZ_AN_KEY" anthropic_key
      else
        ok "  $_S_WIZ_AN_SKIP"
      fi
    elif [[ "$llm" == "ollama" ]]; then
      echo ""
      echo "$_S_TXT_OL"
      echo ""
      _ask_inline "$_S_WIZ_OL_URL [http://localhost:11434]:" ollama_url
      ollama_url="${ollama_url:-http://localhost:11434}"
      _ask_inline "$_S_WIZ_OL_MODEL [llama3]:" ollama_model
      ollama_model="${ollama_model:-llama3}"
    elif [[ "$llm" == "gemini" ]]; then
      echo ""
      echo "$_S_TXT_GE"
      echo ""
      _ask_req "$_S_WIZ_GE_KEY" gemini_key
      _ask_inline "$_S_WIZ_GE_MODEL [gemini-2.0-flash]:" gemini_model
      gemini_model="${gemini_model:-gemini-2.0-flash}"
    fi

    _sep
    if [[ "$proxy" == "external" ]]; then
      while true; do
        _ask_inline "$_S_WIZ_EXT_URL" public_url
        [[ "$public_url" == https://* ]] && break
        warn "    $_S_URL_HTTPS"
      done
    elif [[ "$proxy" == "ngrok" ]]; then
      echo ""
      echo "▶ $_S_WIZ_NGROK_INFO_TITLE"
      echo ""
      printf "  %b\n" "$_S_WIZ_NGROK_INFO_MSG"
      echo ""
      _ask_inline "$_S_WIZ_NGROK_TOKEN" ngrok_token
      _ask_inline "$_S_WIZ_NGROK_DOMAIN" ngrok_domain
    elif [[ "$proxy" == "cloudflared" ]]; then
      echo ""
      echo "▶ $_S_WIZ_CF_INFO_TITLE"
      echo ""
      printf "  %b\n" "$_S_WIZ_CF_INFO_MSG"
      if ! command -v cloudflared &>/dev/null; then warn "$_S_WIZ_CF_MISSING"; fi
    fi

    _sep
    echo ""
    echo "▶ $_S_WIZ_TZ_TITLE"
    echo "  1) $_S_WIZ_TZ_TRT   2) $_S_WIZ_TZ_LON   3) $_S_WIZ_TZ_PAR   4) $_S_WIZ_TZ_NYC"
    echo "  5) $_S_WIZ_TZ_LAX   6) $_S_WIZ_TZ_TYO   7) $_S_WIZ_TZ_UTC   8) $_S_WIZ_TZ_OTH"
    echo ""
    _ask_inline "[1-8]:" _tz
    case "${_tz:-1}" in
      2) tz_value="Europe/London" ;;
      3) tz_value="Europe/Paris" ;;
      4) tz_value="America/New_York" ;;
      5) tz_value="America/Los_Angeles" ;;
      6) tz_value="Asia/Tokyo" ;;
      7) tz_value="UTC" ;;
      8) _ask_inline "$_S_WIZ_TZ_CUSTOM" tz_value; tz_value="${tz_value:-Europe/Istanbul}" ;;
      *) tz_value="Europe/Istanbul" ;;
    esac
  fi

  # ── Güvenlik anahtarları ──────────────────────────────────────────────────
  _sep
  echo ""
  echo "$_S_TXT_SEC"
  local api_key totp_secret
  api_key="$(_gen_api_key)"
  totp_secret="$(_gen_totp)"
  ok "  $_S_TXT_SEC_DONE"

  _write_env "$env_dst" "$messenger" "$llm" "$proxy" \
    "$wa_token" "$wa_phone_id" "$wa_secret" "$wa_verify" "$wa_owner" \
    "$tg_token" "$tg_chat_id" "$tg_webhook_secret" \
    "$anthropic_key" "$ollama_url" "$ollama_model" "$gemini_key" "$gemini_model" \
    "$public_url" "$ngrok_token" "$ngrok_domain" \
    "$api_key" "$totp_secret" \
    "$tz_value"

  # WhatsApp: setup-complete summary
  if [[ "$messenger" == "whatsapp" && -n "$wa_token" && -n "$wa_phone_id" && -n "$wa_owner" ]]; then
    local _summary
    _summary="$(printf '%s\n  Messenger : %s\n  LLM       : %s\n  Proxy     : %s\n  Timezone  : %s' \
      "$_S_MSG_WIZ_WA_SUMMARY" "$messenger" "$llm" "$proxy" "$tz_value")"
    [[ -n "$public_url" ]] && _summary+="$(printf '\n  URL       : %s' "$public_url")"
    _wa_notify "$wa_token" "$wa_phone_id" "$wa_owner" "$_summary" || true
  fi
}


_write_env() {
  local env_dst="$1"
  local messenger="$2" llm="$3" proxy="$4"
  local wa_token="$5" wa_phone_id="$6" wa_secret="$7" wa_verify="$8" wa_owner="$9"
  local tg_token="${10}" tg_chat_id="${11}" tg_webhook_secret="${12}"
  local anthropic_key="${13}" ollama_url="${14}" ollama_model="${15}"
  local gemini_key="${16}" gemini_model="${17}"
  local public_url="${18}" ngrok_token="${19}" ngrok_domain="${20}"
  local api_key="${21}" totp_secret="${22}"
  local tz_value="${23:-Europe/Istanbul}"

  local env_src="$BACKEND_DIR/.env.example"
  if [ ! -f "$env_dst" ]; then
    # Strip capability flags so step_capabilities can ask the user interactively
    grep -vE "^(RESTRICT_|DESKTOP_ENABLED|BROWSER_ENABLED|HOST_FS_ACCESS)" "$env_src" > "$env_dst"
  fi

  _env_set "MESSENGER_TYPE" "$messenger" "$env_dst"
  [[ -n "$wa_token"    ]] && _env_set "WHATSAPP_ACCESS_TOKEN"    "$wa_token"    "$env_dst"
  [[ -n "$wa_phone_id" ]] && _env_set "WHATSAPP_PHONE_NUMBER_ID" "$wa_phone_id" "$env_dst"
  [[ -n "$wa_secret"   ]] && _env_set "WHATSAPP_APP_SECRET"      "$wa_secret"   "$env_dst"
  [[ -n "$wa_verify"   ]] && _env_set "WHATSAPP_VERIFY_TOKEN"    "$wa_verify"   "$env_dst"
  [[ -n "$wa_owner"    ]] && _env_set "WHATSAPP_OWNER"           "$wa_owner"    "$env_dst"
  [[ -n "$tg_token"    ]] && _env_set "TELEGRAM_BOT_TOKEN"       "$tg_token"    "$env_dst"
  [[ -n "$tg_chat_id"  ]] && _env_set "TELEGRAM_CHAT_ID"         "$tg_chat_id"  "$env_dst"
  if [[ -n "$tg_webhook_secret" ]]; then _env_set "TELEGRAM_WEBHOOK_SECRET" "$tg_webhook_secret" "$env_dst"; fi

  _env_set "LLM_BACKEND" "$llm" "$env_dst"
  if [[ -n "$anthropic_key" ]]; then
    _env_set "ANTHROPIC_API_KEY" "$anthropic_key" "$env_dst"
  else
    # Claude Login seçildi — placeholder satırını sil ki step_claude_auth atlama
    _sed_i "$env_dst" '/^ANTHROPIC_API_KEY=/d'
  fi
  [[ -n "$ollama_url"    ]] && _env_set "OLLAMA_BASE_URL"   "$ollama_url"    "$env_dst"
  [[ -n "$ollama_model"  ]] && _env_set "OLLAMA_MODEL"      "$ollama_model"  "$env_dst"
  [[ -n "$gemini_key"    ]] && _env_set "GEMINI_API_KEY"    "$gemini_key"    "$env_dst"
  [[ -n "$gemini_model"  ]] && _env_set "GEMINI_MODEL"      "$gemini_model"  "$env_dst"

  _env_set "WEBHOOK_PROXY" "$proxy" "$env_dst"
  [[ -n "$public_url"   ]] && _env_set "PUBLIC_URL"      "$public_url"   "$env_dst"
  [[ -n "$ngrok_token"  ]] && _env_set "NGROK_AUTHTOKEN" "$ngrok_token"  "$env_dst"
  [[ -n "$ngrok_domain" ]] && _env_set "NGROK_DOMAIN"    "$ngrok_domain" "$env_dst"

  _env_set "API_KEY"     "$api_key"     "$env_dst"
  _env_set "TOTP_SECRET" "$totp_secret" "$env_dst"

  _env_set "TIMEZONE" "$tz_value" "$env_dst"

  ok "$_S_WIZ_ENV_DONE $env_dst"
}


step_env() {
  local env_dst="$BACKEND_DIR/.env"

  if $NO_WIZARD; then
    local env_src="$BACKEND_DIR/.env.example"
    if [ ! -f "$env_dst" ]; then cp "$env_src" "$env_dst"; warn "$_S_WIZ_ENV_SKIP_FLAG: $env_dst"
    else ok "$_S_WIZ_ENV_EXIST_OK"; fi
    return
  fi

  if [ ! -t 0 ]; then
    local env_src="$BACKEND_DIR/.env.example"
    [ ! -f "$env_dst" ] && cp "$env_src" "$env_dst"
    warn "$_S_WIZ_ENV_SKIP_CI $env_dst"
    return
  fi

  if [ -f "$env_dst" ] && grep -q "^ANTHROPIC_API_KEY=sk-\|^TELEGRAM_BOT_TOKEN=\|^WHATSAPP_ACCESS_TOKEN=[^Y]" "$env_dst" 2>/dev/null; then
    local rerun
    if _wt_available; then
      _wt_yesno "$_S_WIZ_ENV_EXISTS_TITLE" "$_S_WIZ_ENV_EXISTS_MSG" && rerun="$_S_TXT_RERUN_Y" || rerun="n"
    else
      _ask_inline "$_S_TXT_RERUN" rerun
    fi
    [[ "${rerun,,}" != "$_S_TXT_RERUN_Y" ]] && { ok "$_S_WIZ_ENV_EXIST_OK"; return; }
  fi

  if _wt_available; then
    _wizard_whiptail "$env_dst"
  else
    warn "$_S_TXT_NOWHIPTAIL"
    _wizard_text "$env_dst"
  fi
}

