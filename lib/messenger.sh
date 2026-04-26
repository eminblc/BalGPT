#!/usr/bin/env bash
# lib/messenger.sh — WhatsApp/Telegram notify + bot wizard runner.
#
# Sourced by install.sh; do not execute directly.
# shellcheck shell=bash

_run_messenger_wizard() {
  local _tg_token="$1" _tg_chat_id="$2"
  local _script="$SCRIPTS_DIR/setup_wizard_messenger.py"
  [ ! -f "$_script" ] && return 1
  [[ -z "${PY:-}" ]] && return 1

  WIZARD_MESSENGER="telegram" \
  WIZARD_TG_TOKEN="$_tg_token" \
  WIZARD_TG_CHAT_ID="$_tg_chat_id" \
  INSTALL_LANG="$INSTALL_LANG" \
  "$PY" "$_script" 2>/tmp/wizard_err.log
}


_wa_notify() {
  local _tok="$1" _pid="$2" _owner="${3#+}" _msg="$4"
  [ -z "$_tok" ] || [ -z "$_pid" ] || [ -z "$_owner" ] && return 0
  local _body
  _body="$("$PY" -c "
import sys, json
msg, owner = sys.argv[1], sys.argv[2]
print(json.dumps({'messaging_product':'whatsapp','to':owner,'type':'text','text':{'body':msg}}))
" "$_msg" "$_owner" 2>/dev/null)" || return 0
  curl -s --max-time 10 \
    -H "Authorization: Bearer $_tok" \
    -H "Content-Type: application/json" \
    -d "$_body" \
    "https://graph.facebook.com/${_WA_API_VER}/$_pid/messages" \
    >/dev/null 2>&1 || true
}


_tg_notify() {
  local _tok="$1" _cid="$2" _msg="$3"
  [ -z "$_tok" ] || [ -z "$_cid" ] && return 0
  local _body
  _body="$("$PY" -c "import sys,json; print(json.dumps({'chat_id':int(sys.argv[1]),'text':sys.argv[2]}))" \
    "$_cid" "$_msg" 2>/dev/null)" || return 0
  curl -s --max-time 10 \
    -H "Content-Type: application/json" \
    -d "$_body" \
    "https://api.telegram.org/bot${_tok}/sendMessage" \
    >/dev/null 2>&1 || true
}


_apply_wiz_to_env() {
  local _json="$1" _env="$2"
  local _llm _proxy _tz _ak _ou _om _gk _gm _pu _nt _nd _caps

  _llm="$(_parse_wiz "$_json" "llm"          "anthropic")"
  _proxy="$(_parse_wiz "$_json" "proxy"       "none")"
  _tz="$(_parse_wiz "$_json"   "timezone"     "Europe/Istanbul")"
  _ak="$(_parse_wiz "$_json"   "anthropic_key" "")"
  _ou="$(_parse_wiz "$_json"   "ollama_url"   "http://localhost:11434")"
  _om="$(_parse_wiz "$_json"   "ollama_model" "llama3")"
  _gk="$(_parse_wiz "$_json"   "gemini_key"   "")"
  _gm="$(_parse_wiz "$_json"   "gemini_model" "gemini-2.0-flash")"
  _pu="$(_parse_wiz "$_json"   "public_url"   "")"
  _nt="$(_parse_wiz "$_json"   "ngrok_token"  "")"
  _nd="$(_parse_wiz "$_json"   "ngrok_domain" "")"
  _caps="$(_parse_wiz "$_json" "caps_selected" "")"

  _env_set "LLM_BACKEND"   "$_llm"   "$_env"
  _env_set "WEBHOOK_PROXY" "$_proxy" "$_env"
  _env_set "TIMEZONE"      "$_tz"    "$_env"

  if [[ -n "$_ak" ]]; then
    _env_set "ANTHROPIC_API_KEY" "$_ak" "$_env"
  else
    _sed_i "$_env" '/^ANTHROPIC_API_KEY=/d'
  fi
  [[ -n "$_ou" ]] && _env_set "OLLAMA_BASE_URL" "$_ou" "$_env"
  [[ -n "$_om" ]] && _env_set "OLLAMA_MODEL"    "$_om" "$_env"
  [[ -n "$_gk" ]] && _env_set "GEMINI_API_KEY"  "$_gk" "$_env"
  [[ -n "$_gm" ]] && _env_set "GEMINI_MODEL"    "$_gm" "$_env"
  [[ -n "$_pu" ]] && _env_set "PUBLIC_URL"       "$_pu" "$_env"
  [[ -n "$_nt" ]] && _env_set "NGROK_AUTHTOKEN"  "$_nt" "$_env"
  [[ -n "$_nd" ]] && _env_set "NGROK_DOMAIN"     "$_nd" "$_env"

  if [[ -n "$_caps" ]]; then
    _write_capabilities "$_caps"
    ok "  ↳ Capabilities written from Telegram wizard"
  fi
}


_collect_terminal_secrets() {
  local _json="$1" _env="$2"
  local _sentinel="__TERMINAL__"
  local _ak _gk _nt
  _ak="$(_parse_wiz "$_json" "anthropic_key" "")"
  _gk="$(_parse_wiz "$_json" "gemini_key"    "")"
  _nt="$(_parse_wiz "$_json" "ngrok_token"   "")"

  if [[ "$_ak" == "$_sentinel" || "$_gk" == "$_sentinel" || "$_nt" == "$_sentinel" ]]; then
    echo ""
    echo "  ════════════════════════════════════════════════════"
    echo "  $_S_TXT_WIZ_TERMINAL_SECRETS_TITLE"
    echo "  ════════════════════════════════════════════════════"
    echo ""
    if [[ "$_ak" == "$_sentinel" ]]; then
      local _val=""
      _ask_secret "$_S_TXT_WIZ_ANTHROPIC_KEY" _val
      [[ -n "$_val" ]] && _env_set "ANTHROPIC_API_KEY" "$_val" "$_env"
    fi
    if [[ "$_gk" == "$_sentinel" ]]; then
      local _val=""
      _ask_secret "$_S_TXT_WIZ_GEMINI_KEY" _val
      [[ -n "$_val" ]] && _env_set "GEMINI_API_KEY" "$_val" "$_env"
    fi
    if [[ "$_nt" == "$_sentinel" ]]; then
      local _val=""
      _ask_secret "$_S_TXT_WIZ_NGROK_TOKEN" _val
      [[ -n "$_val" ]] && _env_set "NGROK_AUTHTOKEN" "$_val" "$_env"
    fi
    echo ""
  fi
}

