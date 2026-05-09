#!/usr/bin/env bash
# lib/totp.sh — TOTP QR rendering + messenger send fallback.
#
# Sourced by install.sh; do not execute directly.
# shellcheck shell=bash

step_show_totp() {
  local env_dst="$BACKEND_DIR/.env"
  [ ! -f "$env_dst" ] && return

  local totp_secret
  totp_secret="$(_read_env_var "TOTP_SECRET" "$env_dst")"
  if [[ -z "$totp_secret" || "$totp_secret" == *DOLDUR* || "$totp_secret" == *FILL* ]]; then return; fi

  # _TOTP_QR_OK: set to true by _print_qr when a terminal QR is actually rendered
  _TOTP_QR_OK=false

  _print_qr() {
    local label="$1" secret="$2"
    local heading="$_S_TOTP_OWNER"
    local uri="otpauth://totp/BalGPT%3A${label}?secret=${secret}&issuer=BalGPT"
    echo ""
    echo "  ── $heading ──────────────────────────────"
    echo "  $_S_TOTP_SECRET : $secret"
    echo "  $_S_TOTP_URI    : $uri"
    # Locate a Python interpreter with the `qrcode` package available.
    # Tiered fallback (best → worst):
    #   1. Project venv (native install)
    #   2. System python that already has qrcode (distro pkg, prior pip)
    #   3. Ephemeral venv at $TMPDIR/balgpt_qr_venv_$$ — survives PEP 668
    #      (Ubuntu 23+/Debian 12+/brew block `pip install --user`).  Cached
    #      across owner+admin calls; cleaned up at end of step_show_totp.
    local _py=""
    # Windows uses Scripts/python.exe, Linux/macOS uses bin/python
    local _venv_py="$BACKEND_DIR/venv/bin/python"
    [[ -x "$BACKEND_DIR/venv/Scripts/python.exe" ]] && _venv_py="$BACKEND_DIR/venv/Scripts/python.exe"
    if [[ -x "$_venv_py" ]] && "$_venv_py" -c "import qrcode" 2>/dev/null; then
      _py="$_venv_py"
    fi
    if [[ -z "$_py" ]] && [[ -n "${PY:-}" ]] && "$PY" -c "import qrcode" 2>/dev/null; then
      _py="$PY"
    fi
    if [[ -z "$_py" ]] && [[ -n "${PY:-}" ]]; then
      : "${_TOTP_QR_VENV:=${TMPDIR:-/tmp}/balgpt_qr_venv_$$}"
      local _vbin="bin"; is_windows && _vbin="Scripts"
      local _vpy="$_TOTP_QR_VENV/$_vbin/python"
      is_windows && _vpy="${_vpy}.exe"
      if [[ ! -x "$_vpy" ]]; then
        "$PY" -m venv "$_TOTP_QR_VENV" 2>/dev/null \
          && "$_TOTP_QR_VENV/$_vbin/pip" install --quiet qrcode 2>/dev/null \
          || true
      fi
      [[ -x "$_vpy" ]] && "$_vpy" -c "import qrcode" 2>/dev/null && _py="$_vpy"
    fi
    local _qr_script
    _qr_script="$(mktemp /tmp/qr_XXXXXX.py 2>/dev/null || echo /tmp/qr_print.py)"
    cat > "$_qr_script" <<'PYEOF'
import sys, qrcode
uri = sys.argv[1]
qr = qrcode.QRCode(border=1)
qr.add_data(uri)
qr.make(fit=True)
qr.print_ascii(invert=True)
PYEOF
    if command -v qrencode &>/dev/null; then
      echo ""
      qrencode -t ANSIUTF8 -m 2 "$uri"
      _TOTP_QR_OK=true
    elif [[ -n "$_py" ]]; then
      echo ""
      # PYTHONIOENCODING=utf-8 — Windows code pages (e.g. cp1254 on TR) cannot
      # encode the Unicode block chars (█▀▄▌▐) qrcode prints, raising
      # UnicodeEncodeError and crashing the installer. Make it non-fatal:
      # the secret/URI is already shown above, and the no-QR recovery path
      # below offers to send TOTP codes via messenger.
      if PYTHONIOENCODING=utf-8 "$_py" "$_qr_script" "$uri" 2>/dev/null; then
        _TOTP_QR_OK=true
      else
        warn "  QR terminalde çizilemedi — yukarıdaki Secret'ı elle Authenticator'a girin"
      fi
    else
      # Online QR URL fallback — no terminal rendering possible
      local _encoded_uri
      if [[ -n "${PY:-}" ]]; then
        _encoded_uri="$(printf '%s' "$uri" | "$PY" -c 'import sys,urllib.parse; print(urllib.parse.quote(sys.stdin.read().strip(), safe=""))')"
      else
        _encoded_uri="$(printf '%s' "$uri" | sed 's/&/%26/g; s/=/%3D/g; s/?/%3F/g; s/:/%3A/g; s|/|%2F|g')"
      fi
      echo ""
      echo "  $_S_TOTP_QR_ONLINE"
      echo "  → https://api.qrserver.com/v1/create-qr-code/?size=300x300&data=${_encoded_uri}"
      echo ""
      echo "  ┌─ $_S_TOTP_QR_MANUAL ─────────────────────────────────┐"
      echo "  │  1. Authenticator uygulamasını aç (Google/Authy)     │"
      echo "  │  2. '+' → 'Kurulum anahtarı gir' seç                 │"
      echo "  │  3. Hesap: BalGPT:${label}                          │"
      echo "  │  4. Anahtar: $secret"
      echo "  │  5. Tür: Zamana dayalı (TOTP)                        │"
      echo "  └──────────────────────────────────────────────────────┘"
    fi
    echo ""
    echo "  ── $_S_TOTP_GA_TITLE ──"
    printf "  %b\n" "$_S_TOTP_GA_STEPS"
    echo "  $_S_TOTP_GA_NOQUR"
    echo "  ────────────────────────────────────────────────────"
    rm -f "$_qr_script" 2>/dev/null || true
  }

  echo ""
  echo "╔══════════════════════════════════════════════════════╗"
  echo "║  $_S_TOTP_TITLE"
  echo "║  $_S_TOTP_SUBTITLE"
  echo "╚══════════════════════════════════════════════════════╝"
  _print_qr "owner" "$totp_secret"
  echo ""
  warn "$_S_TOTP_WARN"

  # ── QR kod oluşturulamadıysa: gizli kodları net göster + messenger gönder seçeneği
  if [[ "$_TOTP_QR_OK" != "true" ]] && [ -t 0 ]; then
    echo ""
    echo "  ════════════════════════════════════════════════════"
    warn "  $_S_TOTP_NO_QR_HEADING"
    echo "  ════════════════════════════════════════════════════"
    echo ""
    echo "  ★  $_S_TOTP_NO_QR_OWNER : $totp_secret"
    echo ""
    _ask_inline "  $_S_TOTP_NO_QR_SEND_HINT" _totp_send_choice
    # shellcheck disable=SC2154  # _totp_send_choice set by _ask_inline (indirect)
    if [[ "${_totp_send_choice}" == "1" ]]; then
      log "  $_S_TOTP_NO_QR_SENDING"
      if _totp_send_via_messenger "$totp_secret" "$env_dst"; then
        ok "  $_S_TOTP_NO_QR_SENT"
      else
        warn "  $_S_TOTP_NO_QR_SEND_FAIL"
      fi
    else
      echo "  $_S_TOTP_NO_QR_CLOSE"
    fi
  fi

  # Cleanup ephemeral QR venv if we created one (Tier 3 fallback)
  if [[ -n "${_TOTP_QR_VENV:-}" && -d "$_TOTP_QR_VENV" ]]; then
    rm -rf "$_TOTP_QR_VENV" 2>/dev/null || true
    unset _TOTP_QR_VENV
  fi
}


_totp_send_via_messenger() {
  local _sec="$1" _env="$2"
  local _messenger _msg _msg_json

  _messenger="$(_read_env_var "MESSENGER_TYPE" "$_env")"

  if [[ "$_messenger" == "telegram" ]]; then
    local _tok _cid
    _tok="$(_read_env_var "TELEGRAM_BOT_TOKEN" "$_env")"
    _cid="$(_read_env_var "TELEGRAM_CHAT_ID"   "$_env")"
    [[ -z "$_tok" || -z "$_cid" ]] && return 1
    _msg="🔐 <b>TOTP Secret (backup)</b>

<b>TOTP:</b> <code>$_sec</code>

To add to Google Authenticator:
• Open app → + → Enter setup key
• Account <code>BalGPT:owner</code>, Key <code>$_sec</code>
• Type: Time-based (TOTP)"

    _msg_json="$("$PY" -c "import sys,json; print(json.dumps(sys.argv[1]))" "$_msg" 2>/dev/null)" || return 1
    curl -s --max-time 15 \
      -H "Content-Type: application/json" \
      -d "{\"chat_id\":$_cid,\"text\":$_msg_json,\"parse_mode\":\"HTML\"}" \
      "https://api.telegram.org/bot${_tok}/sendMessage" \
      | "$PY" -c "import sys,json; d=json.load(sys.stdin); exit(0 if d.get('ok') else 1)" 2>/dev/null
    return $?

  elif [[ "$_messenger" == "whatsapp" ]]; then
    local _wtok _wpid _wown
    _wtok="$(_read_env_var "WHATSAPP_ACCESS_TOKEN"    "$_env")"
    _wpid="$(_read_env_var "WHATSAPP_PHONE_NUMBER_ID" "$_env")"
    _wown="$(_read_env_var "WHATSAPP_OWNER"           "$_env")"
    _wown="${_wown#+}"
    [[ -z "$_wtok" || -z "$_wpid" || -z "$_wown" ]] && return 1
    _msg="🔐 TOTP Secret (backup)

TOTP: $_sec

Google Authenticator:
• Account: BalGPT:owner  Key: $_sec
• Type: Time-based (TOTP)"

    _msg_json="$("$PY" -c "import sys,json; print(json.dumps(sys.argv[1]))" "$_msg" 2>/dev/null)" || return 1
    curl -s --max-time 15 \
      -H "Authorization: Bearer $_wtok" \
      -H "Content-Type: application/json" \
      -d "{\"messaging_product\":\"whatsapp\",\"to\":\"$_wown\",\"type\":\"text\",\"text\":{\"body\":$_msg_json}}" \
      "https://graph.facebook.com/${_WA_API_VER}/${_wpid}/messages" \
      | "$PY" -c "import sys,json; d=json.load(sys.stdin); exit(0 if d.get('messages') else 1)" 2>/dev/null
    return $?
  fi
  return 1
}

