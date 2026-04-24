#!/usr/bin/env bash
# install.sh — 99-root Personal AI Agent / Kişisel AI Ajan — Setup Script
#
# Usage / Kullanım:
#   ./install.sh                         # Interactive wizard / İnteraktif sihirbaz
#   sudo ./install.sh                    # With systemd unit install / Systemd kurulumu ile
#   ./install.sh --no-systemd            # Dependencies + .env only / Yalnızca bağımlılıklar
#   ./install.sh --pm2                   # PM2 process manager
#   ./install.sh --docker                # Docker: wizard + selective image build / Docker: sihirbaz + seçici image build
#   ./install.sh --no-wizard             # Skip .env wizard (CI) / .env sihirbazını atla
#   ./install.sh --reconfigure-capabilities  # Re-run capability wizard only / Yalnızca yetenek sihirbazı
#   INSTALL_LANG=en ./install.sh         # Force language / Dil seç (tr|en)
#
# Messengers:  whatsapp | telegram | cli
# LLM:         anthropic | ollama | gemini
# Proxy:       none | ngrok | cloudflared | external
# Deployment:  systemd | pm2 | docker

set -euo pipefail

# ── Constants / Sabitler ──────────────────────────────────────────────────────

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS_DIR="$ROOT_DIR/scripts"
BACKEND_DIR="$SCRIPTS_DIR/backend"
BRIDGE_DIR="$SCRIPTS_DIR/claude-code-bridge"
SYSTEMD_DIR="$ROOT_DIR/systemd"
SYSTEM_UNIT_DIR="/etc/systemd/system"

CURRENT_USER="${SUDO_USER:-${USER:-$(whoami)}}"
NODE_PATH="$(command -v node 2>/dev/null || echo /usr/bin/node)"
API_PORT="${PORT:-8010}"
BRIDGE_PORT="${BRIDGE_PORT:-8013}"

NO_SYSTEMD=false
USE_PM2=false
USE_DOCKER=false
NO_WIZARD=false
RECONFIGURE_CAPS=false

for arg in "$@"; do
  [[ "$arg" == "--no-systemd"              ]] && NO_SYSTEMD=true
  [[ "$arg" == "--pm2"                     ]] && USE_PM2=true && NO_SYSTEMD=true
  [[ "$arg" == "--docker"                  ]] && USE_DOCKER=true && NO_SYSTEMD=true
  [[ "$arg" == "--no-wizard"               ]] && NO_WIZARD=true
  [[ "$arg" == "--reconfigure-capabilities" ]] && RECONFIGURE_CAPS=true
done

# ── Language selection / Dil seçimi ──────────────────────────────────────────

INSTALL_LANG="${INSTALL_LANG:-}"  # override via env; empty = ask

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
    read -rp "  [1]: " _lang_choice
    case "${_lang_choice:-1}" in
      2|en|EN) INSTALL_LANG="en" ;;
      *)        INSTALL_LANG="tr" ;;
    esac
  fi
}

# ── i18n string loader / Dil dizisi yükleyici ─────────────────────────────────

_load_strings() {
  if [[ "$INSTALL_LANG" == "en" ]]; then

    # ── General
    _S_BANNER_TITLE="Personal AI Agent — Setup"
    _S_DONE="Done"
    _S_WARNING="Warning"
    _S_ERROR="Error"
    _S_REQUIRED="Required field."
    _S_URL_HTTPS="URL must start with https://"
    _S_OPTIONAL="(optional)"
    _S_CONTINUE="OK to continue"
    _S_CANCEL="Setup cancelled."
    _S_SKIP="Skipped"

    # ── Prereqs
    _S_PRE_PY_MISSING="python3 not found. Install Python 3.11+."
    _S_PRE_PY_OLD="Python 3.11+ required (current: "
    _S_PRE_PY_OLD2="). Upgrade and rerun."
    _S_PRE_NODE_MISSING="node not found. Install Node.js 18+ (https://nodejs.org)."
    _S_PRE_NODE_OLD="Node.js 18+ required (current: "
    _S_PRE_NODE_OLD2="). Upgrade and rerun."
    _S_PRE_CLAUDE_MISSING="Claude CLI not found — bridge will not work!"
    _S_PRE_CLAUDE_HINT="Install with: npm install -g @anthropic-ai/claude-code"
    _S_PRE_CLAUDE_CONT="(Continuing setup — install Claude CLI before starting services)"

    # ── Claude auth
    _S_AUTH_ALREADY="Claude CLI already authenticated"
    _S_AUTH_NEEDED="Claude CLI — login required. Starting 'claude auth login'..."
    _S_AUTH_APIKEY="ANTHROPIC_API_KEY is set — API key auth will be used (no login needed)"
    _S_AUTH_INSTR="A browser window will open (or follow the URL shown below). Log in with your Claude account."
    _S_AUTH_OK="Claude CLI authenticated successfully"
    _S_AUTH_WARN="Authentication may be incomplete — run 'claude auth login' manually if Bridge fails to start"
    _S_AUTH_SKIP="Claude CLI not found — skipping auth step"
    _S_AUTH_INSTALLING="Claude CLI not found — installing via npm (npm install -g @anthropic-ai/claude-code)..."
    _S_AUTH_INSTALLED="Claude CLI installed"
    _S_AUTH_INSTALL_FAIL="Claude CLI install failed. Install manually: npm install -g @anthropic-ai/claude-code"
    _S_AUTH_NPM_MISSING="Claude CLI missing AND npm missing. Install Node.js 18+ first: https://nodejs.org then re-run install.sh"

    # ── Steps
    _S_STEP_VENV="Creating Python venv →"
    _S_STEP_VENV_DONE="Python dependencies synced"
    _S_STEP_PKG_BOOTSTRAP="  ↳ Bootstrapping pip + pip-tools..."
    _S_STEP_PKG_COMPILE="  ↳ Resolving all dependencies (pip-compile)..."
    _S_STEP_PKG_SYNC="  ↳ Syncing venv (install missing + remove unused):"
    _S_STEP_PKG_CAP="  ↳ Installing packages for capability:"
    _S_STEP_PKG_ALL="  ↳ No capability config found — installing all packages"
    _S_STEP_NPM="Installing Node dependencies →"
    _S_STEP_NPM_DONE="npm dependencies installed"
    _S_STEP_DIRS="Creating data directories..."
    _S_STEP_DIRS_DONE="Data directories ready"
    _S_STEP_DOCKER_OK="Docker: user already has access"
    _S_STEP_DOCKER_ADDED="Docker: user added to 'docker' group (re-login to activate)"
    _S_STEP_DOCKER_WARN="Docker installed but user is not in 'docker' group."
    _S_STEP_DOCKER_FIX="Fix with: sudo usermod -aG docker"
    _S_STEP_SYSTEMD_SKIP="--no-systemd flag set, skipping systemd step"
    _S_STEP_SYSTEMD_MISSING="systemd not found, skipping unit files"
    _S_STEP_SYSTEMD_RENDER="Creating systemd unit files..."
    _S_STEP_SYSTEMD_DONE="Unit files rendered:"
    _S_STEP_SYSTEMD_INSTALLED="Systemd services installed and enabled"
    _S_STEP_SYSTEMD_START="To start: sudo systemctl start personal-agent personal-agent-bridge"
    _S_STEP_SYSTEMD_NOROOT="No root access; unit files created at"
    _S_STEP_SYSTEMD_MANUAL="To install manually:"
    _S_STEP_PM2_START="Installing PM2 and starting services..."
    _S_STEP_PM2_INSTALLED="PM2 installed"
    _S_STEP_PM2_EXISTS="PM2 already installed:"
    _S_STEP_PM2_DONE="PM2 services started"
    _S_STEP_PM2_STARTUP="pm2 startup may require root — run the printed command"
    _S_STEP_SYNTAX="Running syntax checks..."
    _S_STEP_TESTS="Running unit tests..."
    _S_STEP_HEALTH_PM2="Service health check (PM2)..."

    # ── Wizard — whiptail
    _S_WIZ_WELCOME_TITLE="99-root Setup Wizard"
    _S_WIZ_WELCOME_MSG="Welcome! This wizard will configure your .env file step by step.

Press Enter to confirm each step, ESC to cancel.

Press OK to begin."
    _S_WIZ_ENV_EXISTS_TITLE=".env Already Exists"
    _S_WIZ_ENV_EXISTS_MSG=".env appears to be already filled.\nRun the wizard again?"
    _S_WIZ_ENV_SKIP_CI="Non-interactive terminal — .env wizard skipped. Fill in manually:"
    _S_WIZ_ENV_SKIP_FLAG=".env skipped (--no-wizard)"
    _S_WIZ_ENV_EXIST_OK=".env already exists, skipped"

    # ── Messenger
    _S_WIZ_MSG_TITLE="Messenger Platform"
    _S_WIZ_MSG_MSG="Which platform will receive messages?"
    _S_WIZ_MSG_WA="WhatsApp (Meta Cloud API)"
    _S_WIZ_MSG_TG="Telegram (BotFather token)"
    _S_WIZ_MSG_CLI="CLI — Terminal output only (testing)"

    # ── LLM
    _S_WIZ_LLM_TITLE="LLM Backend"
    _S_WIZ_LLM_MSG="Which AI model do you want to use?"
    _S_WIZ_LLM_AN="Anthropic Claude (claude.ai API key)"
    _S_WIZ_LLM_OL="Ollama — Local, open-source model"
    _S_WIZ_LLM_GE="Google Gemini (AI Studio API key)"

    # ── Proxy
    _S_WIZ_PRX_TITLE="Webhook Proxy"
    _S_WIZ_PRX_MSG="How will Meta/Telegram reach your server?
(The webhook endpoint must be publicly accessible)"
    _S_WIZ_PRX_NONE="None — Local dev / VPS with static IP"
    _S_WIZ_PRX_NGROK="ngrok — Free static domain available (permanent URL)"
    _S_WIZ_PRX_CF="Cloudflare Tunnel — Persistent option (free)"
    _S_WIZ_PRX_EXT="External URL — You have your own domain"

    # ── WhatsApp credentials
    _S_WIZ_WA_INFO_TITLE="WhatsApp Credentials"
    _S_WIZ_WA_INFO_MSG="Get credentials from Meta Developer Console:
  developers.facebook.com → My Apps → <Your App> → WhatsApp → API Setup

  Access Token   — temporary 24h token on that page, or create a permanent
                   System User token in Business Settings → System Users
  Phone Number ID — numeric ID shown next to your phone number (e.g. 1234567890)
  App Secret     — Settings → Basic → App Secret  (used to verify webhook signatures)
  Owner Number   — your own WhatsApp number WITH country code (e.g. +1XXXXXXXXXX)

  Verify Token and webhook secret are auto-generated — no input needed.

Press OK when ready."
    _S_WIZ_WA_TOKEN="(*) Access Token (EAA...):"
    _S_WIZ_WA_PHONE="(*) Phone Number ID (numeric, e.g. 1234567890):"
    _S_WIZ_WA_SECRET="(*) App Secret (from Settings → Basic):"
    _S_WIZ_WA_VERIFY="(*) Verify Token (auto-generated — leave blank):"
    _S_WIZ_WA_OWNER="(*) Your WhatsApp number (+1XXXXXXXXXX):"

    # ── Telegram credentials
    _S_WIZ_TG_INFO_TITLE="Telegram Credentials"
    _S_WIZ_TG_INFO_MSG="Create a bot with @BotFather on Telegram:
  1. Open Telegram → search @BotFather → /newbot
  2. Choose a name and username (must end with 'bot')
  3. BotFather gives you a token like: 123456789:ABCdef...

After entering the token, the wizard will try to auto-detect your Chat ID.
For this to work: open your new bot and send any message (e.g. 'hello').

Press OK when ready."
    _S_WIZ_TG_TOKEN="(*) Bot Token (123456789:ABCdef...):"
    _S_WIZ_TG_SEND_MSG_TITLE="Auto-detect Chat ID"
    _S_WIZ_TG_SEND_MSG="Open your new Telegram bot and send any message (e.g. 'hello').

  How to find your bot:
  • In Telegram, search for the username you just set with BotFather
  • Tap START or send any text

  Then click OK — the wizard will detect your Chat ID automatically."
    _S_WIZ_TG_CHAT="(*) Your Chat ID (numeric, e.g. 123456789):"
    _S_TXT_TG_CHATID_TIP="Open your bot in Telegram, send 'hello', then press Enter to auto-detect your Chat ID (or type it manually):"
    _S_TXT_TG_CHATID_OK="Chat ID auto-detected"
    _S_TXT_TG_CHATID_FAIL="Auto-detect failed. Get your Chat ID in 10 seconds:
  → Open Telegram → search @userinfobot → tap Start → it replies with your ID
  → Copy the number (e.g. 123456789) and enter it below."

    # ── Anthropic
    _S_WIZ_AN_INFO_TITLE="Anthropic — Authentication Method"
    _S_WIZ_AN_CHOICE_MSG="How do you want to authenticate with Anthropic?

  [1] Claude Login  ✦ RECOMMENDED
      Sign in with your claude.ai account (Pro/Max subscription).
      More secure — no key to manage or leak. The wizard runs
      'claude auth login' automatically after this step.

  [2] API Key
      Pay-per-use key from Anthropic Console.
      console.anthropic.com → Settings → API Keys → Create Key"
    _S_WIZ_AN_CHOICE_1="Claude Login (subscription)"
    _S_WIZ_AN_CHOICE_2="API Key (pay-per-use)"
    _S_WIZ_AN_KEY="API Key (sk-ant-api03-...):"
    _S_WIZ_AN_SKIP="Claude Login selected — 'claude auth login' will run after wizard"

    # ── Ollama
    _S_WIZ_OL_INFO_TITLE="Ollama"
    _S_WIZ_OL_INFO_MSG="Ollama must be running locally before starting the agent.

  Install:     curl -fsSL https://ollama.com/install.sh | sh
  Pull model:  ollama pull llama3   (or mistral, qwen2, gemma3, phi3 …)
  Check:       curl http://localhost:11434/api/tags

  Tip: basic conversation works well; complex tool use may be unreliable."
    _S_WIZ_OL_URL="Base URL [http://localhost:11434]:"
    _S_WIZ_OL_MODEL="Model name [llama3]:"

    # ── Gemini
    _S_WIZ_GE_INFO_TITLE="Google Gemini"
    _S_WIZ_GE_INFO_MSG="Get your free API key from Google AI Studio:
  aistudio.google.com → Get API Key → Create API key

  Default model: gemini-2.0-flash (fast, good for most tasks).
  Use gemini-1.5-pro for complex reasoning."
    _S_WIZ_GE_KEY="(*) Gemini API Key (AIza...):"
    _S_WIZ_GE_MODEL="Model name [gemini-2.0-flash]:"

    # ── Proxy details
    _S_WIZ_CF_INFO_TITLE="Cloudflare Tunnel"
    _S_WIZ_CF_INFO_MSG="Cloudflare Tunnel gives a persistent free HTTPS URL.

  Install cloudflared:
    curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \\
         -o /usr/local/bin/cloudflared && chmod +x /usr/local/bin/cloudflared

  Create a persistent tunnel (one-time setup):
    cloudflared tunnel login
    cloudflared tunnel create personal-agent
    cloudflared tunnel route dns personal-agent <your-subdomain>

  Or use a quick temporary tunnel (no account needed):
    cloudflared tunnel --url http://localhost:8010

  (Can be done after setup)"
    _S_WIZ_CF_MISSING="cloudflared binary not found — install it before starting services."
    _S_WIZ_NGROK_INFO_TITLE="ngrok"
    _S_WIZ_NGROK_INFO_MSG="ngrok creates a public HTTPS tunnel to your local server.
  No binary installation needed — the agent manages ngrok via the pyngrok package.

  Free accounts include ONE permanent static domain (URL never changes):
    ngrok Dashboard → Domains → New Domain → claim your free domain

  To get your auth token (required for static domain):
    ngrok.com → Sign up (free) → Dashboard → Your Authtoken

  Leave the token blank to use ngrok anonymously — URL changes on every restart."
    _S_WIZ_NGROK_TOKEN="ngrok Auth Token — alphanumeric string from Dashboard → Your Authtoken
  (NOT the domain name; leave blank for anonymous mode):"
    _S_WIZ_NGROK_DOMAIN="Static domain from ngrok Dashboard → Domains
  (e.g. yourname.ngrok-free.app — leave blank if you have no account):"
    _S_WIZ_EXT_URL="(*) Public URL (https://yourdomain.com):"

    # ── Security keys
    _S_WIZ_SEC_TITLE="Security Keys — Auto-Generated"
    _S_WIZ_SEC_MSG="All security keys have been generated automatically.
No input needed — they are written to .env.

What they are used for:
  API_KEY          — authenticates internal /agent/* API calls
  TOTP_SECRET      — 6-digit code for owner commands (!lock, !schedule …)
  TOTP_SECRET_ADMIN — 6-digit code for destructive commands (!restart, !shutdown)

You will scan the QR codes on the next screen to add them to Google Authenticator.
Store the secrets in a password manager as backup."
    _S_WIZ_SEC_APIKEY="API_KEY (internal access):"
    _S_WIZ_SEC_TOTP="TOTP_SECRET (owner commands):"
    _S_WIZ_SEC_ADMIN="TOTP_SECRET_ADMIN (destructive commands):"

    # ── Timezone
    _S_WIZ_TZ_TITLE="Timezone"
    _S_WIZ_TZ_MSG="Select the timezone for APScheduler and cron expressions:"
    _S_WIZ_TZ_TRT="Europe/Istanbul (UTC+3, Turkey)"
    _S_WIZ_TZ_LON="Europe/London (UTC+0/+1)"
    _S_WIZ_TZ_PAR="Europe/Paris (UTC+1/+2)"
    _S_WIZ_TZ_NYC="America/New_York (UTC-5/-4)"
    _S_WIZ_TZ_LAX="America/Los_Angeles (UTC-8/-7)"
    _S_WIZ_TZ_TYO="Asia/Tokyo (UTC+9)"
    _S_WIZ_TZ_UTC="UTC"
    _S_WIZ_TZ_OTH="Other (type manually)"
    _S_WIZ_TZ_CUSTOM="IANA timezone name (e.g. America/Chicago):"

    # ── Summary
    _S_WIZ_SUM_TITLE="Setup Summary"
    _S_WIZ_SUM_MSG_AUTO="Security keys were auto-generated."
    _S_WIZ_SUM_MSG_CONF="Press OK to write .env file."
    _S_WIZ_ENV_DONE=".env written:"

    # ── Text mode labels
    _S_TXT_TITLE="99-root Setup Wizard (text mode)"
    _S_TXT_HINT="Leave blank to accept [default] values shown in brackets."
    _S_TXT_MESSENGER="▶ Messenger Platform  (which app you will use to control the agent)"
    _S_TXT_M1="1) whatsapp  — Meta Cloud API  [recommended if you already have a Meta app] (default)"
    _S_TXT_M2="2) telegram  — Telegram Bot    [recommended — easiest setup, no business account needed]"
    _S_TXT_M3="3) cli       — Terminal only   [for local testing, no app needed]"
    _S_TXT_LLM="▶ LLM Backend  (which AI model powers the agent)"
    _S_TXT_L1="1) anthropic — Anthropic Claude  [recommended — full tool use, best results] (default)"
    _S_TXT_L2="2) ollama    — Local Ollama      [free, fully local, limited tool support]"
    _S_TXT_L3="3) gemini    — Google Gemini     [free quota, cloud, works for most tasks]"
    _S_TXT_PROXY="▶ Webhook Proxy  (how Meta/Telegram delivers messages to your server)"
    _S_TXT_P1="1) none        — No proxy  [use if server has a static public IP or domain] (default)"
    _S_TXT_P2="2) ngrok       — ngrok tunnel  [easiest for local setup; free static domain available]"
    _S_TXT_P3="3) cloudflared — Cloudflare Tunnel  [persistent free URL; requires Cloudflare account]"
    _S_TXT_P4="4) external    — Your own domain  [enter your public HTTPS URL manually]"
    _S_TXT_WA="▶ WhatsApp Credentials  (from developers.facebook.com → WhatsApp → API Setup)"
    _S_TXT_TG="▶ Telegram Credentials  (create a bot at t.me/BotFather)"
    _S_TXT_AN="▶ Anthropic API Key  (console.anthropic.com → Settings → API Keys)"
    _S_TXT_OL="▶ Ollama  (must be running locally — ollama.com)"
    _S_TXT_GE="▶ Google Gemini  (aistudio.google.com → Get API Key)"
    _S_TXT_SEC="▶ Security Keys — auto-generating..."
    _S_TXT_SEC_DONE="Security keys generated automatically (API key, TOTP secrets)"
    _S_TXT_VERIFY_AUTO="Verify token auto-generated"
    _S_TXT_WSECRET_AUTO="Webhook secret auto-generated"
    _S_TOTP_GA_TITLE="Add to Google Authenticator"
    _S_TOTP_GA_STEPS="  1. Open Google Authenticator (or any TOTP app)\n  2. Tap '+' → 'Scan QR code'\n  3. Scan the QR code above\n  4. Done — use the 6-digit code when prompted"
    _S_TOTP_GA_NOQUR="  No QR code? Enter the secret manually in your TOTP app."
    _S_TOTP_QR_ONLINE="Open in browser to view the QR code:"
    _S_TOTP_QR_MANUAL="Manual entry"
    _S_TXT_NOWHIPTAIL="whiptail not found or terminal not compatible — using text mode."
    _S_TXT_RERUN="[?] .env already filled. Run wizard again? [y/N]: "
    _S_TXT_RERUN_Y="y"

    # ── TOTP
    _S_TOTP_TITLE="TOTP Setup — Google Authenticator / Authy"
    _S_TOTP_SUBTITLE="Scan QR code or enter secret manually"
    _S_TOTP_SECRET="Secret"
    _S_TOTP_URI="URI"
    _S_TOTP_QR_HINT="(For QR code: sudo apt install qrencode)"
    _S_TOTP_OWNER="owner TOTP"
    _S_TOTP_ADMIN="admin TOTP"
    _S_TOTP_WARN="Store these secrets somewhere safe — they won't be shown again."

    # ── Webhook URL
    _S_WH_TITLE="Next Step: Webhook Setup"
    _S_WH_WA_URL="WhatsApp Webhook URL:"
    _S_WH_WA_CONSOLE="Register this URL in Meta Developer Console:"
    _S_WH_WA_PATH="developers.facebook.com → WhatsApp → Configuration → Webhook URL"
    _S_WH_WA_PROXY_WARN="Local IP won't work for webhooks. Set up ngrok/cloudflared/external proxy."
    _S_WH_TG_SETUP="Telegram Webhook setup (after starting services):"
    _S_WH_TG_NO_URL="A Public URL is required. Set PUBLIC_URL in .env, then:"
    _S_WH_TG_SETWEBHOOK="curl -s \"https://api.telegram.org/bot<TOKEN>/setWebhook?url=<URL>/telegram/webhook\""
    _S_WH_TG_PROXY_RUNTIME="Webhook will be auto-registered when services start (proxy URL assigned at runtime)"
    _S_WH_CLI="CLI mode — no webhook setup needed."
    _S_WH_CLI_HINT="Start FastAPI and test from terminal."
    _S_WH_HEALTH="Health checks (after starting services):"

    # ── Docker build
    _S_DOCKER_BUILD="Building Docker image with selected capabilities →"
    _S_DOCKER_BUILD_CAPS="  ↳ Capabilities:"
    _S_DOCKER_OVERRIDE="  ↳ Writing docker-compose.override.yml..."
    _S_DOCKER_BUILD_RUN="  ↳ Running docker compose build..."
    _S_DOCKER_UP="  ↳ Starting containers..."
    _S_DOCKER_BUILD_DONE="Docker image built and containers started"
    _S_DOCKER_NOT_FOUND="docker not found — install Docker first."
    _S_DOCKER_COMPOSE_NOT_FOUND="docker compose not found — install Docker Compose v2."
    _S_DOCKER_CRED_CREATED="Created empty ~/.claude/.credentials.json so Docker mounts a file (not a directory). Re-run 'claude auth login' to populate it if using a Claude subscription."
    _S_DOCKER_CRED_OK="~/.claude/.credentials.json found — will be mounted in bridge container"
    _S_DOCKER_WAIT_URL="  ↳ Waiting for proxy public URL (up to 90s)..."
    _S_DOCKER_URL_FOUND="  ↳ Public URL detected"
    _S_DOCKER_URL_TIMEOUT="  ↳ Public URL not yet available — register webhook manually after services are ready"

    # ── Test / health
    _S_WH_TG_REGISTERED="Telegram webhook auto-registered"
    _S_STEP_TEST_PASS="All unit tests passed"
    _S_STEP_TEST_FAIL="Some unit tests failed — check output above. Setup complete but investigate before running."
    _S_STEP_HEALTH_OK_API="FastAPI is healthy (port"
    _S_STEP_HEALTH_FAIL_API="FastAPI not responding — check: pm2 logs 99-api"
    _S_STEP_HEALTH_OK_BRIDGE="Bridge is healthy (port"
    _S_STEP_HEALTH_FAIL_BRIDGE="Bridge not responding — check: pm2 logs 99-bridge"

    # ── Completion
    _S_DONE_TITLE="Setup complete."
    _S_DONE_PM2="Service status: pm2 status  |  Logs: pm2 logs 99-api"
    _S_DONE_SYSTEMD="Start services: sudo systemctl start personal-agent personal-agent-bridge"
    _S_DONE_DOCKER="Containers started — check health: curl http://localhost:8010/health"
    _S_DONE_MANUAL="Start manually:  cd scripts && backend/venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8010"

    # ── Capability configuration (FEAT-3)
    _S_CAP_TITLE="Capability Configuration"
    _S_CAP_DESC="Select which capabilities to ENABLE.\nUnchecked = disabled (smaller image, fewer packages).\n\nRecommended for most users: keep defaults.\nDisable Desktop/Browser unless you need GUI automation.\nDisable Intent Classifier to save one API call per message."
    _S_CAP_SKIP="Capability configuration skipped (RESTRICT_* already set)."
    _S_CAP_RECONFIG="Resetting existing capability settings..."
    _S_CAP_FS="File access outside project root  (read files anywhere)"
    _S_CAP_NET="External network / HTTP requests  (curl, webhooks)"
    _S_CAP_SHELL="Shell command execution          (!terminal command)"
    _S_CAP_SVC="Service management               (systemd/tmux restart)"
    _S_CAP_MEDIA="Media messages                  (images, audio, video)"
    _S_CAP_CAL="Calendar & reminders             (!schedule, events)"
    _S_CAP_WIZ="Project creation wizard          (!project new)"
    _S_CAP_SS="Playwright screenshots           (web page capture)"
    _S_CAP_SCHED="Cron jobs / APScheduler         (timed tasks, reminders)"
    _S_CAP_PDF="PDF import                      (send PDF → parse & store)"
    _S_CAP_HIST="Conversation history logging    (stored in SQLite)"
    _S_CAP_PLANS="Work plans                      (!plan commands)"
    _S_CAP_IC="Intent classifier               (1 extra API call/message)"
    _S_CAP_WIZ_LLM="Wizard AI preview               (LLM call on project create)"
    _S_CAP_DESKTOP="Desktop automation  [BETA]      (Linux + display required)"
    _S_CAP_BROWSER="Browser automation              (Playwright, ~500 MB extra)"

  else  # ── Turkish / Türkçe (default) ──────────────────────────────────────

    # ── Genel
    _S_BANNER_TITLE="Kişisel AI Ajan — Kurulum"
    _S_DONE="Tamam"
    _S_WARNING="Uyarı"
    _S_ERROR="Hata"
    _S_REQUIRED="Zorunlu alan."
    _S_URL_HTTPS="URL https:// ile başlamalıdır."
    _S_OPTIONAL="(opsiyonel)"
    _S_CONTINUE="Devam etmek için OK"
    _S_CANCEL="Kurulum iptal edildi."
    _S_SKIP="Atlandı"

    # ── Önkoşullar
    _S_PRE_PY_MISSING="python3 bulunamadı. Python 3.11+ kur."
    _S_PRE_PY_OLD="Python 3.11+ gerekli (mevcut: "
    _S_PRE_PY_OLD2="). Yükselttikten sonra tekrar çalıştır."
    _S_PRE_NODE_MISSING="node bulunamadı. Node.js 18+ kur (https://nodejs.org)."
    _S_PRE_NODE_OLD="Node.js 18+ gerekli (mevcut: "
    _S_PRE_NODE_OLD2="). Yükselttikten sonra tekrar çalıştır."
    _S_PRE_CLAUDE_MISSING="Claude CLI bulunamadı — bridge çalışmaz!"
    _S_PRE_CLAUDE_HINT="Kurmak için: npm install -g @anthropic-ai/claude-code"
    _S_PRE_CLAUDE_CONT="(Kurulum devam ediyor — servisleri başlatmadan önce mutlaka kur)"

    # ── Claude auth
    _S_AUTH_ALREADY="Claude CLI zaten authenticate edilmiş"
    _S_AUTH_NEEDED="Claude CLI — giriş gerekli. 'claude auth login' başlatılıyor..."
    _S_AUTH_APIKEY="ANTHROPIC_API_KEY tanımlı — API key auth kullanılacak (giriş gerekmez)"
    _S_AUTH_INSTR="Tarayıcı açılacak (veya aşağıdaki URL'yi açın). Claude hesabınızla giriş yapın."
    _S_AUTH_OK="Claude CLI başarıyla authenticate edildi"
    _S_AUTH_WARN="Kimlik doğrulama tamamlanmamış olabilir — Bridge başlamazsa 'claude auth login' çalıştırın"
    _S_AUTH_SKIP="Claude CLI bulunamadı — auth adımı atlanıyor"
    _S_AUTH_INSTALLING="Claude CLI bulunamadı — npm ile kuruluyor (npm install -g @anthropic-ai/claude-code)..."
    _S_AUTH_INSTALLED="Claude CLI kuruldu"
    _S_AUTH_INSTALL_FAIL="Claude CLI kurulamadı. Manuel kur: npm install -g @anthropic-ai/claude-code"
    _S_AUTH_NPM_MISSING="Claude CLI VE npm eksik. Önce Node.js 18+ kur: https://nodejs.org sonra install.sh'yi tekrar çalıştır"

    # ── Adımlar
    _S_STEP_VENV="Python venv oluşturuluyor →"
    _S_STEP_VENV_DONE="Python bağımlılıkları senkronize edildi"
    _S_STEP_PKG_BOOTSTRAP="  ↳ pip + pip-tools bootstrap ediliyor..."
    _S_STEP_PKG_COMPILE="  ↳ Tüm bağımlılıklar çözülüyor (pip-compile)..."
    _S_STEP_PKG_SYNC="  ↳ Venv senkronize ediliyor (eksik kur + fazla kaldır):"
    _S_STEP_PKG_CAP="  ↳ Yetenek paketleri kuruluyor:"
    _S_STEP_PKG_ALL="  ↳ Yetenek yapılandırması yok — tüm paketler kuruluyor"
    _S_STEP_NPM="Node bağımlılıkları kuruluyor →"
    _S_STEP_NPM_DONE="npm bağımlılıkları kuruldu"
    _S_STEP_DIRS="Veri dizinleri oluşturuluyor..."
    _S_STEP_DIRS_DONE="Veri dizinleri hazır"
    _S_STEP_DOCKER_OK="Docker: kullanıcı zaten erişebiliyor"
    _S_STEP_DOCKER_ADDED="Docker: kullanıcı 'docker' grubuna eklendi (yeniden giriş sonrası aktif)"
    _S_STEP_DOCKER_WARN="Docker kurulu ama kullanıcı 'docker' grubunda değil."
    _S_STEP_DOCKER_FIX="Düzeltmek için: sudo usermod -aG docker"
    _S_STEP_SYSTEMD_SKIP="--no-systemd belirtildi, systemd adımı atlandı"
    _S_STEP_SYSTEMD_MISSING="systemd bulunamadı, unit dosyaları atlandı"
    _S_STEP_SYSTEMD_RENDER="Systemd unit dosyaları oluşturuluyor..."
    _S_STEP_SYSTEMD_DONE="Unit dosyaları render edildi:"
    _S_STEP_SYSTEMD_INSTALLED="Systemd servisleri kuruldu ve etkinleştirildi"
    _S_STEP_SYSTEMD_START="Başlatmak için: sudo systemctl start personal-agent personal-agent-bridge"
    _S_STEP_SYSTEMD_NOROOT="Root yetkisi yok; unit dosyaları oluşturuldu:"
    _S_STEP_SYSTEMD_MANUAL="Kurmak için:"
    _S_STEP_PM2_START="PM2 kuruluyor ve servisler başlatılıyor..."
    _S_STEP_PM2_INSTALLED="PM2 kuruldu"
    _S_STEP_PM2_EXISTS="PM2 zaten kurulu:"
    _S_STEP_PM2_DONE="PM2 servisleri başlatıldı"
    _S_STEP_PM2_STARTUP="pm2 startup root yetkisi gerektirebilir — çıktıdaki komutu çalıştır"
    _S_STEP_SYNTAX="Sözdizimi kontrolleri yapılıyor..."
    _S_STEP_TESTS="Unit testler çalıştırılıyor..."
    _S_STEP_HEALTH_PM2="Servis sağlık kontrolü (PM2)..."

    # ── Sihirbaz — whiptail
    _S_WIZ_WELCOME_TITLE="99-root Kurulum Sihirbazı"
    _S_WIZ_WELCOME_MSG="Hoş geldiniz! Bu sihirbaz .env dosyanızı adım adım oluşturacak.

Her adımı onaylamak için Enter, iptal için ESC kullanabilirsiniz.

Başlamak için OK'a basın."
    _S_WIZ_ENV_EXISTS_TITLE=".env Mevcut"
    _S_WIZ_ENV_EXISTS_MSG=".env zaten dolu görünüyor.\nSihirbazı tekrar çalıştırmak istiyor musunuz?"
    _S_WIZ_ENV_SKIP_CI="Etkileşimsiz terminal — .env sihirbazı atlandı. Değerleri elle doldur:"
    _S_WIZ_ENV_SKIP_FLAG=".env atlandı (--no-wizard)"
    _S_WIZ_ENV_EXIST_OK=".env zaten mevcut, atlandı"

    # ── Messenger
    _S_WIZ_MSG_TITLE="Messenger Platformu"
    _S_WIZ_MSG_MSG="Hangi platform üzerinden mesaj alınacak?"
    _S_WIZ_MSG_WA="WhatsApp (Meta Cloud API)"
    _S_WIZ_MSG_TG="Telegram (BotFather token)"
    _S_WIZ_MSG_CLI="CLI — Sadece terminal çıktı (test)"

    # ── LLM
    _S_WIZ_LLM_TITLE="LLM Backend"
    _S_WIZ_LLM_MSG="Hangi yapay zeka modelini kullanmak istiyorsunuz?"
    _S_WIZ_LLM_AN="Anthropic Claude (claude.ai API key)"
    _S_WIZ_LLM_OL="Ollama — Yerel, açık kaynak model"
    _S_WIZ_LLM_GE="Google Gemini (AI Studio API key)"

    # ── Proxy
    _S_WIZ_PRX_TITLE="Webhook Proxy"
    _S_WIZ_PRX_MSG="Dış erişim için hangi yöntem kullanılacak?
(Meta/Telegram'ın webhook'u bu adrese mesaj gönderir)"
    _S_WIZ_PRX_NONE="Yok — Yerel geliştirme / VPS sabit IP"
    _S_WIZ_PRX_NGROK="ngrok — Ücretsiz static domain var (kalıcı URL)"
    _S_WIZ_PRX_CF="Cloudflare Tunnel — Kalıcı seçenek (ücretsiz)"
    _S_WIZ_PRX_EXT="Harici URL — Kendi domainin var"

    # ── WhatsApp bilgileri
    _S_WIZ_WA_INFO_TITLE="WhatsApp Bilgileri"
    _S_WIZ_WA_INFO_MSG="Meta Developer Console'dan bilgileri alın:
  developers.facebook.com → My Apps → <Uygulamanız> → WhatsApp → API Setup

  Access Token   — o sayfadaki geçici 24 saatlik token, ya da Business
                   Settings → System Users'dan kalıcı token oluşturun
  Phone Number ID — telefon numarasının yanındaki sayısal ID (numaranın kendisi değil)
  App Secret     — Settings → Basic → App Secret  (webhook imza doğrulaması için)
  Owner Number   — kendi WhatsApp numaranız ülke koduyla (+90XXXXXXXXXX)

  Verify Token ve webhook secret otomatik üretilir — giriş gerekmez.

Hazır olduğunuzda OK'a basın."
    _S_WIZ_WA_TOKEN="(*) Access Token (EAA...):"
    _S_WIZ_WA_PHONE="(*) Phone Number ID (sayısal, ör. 1234567890):"
    _S_WIZ_WA_SECRET="(*) App Secret (Settings → Basic'ten):"
    _S_WIZ_WA_VERIFY="(*) Verify Token (otomatik üretilir — boş bırakın):"
    _S_WIZ_WA_OWNER="(*) WhatsApp numaranız (+90XXXXXXXXXX):"

    # ── Telegram bilgileri
    _S_WIZ_TG_INFO_TITLE="Telegram Bilgileri"
    _S_WIZ_TG_INFO_MSG="Telegram'da @BotFather'a yazarak bot oluşturun:
  1. Telegram'ı aç → @BotFather'ı ara → /newbot
  2. Bot adı ve kullanıcı adı gir (kullanıcı adı 'bot' ile bitmeli)
  3. BotFather token verir: 123456789:ABCdef...

Token girdikten sonra sihirbaz Chat ID'nizi otomatik algılamayı dener.
Bunun çalışması için: yeni botunuzu açın ve herhangi bir mesaj gönderin (örn. 'merhaba').

Hazır olduğunuzda OK'a basın."
    _S_WIZ_TG_TOKEN="(*) Bot Token (123456789:ABCdef...):"
    _S_WIZ_TG_SEND_MSG_TITLE="Chat ID Otomatik Algılama"
    _S_WIZ_TG_SEND_MSG="Az önce oluşturduğunuz Telegram botunu açın ve herhangi bir mesaj gönderin (örn. 'merhaba').

  Botu nasıl bulursunuz:
  • Telegram'da BotFather'da belirlediniz kullanıcı adını aratın
  • BAŞLAT'a dokunun veya herhangi bir metin gönderin

  Sonra OK'a tıklayın — sihirbaz Chat ID'nizi otomatik algılayacak."
    _S_WIZ_TG_CHAT="(*) Chat ID'niz (sayısal, örn. 123456789):"
    _S_TXT_TG_CHATID_TIP="Telegram'da botunuzu açın, 'merhaba' gönderin, ardından Enter'a basın — Chat ID otomatik algılanır (veya manuel girin):"
    _S_TXT_TG_CHATID_OK="Chat ID otomatik algılandı"
    _S_TXT_TG_CHATID_FAIL="Otomatik algılama başarısız. Chat ID'nizi 10 saniyede öğrenin:
  → Telegram'ı açın → @userinfobot'u aratın → Başlat'a dokunun → anında ID'nizi söyler
  → Gelen numarayı (örn. 123456789) aşağıya girin."

    # ── Anthropic
    _S_WIZ_AN_INFO_TITLE="Anthropic — Kimlik Doğrulama Yöntemi"
    _S_WIZ_AN_CHOICE_MSG="Anthropic ile nasıl kimlik doğrulamak istersiniz?

  [1] Claude Girişi  ✦ ÖNERİLEN
      claude.ai hesabınızla giriş yapın (Pro/Max aboneliği).
      Daha güvenli — yönetilecek veya sızabilecek anahtar yok.
      Sihirbaz bu adımdan sonra 'claude auth login' çalıştırır.

  [2] API Key
      Anthropic Console'dan kullandıkça öde anahtarı.
      console.anthropic.com → Settings → API Keys → Create Key"
    _S_WIZ_AN_CHOICE_1="Claude Girişi (abonelik)"
    _S_WIZ_AN_CHOICE_2="API Key (kullandıkça öde)"
    _S_WIZ_AN_KEY="API Key (sk-ant-api03-...):"
    _S_WIZ_AN_SKIP="Claude Girişi seçildi — sihirbaz bittikten sonra 'claude auth login' çalışacak"

    # ── Ollama
    _S_WIZ_OL_INFO_TITLE="Ollama Bilgileri"
    _S_WIZ_OL_INFO_MSG="Ajan başlatılmadan önce Ollama yerel makinede çalışıyor olmalı.

  Kur:     curl -fsSL https://ollama.com/install.sh | sh
  Model:   ollama pull llama3   (veya mistral, qwen2, gemma3, phi3 …)
  Kontrol: curl http://localhost:11434/api/tags

  İpucu: Temel sohbet iyi çalışır; karmaşık araç kullanımı güvenilmeyebilir."
    _S_WIZ_OL_URL="Base URL [http://localhost:11434]:"
    _S_WIZ_OL_MODEL="Model adı [llama3]:"

    # ── Gemini
    _S_WIZ_GE_INFO_TITLE="Google Gemini Bilgileri"
    _S_WIZ_GE_INFO_MSG="Google AI Studio'dan ücretsiz API key alın:
  aistudio.google.com → Get API Key → Create API key

  Varsayılan model: gemini-2.0-flash (hızlı, çoğu görev için yeterli).
  Karmaşık akıl yürütme için gemini-1.5-pro kullanın."
    _S_WIZ_GE_KEY="(*) Gemini API Key (AIza...):"
    _S_WIZ_GE_MODEL="Model adı [gemini-2.0-flash]:"

    # ── Proxy detayları
    _S_WIZ_CF_INFO_TITLE="Cloudflare Tunnel"
    _S_WIZ_CF_INFO_MSG="Cloudflare Tunnel kalıcı ve ücretsiz bir HTTPS URL sağlar.

  cloudflared'ı kur:
    curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \\
         -o /usr/local/bin/cloudflared && chmod +x /usr/local/bin/cloudflared

  Kalıcı tunnel oluştur (tek seferlik kurulum):
    cloudflared tunnel login
    cloudflared tunnel create personal-agent
    cloudflared tunnel route dns personal-agent <subdomain>

  Hesapsız hızlı geçici tünel:
    cloudflared tunnel --url http://localhost:8010

  (Kurulum sonrası yapılabilir)"
    _S_WIZ_CF_MISSING="cloudflared bulunamadı — servisleri başlatmadan önce kurun."
    _S_WIZ_NGROK_INFO_TITLE="ngrok Bilgileri"
    _S_WIZ_NGROK_INFO_MSG="ngrok, yerel sunucunuza genel HTTPS tüneli oluşturur.
  Binary kurulumu gerekmez — ajan ngrok'u pyngrok paketi aracılığıyla yönetir.

  Ücretsiz hesaplarda BİR adet kalıcı static domain var (URL hiç değişmez):
    ngrok Dashboard → Domains → New Domain → ücretsiz domain'i al

  Auth token almak için (static domain kullanmak zorunlu):
    ngrok.com → Ücretsiz kayıt → Dashboard → Your Authtoken

  Token boş bırakılırsa anonim kullanılır — URL her yeniden başlatmada değişir."
    _S_WIZ_NGROK_TOKEN="ngrok Auth Token — Dashboard → Your Authtoken sayfasındaki alfanümerik kod
  (Domain adı değil; anonim mod için boş bırakın):"
    _S_WIZ_NGROK_DOMAIN="Static domain — ngrok Dashboard → Domains sayfasındaki domain adı
  (örn. adın.ngrok-free.app — hesabın yoksa boş bırak):"
    _S_WIZ_EXT_URL="(*) Public URL (https://alanadi.com):"

    # ── Güvenlik anahtarları
    _S_WIZ_SEC_TITLE="Güvenlik Anahtarları — Otomatik Üretildi"
    _S_WIZ_SEC_MSG="Tüm güvenlik anahtarları otomatik olarak üretildi.
Giriş gerekmez — .env dosyasına yazılacak.

Ne işe yararlar:
  API_KEY           — dahili /agent/* API çağrılarını doğrular
  TOTP_SECRET       — owner komutları için 6 haneli kod (!lock, !schedule …)
  TOTP_SECRET_ADMIN — yıkıcı komutlar için 6 haneli kod (!restart, !shutdown)

Bir sonraki ekranda QR kodları Google Authenticator'a ekleyeceksiniz.
Secret'ları yedek olarak bir parola yöneticisine kaydedin."
    _S_WIZ_SEC_APIKEY="API_KEY (dahili erişim):"
    _S_WIZ_SEC_TOTP="TOTP_SECRET (owner komutları):"
    _S_WIZ_SEC_ADMIN="TOTP_SECRET_ADMIN (yıkıcı komutlar):"

    # ── Saat dilimi
    _S_WIZ_TZ_TITLE="Saat Dilimi"
    _S_WIZ_TZ_MSG="APScheduler ve cron ifadeleri için saat dilimi seçin:"
    _S_WIZ_TZ_TRT="Europe/Istanbul (UTC+3, Türkiye)"
    _S_WIZ_TZ_LON="Europe/London (UTC+0/+1)"
    _S_WIZ_TZ_PAR="Europe/Paris (UTC+1/+2)"
    _S_WIZ_TZ_NYC="America/New_York (UTC-5/-4)"
    _S_WIZ_TZ_LAX="America/Los_Angeles (UTC-8/-7)"
    _S_WIZ_TZ_TYO="Asia/Tokyo (UTC+9)"
    _S_WIZ_TZ_UTC="UTC"
    _S_WIZ_TZ_OTH="Diğer (elle gir)"
    _S_WIZ_TZ_CUSTOM="IANA saat dilimi adı (ör. America/Chicago):"

    # ── Özet
    _S_WIZ_SUM_TITLE="Kurulum Özeti"
    _S_WIZ_SUM_MSG_AUTO="Güvenlik anahtarları otomatik üretildi."
    _S_WIZ_SUM_MSG_CONF="Tamam'a basarsanız .env dosyası oluşturulacak."
    _S_WIZ_ENV_DONE=".env dolduruldu:"

    # ── Metin modu etiketleri
    _S_TXT_TITLE="99-root Kurulum Sihirbazı (metin modu)"
    _S_TXT_HINT="Köşeli parantez içindeki [varsayılan] değeri için boş bırakın."
    _S_TXT_MESSENGER="▶ Messenger Platformu  (ajanı hangi uygulamayla kontrol edeceksiniz)"
    _S_TXT_M1="1) whatsapp  — Meta Cloud API       [Meta uygulamanız varsa] (varsayılan)"
    _S_TXT_M2="2) telegram  — Telegram Bot          [önerilen — en kolay kurulum, iş hesabı gerekmez]"
    _S_TXT_M3="3) cli       — Yalnızca terminal     [yerel test, uygulama gerekmez]"
    _S_TXT_LLM="▶ LLM Backend  (ajanı hangi yapay zeka modeli çalıştıracak)"
    _S_TXT_L1="1) anthropic — Anthropic Claude  [önerilen — tam araç desteği, en iyi sonuç] (varsayılan)"
    _S_TXT_L2="2) ollama    — Yerel Ollama      [ücretsiz, tamamen yerel, sınırlı araç desteği]"
    _S_TXT_L3="3) gemini    — Google Gemini     [ücretsiz kota, bulut, çoğu görev için yeterli]"
    _S_TXT_PROXY="▶ Webhook Proxy  (Meta/Telegram mesajları sunucunuza nasıl iletecek)"
    _S_TXT_P1="1) none        — Proxy yok  [sabit IP'li sunucu veya domain için] (varsayılan)"
    _S_TXT_P2="2) ngrok       — ngrok tüneli  [yerel kurulum için en kolay; ücretsiz static domain mevcut]"
    _S_TXT_P3="3) cloudflared — Cloudflare Tunnel  [kalıcı ücretsiz URL; Cloudflare hesabı gerekir]"
    _S_TXT_P4="4) external    — Kendi domain'in  [HTTPS URL'inizi manuel girin]"
    _S_TXT_WA="▶ WhatsApp Bilgileri  (developers.facebook.com → WhatsApp → API Setup)"
    _S_TXT_TG="▶ Telegram Bilgileri  (t.me/BotFather ile bot oluşturun)"
    _S_TXT_AN="▶ Anthropic API Key  (console.anthropic.com → Settings → API Keys)"
    _S_TXT_OL="▶ Ollama  (yerel makinede çalışıyor olmalı — ollama.com)"
    _S_TXT_GE="▶ Google Gemini  (aistudio.google.com → Get API Key)"
    _S_TXT_SEC="▶ Güvenlik Anahtarları — otomatik üretiliyor..."
    _S_TXT_SEC_DONE="Güvenlik anahtarları otomatik üretildi (API key, TOTP secret'lar)"
    _S_TXT_VERIFY_AUTO="Verify token otomatik üretildi"
    _S_TXT_WSECRET_AUTO="Webhook secret otomatik üretildi"
    _S_TOTP_GA_TITLE="Google Authenticator'a Ekle"
    _S_TOTP_GA_STEPS="  1. Google Authenticator'ı aç (veya herhangi bir TOTP uygulaması)\n  2. '+' → 'QR kodu tara' seç\n  3. Yukarıdaki QR kodu tara\n  4. Hazır — istendiğinde 6 haneli kodu gir"
    _S_TOTP_GA_NOQUR="  QR kod yok mu? TOTP uygulamanıza secret'ı manuel girin."
    _S_TOTP_QR_ONLINE="QR kodu tarayıcıda açmak için:"
    _S_TOTP_QR_MANUAL="Manuel Giriş"
    _S_TXT_NOWHIPTAIL="whiptail bulunamadı veya terminal uygun değil — metin modu kullanılıyor."
    _S_TXT_RERUN="[?] .env zaten dolu. Sihirbazı tekrar çalıştır? [e/H]: "
    _S_TXT_RERUN_Y="e"

    # ── TOTP
    _S_TOTP_TITLE="TOTP Kurulumu — Google Authenticator / Authy"
    _S_TOTP_SUBTITLE="QR kodu tara veya secret'ı elle gir"
    _S_TOTP_SECRET="Secret"
    _S_TOTP_URI="URI"
    _S_TOTP_QR_HINT="(QR kodu için: sudo apt install qrencode)"
    _S_TOTP_OWNER="owner TOTP"
    _S_TOTP_ADMIN="admin TOTP"
    _S_TOTP_WARN="Bu secret'ları güvenli bir yere kaydet — bir daha gösterilmez."

    # ── Webhook URL
    _S_WH_TITLE="Sonraki Adım: Webhook Ayarı"
    _S_WH_WA_URL="WhatsApp Webhook URL:"
    _S_WH_WA_CONSOLE="Bu URL'yi Meta Developer Console'a gir:"
    _S_WH_WA_PATH="developers.facebook.com → WhatsApp → Configuration → Webhook URL"
    _S_WH_WA_PROXY_WARN="Yerel IP ile webhook çalışmaz. ngrok/cloudflared/external proxy kur."
    _S_WH_TG_SETUP="Telegram Webhook kurulumu (servis başlatıldıktan sonra):"
    _S_WH_TG_NO_URL="Public URL gerekli. .env içinde PUBLIC_URL ayarla, ardından:"
    _S_WH_TG_SETWEBHOOK="curl -s \"https://api.telegram.org/bot<TOKEN>/setWebhook?url=<URL>/telegram/webhook\""
    _S_WH_TG_PROXY_RUNTIME="Servisler başlayınca webhook otomatik kaydedilecek (proxy URL çalışma zamanında belirlenir)"
    _S_WH_CLI="CLI modu — webhook kurulumu gerekmez."
    _S_WH_CLI_HINT="FastAPI'yi başlat ve terminalden test et."
    _S_WH_HEALTH="Sağlık kontrolü (servis başlatıldıktan sonra):"

    # ── Docker build
    _S_DOCKER_BUILD="Seçili yeteneklerle Docker image oluşturuluyor →"
    _S_DOCKER_BUILD_CAPS="  ↳ Yetenekler:"
    _S_DOCKER_OVERRIDE="  ↳ docker-compose.override.yml yazılıyor..."
    _S_DOCKER_BUILD_RUN="  ↳ docker compose build çalıştırılıyor..."
    _S_DOCKER_UP="  ↳ Container'lar başlatılıyor..."
    _S_DOCKER_BUILD_DONE="Docker image oluşturuldu ve container'lar başlatıldı"
    _S_DOCKER_NOT_FOUND="docker bulunamadı — önce Docker kur."
    _S_DOCKER_COMPOSE_NOT_FOUND="docker compose bulunamadı — Docker Compose v2 kur."
    _S_DOCKER_CRED_CREATED="Boş ~/.claude/.credentials.json oluşturuldu (Docker directory değil dosya mount etsin diye). Claude subscription kullanıyorsanız 'claude auth login' ile doldurun."
    _S_DOCKER_CRED_OK="~/.claude/.credentials.json mevcut — bridge container'a mount edilecek"
    _S_DOCKER_WAIT_URL="  ↳ Proxy public URL bekleniyor (max 90s)..."
    _S_DOCKER_URL_FOUND="  ↳ Public URL tespit edildi"
    _S_DOCKER_URL_TIMEOUT="  ↳ Public URL henüz hazır değil — servisler hazırlandıktan sonra webhook'u manuel kaydet"

    # ── Test / sağlık kontrolü
    _S_WH_TG_REGISTERED="Telegram webhook otomatik kaydedildi"
    _S_STEP_TEST_PASS="Tüm unit testler geçti"
    _S_STEP_TEST_FAIL="Bazı unit testler başarısız — yukarıdaki çıktıyı incele. Kurulum tamamlandı ama başlatmadan önce kontrol et."
    _S_STEP_HEALTH_OK_API="FastAPI sağlıklı (port"
    _S_STEP_HEALTH_FAIL_API="FastAPI yanıt vermiyor — kontrol et: pm2 logs 99-api"
    _S_STEP_HEALTH_OK_BRIDGE="Bridge sağlıklı (port"
    _S_STEP_HEALTH_FAIL_BRIDGE="Bridge yanıt vermiyor — kontrol et: pm2 logs 99-bridge"

    # ── Tamamlama
    _S_DONE_TITLE="Kurulum tamamlandı."
    _S_DONE_PM2="Servis durumu: pm2 status  |  Loglar: pm2 logs 99-api"
    _S_DONE_SYSTEMD="Servisleri başlat: sudo systemctl start personal-agent personal-agent-bridge"
    _S_DONE_DOCKER="Container'lar başlatıldı — sağlık kontrol: curl http://localhost:8010/health"
    _S_DONE_MANUAL="Manuel başlat:  cd scripts && backend/venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8010"

    # ── Yetenek yapılandırması (FEAT-3)
    _S_CAP_TITLE="Yetenek Yapılandırması"
    _S_CAP_DESC="Hangi yeteneklerin AKTİF olmasını seçin.\nİşaretsiz = devre dışı (daha küçük image, daha az paket).\n\nÇoğu kullanıcı için: varsayılanları koru.\nDesktop/Browser'ı yalnızca GUI otomasyonu gerekiyorsa aç.\nIntent Classifier'ı kapatmak mesaj başına 1 API çağrısı azaltır."
    _S_CAP_SKIP="Yetenek yapılandırması atlandı (RESTRICT_* zaten tanımlı)."
    _S_CAP_RECONFIG="Mevcut yetenek ayarları sıfırlanıyor..."
    _S_CAP_FS="Proje kökü dışı dosya erişimi  (her yerden dosya okuma)"
    _S_CAP_NET="Dış ağ / HTTP istekleri        (curl, webhook çağrıları)"
    _S_CAP_SHELL="Kabuk komutu çalıştırma        (!terminal komutu)"
    _S_CAP_SVC="Servis yönetimi               (systemd/tmux yeniden başlatma)"
    _S_CAP_MEDIA="Medya mesajları               (resim, ses, video gönderme)"
    _S_CAP_CAL="Takvim ve hatırlatıcılar       (!schedule, etkinlik)"
    _S_CAP_WIZ="Proje oluşturma sihirbazı      (!project new)"
    _S_CAP_SS="Playwright ekran görüntüsü     (web sayfası yakalama)"
    _S_CAP_SCHED="Cron görevleri / APScheduler  (zamanlanmış görevler)"
    _S_CAP_PDF="PDF içe aktarma               (PDF gönder → çözümle & kaydet)"
    _S_CAP_HIST="Konuşma geçmişi kaydı         (SQLite'a kaydedilir)"
    _S_CAP_PLANS="İş planları                   (!plan komutları)"
    _S_CAP_IC="Niyet sınıflandırıcı          (mesaj başına 1 ekstra API çağrısı)"
    _S_CAP_WIZ_LLM="Wizard AI önizlemesi          (proje oluştururken LLM çağrısı)"
    _S_CAP_DESKTOP="Masaüstü otomasyonu [BETA]    (Linux + ekran gerektirir)"
    _S_CAP_BROWSER="Tarayıcı otomasyonu           (Playwright, ~500 MB ekstra)"

  fi
}

# ── Helpers / Yardımcılar ─────────────────────────────────────────────────────

log()  { echo "[install] $*"; }
ok()   { echo "[✓] $*"; }
warn() { echo "[!] $*"; }
die()  { echo "[✗] $*" >&2; exit 1; }

_env_set() {
  local key="$1" val="$2" file="$3"
  if grep -q "^${key}=" "$file" 2>/dev/null; then
    # Use awk instead of sed to avoid breakage when val contains sed delimiters (@ / \)
    local tmp; tmp="$(mktemp "${file}.XXXXXX")"
    awk -v k="$key" -v v="$val" 'BEGIN{OFS=""} $0 ~ "^"k"=" {print k"="v; next} {print}' "$file" > "$tmp"
    mv "$tmp" "$file"
  else
    printf '%s=%s\n' "$key" "$val" >> "$file"
  fi
}

# _env_comment_out <KEY> <file>
# Aktif satırı (KEY=...) yorum satırına dönüştürür (# KEY=...).
# Zaten yorum satırıysa veya yoksa işlem yapmaz.
_env_comment_out() {
  local key="$1" file="$2"
  if grep -q "^${key}=" "$file" 2>/dev/null; then
    sed -i "s@^${key}=@# ${key}=@" "$file"
  fi
}

# _env_uncomment <KEY> <file>
# Yorum satırını (# KEY=...) aktif satıra dönüştürür (KEY=...).
# Zaten aktifse veya yoksa işlem yapmaz.
_env_uncomment() {
  local key="$1" file="$2"
  if grep -q "^# ${key}=" "$file" 2>/dev/null; then
    sed -i "s@^# ${key}=@${key}=@" "$file"
  fi
}

# ── whiptail helpers ──────────────────────────────────────────────────────────

_wt_available() {
  command -v whiptail &>/dev/null && [ -t 0 ] && [ -t 2 ]
}

_wt_radio() {
  local title="$1" msg="$2"; shift 2
  whiptail --title "$title" --radiolist "$msg" 20 70 10 "$@" 3>&1 1>&2 2>&3
}

_wt_input() {
  local title="$1" msg="$2" default="${3:-}"
  whiptail --title "$title" --inputbox "$msg" 10 70 "$default" 3>&1 1>&2 2>&3
}

_wt_password() {
  local title="$1" msg="$2"
  whiptail --title "$title" --inputbox "$msg" 10 70 3>&1 1>&2 2>&3
}

_wt_yesno() {
  local title="$1" msg="$2"
  whiptail --title "$title" --yesno "$msg" 10 70 3>&1 1>&2 2>&3
}

_wt_msg() {
  local title="$1" msg="$2"
  whiptail --title "$title" --msgbox "$msg" 20 70 3>&1 1>&2 2>&3
}

# ── Prerequisites / Önkoşullar ────────────────────────────────────────────────

check_prereqs() {
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

  if ! command -v python3 &>/dev/null; then die "$_S_PRE_PY_MISSING"; fi
  local py_major py_minor
  py_major="$(python3 -c 'import sys; print(sys.version_info.major)' 2>/dev/null || echo 0)"
  py_minor="$(python3 -c 'import sys; print(sys.version_info.minor)' 2>/dev/null || echo 0)"
  if [[ "$py_major" -lt 3 ]] || [[ "$py_major" -eq 3 && "$py_minor" -lt 11 ]]; then
    die "${_S_PRE_PY_OLD}$(python3 --version)${_S_PRE_PY_OLD2}"
  fi
  ok "Python: $(python3 --version)"

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

# ── Package resolution — modüler kurulum ─────────────────────────────────────
#
# Veri odaklı yaklaşım (OCP): yeni yetenek = yeni satır aşağıdaki tablolara,
# _resolve_requirements fonksiyonu değişmez.
#
# Tablo sütunları:
#   _PKG_CAP_KEYS   : yetenek adı (requirements/<name>.txt dosyasıyla eşleşmeli)
#   _PKG_ENV_VARS   : .env'deki değişken adı
#   _PKG_ACTIVE_VAL : bu değerde yetenek "etkin" sayılır
#
_PKG_CAP_KEYS=(   "scheduler" "pdf_import" "calendar" "screenshot" "media" "desktop"        "browser"        )
_PKG_ENV_VARS=(   "RESTRICT_SCHEDULER" "RESTRICT_PDF_IMPORT" "RESTRICT_CALENDAR" "RESTRICT_SCREENSHOT" "RESTRICT_MEDIA" "DESKTOP_ENABLED" "BROWSER_ENABLED" )
_PKG_ACTIVE_VAL=( "false"     "false"      "false"    "false"      "false"  "true"           "true"           )

# _read_env_var <VAR> <env_file>
# .env dosyasından değişken değerini okur; yoksa boş string döner.
_read_env_var() {
  grep "^${1}=" "${2}" 2>/dev/null | cut -d= -f2- | tr -d '"' | head -1 || true
}

# _resolve_requirements
# Seçili yeteneklere göre yüklenecek requirements dosya yollarını stdout'a yazar.
# .env yoksa veya capability flag'leri yoksa tüm dosyaları döner (güvenli fallback).
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

# ── Step 1: Python venv ───────────────────────────────────────────────────────

step_venv() {
  log "$_S_STEP_VENV $BACKEND_DIR/venv"
  if [ ! -d "$BACKEND_DIR/venv" ]; then python3 -m venv "$BACKEND_DIR/venv"; fi

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
    --quiet --no-header --no-annotate --no-strip-extras \
    --output-file="$compiled" \
    "${req_files[@]}"

  # pip-sync: compiled.txt'e göre venv'i atomik senkronize et.
  # Eksik paketleri kurar; listede olmayan (devre dışı capability) paketleri kaldırır.
  log "$_S_STEP_PKG_SYNC ${cap_names[*]}"
  "$BACKEND_DIR/venv/bin/pip-sync" --quiet "$compiled"

  ok "$_S_STEP_VENV_DONE"
}

# ── Step 2: npm ───────────────────────────────────────────────────────────────

step_npm() {
  log "$_S_STEP_NPM $BRIDGE_DIR/node_modules"
  (cd "$BRIDGE_DIR" && npm install --silent)
  ok "$_S_STEP_NPM_DONE"
}

# ── Step 3: Data directories / Veri dizinleri ────────────────────────────────

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
  ok "$_S_STEP_DIRS_DONE"
}

# ── Step 4: Docker group ──────────────────────────────────────────────────────

step_docker_group() {
  if ! command -v docker &>/dev/null; then return; fi
  if docker info &>/dev/null 2>&1; then
    ok "$_S_STEP_DOCKER_OK"; return
  fi
  if [ "$EUID" -eq 0 ]; then
    usermod -aG docker "$CURRENT_USER"
    ok "$_S_STEP_DOCKER_ADDED"
  else
    warn "$_S_STEP_DOCKER_WARN"
    warn "$_S_STEP_DOCKER_FIX $CURRENT_USER && newgrp docker"
  fi
}

# ── Step 5: Docker build ─────────────────────────────────────────────────────

step_docker_build() {
  if ! command -v docker &>/dev/null; then
    die "$_S_DOCKER_NOT_FOUND"
  fi
  if ! docker compose version &>/dev/null 2>&1; then
    die "$_S_DOCKER_COMPOSE_NOT_FOUND"
  fi

  # ── credentials.json pre-flight: Docker file mount requires source to be a file.
  # If it doesn't exist, Docker creates a directory — breaking claude CLI auth.
  local cred_file="$HOME/.claude/.credentials.json"
  if [ ! -f "$cred_file" ]; then
    mkdir -p "$HOME/.claude"
    echo "{}" > "$cred_file"
    warn "$_S_DOCKER_CRED_CREATED"
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

  # docker-compose.override.yml yaz — build-arg olarak ilet
  log "$_S_DOCKER_OVERRIDE"
  cat > "$ROOT_DIR/docker-compose.override.yml" <<EOF
# Auto-generated by install.sh --docker — do not edit manually
# Re-run: bash install.sh --docker
services:
  99-api:
    build:
      args:
        CAPABILITIES: "${caps_str}"
EOF

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
  _proxy="$(grep '^WEBHOOK_PROXY=' "$_env_dst" 2>/dev/null | cut -d= -f2- | tr -d '"' | head -1 || true)"
  _messenger="$(grep '^MESSENGER_TYPE=' "$_env_dst" 2>/dev/null | cut -d= -f2- | tr -d '"' | head -1 || true)"
  _messenger="${_messenger:-whatsapp}"

  if [[ "$_proxy" == "ngrok" || "$_proxy" == "cloudflared" ]]; then
    log "$_S_DOCKER_WAIT_URL"
    local _pub_url="" _retry=0 _health

    # Helper: extract public_url from JSON without requiring python3
    _extract_pub_url() {
      local _json="$1"
      # Try python3 first, fall back to grep+sed
      if command -v python3 &>/dev/null; then
        echo "$_json" | python3 -c "import sys,json
try: print(json.load(sys.stdin).get('public_url',''))
except: pass" 2>/dev/null || true
      else
        echo "$_json" | grep -o '"public_url":"[^"]*"' | cut -d'"' -f4 || true
      fi
    }

    while [[ -z "$_pub_url" && $_retry -lt 45 ]]; do
      sleep 2
      _retry=$((_retry + 1))
      _health="$(curl -s --max-time 4 "http://localhost:${API_PORT}/health" 2>/dev/null || true)"
      [[ -n "$_health" ]] && _pub_url="$(_extract_pub_url "$_health")"
    done

    if [[ -n "$_pub_url" ]]; then
      ok "$_S_DOCKER_URL_FOUND: $_pub_url"
      if [[ "$_messenger" == "telegram" ]]; then
        local _tg_token _tg_secret _wh_url _wh_result
        _tg_token="$(grep '^TELEGRAM_BOT_TOKEN=' "$_env_dst" 2>/dev/null | cut -d= -f2- | tr -d '"' | head -1 || true)"
        _tg_secret="$(grep '^TELEGRAM_WEBHOOK_SECRET=' "$_env_dst" 2>/dev/null | cut -d= -f2- | tr -d '"' | head -1 || true)"
        _wh_url="${_pub_url}/telegram/webhook"
        _wh_result="$(curl -s --max-time 8 -X POST \
          "https://api.telegram.org/bot${_tg_token}/setWebhook" \
          -H "Content-Type: application/json" \
          -d "{\"url\":\"${_wh_url}\",\"secret_token\":\"${_tg_secret}\",\"allowed_updates\":[\"message\",\"callback_query\"]}" \
          2>/dev/null || true)"
        if echo "$_wh_result" | grep -q '"ok":true'; then
          ok "$_S_WH_TG_REGISTERED: $_wh_url"
        else
          warn "  Webhook registration failed. Manual: curl -s -X POST 'https://api.telegram.org/bot${_tg_token}/setWebhook' -d 'url=${_wh_url}'"
        fi
      fi
    else
      warn "$_S_DOCKER_URL_TIMEOUT"
    fi
  fi
}

# ── Step 7: Systemd ───────────────────────────────────────────────────────────

render_template() {
  local template="$1" output="$2"
  sed \
    -e "s|{{USER}}|$CURRENT_USER|g" \
    -e "s|{{ROOT_DIR}}|$ROOT_DIR|g" \
    -e "s|{{NODE_PATH}}|$NODE_PATH|g" \
    -e "s|{{API_PORT}}|$API_PORT|g" \
    -e "s|{{BRIDGE_PORT}}|$BRIDGE_PORT|g" \
    "$template" > "$output"
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

# ── Step 8: PM2 ───────────────────────────────────────────────────────────────

step_pm2() {
  if ! $USE_PM2; then return; fi
  log "$_S_STEP_PM2_START"
  if ! command -v pm2 &>/dev/null; then
    npm install -g pm2; ok "$_S_STEP_PM2_INSTALLED"
  else
    ok "$_S_STEP_PM2_EXISTS $(pm2 --version)"
  fi
  pm2 start "$ROOT_DIR/ecosystem.config.js"
  pm2 save
  pm2 startup || warn "$_S_STEP_PM2_STARTUP"
  ok "$_S_STEP_PM2_DONE"
}

# ── Security key generators ───────────────────────────────────────────────────

_gen_api_key() {
  if command -v openssl &>/dev/null; then openssl rand -hex 32
  else date +%s%N | sha256sum | head -c 64; fi
}

_gen_totp() {
  # venv python (systemd/PM2 modu)
  if "$BACKEND_DIR/venv/bin/python" -c "import pyotp" 2>/dev/null; then
    "$BACKEND_DIR/venv/bin/python" -c 'import pyotp; print(pyotp.random_base32())'
  # system python3 (Docker modu / Git Bash)
  elif python3 -c "import pyotp" 2>/dev/null; then
    python3 -c 'import pyotp; print(pyotp.random_base32())'
  elif python -c "import pyotp" 2>/dev/null; then
    python -c 'import pyotp; print(pyotp.random_base32())'
  # pyotp yoksa base32 uyumlu rastgele string üret
  else
    local raw
    if command -v openssl &>/dev/null; then
      raw="$(openssl rand -base64 20 | tr -dc 'A-Z2-7' | head -c 32)"
    else
      raw="$(date +%s%N | sha256sum | tr -dc 'A-Z2-7' | head -c 32)"
    fi
    echo "$raw"
  fi
}

# ── whiptail wizard ───────────────────────────────────────────────────────────

_wizard_whiptail() {
  local env_dst="$1"

  _wt_msg "$_S_WIZ_WELCOME_TITLE" "$_S_WIZ_WELCOME_MSG" || { warn "$_S_CANCEL"; return 1; }

  local messenger
  messenger=$(_wt_radio "$_S_WIZ_MSG_TITLE" "$_S_WIZ_MSG_MSG" \
    "whatsapp" "$_S_WIZ_MSG_WA"  ON  \
    "telegram" "$_S_WIZ_MSG_TG"  OFF \
    "cli"      "$_S_WIZ_MSG_CLI" OFF \
  ) || { warn "$_S_CANCEL"; return 1; }

  local llm
  llm=$(_wt_radio "$_S_WIZ_LLM_TITLE" "$_S_WIZ_LLM_MSG" \
    "anthropic" "$_S_WIZ_LLM_AN" ON  \
    "ollama"    "$_S_WIZ_LLM_OL" OFF \
    "gemini"    "$_S_WIZ_LLM_GE" OFF \
  ) || { warn "$_S_CANCEL"; return 1; }

  local proxy
  proxy=$(_wt_radio "$_S_WIZ_PRX_TITLE" "$_S_WIZ_PRX_MSG" \
    "none"        "$_S_WIZ_PRX_NONE"  ON  \
    "ngrok"       "$_S_WIZ_PRX_NGROK" OFF \
    "cloudflared" "$_S_WIZ_PRX_CF"    OFF \
    "external"    "$_S_WIZ_PRX_EXT"   OFF \
  ) || { warn "$_S_CANCEL"; return 1; }

  local wa_token="" wa_phone_id="" wa_secret="" wa_verify="" wa_owner=""
  local tg_token="" tg_chat_id="" tg_webhook_secret=""

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
    wa_verify="$(_gen_api_key | head -c 32)"
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
    # Delete any existing webhook so getUpdates works (previous failed install may leave one)
    curl -s --max-time 5 -X POST "https://api.telegram.org/bot${tg_token}/deleteWebhook" >/dev/null 2>&1 || true
    # Flush old updates so only the next fresh message is returned
    local _tg_flush _tg_next_offset=0
    _tg_flush="$(curl -s --max-time 8 "https://api.telegram.org/bot${tg_token}/getUpdates?limit=100" 2>/dev/null || true)"
    _tg_next_offset="$(echo "$_tg_flush" | python3 -c "
import sys,json
try:
    r=json.load(sys.stdin)['result']
    if r: print(r[-1]['update_id']+1)
    else: print(0)
except: print(0)" 2>/dev/null || \
    echo "$_tg_flush" | grep -o '"update_id":[0-9]*' | tail -1 | grep -o '[0-9]*' | awk '{print $1+1}' 2>/dev/null || echo 0)"
    # Ask user to send a message, then long-poll for the NEW message only
    _wt_msg "$_S_WIZ_TG_SEND_MSG_TITLE" "$_S_WIZ_TG_SEND_MSG" || return 1
    local _tg_auto_id=""
    _tg_auto_id="$(curl -s --max-time 35 "https://api.telegram.org/bot${tg_token}/getUpdates?timeout=30&limit=1&offset=${_tg_next_offset}" 2>/dev/null \
      | python3 -c "import sys,json
try:
    d=json.load(sys.stdin)
    print(d['result'][0]['message']['chat']['id'])
except: pass" 2>/dev/null || true)"
    if [[ -n "$_tg_auto_id" ]]; then
      _wt_msg "$_S_WIZ_TG_INFO_TITLE" "$_S_TXT_TG_CHATID_OK: $_tg_auto_id" || return 1
      tg_chat_id="$_tg_auto_id"
    else
      _wt_msg "$_S_WIZ_TG_INFO_TITLE" "$_S_TXT_TG_CHATID_FAIL" || return 1
      while true; do
        tg_chat_id=$(_wt_input "$_S_WIZ_TG_INFO_TITLE" "$_S_WIZ_TG_CHAT") || return 1
        [[ -n "$tg_chat_id" ]] && break; _wt_msg "$_S_ERROR" "$_S_REQUIRED"
      done
    fi
    tg_webhook_secret="$(_gen_api_key | head -c 32)"
  fi

  local anthropic_key="" ollama_url="" ollama_model="" gemini_key="" gemini_model=""

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

  local public_url="" ngrok_token="" ngrok_domain=""

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

  # ── Timezone / Saat Dilimi
  local tz_choice tz_value
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

  local api_key totp_secret totp_admin
  api_key="$(_gen_api_key)"
  totp_secret="$(_gen_totp)"
  totp_admin="$(_gen_totp)"

  local summary="Messenger  : $messenger\nLLM Backend: $llm\nProxy      : $proxy\nTimezone   : $tz_value"
  [[ -n "$public_url" ]] && summary+="\nPublic URL : $public_url"
  [[ -n "$wa_owner"   ]] && summary+="\nWA Owner   : $wa_owner"
  [[ -n "$tg_chat_id" ]] && summary+="\nTG Chat ID : $tg_chat_id"
  summary+="\n\n$_S_WIZ_SUM_MSG_AUTO\n$_S_WIZ_SUM_MSG_CONF"
  _wt_msg "$_S_WIZ_SUM_TITLE" "$summary" || return 1

  _write_env "$env_dst" "$messenger" "$llm" "$proxy" \
    "$wa_token" "$wa_phone_id" "$wa_secret" "$wa_verify" "$wa_owner" \
    "$tg_token" "$tg_chat_id" "$tg_webhook_secret" \
    "$anthropic_key" "$ollama_url" "$ollama_model" "$gemini_key" "$gemini_model" \
    "$public_url" "$ngrok_token" "$ngrok_domain" \
    "$api_key" "$totp_secret" "$totp_admin" \
    "$tz_value"
}

# ── Text fallback wizard / Metin modu ────────────────────────────────────────

_wizard_text() {
  local env_dst="$1"
  echo ""
  echo "════════════════════════════════════════════"
  echo " $_S_TXT_TITLE"
  echo " $_S_TXT_HINT"
  echo "════════════════════════════════════════════"

  echo ""; echo "$_S_TXT_MESSENGER"
  echo "  $_S_TXT_M1"; echo "  $_S_TXT_M2"; echo "  $_S_TXT_M3"
  read -rp "  [1]: " _m
  local messenger
  case "${_m:-1}" in 2) messenger="telegram";; 3) messenger="cli";; *) messenger="whatsapp";; esac

  echo ""; echo "  ════════════════════════════════════════════════════"; echo "  ════════════════════════════════════════════════════"
  echo ""; echo "$_S_TXT_LLM"
  echo "  $_S_TXT_L1"; echo "  $_S_TXT_L2"; echo "  $_S_TXT_L3"
  read -rp "  [1]: " _l
  local llm
  case "${_l:-1}" in 2) llm="ollama";; 3) llm="gemini";; *) llm="anthropic";; esac

  echo ""; echo "  ════════════════════════════════════════════════════"; echo "  ════════════════════════════════════════════════════"
  echo ""; echo "$_S_TXT_PROXY"
  echo "  $_S_TXT_P1"; echo "  $_S_TXT_P2"; echo "  $_S_TXT_P3"; echo "  $_S_TXT_P4"
  read -rp "  [1]: " _p
  local proxy
  case "${_p:-1}" in 2) proxy="ngrok";; 3) proxy="cloudflared";; 4) proxy="external";; *) proxy="none";; esac

  echo ""; echo "  ════════════════════════════════════════════════════"; echo "  ════════════════════════════════════════════════════"
  local wa_token="" wa_phone_id="" wa_secret="" wa_verify="" wa_owner=""
  local tg_token="" tg_chat_id="" tg_webhook_secret=""

  if [[ "$messenger" == "whatsapp" ]]; then
    echo ""; echo "$_S_TXT_WA"
    while true; do read -rp "  $_S_WIZ_WA_TOKEN " wa_token; [[ -n "$wa_token" ]] && break; warn "$_S_REQUIRED"; done
    while true; do read -rp  "  $_S_WIZ_WA_PHONE " wa_phone_id;       [[ -n "$wa_phone_id" ]] && break; warn "$_S_REQUIRED"; done
    while true; do read -rp "  $_S_WIZ_WA_SECRET " wa_secret;  [[ -n "$wa_secret"   ]] && break; warn "$_S_REQUIRED"; done
    wa_verify="$(_gen_api_key | head -c 32)"
    ok "  $_S_TXT_VERIFY_AUTO: $wa_verify"
    while true; do read -rp  "  $_S_WIZ_WA_OWNER "  wa_owner;         [[ -n "$wa_owner"    ]] && break; warn "$_S_REQUIRED"; done
  elif [[ "$messenger" == "telegram" ]]; then
    echo ""; echo "$_S_TXT_TG"
    while true; do read -rp "  $_S_WIZ_TG_TOKEN " tg_token; [[ -n "$tg_token" ]] && break; warn "$_S_REQUIRED"; done
    echo ""
    echo "  ▶ $_S_WIZ_TG_SEND_MSG_TITLE"
    printf "  %b\n" "$_S_WIZ_TG_SEND_MSG"
    echo ""
    # Delete any existing webhook so getUpdates works
    curl -s --max-time 5 -X POST "https://api.telegram.org/bot${tg_token}/deleteWebhook" >/dev/null 2>&1 || true
    # Flush old updates first
    local _tg_flush2 _tg_next_offset2=0
    _tg_flush2="$(curl -s --max-time 8 "https://api.telegram.org/bot${tg_token}/getUpdates?limit=100" 2>/dev/null || true)"
    _tg_next_offset2="$(echo "$_tg_flush2" | python3 -c "
import sys,json
try:
    r=json.load(sys.stdin)['result']
    if r: print(r[-1]['update_id']+1)
    else: print(0)
except: print(0)" 2>/dev/null || \
    echo "$_tg_flush2" | grep -o '"update_id":[0-9]*' | tail -1 | grep -o '[0-9]*' | awk '{print $1+1}' 2>/dev/null || echo 0)"
    read -rp "  $_S_TXT_TG_CHATID_TIP " tg_chat_id
    if [[ -z "$tg_chat_id" ]]; then
      local _tg_updates
      log "  $_S_WIZ_TG_SEND_MSG_TITLE..."
      _tg_updates="$(curl -s --max-time 35 "https://api.telegram.org/bot${tg_token}/getUpdates?timeout=30&limit=1&offset=${_tg_next_offset2}" 2>/dev/null || true)"
      tg_chat_id="$(echo "$_tg_updates" | python3 -c "import sys,json
try:
    d=json.load(sys.stdin)
    print(d['result'][0]['message']['chat']['id'])
except: pass" 2>/dev/null || true)"
      if [[ -n "$tg_chat_id" ]]; then
        ok "  $_S_TXT_TG_CHATID_OK: $tg_chat_id"
      else
        warn "  $_S_TXT_TG_CHATID_FAIL"
        while true; do read -rp "  $_S_WIZ_TG_CHAT " tg_chat_id; [[ -n "$tg_chat_id" ]] && break; warn "$_S_REQUIRED"; done
      fi
    fi
    tg_webhook_secret="$(_gen_api_key | head -c 32)"
    ok "  $_S_TXT_WSECRET_AUTO"
  fi

  echo ""; echo "  ════════════════════════════════════════════════════"; echo "  ════════════════════════════════════════════════════"
  local anthropic_key="" ollama_url="" ollama_model="" gemini_key="" gemini_model=""

  if [[ "$llm" == "anthropic" ]]; then
    echo ""; echo "$_S_TXT_AN"
    printf "  %b\n" "$_S_WIZ_AN_CHOICE_MSG"
    echo ""
    local _an_method_txt
    read -rp "  [1]: " _an_method_txt
    if [[ "${_an_method_txt:-1}" == "2" ]]; then
      while true; do read -rp "  $_S_WIZ_AN_KEY " anthropic_key; [[ -n "$anthropic_key" ]] && break; warn "$_S_REQUIRED"; done
    else
      ok "  $_S_WIZ_AN_SKIP"
    fi
  elif [[ "$llm" == "ollama" ]]; then
    echo ""; echo "$_S_TXT_OL"
    read -rp "  $_S_WIZ_OL_URL [http://localhost:11434]: " ollama_url
    ollama_url="${ollama_url:-http://localhost:11434}"
    read -rp "  $_S_WIZ_OL_MODEL [llama3]: " ollama_model
    ollama_model="${ollama_model:-llama3}"
  elif [[ "$llm" == "gemini" ]]; then
    echo ""; echo "$_S_TXT_GE"
    while true; do read -rp "  $_S_WIZ_GE_KEY " gemini_key; [[ -n "$gemini_key" ]] && break; warn "$_S_REQUIRED"; done
    read -rp "  $_S_WIZ_GE_MODEL [gemini-2.0-flash]: " gemini_model
    gemini_model="${gemini_model:-gemini-2.0-flash}"
  fi

  echo ""; echo "  ════════════════════════════════════════════════════"; echo "  ════════════════════════════════════════════════════"
  local public_url="" ngrok_token="" ngrok_domain=""
  if [[ "$proxy" == "external" ]]; then
    while true; do read -rp "  $_S_WIZ_EXT_URL " public_url; [[ "$public_url" == https://* ]] && break; warn "$_S_URL_HTTPS"; done
  elif [[ "$proxy" == "ngrok" ]]; then
    echo ""; echo "▶ $_S_WIZ_NGROK_INFO_TITLE"
    printf "  %b\n" "$_S_WIZ_NGROK_INFO_MSG"
    echo ""
    read -rp "  $_S_WIZ_NGROK_TOKEN " ngrok_token
    echo ""
    read -rp "  $_S_WIZ_NGROK_DOMAIN " ngrok_domain
  elif [[ "$proxy" == "cloudflared" ]]; then
    echo ""; echo "▶ $_S_WIZ_CF_INFO_TITLE"
    printf "  %b\n" "$_S_WIZ_CF_INFO_MSG"
    if ! command -v cloudflared &>/dev/null; then warn "$_S_WIZ_CF_MISSING"; fi
  fi

  echo ""; echo "  ════════════════════════════════════════════════════"; echo "  ════════════════════════════════════════════════════"
  # ── Timezone / Saat Dilimi
  echo ""; echo "▶ $_S_WIZ_TZ_TITLE"
  echo "  1) $_S_WIZ_TZ_TRT"
  echo "  2) $_S_WIZ_TZ_LON"
  echo "  3) $_S_WIZ_TZ_PAR"
  echo "  4) $_S_WIZ_TZ_NYC"
  echo "  5) $_S_WIZ_TZ_LAX"
  echo "  6) $_S_WIZ_TZ_TYO"
  echo "  7) $_S_WIZ_TZ_UTC"
  echo "  8) $_S_WIZ_TZ_OTH"
  read -rp "  [1]: " _tz
  local tz_value
  case "${_tz:-1}" in
    2) tz_value="Europe/London" ;;
    3) tz_value="Europe/Paris" ;;
    4) tz_value="America/New_York" ;;
    5) tz_value="America/Los_Angeles" ;;
    6) tz_value="Asia/Tokyo" ;;
    7) tz_value="UTC" ;;
    8) read -rp "  $_S_WIZ_TZ_CUSTOM " tz_value; tz_value="${tz_value:-Europe/Istanbul}" ;;
    *) tz_value="Europe/Istanbul" ;;
  esac

  echo ""; echo "  ════════════════════════════════════════════════════"; echo "  ════════════════════════════════════════════════════"
  echo ""; echo "$_S_TXT_SEC"
  local api_key totp_secret totp_admin
  api_key="$(_gen_api_key)"
  totp_secret="$(_gen_totp)"
  totp_admin="$(_gen_totp)"
  ok "  $_S_TXT_SEC_DONE"

  _write_env "$env_dst" "$messenger" "$llm" "$proxy" \
    "$wa_token" "$wa_phone_id" "$wa_secret" "$wa_verify" "$wa_owner" \
    "$tg_token" "$tg_chat_id" "$tg_webhook_secret" \
    "$anthropic_key" "$ollama_url" "$ollama_model" "$gemini_key" "$gemini_model" \
    "$public_url" "$ngrok_token" "$ngrok_domain" \
    "$api_key" "$totp_secret" "$totp_admin" \
    "$tz_value"
}

# ── .env writer (shared) ──────────────────────────────────────────────────────

_write_env() {
  local env_dst="$1"
  local messenger="$2" llm="$3" proxy="$4"
  local wa_token="$5" wa_phone_id="$6" wa_secret="$7" wa_verify="$8" wa_owner="$9"
  local tg_token="${10}" tg_chat_id="${11}" tg_webhook_secret="${12}"
  local anthropic_key="${13}" ollama_url="${14}" ollama_model="${15}"
  local gemini_key="${16}" gemini_model="${17}"
  local public_url="${18}" ngrok_token="${19}" ngrok_domain="${20}"
  local api_key="${21}" totp_secret="${22}" totp_admin="${23}"
  local tz_value="${24:-Europe/Istanbul}"

  local env_src="$BACKEND_DIR/.env.example"
  if [ ! -f "$env_dst" ]; then
    # Strip capability flags so step_capabilities can ask the user interactively
    grep -vE "^(RESTRICT_|DESKTOP_ENABLED|BROWSER_ENABLED)" "$env_src" > "$env_dst"
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
    sed -i '/^ANTHROPIC_API_KEY=/d' "$env_dst"
  fi
  [[ -n "$ollama_url"    ]] && _env_set "OLLAMA_BASE_URL"   "$ollama_url"    "$env_dst"
  [[ -n "$ollama_model"  ]] && _env_set "OLLAMA_MODEL"      "$ollama_model"  "$env_dst"
  [[ -n "$gemini_key"    ]] && _env_set "GEMINI_API_KEY"    "$gemini_key"    "$env_dst"
  [[ -n "$gemini_model"  ]] && _env_set "GEMINI_MODEL"      "$gemini_model"  "$env_dst"

  _env_set "WEBHOOK_PROXY" "$proxy" "$env_dst"
  [[ -n "$public_url"   ]] && _env_set "PUBLIC_URL"      "$public_url"   "$env_dst"
  [[ -n "$ngrok_token"  ]] && _env_set "NGROK_AUTHTOKEN" "$ngrok_token"  "$env_dst"
  [[ -n "$ngrok_domain" ]] && _env_set "NGROK_DOMAIN"    "$ngrok_domain" "$env_dst"

  _env_set "API_KEY"           "$api_key"     "$env_dst"
  _env_set "TOTP_SECRET"       "$totp_secret" "$env_dst"
  _env_set "TOTP_SECRET_ADMIN" "$totp_admin"  "$env_dst"

  _env_set "TIMEZONE" "$tz_value" "$env_dst"

  ok "$_S_WIZ_ENV_DONE $env_dst"
}

# ── Step 7: .env wizard entry / Sihirbaz giriş noktası ───────────────────────

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
      read -rp "$_S_TXT_RERUN" rerun
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

# ── Step 8: Yetenek yapılandırması (FEAT-3) ──────────────────────────────────
# OCP: Yeni kısıtlama = _CAPS dizisine yeni eleman + capability_guard.py'e register çağrısı.

# Capability → ilgili .env parametreleri eşlemesi (boşlukla ayrılmış liste).
# Yetenek devre dışı bırakıldığında bu parametreler yorum satırına alınır;
# etkinleştirildiğinde aktif hâle getirilir.
# OCP: Yeni capability için sadece bir satır eklenir, fonksiyonlar değişmez.
declare -A _CAP_ASSOC_PARAMS=(
  ["desktop"]="DESKTOP_RECORDING DESKTOP_RECORDING_MAX_MB"
  ["browser"]="BROWSER_HEADLESS BROWSER_SESSIONS_DIR"
)

# _apply_cap_visibility <cap_key> <enabled: true|false> <file>
# Capability'ye bağlı .env parametrelerini yorum/aktif yapar.
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
      read -rp "  ${labels[$i]} [Y/n]: " ans
      ans="${ans:-Y}"
    else
      read -rp "  ${labels[$i]} [y/N]: " ans
      ans="${ans:-N}"
    fi
    [[ "${ans,,}" =~ ^y ]] && selected+=" \"${keys[$i]}\""
  done
  _write_capabilities "$selected"
}

step_capabilities() {
  local env_dst="$BACKEND_DIR/.env"
  log "🔧 $_S_CAP_TITLE..."

  # .env yoksa henüz wizard çalışmamış demektir — atla
  [ ! -f "$env_dst" ] && return 0

  # İdempotent: RESTRICT_* veya *_ENABLED zaten tanımlıysa atla (--reconfigure-capabilities olmadığı sürece)
  if ! $RECONFIGURE_CAPS && grep -qE "^(RESTRICT_|DESKTOP_ENABLED|BROWSER_ENABLED)" "$env_dst" 2>/dev/null; then
    ok "  ↳ $_S_CAP_SKIP"
    return 0
  fi

  # --reconfigure-capabilities: mevcut capability satırlarını sil ve yeniden sor
  if $RECONFIGURE_CAPS && grep -qE "^(RESTRICT_|DESKTOP_ENABLED|BROWSER_ENABLED)" "$env_dst" 2>/dev/null; then
    log "  ↳ $_S_CAP_RECONFIG"
    sed -i '/^RESTRICT_/d;/^DESKTOP_ENABLED/d;/^BROWSER_ENABLED/d' "$env_dst"
  fi

  if _wt_available; then
    _capabilities_whiptail
  else
    _capabilities_text
  fi
}

# ── Claude CLI auth ──────────────────────────────────────────────────────────

step_claude_auth() {
  # ANTHROPIC_API_KEY .env'de tanımlıysa OAuth gerekmez
  local env_dst="$BACKEND_DIR/.env"
  local api_key
  api_key="$(_read_env_var "ANTHROPIC_API_KEY" "$env_dst" 2>/dev/null || true)"
  if [[ -n "$api_key" && "$api_key" != *"FILL"* && "$api_key" != *"DOLDUR"* && "$api_key" != *"YOUR_"* ]]; then
    ok "$_S_AUTH_APIKEY"; return
  fi

  # Zaten authenticate ise atla — empty {} (Docker pre-flight) sayılmaz
  if [[ -f "$HOME/.claude/.credentials.json" ]]; then
    local _cred_content
    _cred_content="$(tr -d ' \n\r\t' < "$HOME/.claude/.credentials.json" 2>/dev/null || echo "{}")"
    if [[ "$_cred_content" != "{}" && ${#_cred_content} -gt 5 ]]; then
      ok "$_S_AUTH_ALREADY"; return
    fi
  fi

  # Claude CLI yoksa → npm ile kur (veya kullanıcıya yönlendir)
  if ! command -v claude &>/dev/null; then
    if command -v npm &>/dev/null; then
      log "$_S_AUTH_INSTALLING"
      if npm install -g @anthropic-ai/claude-code 2>&1 | tail -3; then
        if command -v claude &>/dev/null; then
          ok "$_S_AUTH_INSTALLED: $(claude --version 2>/dev/null | head -1 || echo 'installed')"
        else
          # npm PATH'e henüz yansımamış olabilir
          local _npm_bin
          _npm_bin="$(npm bin -g 2>/dev/null || npm prefix -g 2>/dev/null)/bin"
          export PATH="$_npm_bin:$PATH"
          if ! command -v claude &>/dev/null; then
            warn "$_S_AUTH_INSTALL_FAIL"
            return
          fi
        fi
      else
        warn "$_S_AUTH_INSTALL_FAIL"
        return
      fi
    else
      warn "$_S_AUTH_NPM_MISSING"
      return
    fi
  fi

  # claude auth login'i doğrudan çalıştır
  echo ""
  log "$_S_AUTH_NEEDED"
  echo "  $_S_AUTH_INSTR"
  echo ""
  claude auth login || true

  local _cred_after
  _cred_after="$(tr -d ' \n\r\t' < "$HOME/.claude/.credentials.json" 2>/dev/null || echo "{}")"
  if [[ "$_cred_after" != "{}" && ${#_cred_after} -gt 5 ]]; then
    ok "$_S_AUTH_OK"
  else
    warn "$_S_AUTH_WARN"
  fi
}

# ── TOTP QR ───────────────────────────────────────────────────────────────────

step_show_totp() {
  local env_dst="$BACKEND_DIR/.env"
  [ ! -f "$env_dst" ] && return

  local totp_secret totp_admin
  totp_secret="$(grep '^TOTP_SECRET=' "$env_dst" 2>/dev/null | cut -d= -f2- | tr -d '"' | head -1 || true)"
  totp_admin="$(grep  '^TOTP_SECRET_ADMIN=' "$env_dst" 2>/dev/null | cut -d= -f2- | tr -d '"' | head -1 || true)"
  if [[ -z "$totp_secret" || "$totp_secret" == *DOLDUR* || "$totp_secret" == *FILL* ]]; then return; fi

  _print_qr() {
    local label="$1" secret="$2"
    local heading
    [[ "$label" == "admin" ]] && heading="$_S_TOTP_ADMIN" || heading="$_S_TOTP_OWNER"
    local uri="otpauth://totp/99-root%3A${label}?secret=${secret}&issuer=99-root"
    echo ""
    echo "  ── $heading ──────────────────────────────"
    echo "  $_S_TOTP_SECRET : $secret"
    echo "  $_S_TOTP_URI    : $uri"
    # QR renderer: qrencode → venv python → python3/python + qrcode → pip install → hint
    local _py="" _py_extra_path=""
    "$BACKEND_DIR/venv/bin/python" -c "import qrcode" 2>/dev/null && _py="$BACKEND_DIR/venv/bin/python"
    [[ -z "$_py" ]] && python3 -c "import qrcode" 2>/dev/null && _py="python3"
    [[ -z "$_py" ]] && python  -c "import qrcode" 2>/dev/null && _py="python"
    # No qrcode yet — pip install --user (persists, no PYTHONPATH needed)
    if [[ -z "$_py" ]]; then
      for _candidate in python3 python; do
        if command -v "$_candidate" &>/dev/null; then
          "$_candidate" -m pip install --user --quiet qrcode 2>/dev/null || true
          if "$_candidate" -c "import qrcode" 2>/dev/null; then
            _py="$_candidate"
          fi
          break
        fi
      done
    fi
    # Write Python script to a temp file so we can pass it directly (no eval/heredoc race)
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
    elif [[ -n "$_py" ]]; then
      echo ""
      PYTHONPATH="$_py_extra_path" "$_py" "$_qr_script" "$uri"
    else
      # Son çare: online QR servisi URL'si — tarayıcıda açılır
      local _encoded_uri
      if command -v python3 &>/dev/null; then
        _encoded_uri="$(printf '%s' "$uri" | python3 -c 'import sys,urllib.parse; print(urllib.parse.quote(sys.stdin.read().strip(), safe=""))')"
      elif command -v python &>/dev/null; then
        _encoded_uri="$(printf '%s' "$uri" | python -c 'import sys; from urllib import quote; print(quote(sys.stdin.read().strip(), safe=""))' 2>/dev/null || printf '%s' "$uri" | sed 's/&/%26/g; s/=/%3D/g; s/?/%3F/g; s/:/%3A/g; s|/|%2F|g')"
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
      echo "  │  3. Hesap: 99-root:${label}                           │"
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
  if [[ -n "$totp_admin" && "$totp_admin" != "$totp_secret" ]]; then
    _print_qr "admin" "$totp_admin"
  fi
  echo ""
  warn "$_S_TOTP_WARN"
}

# ── Webhook URL info ──────────────────────────────────────────────────────────

step_show_webhook_url() {
  local env_dst="$BACKEND_DIR/.env"
  [ ! -f "$env_dst" ] && return

  local messenger proxy public_url port
  messenger="$(grep '^MESSENGER_TYPE=' "$env_dst" 2>/dev/null | cut -d= -f2- | tr -d '"' | head -1 || true)"
  messenger="${messenger:-whatsapp}"
  proxy="$(grep '^WEBHOOK_PROXY=' "$env_dst" 2>/dev/null | cut -d= -f2- | tr -d '"' | head -1 || true)"
  proxy="${proxy:-none}"
  public_url="$(grep '^PUBLIC_URL=' "$env_dst" 2>/dev/null | cut -d= -f2- | tr -d '"' | head -1 || true)"
  port="$(grep '^FASTAPI_PORT=' "$env_dst" 2>/dev/null | cut -d= -f2- | tr -d '"' | head -1 || true)"
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
    tg_token="$(grep '^TELEGRAM_BOT_TOKEN=' "$env_dst" 2>/dev/null | cut -d= -f2- | tr -d '"' | head -1 || true)"
    tg_secret="$(grep '^TELEGRAM_WEBHOOK_SECRET=' "$env_dst" 2>/dev/null | cut -d= -f2- | tr -d '"' | head -1 || true)"
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
      else
        echo "  → $_wh_url"
        warn "  $_S_WH_TG_SETUP (manual): curl -s -X POST 'https://api.telegram.org/bot${tg_token}/setWebhook' -d 'url=${_wh_url}'"
      fi
    elif [[ "$proxy" == "ngrok" || "$proxy" == "cloudflared" ]]; then
      # Dynamic proxy — URL only known at runtime; Docker auto-registers on startup
      ok "  $_S_WH_TG_PROXY_RUNTIME"
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

# ── Main ──────────────────────────────────────────────────────────────────────

main() {
  _select_language
  _load_strings

  # Hızlı yol: --reconfigure-capabilities — yalnızca yetenek sihirbazını çalıştır
  if $RECONFIGURE_CAPS && ! $NO_WIZARD; then
    echo "=================================================="
    echo " 99-root — $_S_CAP_TITLE"
    echo "=================================================="
    step_capabilities
    if $USE_DOCKER; then
      # Docker modunda image'ı yeni seçime göre yeniden build et
      step_docker_build
    elif [ -d "$BACKEND_DIR/venv" ]; then
      # Yeni seçime göre paketleri yeniden kur (venv varsa)
      step_venv
    fi
    ok "$_S_DONE_TITLE"
    return 0
  fi

  echo "=================================================="
  echo " 99-root — $_S_BANNER_TITLE"
  echo " ROOT_DIR  : $ROOT_DIR"
  echo " USER      : $CURRENT_USER"
  echo " NODE      : $NODE_PATH"
  echo " API_PORT  : $API_PORT  |  BRIDGE_PORT: $BRIDGE_PORT"
  echo "=================================================="

  check_prereqs
  step_env           # .env oluştur / güncelle
  step_capabilities  # RESTRICT_* / *_ENABLED flag'lerini yaz

  if $USE_DOCKER; then
    # Docker modu: auth → data dirs → build & start
    # claude auth login BEFORE docker_build so credentials are ready for the bind mount
    step_claude_auth
    step_data_dirs
    step_docker_group
    step_docker_build
  else
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

main "$@"
