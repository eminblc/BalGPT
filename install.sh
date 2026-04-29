#!/usr/bin/env bash
# install.sh — BalGPT Setup Script (Personal AI Agent / Kişisel AI Ajan)
#
# Usage / Kullanım:
#   ./install.sh                         # Interactive wizard / İnteraktif sihirbaz
#   sudo ./install.sh                    # With systemd unit install / Systemd kurulumu ile
#   ./install.sh --no-systemd            # Dependencies + .env only / Yalnızca bağımlılıklar
#   ./install.sh --pm2                   # PM2 process manager
#   ./install.sh --docker                # Docker: wizard + selective image build / Docker: sihirbaz + seçici image build
#   ./install.sh --no-wizard             # Skip .env wizard (CI) / .env sihirbazını atla
#   ./install.sh --reconfigure-capabilities  # Re-run capability wizard only / Yalnızca yetenek sihirbazı
#   ./install.sh --register-webhook         # Register Telegram webhook (after services start) / Telegram webhook kaydı (servisler başladıktan sonra)
#   INSTALL_LANG=en ./install.sh         # Force language / Dil seç (tr|en)
#
# Messengers:  whatsapp | telegram | cli
# LLM:         anthropic | ollama | gemini
# Proxy:       none | ngrok | cloudflared | external
# Deployment:  systemd | pm2 | docker

set -euo pipefail

# ── Constants / Sabitler ──────────────────────────────────────────────────────

ROOT_DIR="${ROOT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
SCRIPTS_DIR="$ROOT_DIR/scripts"
BACKEND_DIR="$SCRIPTS_DIR/backend"
BRIDGE_DIR="$SCRIPTS_DIR/claude-code-bridge"
# These two are consumed inside lib/steps.sh (step_systemd) — shellcheck can't
# follow sources for unused-var analysis, hence the per-line disables.
# shellcheck disable=SC2034
SYSTEMD_DIR="$ROOT_DIR/systemd"
# shellcheck disable=SC2034
SYSTEM_UNIT_DIR="/etc/systemd/system"

set +u
CURRENT_USER="${SUDO_USER:-${USER:-$(id -un 2>/dev/null || whoami 2>/dev/null || echo user)}}"
set -u
NODE_PATH="$(command -v node 2>/dev/null || echo /usr/bin/node)"
API_PORT="${PORT:-8010}"
BRIDGE_PORT="${BRIDGE_PORT:-8013}"
_WA_API_VER="v21.0"

NO_SYSTEMD=false
USE_PM2=false
USE_DOCKER=false
NO_WIZARD=false
RECONFIGURE_CAPS=false
REGISTER_WEBHOOK=false

for arg in "$@"; do
  [[ "$arg" == "--no-systemd"              ]] && NO_SYSTEMD=true
  [[ "$arg" == "--pm2"                     ]] && USE_PM2=true && NO_SYSTEMD=true
  [[ "$arg" == "--docker"                  ]] && USE_DOCKER=true && NO_SYSTEMD=true
  [[ "$arg" == "--no-wizard"               ]] && NO_WIZARD=true
  [[ "$arg" == "--reconfigure-capabilities" ]] && RECONFIGURE_CAPS=true
  [[ "$arg" == "--register-webhook"        ]] && REGISTER_WEBHOOK=true
done

# ── Library modules ───────────────────────────────────────────────────────────
# Each lib/*.sh handles a single concern (logging, env, wizards, etc).
# See lib/<file>.sh headers for what each provides.
# shellcheck source=lib/log.sh
source "$ROOT_DIR/lib/log.sh"
# shellcheck source=lib/env.sh
source "$ROOT_DIR/lib/env.sh"
# shellcheck source=lib/i18n.sh
source "$ROOT_DIR/lib/i18n.sh"
# shellcheck source=lib/security.sh
source "$ROOT_DIR/lib/security.sh"
# shellcheck source=lib/wizard_ui.sh
source "$ROOT_DIR/lib/wizard_ui.sh"
# shellcheck source=lib/messenger.sh
source "$ROOT_DIR/lib/messenger.sh"
# shellcheck source=lib/wizard.sh
source "$ROOT_DIR/lib/wizard.sh"
# shellcheck source=lib/capabilities.sh
source "$ROOT_DIR/lib/capabilities.sh"
# shellcheck source=lib/totp.sh
source "$ROOT_DIR/lib/totp.sh"
# shellcheck source=lib/packages.sh
source "$ROOT_DIR/lib/packages.sh"
# shellcheck source=lib/steps.sh
source "$ROOT_DIR/lib/steps.sh"

# Platform detection — Git Bash/MSYS/Cygwin venv layout differs (Scripts/ vs bin/)
is_windows() { [[ "$(uname -s 2>/dev/null)" =~ ^(MINGW|MSYS|CYGWIN) ]]; }

# ── Python interpreter selection (cross-platform) ─────────────────────────────
# Single source of truth: every script-side python call uses "$PY".
# Detects MS Store python3.exe stub (Win10/11) which is found by `command -v`
# but exits silently — version probe rejects it (no usable output).
# Windows order: py (PEP 397 launcher) → python3 → python.
# Linux/macOS order: python3 → python → py  (avoids tools named "py" that are
#   not real interpreters, e.g. the "pythonpy" one-liner utility on Ubuntu).
# Pyotp-dependent code (security.sh, totp.sh) prefers the venv binary first
# and falls back to "$PY" — this is the system-side picker only.
_pick_python() {
  local _c _v
  local _list
  if is_windows; then
    _list="py python3 python"
  else
    _list="python3 python py"
  fi
  for _c in $_list; do
    command -v "$_c" >/dev/null 2>&1 || continue
    "$_c" -c '' 2>/dev/null || continue
    _v="$("$_c" -c 'import sys; print(sys.version_info.major)' 2>/dev/null)" || continue
    [[ "$_v" == "3" ]] && { echo "$_c"; return 0; }
  done
  return 1
}
PY="$(_pick_python)" || {
  echo "[install] FATAL: Python 3 bulunamadı / Python 3 not found (tried: py python3 python)" >&2
  exit 1
}
export PY

# ── Language selection / Dil seçimi ──────────────────────────────────────────

INSTALL_LANG="${INSTALL_LANG:-}"  # override via env; empty = ask

# ── Prerequisites / Önkoşullar ────────────────────────────────────────────────

check_prereqs() {
  # Windows (Git Bash / MSYS / Cygwin) native install is not supported:
  # venv layout uses Scripts/ instead of bin/, and many Linux-only packages
  # (uvloop, dbus-python, python-xlib) cannot be installed.  Force Docker.
  if is_windows && ! $USE_DOCKER; then
    die "Windows native install desteklenmiyor — 'bash install.sh --docker' ile çalıştırın. / Native install on Windows is not supported — use 'bash install.sh --docker'."
  fi

  if $USE_DOCKER; then
    # Docker modunda host'ta Python/Node/Claude gerekmez; docker ve compose yeterli
    if ! command -v docker &>/dev/null; then die "$_S_DOCKER_NOT_FOUND"; fi
    if ! docker compose version &>/dev/null 2>&1; then die "$_S_DOCKER_COMPOSE_NOT_FOUND"; fi
    # Daemon çalışıyor mu? (--version değil, info kullan)
    if ! docker info &>/dev/null 2>&1; then
      die "Docker daemon çalışmıyor — Docker Desktop'ı başlat ve tekrar dene. / Docker daemon is not running — start Docker Desktop and try again."
    fi
    ok "Docker: $(docker --version)"
    return
  fi

  [[ -z "${PY:-}" ]] && die "$_S_PRE_PY_MISSING"
  local py_major py_minor
  py_major="$("$PY" -c 'import sys; print(sys.version_info.major)' 2>/dev/null || echo 0)"
  py_minor="$("$PY" -c 'import sys; print(sys.version_info.minor)' 2>/dev/null || echo 0)"
  if [[ "$py_major" -lt 3 ]] || [[ "$py_major" -eq 3 && "$py_minor" -lt 11 ]]; then
    die "${_S_PRE_PY_OLD}$("$PY" --version)${_S_PRE_PY_OLD2}"
  fi
  ok "Python: $("$PY" --version)"

  if ! command -v node &>/dev/null; then die "$_S_PRE_NODE_MISSING"; fi
  local node_major
  node_major="$(node --version 2>/dev/null | tr -d 'v' | cut -d. -f1)"
  if [[ "${node_major:-0}" -lt 18 ]]; then
    die "${_S_PRE_NODE_OLD}$(node --version)${_S_PRE_NODE_OLD2}"
  fi
  ok "Node: $(node --version)"

  if command -v claude &>/dev/null; then
    ok "Claude CLI: $(claude --version 2>/dev/null | head -1 || echo 'installed')"
  else
    warn "$_S_PRE_CLAUDE_MISSING"
    warn "$_S_PRE_CLAUDE_HINT"
    warn "$_S_PRE_CLAUDE_CONT"
  fi
}

# ── Main ──────────────────────────────────────────────────────────────────────

main() {
  # ── Debug logging ─────────────────────────────────────────────────────────
  # All stdout+stderr goes to both terminal and log file.
  # set -x trace goes to a separate trace file (no terminal clutter).
  local _ts _state_dir
  _ts="$(date +%Y%m%d_%H%M%S 2>/dev/null || echo 'x')"
  # Logs contain secrets when set -x trace is active (tokens, TOTP, API keys).
  # Write to XDG_STATE_HOME with 0600 perms instead of project root to prevent
  # accidental commits or world-readable exposure.
  _state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/balgpt"
  mkdir -p "$_state_dir" 2>/dev/null && chmod 700 "$_state_dir" 2>/dev/null || _state_dir="$ROOT_DIR"
  LOG_FILE="${_state_dir}/install_${_ts}.log"
  TRACE_FILE="${_state_dir}/install_${_ts}_trace.log"
  ( umask 077; : > "$LOG_FILE"; : > "$TRACE_FILE" ) 2>/dev/null || true
  exec > >(tee -a "$LOG_FILE") 2>&1
  if exec 9>"$TRACE_FILE" 2>/dev/null; then
    export BASH_XTRACEFD=9
    set -x
  fi
  # shellcheck disable=SC2154  # _rc is assigned inside the trap body itself
  trap '
    _rc=$?; set +x 2>/dev/null
    echo ""
    echo "════════════════════════════════════════════"
    if [[ $_rc -ne 0 ]]; then
      echo " ❌ install.sh CRASH — exit $_rc — $(date)"
      echo " 📋 Log  : '"$LOG_FILE"'"
      echo " 🔍 Trace: '"$TRACE_FILE"'"
    else
      echo " ✅ install.sh OK — $(date)"
      echo " 📋 Log  : '"$LOG_FILE"'"
    fi
    echo "════════════════════════════════════════════"
  ' EXIT
  {
    echo "============================================"
    echo " install.sh — $(date)"
    echo " bash  : $BASH_VERSION"
    echo " OS    : $(uname -s -r 2>/dev/null || echo unknown)"
    echo " ROOT  : $ROOT_DIR"
    echo " USER  : $CURRENT_USER"
    echo "============================================"
  }

  _select_language
  _load_strings
  echo " 📋 $_S_LOG_FILE  : $LOG_FILE"
  echo " 🔍 $_S_LOG_TRACE : $TRACE_FILE"
  echo ""

  # Friendly welcome — only when wizard will actually run (skip in --no-wizard CI).
  if ! $NO_WIZARD && ! $RECONFIGURE_CAPS && [ -t 0 ]; then
    echo "  ╭──────────────────────────────────────────────────────────────────╮"
    if [[ "$INSTALL_LANG" == "en" ]]; then
      echo "  │  Welcome! 👋  This will take ~10–20 minutes.                     │"
      echo "  │                                                                  │"
      echo "  │  You'll be asked ~6 questions.  Each has a 🎯 RECOMMENDED       │"
      echo "  │  answer — when in doubt, pick that one.                          │"
      echo "  │                                                                  │"
      echo "  │  💡 Tips for first-time users:                                  │"
      echo "  │     • Messenger →  pick Telegram (easiest)                       │"
      echo "  │     • Webhook   →  pick ngrok (free static URL)                  │"
      echo "  │     • LLM       →  pick Anthropic + Claude Login                 │"
      echo "  │     • You can press ESC anytime to cancel and re-run later.      │"
      echo "  ╰──────────────────────────────────────────────────────────────────╯"
    else
      echo "  │  Hoş geldin! 👋  Süre: ~10–20 dakika.                            │"
      echo "  │                                                                  │"
      echo "  │  Sana ~6 soru soracağım.  Her birinin 🎯 ÖNERİLEN cevabı var —  │"
      echo "  │  emin değilsen onu seç.                                          │"
      echo "  │                                                                  │"
      echo "  │  💡 İlk kez kuruyorsan:                                         │"
      echo "  │     • Messenger →  Telegram seç (en kolay)                       │"
      echo "  │     • Webhook   →  ngrok seç (ücretsiz statik URL)               │"
      echo "  │     • LLM       →  Anthropic + Claude Login seç                  │"
      echo "  │     • İstediğin an ESC ile iptal edip sonra tekrar çalıştırabilirsin. │"
      echo "  ╰──────────────────────────────────────────────────────────────────╯"
    fi
    echo ""
  fi

  # Hızlı yol: --register-webhook — servislerin public URL'ini bekle, webhook'u kaydet
  if $REGISTER_WEBHOOK; then
    step_register_webhook
    ok "$_S_DONE_TITLE"
    return 0
  fi

  # Hızlı yol: --reconfigure-capabilities — yalnızca yetenek sihirbazını çalıştır
  if $RECONFIGURE_CAPS && ! $NO_WIZARD; then
    echo "=================================================="
    echo " BalGPT —$_S_CAP_TITLE"
    echo "=================================================="
    step_capabilities
    if $USE_DOCKER; then
      # Docker modunda image'ı yeni seçime göre yeniden build et
      step_docker_build
    elif [ -d "$BACKEND_DIR/venv" ]; then
      # Yeni seçime göre paketleri yeniden kur (venv varsa)
      step_proxy_binary
      step_venv
    fi
    ok "$_S_DONE_TITLE"
    return 0
  fi

  echo "=================================================="
  echo " $_S_BANNER_TITLE"
  echo " ROOT_DIR  : $ROOT_DIR"
  echo " USER      : $CURRENT_USER"
  echo " NODE      : $NODE_PATH"
  echo " API_PORT  : $API_PORT  |  BRIDGE_PORT: $BRIDGE_PORT"
  echo "=================================================="

  check_prereqs
  step_env  # .env oluştur / güncelle (Telegram için sadece creds; LLM/proxy/tz/caps sonra)

  # ── Telegram: write sensible defaults; Stage-2 wizard finishes the rest ──
  # Per TG-WIZ-1 design: install.sh asks only bot creds + ngrok in terminal;
  # LLM/timezone/capabilities are configured from inside the bot via !wizard.
  local _env_file="$BACKEND_DIR/.env"
  if [[ "$(_env_get "MESSENGER_TYPE" "$_env_file")" == "telegram" ]] \
     && [[ -z "$(_env_get "LLM_BACKEND" "$_env_file")" ]] \
     && ! $NO_WIZARD; then
    log "  $_S_MSG_WIZ_TG_INSTALL_NOTICE"
    _env_set "LLM_BACKEND"   "anthropic"        "$_env_file"
    _env_set "WEBHOOK_PROXY" "ngrok"             "$_env_file"
    _env_set "TIMEZONE"      "Europe/Istanbul"   "$_env_file"
    _sed_i "$_env_file" '/^ANTHROPIC_API_KEY=YOUR_ANTHROPIC_API_KEY/d' 2>/dev/null || true
    # Spec-defined defaults: core caps on, desktop+browser off.
    _write_capabilities '"fs" "network" "shell" "service_mgmt" "media" "calendar" "project_wizard" "screenshot" "scheduler" "pdf_import" "conv_history" "plans" "intent_classifier" "wizard_llm_scaffold"'
  fi

  step_capabilities    # RESTRICT_* / *_ENABLED flag'lerini yaz (caps wizard'dan veya varsayılan)
  step_host_fs_access  # Docker host filesystem erişimi (none/ro/rw)

  if $USE_DOCKER; then
    # Docker modu: auth → data dirs → build & start
    # claude auth login BEFORE docker_build so credentials are ready for the bind mount
    step_claude_auth
    step_data_dirs
    step_docker_group
    step_docker_build
  else
    step_proxy_binary  # cloudflared seçildiyse binary'yi kur
    step_venv          # seçili yeteneklere göre paketleri kur
    step_npm
    step_data_dirs
    step_docker_group
    step_systemd
    step_pm2

    echo ""
    log "$_S_STEP_SYNTAX"
    (cd "$SCRIPTS_DIR" && backend/venv/bin/python -c "from backend.main import app; print('[✓] Python import OK')")
    node --check "$BRIDGE_DIR/server.js" && echo "[✓] Node syntax OK"

    echo ""
    log "$_S_STEP_TESTS"
    if (cd "$SCRIPTS_DIR" && backend/venv/bin/python -m pytest tests/ -q --tb=short 2>&1); then
      ok "$_S_STEP_TEST_PASS"
    else
      warn "$_S_STEP_TEST_FAIL"
    fi

    if $USE_PM2; then
      echo ""
      log "$_S_STEP_HEALTH_PM2"
      sleep 3
      if curl -sf "http://localhost:${API_PORT}/health" > /dev/null 2>&1; then
        ok "$_S_STEP_HEALTH_OK_API ${API_PORT})"
      else
        warn "$_S_STEP_HEALTH_FAIL_API"
      fi
      if curl -sf "http://localhost:${BRIDGE_PORT}/health" > /dev/null 2>&1; then
        ok "$_S_STEP_HEALTH_OK_BRIDGE ${BRIDGE_PORT})"
      else
        warn "$_S_STEP_HEALTH_FAIL_BRIDGE"
      fi
    fi
  fi

  if ! $USE_DOCKER; then step_claude_auth; fi
  step_show_totp
  step_show_webhook_url

  echo ""
  ok "$_S_DONE_TITLE"
  if $USE_DOCKER; then
    echo "  $_S_DONE_DOCKER"
  elif $USE_PM2; then
    echo "  $_S_DONE_PM2"
  elif ! $NO_SYSTEMD && command -v systemctl &>/dev/null; then
    echo "  $_S_DONE_SYSTEMD"
  else
    echo "  $_S_DONE_MANUAL"
  fi
}

# Run main() only when executed directly — not when sourced for testing.
# Single-line if: head -n -1 removes it for pytest; if-false exits 0 for bats (set -e safe).
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then main "$@"; fi
