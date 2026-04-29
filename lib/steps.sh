#!/usr/bin/env bash
# lib/steps.sh — Install steps: venv, npm, dirs, docker, systemd, pm2, claude, webhook.
#
# Sourced by install.sh; do not execute directly.
# shellcheck shell=bash

step_venv() {
  log "$_S_STEP_VENV $BACKEND_DIR/venv"
  if [ ! -d "$BACKEND_DIR/venv" ]; then "$PY" -m venv "$BACKEND_DIR/venv"; fi

  # Bootstrap: pip-compile ve pip-sync için pip-tools'u regular pip ile kur
  log "$_S_STEP_PKG_BOOTSTRAP"
  "$BACKEND_DIR/venv/bin/pip" install --quiet --upgrade pip pip-tools

  # Seçili capability dosyalarını belirle
  local req_files cap_names=()
  mapfile -t req_files < <(_resolve_requirements)
  for f in "${req_files[@]}"; do cap_names+=( "$(basename "$f" .txt)" ); done
  log "$_S_STEP_PKG_COMPILE ${cap_names[*]}"

  # pip-compile: seçili dosyaları birleştir + tüm transitive dep'leri çöz → pinned file.
  # compiled.txt machine-specific, gitignored.
  local compiled="$BACKEND_DIR/requirements/compiled.txt"
  "$BACKEND_DIR/venv/bin/pip-compile" \
    --no-header --no-annotate --no-strip-extras \
    --output-file="$compiled" \
    "${req_files[@]}"

  # pip-sync: compiled.txt'e göre venv'i atomik senkronize et.
  # Eksik paketleri kurar; listede olmayan (devre dışı capability) paketleri kaldırır.
  log "$_S_STEP_PKG_SYNC ${cap_names[*]}"
  "$BACKEND_DIR/venv/bin/pip-sync" "$compiled"

  # sudo-mode: venv was created as root; service runs as $SUDO_USER and must
  # be able to read .pyc files etc.  Restore ownership.
  if [ "$EUID" -eq 0 ] && [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
    local _grp
    _grp="$(id -gn "$SUDO_USER" 2>/dev/null || echo "$SUDO_USER")"
    chown -R "$SUDO_USER:$_grp" "$BACKEND_DIR/venv" 2>/dev/null || true
  fi
  ok "$_S_STEP_VENV_DONE"
}


step_npm() {
  log "$_S_STEP_NPM $BRIDGE_DIR/node_modules"
  (cd "$BRIDGE_DIR" && npm install --silent)
  ok "$_S_STEP_NPM_DONE"
}


step_proxy_binary() {
  local _proxy
  _proxy="$(_read_env_var "WEBHOOK_PROXY" "$ENV_FILE")"
  [[ "$_proxy" != "cloudflared" ]] && return 0

  if command -v cloudflared &>/dev/null; then
    ok "  $_S_STEP_CF_SKIP: $(cloudflared --version 2>&1 | head -1)"
    return 0
  fi

  log "$_S_STEP_CF_INSTALL"
  local _arch _url
  _arch="$(uname -m)"
  case "$_arch" in
    x86_64)  _url="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64" ;;
    aarch64) _url="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64" ;;
    armv7l)  _url="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm"   ;;
    *)       warn "  $_S_STEP_CF_ARCH_WARN"; return 1 ;;
  esac

  if curl -fL "$_url" -o /usr/local/bin/cloudflared 2>/dev/null \
      && chmod +x /usr/local/bin/cloudflared; then
    ok "  $_S_STEP_CF_DONE: $(cloudflared --version 2>&1 | head -1)"
  else
    warn "  $_S_STEP_CF_FAIL"
    return 1
  fi
}


step_data_dirs() {
  log "$_S_STEP_DIRS"
  mkdir -p \
    "$ROOT_DIR/data/projects" \
    "$ROOT_DIR/data/media" \
    "$ROOT_DIR/data/claude_sessions" \
    "$ROOT_DIR/data/conv_history" \
    "$ROOT_DIR/outputs/logs" \
    "$ROOT_DIR/reports/done" \
    "$ROOT_DIR/research/done"

  # When run via sudo, dirs are owned by root — but services start as $SUDO_USER,
  # which then can't write to data/personal_agent.db etc.  Restore ownership.
  # NOT: Bridge container artık entrypoint'inde root → claude:claude (UID 1001) drop'u
  # yapıyor (bkz. docker/entrypoint-bridge.sh). Bu yüzden install.sh'ın 1001:1001'e
  # chown yapmasına gerek yok; aksine native (systemd) bridge SUDO_USER olarak çalışır,
  # 1001 sahipliği yazma hatasına neden olur. Tüm data dizinlerini SUDO_USER'a ata.
  if [ "$EUID" -eq 0 ] && [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
    local _grp
    _grp="$(id -gn "$SUDO_USER" 2>/dev/null || echo "$SUDO_USER")"
    chown -R "$SUDO_USER:$_grp" \
      "$ROOT_DIR/data/projects" "$ROOT_DIR/data/media" \
      "$ROOT_DIR/data/claude_sessions" "$ROOT_DIR/data/conv_history" \
      "$ROOT_DIR/outputs" "$ROOT_DIR/reports" "$ROOT_DIR/research" \
      2>/dev/null || warn "  ↳ chown failed for data dirs (continuing)"
  fi
  ok "$_S_STEP_DIRS_DONE"
}


_hfs_telegram() {
  local env_dst="$1"
  local _tok _cid _offset _cb _cb_uid _cb_id _cb_data
  _tok="$(_env_get "TELEGRAM_BOT_TOKEN" "$env_dst" 2>/dev/null || true)"
  _cid="$(_env_get "TELEGRAM_CHAT_ID"   "$env_dst" 2>/dev/null || true)"
  if [[ -z "$_tok" || -z "$_cid" ]]; then
    warn "  ↳ Telegram credentials not in .env — falling back to text mode"
    _hfs_text "$env_dst"
    return
  fi

  _offset="$(_tg_get_offset "$_tok")"

  # Intro: erişim ver / verme
  log "  $_S_TXT_TG_WAIT"
  _tg_send_buttons "$_tok" "$_cid" \
    "*$_S_WIZ_HFS_TITLE*\n\n$_S_WIZ_HFS_MSG" \
    "$_S_CAP_TG_BTN_ENABLE:hfs_yes" "|" "$_S_CAP_TG_BTN_DISABLE:hfs_no" >/dev/null

  local _gate="" _a=0
  while (( _a < 3 )); do
    _cb="$(_tg_poll_callback "$_tok" "$_cid" "$_offset" 300)" || _cb="0 0 hfs_no"
    _cb_uid="$(echo "$_cb" | cut -d' ' -f1)"
    _cb_id="$(echo  "$_cb" | cut -d' ' -f2)"
    _cb_data="$(echo "$_cb" | cut -d' ' -f3)"
    _tg_answer_callback "$_tok" "$_cb_id"
    [[ "$_cb_uid" =~ ^[0-9]+$ && "$_cb_uid" -gt 0 ]] && _offset=$(( _cb_uid + 1 ))
    [[ "$_cb_data" == "hfs_yes" || "$_cb_data" == "hfs_no" ]] && { _gate="$_cb_data"; break; }
    _a=$(( _a + 1 ))
  done
  [[ -z "$_gate" ]] && _gate="hfs_no"

  if [[ "$_gate" == "hfs_no" ]]; then
    _env_set "HOST_FS_ACCESS" "none" "$env_dst"
    _tg_notify "$_tok" "$_cid" "$_S_WIZ_HFS_RESULT_NONE"
    ok "  $_S_WIZ_HFS_RESULT_NONE"
    return
  fi

  # 4 ayrı soru: okuma / yazma / silme / düzenleme
  local -a _hfs_keys=( "read"              "write"              "delete"              "edit"             )
  local -a _hfs_labels=( "$_S_WIZ_HFS_READ" "$_S_WIZ_HFS_WRITE" "$_S_WIZ_HFS_DELETE" "$_S_WIZ_HFS_EDIT" )
  local _hfs_read=false _hfs_write=false _hfs_delete=false _hfs_edit=false
  local i
  for (( i=0; i<4; i++ )); do
    local _key="${_hfs_keys[$i]}" _label="${_hfs_labels[$i]}"
    log "  $_S_TXT_TG_WAIT"
    _tg_send_buttons "$_tok" "$_cid" "*${_label}*" \
      "$_S_CAP_TG_BTN_ENABLE:y" "$_S_CAP_TG_BTN_DISABLE:n" >/dev/null
    local _yn="" _ya=0
    while (( _ya < 3 )); do
      _cb="$(_tg_poll_callback "$_tok" "$_cid" "$_offset" 300)" || _cb="0 0 y"
      _cb_uid="$(echo "$_cb" | cut -d' ' -f1)"
      _cb_id="$(echo  "$_cb" | cut -d' ' -f2)"
      _cb_data="$(echo "$_cb" | cut -d' ' -f3)"
      _tg_answer_callback "$_tok" "$_cb_id"
      [[ "$_cb_uid" =~ ^[0-9]+$ && "$_cb_uid" -gt 0 ]] && _offset=$(( _cb_uid + 1 ))
      [[ "$_cb_data" == "y" || "$_cb_data" == "n" ]] && { _yn="$_cb_data"; break; }
      _ya=$(( _ya + 1 ))
    done
    [[ -z "$_yn" ]] && _yn="y"
    [[ "$_yn" == "y" ]] && case "$_key" in
      read)   _hfs_read=true ;;
      write)  _hfs_write=true ;;
      delete) _hfs_delete=true ;;
      edit)   _hfs_edit=true ;;
    esac
  done

  local _host_fs_access="none"
  if $_hfs_write || $_hfs_delete || $_hfs_edit; then
    _host_fs_access="rw"
    _tg_notify "$_tok" "$_cid" "$_S_WIZ_HFS_RESULT_RW"
    ok "  $_S_WIZ_HFS_RESULT_RW"
  elif $_hfs_read; then
    _host_fs_access="ro"
    _tg_notify "$_tok" "$_cid" "$_S_WIZ_HFS_RESULT_RO"
    ok "  $_S_WIZ_HFS_RESULT_RO"
  else
    _tg_notify "$_tok" "$_cid" "$_S_WIZ_HFS_RESULT_NONE"
    ok "  $_S_WIZ_HFS_RESULT_NONE"
  fi
  _env_set "HOST_FS_ACCESS" "$_host_fs_access" "$env_dst"
}


_hfs_whiptail() {
  local env_dst="$1"
  local _host_fs_access="none"
  if _wt_yesno "$_S_WIZ_HFS_TITLE" "$_S_WIZ_HFS_MSG"; then
    local _hfs_read=false _hfs_write=false _hfs_delete=false _hfs_edit=false
    _wt_yesno "$_S_WIZ_HFS_TITLE" "$_S_WIZ_HFS_READ"   && _hfs_read=true   || true
    _wt_yesno "$_S_WIZ_HFS_TITLE" "$_S_WIZ_HFS_WRITE"  && _hfs_write=true  || true
    _wt_yesno "$_S_WIZ_HFS_TITLE" "$_S_WIZ_HFS_DELETE" && _hfs_delete=true || true
    _wt_yesno "$_S_WIZ_HFS_TITLE" "$_S_WIZ_HFS_EDIT"   && _hfs_edit=true   || true
    if $_hfs_write || $_hfs_delete || $_hfs_edit; then
      _host_fs_access="rw"
    elif $_hfs_read; then
      _host_fs_access="ro"
    fi
  fi
  _env_set "HOST_FS_ACCESS" "$_host_fs_access" "$env_dst"
  if [[ "$_host_fs_access" == "rw" ]]; then ok "  $_S_WIZ_HFS_RESULT_RW"
  elif [[ "$_host_fs_access" == "ro" ]]; then ok "  $_S_WIZ_HFS_RESULT_RO"
  else ok "  $_S_WIZ_HFS_RESULT_NONE"; fi
}


_hfs_text() {
  local env_dst="$1"
  echo ""
  echo "▶ $_S_WIZ_HFS_TITLE"
  echo ""
  printf "  %b\n" "$_S_WIZ_HFS_MSG"
  echo ""
  local _host_fs_access="none" _hfs_ans _hfs_r
  _ask_inline "[${_S_TXT_RERUN_Y}/n]:" _hfs_ans
  if [[ "${_hfs_ans,,}" == "$_S_TXT_RERUN_Y" ]]; then
    local _hfs_read=false _hfs_write=false _hfs_delete=false _hfs_edit=false
    _ask_inline "  $_S_WIZ_HFS_READ [${_S_TXT_RERUN_Y}/n]:" _hfs_r
    [[ "${_hfs_r,,}" == "$_S_TXT_RERUN_Y" ]] && _hfs_read=true
    _ask_inline "  $_S_WIZ_HFS_WRITE [${_S_TXT_RERUN_Y}/n]:" _hfs_r
    [[ "${_hfs_r,,}" == "$_S_TXT_RERUN_Y" ]] && _hfs_write=true
    _ask_inline "  $_S_WIZ_HFS_DELETE [${_S_TXT_RERUN_Y}/n]:" _hfs_r
    [[ "${_hfs_r,,}" == "$_S_TXT_RERUN_Y" ]] && _hfs_delete=true
    _ask_inline "  $_S_WIZ_HFS_EDIT [${_S_TXT_RERUN_Y}/n]:" _hfs_r
    [[ "${_hfs_r,,}" == "$_S_TXT_RERUN_Y" ]] && _hfs_edit=true
    if $_hfs_write || $_hfs_delete || $_hfs_edit; then
      _host_fs_access="rw"
    elif $_hfs_read; then
      _host_fs_access="ro"
    fi
  fi
  _env_set "HOST_FS_ACCESS" "$_host_fs_access" "$env_dst"
  if [[ "$_host_fs_access" == "rw" ]]; then ok "  $_S_WIZ_HFS_RESULT_RW"
  elif [[ "$_host_fs_access" == "ro" ]]; then ok "  $_S_WIZ_HFS_RESULT_RO"
  else ok "  $_S_WIZ_HFS_RESULT_NONE"; fi
}


step_host_fs_access() {
  local env_dst="$BACKEND_DIR/.env"
  log "🗂️  $_S_WIZ_HFS_TITLE..."

  [ ! -f "$env_dst" ] && { warn "  ↳ .env not found, skipping"; return 0; }

  # İdempotent: zaten ayarlıysa atla
  local _existing
  _existing="$(_read_env_var "HOST_FS_ACCESS" "$env_dst" 2>/dev/null || true)"
  [[ -n "$_existing" ]] && { ok "  ↳ HOST_FS_ACCESS=$_existing (skipped)"; return 0; }

  # Non-interactive: varsayılan none
  if [ ! -t 0 ]; then
    _env_set "HOST_FS_ACCESS" "none" "$env_dst"
    return 0
  fi

  local _messenger
  _messenger="$(_env_get "MESSENGER_TYPE" "$env_dst" 2>/dev/null || true)"
  if [[ "$_messenger" == "telegram" ]]; then
    _hfs_telegram "$env_dst"
  elif _wt_available; then
    _hfs_whiptail "$env_dst"
  else
    _hfs_text "$env_dst"
  fi
}


step_docker_group() {
  if ! command -v docker &>/dev/null; then return; fi
  if docker info &>/dev/null 2>&1; then
    ok "$_S_STEP_DOCKER_OK"; return
  fi
  if [ "$EUID" -eq 0 ] && command -v usermod &>/dev/null; then
    usermod -aG docker "$CURRENT_USER"
    ok "$_S_STEP_DOCKER_ADDED"
  else
    warn "$_S_STEP_DOCKER_WARN"
    warn "$_S_STEP_DOCKER_FIX $CURRENT_USER && newgrp docker"
  fi
}


step_docker_build() {
  if ! command -v docker &>/dev/null; then
    die "$_S_DOCKER_NOT_FOUND"
  fi
  if ! docker compose version &>/dev/null 2>&1; then
    die "$_S_DOCKER_COMPOSE_NOT_FOUND"
  fi

  # ── ~/.claude/ pre-flight: Docker directory mount requires source to exist.
  # We mount the whole dir (not just .credentials.json) so the CLI can write
  # refreshed tokens and so `docker exec ... claude auth login` works.
  local claude_dir="$HOME/.claude"
  if [ ! -d "$claude_dir" ]; then
    mkdir -p "$claude_dir"
    warn "$_S_DOCKER_CRED_CREATED"
  elif [ ! -f "$claude_dir/.credentials.json" ]; then
    warn "$_S_DOCKER_CRED_NEED_LOGIN"
  else
    ok "$_S_DOCKER_CRED_OK"
  fi

  # Seçili capability dosyalarını belirle
  local req_files cap_names=()
  mapfile -t req_files < <(_resolve_requirements)
  for f in "${req_files[@]}"; do cap_names+=( "$(basename "$f" .txt)" ); done

  local caps_str="${cap_names[*]}"  # "core dev scheduler browser" gibi

  log "$_S_DOCKER_BUILD"
  log "$_S_DOCKER_BUILD_CAPS $caps_str"

  # docker-compose.override.yml yaz — build-arg + host filesystem access
  log "$_S_DOCKER_OVERRIDE"
  local _host_fs_access
  _host_fs_access="$(_read_env_var "HOST_FS_ACCESS" "$ROOT_DIR/scripts/backend/.env")"
  _host_fs_access="${_host_fs_access:-none}"

  local _hfs_mount=""
  if [[ "$_host_fs_access" == "rw" ]]; then
    _hfs_mount="- /:/app/host_root:rw"
  elif [[ "$_host_fs_access" == "ro" ]]; then
    _hfs_mount="- /:/app/host_root:ro"
  fi

  {
    echo "# Auto-generated by install.sh --docker — do not edit manually"
    echo "# Re-run: bash install.sh --docker"
    echo "services:"
    echo "  99-api:"
    echo "    build:"
    echo "      args:"
    echo "        CAPABILITIES: \"${caps_str}\""
    if [[ -n "$_hfs_mount" ]]; then
      echo "    volumes:"
      echo "      $_hfs_mount"
    fi
    echo "  99-bridge:"
    if [[ -n "$_hfs_mount" ]]; then
      echo "    volumes:"
      echo "      $_hfs_mount"
    fi
  } > "$ROOT_DIR/docker-compose.override.yml"

  # Build
  log "$_S_DOCKER_BUILD_RUN"
  docker compose -f "$ROOT_DIR/docker-compose.yml" \
                 -f "$ROOT_DIR/docker-compose.override.yml" \
                 build

  # Up
  log "$_S_DOCKER_UP"
  docker compose -f "$ROOT_DIR/docker-compose.yml" \
                 -f "$ROOT_DIR/docker-compose.override.yml" \
                 up -d

  ok "$_S_DOCKER_BUILD_DONE"

  # ── Webhook auto-registration for ngrok/cloudflared proxy ─────────────────
  # Public URL is only known at runtime (ngrok starts inside the container).
  # Poll /health until public_url appears, then register the webhook.
  local _env_dst="$BACKEND_DIR/.env"
  local _proxy _messenger
  _proxy="$(_read_env_var "WEBHOOK_PROXY"  "$_env_dst")"
  _messenger="$(_read_env_var "MESSENGER_TYPE" "$_env_dst")"
  _messenger="${_messenger:-whatsapp}"

  if [[ "$_proxy" == "ngrok" || "$_proxy" == "cloudflared" ]]; then
    log "$_S_DOCKER_WAIT_URL"
    local _pub_url="" _retry=0 _health

    while [[ -z "$_pub_url" && $_retry -lt 45 ]]; do
      sleep 2
      _retry=$((_retry + 1))
      _health="$(curl -s --max-time 4 "http://localhost:${API_PORT}/health" 2>/dev/null || true)"
      [[ -n "$_health" ]] && _pub_url="$(_extract_json_field "$_health" "public_url")"
    done

    if [[ -n "$_pub_url" ]]; then
      ok "$_S_DOCKER_URL_FOUND: $_pub_url"
      if [[ "$_messenger" == "telegram" ]]; then
        local _tg_token _tg_secret _wh_url _wh_result
        _tg_token="$(_read_env_var "TELEGRAM_BOT_TOKEN"      "$_env_dst")"
        _tg_secret="$(_read_env_var "TELEGRAM_WEBHOOK_SECRET" "$_env_dst")"
        _wh_url="${_pub_url}/telegram/webhook"
        _wh_result="$(curl -s --max-time 8 -X POST \
          "https://api.telegram.org/bot${_tg_token}/setWebhook" \
          -H "Content-Type: application/json" \
          -d "{\"url\":\"${_wh_url}\",\"secret_token\":\"${_tg_secret}\",\"allowed_updates\":[\"message\",\"callback_query\"]}" \
          2>/dev/null || true)"
        if echo "$_wh_result" | grep -q '"ok":true'; then
          ok "$_S_WH_TG_REGISTERED: $_wh_url"
          # TG-WIZ-1: Send Stage-2 wizard welcome ping.
          local _tg_chat
          _tg_chat="$(_read_env_var "TELEGRAM_CHAT_ID" "$_env_dst")"
          if [[ -n "$_tg_chat" ]]; then
            _tg_notify "$_tg_token" "$_tg_chat" "$_S_MSG_WIZ_TG_INSTALL_NOTICE"
          fi
        else
          # Telegram API hatasını göster (örn. bad token, URL unreachable)
          local _wh_desc
          _wh_desc="$(_extract_json_field "$_wh_result" "description")"
          warn "  Webhook registration failed: ${_wh_desc:-unknown error}"
          echo "  Manual: curl -s -X POST 'https://api.telegram.org/bot${_tg_token}/setWebhook' -d 'url=${_wh_url}'"
        fi
      fi
    else
      warn "$_S_DOCKER_URL_TIMEOUT"
      echo "  $_S_DOCKER_URL_DEBUG"
      echo "    docker compose logs 99-api 2>&1 | grep -iE 'ngrok|tunnel|webhook_proxy'"
      if [[ "$_messenger" == "telegram" ]]; then
        echo ""
        echo "  $_S_RW_HINT_CMD"
        echo "    bash install.sh --register-webhook"
      fi
    fi
  fi
}


render_template() {
  local template="$1" output="$2"
  "$PY" - "$template" "$output" \
    "$CURRENT_USER" "$ROOT_DIR" "$NODE_PATH" "$API_PORT" "$BRIDGE_PORT" <<'PYEOF'
import sys
tpl, out, user, root, node, api_port, bridge_port = sys.argv[1:]
with open(tpl) as f:
    t = f.read()
for placeholder, value in [
    ("{{USER}}", user), ("{{ROOT_DIR}}", root), ("{{NODE_PATH}}", node),
    ("{{API_PORT}}", api_port), ("{{BRIDGE_PORT}}", bridge_port),
]:
    t = t.replace(placeholder, value)
with open(out, "w") as f:
    f.write(t)
PYEOF
}


step_systemd() {
  if $NO_SYSTEMD; then log "$_S_STEP_SYSTEMD_SKIP"; return; fi
  if ! command -v systemctl &>/dev/null; then warn "$_S_STEP_SYSTEMD_MISSING"; return; fi

  log "$_S_STEP_SYSTEMD_RENDER"
  render_template "$SYSTEMD_DIR/personal-agent.service.template"        "$SYSTEMD_DIR/personal-agent.service"
  render_template "$SYSTEMD_DIR/personal-agent-bridge.service.template" "$SYSTEMD_DIR/personal-agent-bridge.service"
  ok "$_S_STEP_SYSTEMD_DONE $SYSTEMD_DIR/*.service"

  if [ "$EUID" -eq 0 ]; then
    cp "$SYSTEMD_DIR/personal-agent.service"        "$SYSTEM_UNIT_DIR/"
    cp "$SYSTEMD_DIR/personal-agent-bridge.service" "$SYSTEM_UNIT_DIR/"
    systemctl daemon-reload
    systemctl enable personal-agent.service personal-agent-bridge.service
    ok "$_S_STEP_SYSTEMD_INSTALLED"
    warn "$_S_STEP_SYSTEMD_START"
  else
    warn "$_S_STEP_SYSTEMD_NOROOT $SYSTEMD_DIR/"
    echo "      $_S_STEP_SYSTEMD_MANUAL"
    echo "        sudo cp $SYSTEMD_DIR/personal-agent*.service $SYSTEM_UNIT_DIR/"
    echo "        sudo systemctl daemon-reload"
    echo "        sudo systemctl enable --now personal-agent personal-agent-bridge"
  fi
}


step_pm2() {
  if ! $USE_PM2; then return; fi
  log "$_S_STEP_PM2_START"
  if ! command -v pm2 &>/dev/null; then
    npm install -g pm2 || die "npm install -g pm2 $_S_ERROR"
    ok "$_S_STEP_PM2_INSTALLED"
  else
    ok "$_S_STEP_PM2_EXISTS $(pm2 --version)"
  fi
  pm2 start "$ROOT_DIR/ecosystem.config.js"
  pm2 save
  pm2 startup || warn "$_S_STEP_PM2_STARTUP"
  ok "$_S_STEP_PM2_DONE"
}


step_claude_auth() {
  # Strict failure mode (default): abort install.sh on any auth error so the
  # user can't end up with a deployment that silently fails on first message.
  # Escape hatch: CLAUDE_AUTH_OPTIONAL=1 demotes errors to warnings — for CI
  # builds and advanced users who plan to authenticate later.
  local _strict=true
  [[ "${CLAUDE_AUTH_OPTIONAL:-}" == "1" ]] && _strict=false
  _auth_fail() { if $_strict; then die "$1"; else warn "$1"; warn "$_S_AUTH_OPTIONAL_HINT"; return 0; fi; }

  local env_dst="$BACKEND_DIR/.env"
  local api_key
  api_key="$(_read_env_var "ANTHROPIC_API_KEY" "$env_dst" 2>/dev/null || true)"
  if [[ -n "$api_key" && "$api_key" != *"FILL"* && "$api_key" != *"DOLDUR"* && "$api_key" != *"YOUR_"* ]]; then
    ok "$_S_AUTH_APIKEY"; return
  fi

  # Always run claude auth login — do not silently accept a cached token that
  # may be expired. The CLI handles already-authenticated sessions gracefully.

  # Install claude CLI if missing — strict: hard fail so user fixes Node/npm.
  # On Git Bash for Windows (MINGW) the user often has `node` from MSYS2's
  # `nodejs` package (which doesn't bundle npm) on bash $PATH while npm comes
  # from the separate official Node.js Windows installer at C:\Program
  # Files\nodejs\, which isn't on the MSYS path. We therefore probe in three
  # tiers: (1) bash PATH via `command -v`, (2) Windows PATH via `where.exe`,
  # (3) well-known install locations as a last resort.
  if ! command -v claude &>/dev/null; then
    local _npm_cmd=""
    if   command -v npm     &>/dev/null; then _npm_cmd=npm
    elif command -v npm.cmd &>/dev/null; then _npm_cmd=npm.cmd
    elif command -v where.exe &>/dev/null; then
      local _win_npm
      _win_npm="$(where.exe npm.cmd 2>/dev/null | head -1 | tr -d '\r')"
      if [[ -n "$_win_npm" ]]; then
        # Windows-style path (C:\Program Files\nodejs\npm.cmd) — quote on use.
        _npm_cmd="$_win_npm"
      fi
    fi
    if [[ -z "$_npm_cmd" ]]; then
      local _cand
      for _cand in \
          "/c/Program Files/nodejs/npm.cmd" \
          "/c/Program Files (x86)/nodejs/npm.cmd" \
          "${APPDATA:-}/npm/npm.cmd" \
          "${ProgramFiles:-/c/Program Files}/nodejs/npm.cmd"; do
        if [[ -f "$_cand" ]]; then _npm_cmd="$_cand"; break; fi
      done
    fi
    # Last resort on Windows: bootstrap Node.js via winget or choco. winget
    # ships with Windows 10 1809+ / 11 by default; choco is third-party.
    # Both may trigger a UAC prompt — we let stdout/stderr flow live so the
    # user can respond. After install, the new PATH entry is added by the
    # installer to the *system* PATH but won't propagate to this bash session,
    # so we force-add the standard Node.js dir and clear bash's command hash
    # before re-probing via `command -v`.
    if [[ -z "$_npm_cmd" ]]; then
      local _bootstrap_via=""

      if command -v winget.exe &>/dev/null; then
        log "$_S_AUTH_WINGET_INSTALLING"
        if winget.exe install --silent \
             --accept-source-agreements --accept-package-agreements \
             OpenJS.NodeJS.LTS; then
          _bootstrap_via=winget
        else
          warn "winget exit $?"
        fi
      fi

      if [[ -z "$_bootstrap_via" ]] && command -v choco &>/dev/null; then
        log "$_S_AUTH_CHOCO_INSTALLING"
        if choco install nodejs-lts -y; then
          _bootstrap_via=choco
        else
          warn "choco exit $?"
        fi
      fi

      if [[ -n "$_bootstrap_via" ]]; then
        export PATH="/c/Program Files/nodejs:${ProgramFiles:-/c/Program Files}/nodejs:$PATH"
        hash -r
        if   command -v npm     &>/dev/null; then _npm_cmd=npm
        elif command -v npm.cmd &>/dev/null; then _npm_cmd=npm.cmd
        fi
        if [[ -n "$_npm_cmd" ]]; then
          case "$_bootstrap_via" in
            winget) ok "$_S_AUTH_WINGET_INSTALLED" ;;
            choco)  ok "$_S_AUTH_CHOCO_INSTALLED"  ;;
          esac
        fi
      fi
    fi
    if [[ -z "$_npm_cmd" ]]; then
      _auth_fail "$_S_AUTH_NPM_MISSING"; return
    fi
    log "$_S_AUTH_INSTALLING"
    if ! "$_npm_cmd" install -g @anthropic-ai/claude-code 2>&1 | tail -3; then
      _auth_fail "$_S_AUTH_INSTALL_FAIL"; return
    fi
    if ! command -v claude &>/dev/null; then
      # npm bin may not be on PATH yet — try to find it
      local _npm_bin="" _npm_prefix=""
      _npm_bin="$("$_npm_cmd" bin -g 2>/dev/null || true)"
      if [[ -z "$_npm_bin" ]]; then
        _npm_prefix="$("$_npm_cmd" prefix -g 2>/dev/null || true)"
        [[ -n "$_npm_prefix" ]] && _npm_bin="$_npm_prefix/bin"
      fi
      [[ -n "$_npm_bin" ]] && export PATH="$_npm_bin:$PATH"
      if ! command -v claude &>/dev/null; then
        _auth_fail "$_S_AUTH_INSTALL_FAIL"; return
      fi
    fi
    ok "$_S_AUTH_INSTALLED: $(claude --version 2>/dev/null | head -1 || echo 'installed')"
  fi

  # Run the OAuth flow. The CLI prints an authorization URL and exposes a
  # localhost callback. When MESSENGER_TYPE=telegram we mirror that URL to
  # Telegram so the user can read it from their phone — but emphasise it
  # MUST be opened on the install machine, since the OAuth callback lands
  # on localhost and a phone browser can't reach it.
  echo ""
  log "$_S_AUTH_NEEDED"
  echo "  $_S_AUTH_INSTR"
  echo ""

  local _tg_tok="" _tg_cid=""
  _tg_tok="$(_env_get "TELEGRAM_BOT_TOKEN" "$env_dst" 2>/dev/null || true)"
  _tg_cid="$(_env_get "TELEGRAM_CHAT_ID"   "$env_dst" 2>/dev/null || true)"

  local _rc=0
  if [[ -n "$_tg_tok" && -n "$_tg_cid" ]]; then
    _tg_notify "$_tg_tok" "$_tg_cid" "$_S_AUTH_TG_HEADSUP" || true
    # Mirror claude's stdout to both the terminal (via tee) and a watcher
    # FIFO that scans for the auth URL and pushes it to Telegram once.
    local _fifo
    _fifo="$(mktemp -u 2>/dev/null || echo "/tmp/claude_auth.$$.fifo")"
    if mkfifo "$_fifo" 2>/dev/null; then
      (
        local _sent=0 _line _url
        while IFS= read -r _line; do
          [[ $_sent -eq 1 ]] && continue
          if [[ "$_line" =~ (https://[A-Za-z0-9./?=_\&%+~-]*(claude\.ai|anthropic\.com)[A-Za-z0-9./?=_\&%+~-]*) ]]; then
            _url="${BASH_REMATCH[1]}"
            # shellcheck disable=SC2059
            _tg_notify "$_tg_tok" "$_tg_cid" "$(printf "$_S_AUTH_TG_URL_PROMPT" "$_url")" || true
            _sent=1
          fi
        done < "$_fifo"
      ) &
      local _watcher=$!
      claude auth login 2>&1 | tee "$_fifo"
      _rc=${PIPESTATUS[0]}
      wait "$_watcher" 2>/dev/null || true
      rm -f "$_fifo"
    else
      # FIFO unavailable — fall back to plain run (URL only on terminal)
      claude auth login || _rc=$?
    fi
  else
    claude auth login || _rc=$?
  fi

  if [[ $_rc -ne 0 ]]; then
    _auth_fail "$_S_AUTH_FAIL_HARD"; return
  fi

  # Verify credentials were actually written (login can exit 0 even when
  # the user closes the browser early).
  local _cred_after
  _cred_after="$(tr -d ' \n\r\t' < "$HOME/.claude/.credentials.json" 2>/dev/null || echo "{}")"
  if [[ "$_cred_after" == "{}" || ${#_cred_after} -le 5 ]]; then
    _auth_fail "$_S_AUTH_EMPTY_CREDS"; return
  fi

  ok "$_S_AUTH_OK"
  if [[ -n "$_tg_tok" && -n "$_tg_cid" ]]; then
    _tg_notify "$_tg_tok" "$_tg_cid" "$_S_AUTH_TG_DONE" || true
  fi
}


step_show_webhook_url() {
  local env_dst="$BACKEND_DIR/.env"
  [ ! -f "$env_dst" ] && return

  local messenger proxy public_url port
  messenger="$(_read_env_var "MESSENGER_TYPE" "$env_dst")"
  messenger="${messenger:-whatsapp}"
  proxy="$(_read_env_var "WEBHOOK_PROXY" "$env_dst")"
  proxy="${proxy:-none}"
  public_url="$(_read_env_var "PUBLIC_URL"   "$env_dst")"
  port="$(      _read_env_var "FASTAPI_PORT" "$env_dst")"
  port="${port:-$API_PORT}"

  echo ""
  echo "╔══════════════════════════════════════════════════════╗"
  echo "║  $_S_WH_TITLE"
  echo "╚══════════════════════════════════════════════════════╝"

  if [[ "$messenger" == "whatsapp" ]]; then
    local webhook_url
    if [[ -n "$public_url" ]]; then
      webhook_url="${public_url}/whatsapp/webhook"
    elif [[ "$proxy" == "none" ]]; then
      webhook_url="http://localhost:${port}/whatsapp/webhook"
    else
      webhook_url="<proxy URL — $_S_WH_WA_CONSOLE>"
    fi
    echo ""; echo "  $_S_WH_WA_URL"
    echo "  → $webhook_url"
    echo ""; echo "  $_S_WH_WA_CONSOLE"
    echo "  $_S_WH_WA_PATH"
    if [[ "$proxy" == "none" && -z "$public_url" ]]; then
      echo ""; warn "$_S_WH_WA_PROXY_WARN"
    fi

  elif [[ "$messenger" == "telegram" ]]; then
    local tg_token tg_secret
    tg_token="$( _read_env_var "TELEGRAM_BOT_TOKEN"      "$env_dst")"
    tg_secret="$(_read_env_var "TELEGRAM_WEBHOOK_SECRET" "$env_dst")"
    echo ""; echo "  $_S_WH_TG_SETUP"
    if [[ -n "$public_url" && -n "$tg_token" ]]; then
      # Static public URL (external proxy) — register now
      local _wh_url="${public_url}/telegram/webhook"
      local _wh_result
      _wh_result="$(curl -s --max-time 8 -X POST \
        "https://api.telegram.org/bot${tg_token}/setWebhook" \
        -H "Content-Type: application/json" \
        -d "{\"url\":\"${_wh_url}\",\"secret_token\":\"${tg_secret}\",\"allowed_updates\":[\"message\",\"callback_query\"]}" \
        2>/dev/null || true)"
      if echo "$_wh_result" | grep -q '"ok":true'; then
        ok "  $_S_WH_TG_REGISTERED: $_wh_url"
        # TG-WIZ-1: Stage-2 wizard welcome ping (static-URL path).
        local _tg_chat_static
        _tg_chat_static="$(_read_env_var "TELEGRAM_CHAT_ID" "$env_dst")"
        if [[ -n "$_tg_chat_static" ]]; then
          _tg_notify "$tg_token" "$_tg_chat_static" "$_S_MSG_WIZ_TG_INSTALL_NOTICE"
        fi
      else
        echo "  → $_wh_url"
        warn "  $_S_WH_TG_SETUP (manual): curl -s -X POST 'https://api.telegram.org/bot${tg_token}/setWebhook' -d 'url=${_wh_url}'"
      fi
    elif [[ "$proxy" == "ngrok" || "$proxy" == "cloudflared" ]]; then
      # Dynamic proxy — URL only known at runtime; Docker auto-registers on startup
      ok "  $_S_WH_TG_PROXY_RUNTIME"
      echo "  $_S_WH_TG_REGISTER_HINT"
    else
      echo "  → $_S_WH_TG_NO_URL"
      echo "    $_S_WH_TG_SETWEBHOOK"
    fi

  elif [[ "$messenger" == "cli" ]]; then
    echo ""; echo "  $_S_WH_CLI"
    echo "  $_S_WH_CLI_HINT"
  fi

  echo ""; echo "  $_S_WH_HEALTH"
  echo "  → curl -s http://localhost:${port}/health"
  echo "  → curl -s http://localhost:${BRIDGE_PORT}/health"
  echo ""
}


# Webhook auto-registration for dynamic proxies (ngrok/cloudflared).
# Can be called standalone via: bash install.sh --register-webhook
step_register_webhook() {
  local env_dst="$BACKEND_DIR/.env"
  [ ! -f "$env_dst" ] && die "$_S_RW_NO_ENV"

  local messenger proxy
  messenger="$(_read_env_var "MESSENGER_TYPE" "$env_dst")"
  messenger="${messenger:-whatsapp}"
  proxy="$(_read_env_var "WEBHOOK_PROXY" "$env_dst")"

  if [[ "$messenger" != "telegram" ]]; then
    warn "$_S_RW_NOT_TG"; return 0
  fi
  if [[ "$proxy" != "ngrok" && "$proxy" != "cloudflared" ]]; then
    warn "$_S_RW_STATIC_PROXY"; return 0
  fi

  local tg_token tg_secret tg_chat port
  tg_token="$(_read_env_var "TELEGRAM_BOT_TOKEN"      "$env_dst")"
  tg_secret="$(_read_env_var "TELEGRAM_WEBHOOK_SECRET" "$env_dst")"
  tg_chat="$(  _read_env_var "TELEGRAM_CHAT_ID"        "$env_dst")"
  port="$(     _read_env_var "FASTAPI_PORT"             "$env_dst")"
  port="${port:-$API_PORT}"

  log "$_S_RW_WAITING"
  local pub_url="" retry=0 health
  while [[ -z "$pub_url" && $retry -lt 150 ]]; do
    sleep 2
    retry=$(( retry + 1 ))
    health="$(curl -s --max-time 4 "http://localhost:${port}/health" 2>/dev/null || true)"
    [[ -n "$health" ]] && pub_url="$(_extract_json_field "$health" "public_url")"
    (( retry % 15 == 0 )) && log "  ... ${retry}x / 150"
  done

  if [[ -z "$pub_url" ]]; then
    die "$_S_RW_TIMEOUT"
  fi

  ok "$_S_DOCKER_URL_FOUND: $pub_url"

  local wh_url="${pub_url}/telegram/webhook"
  local wh_result
  wh_result="$(curl -s --max-time 8 -X POST \
    "https://api.telegram.org/bot${tg_token}/setWebhook" \
    -H "Content-Type: application/json" \
    -d "{\"url\":\"${wh_url}\",\"secret_token\":\"${tg_secret}\",\"allowed_updates\":[\"message\",\"callback_query\"]}" \
    2>/dev/null || true)"

  if echo "$wh_result" | grep -q '"ok":true'; then
    ok "$_S_WH_TG_REGISTERED: $wh_url"
    [[ -n "$tg_chat" ]] && _tg_notify "$tg_token" "$tg_chat" "$_S_MSG_WIZ_TG_INSTALL_NOTICE" || true
  else
    local desc
    desc="$(_extract_json_field "$wh_result" "description")"
    die "$_S_RW_FAILED: ${desc:-unknown error}"
  fi
}

