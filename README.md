# BalGPT

> _Self-hosted personal AI agent — chat with it on WhatsApp or Telegram._

**BalGPT** is a self-hosted assistant that lives on your machine and listens on WhatsApp or Telegram. Send it a message, get things done — create projects, manage tasks, set calendar reminders, run shell commands, import PDFs, and talk to Claude Code directly from your phone. Everything runs locally; no data leaves unless you configure cloud services.

---

## Architecture

| Service | Port | Description |
|---------|------|-------------|
| FastAPI (Uvicorn) | 8010 | Webhook receiver, guard chain, command routing |
| Claude Code Bridge | 8013 | Wraps Claude Code CLI, manages sessions |

```
WhatsApp / Telegram → POST /whatsapp/webhook  or  POST /telegram/webhook
                        └─ dedup → blacklist → permission → rate limit → capability
                              └─ "main"    → Claude Code Bridge → Claude Code CLI
                              └─ "project" → Project's own FastAPI (beta mode)
```

---

## 🚀 Getting Started — Beginner Guide

> **Don't worry if you're new to terminals or servers.** This guide assumes nothing. Pick your operating system and follow the steps in order. Total time: ~10–20 minutes (most of it Docker downloading images).

| Your OS | Jump to |
|---------|---------|
| 🪟 **Windows 10 / 11** | [Windows Setup](#-windows-setup) |
| 🍎 **macOS** (Intel or Apple Silicon) | [macOS Setup](#-macos-setup) |
| 🐧 **Linux** (Ubuntu / Debian / Fedora) | [Linux Setup](#-linux-setup) |

> 💡 **What you'll get at the end:** A bot on your phone (Telegram or WhatsApp) that you can chat with. It will create files, run commands, set reminders, and remember what you talked about — all running on your computer.

---

## 🪟 Windows Setup

### What you need (free, install once)

| # | Tool | Download | What it does |
|---|------|----------|--------------|
| 1 | **Docker Desktop** | [docker.com/desktop](https://docs.docker.com/desktop/install/windows-install/) | Runs the bot in a container |
| 2 | **Git for Windows** | [git-scm.com/download/win](https://git-scm.com/download/win) | Provides "Git Bash" — the terminal you'll use |
| 3 | **Python 3.11+** | [python.org/downloads/windows](https://www.python.org/downloads/windows/) | Required by the installer wizard |

**Important during installation:**
- Docker Desktop: leave all defaults checked. After install, **launch it** (whale icon in tray, ~1 min to boot).
- Git for Windows: leave all defaults (especially the "Git Bash Here" option).
- Python: ☑ **Check "Add python.exe to PATH"** on the first install screen — without this, the installer can't find Python.

### Verify everything is ready

Open **Git Bash** (Start Menu → "Git Bash"), then paste these one at a time:

```bash
docker --version
python3 --version   # or: python --version  /  py --version  (Windows)
bash --version | head -1
```

You should see Docker 24+, Python 3.11+, Bash 4+. If any prints `command not found`, reinstall that tool.

> **Windows note:** `python3` may not exist on Windows — `python --version` or `py --version` works too. `install.sh` detects this automatically.

### Step 1 — Make sure Docker is running

Look at the system tray (bottom right). Whale icon should say **"Docker Desktop is running"**. If not, click the icon and start it.

### Step 2 — Download the project

In Git Bash:

```bash
git clone https://github.com/your-username/99-root.git
cd 99-root
```

### Step 3 — Run the installer

```bash
bash install.sh --docker
```

The installer asks ~6 questions, then builds the bot. Each question has a **recommended answer** — when in doubt, pick that. See [What the wizard asks](#-what-the-wizard-asks) below.

### Step 4 — Verify it works

After the installer finishes (10–15 min the first time), run:

```bash
docker compose ps
curl -s http://localhost:8010/health
curl -s http://localhost:8013/health
```

Both `curl` commands should print JSON containing `"status":"ok"`. Then **send a message to your bot** (Telegram or WhatsApp). You should get a reply within a few seconds.

### Common Windows problems

| Symptom | Fix |
|---------|-----|
| `bash: install.sh: No such file or directory` | You're not in the project folder. Run `cd 99-root` first. |
| `Docker daemon is not running` | Open Docker Desktop and wait for the whale icon to stop animating. |
| Wizard appears in PowerShell and looks broken | You ran the script from PowerShell. Close it; open **Git Bash** instead. |
| `python3: command not found` | Reinstall Python from python.org with ☑ **Add to PATH** checked. |
| Browser doesn't open during `claude auth login` | Copy the URL printed in the terminal and paste it into your browser manually. |
| Installer hangs at "Public URL bekleniyor" | ngrok account issue. Sign up at [ngrok.com](https://ngrok.com), copy authtoken, re-run with `--reconfigure-capabilities`. |

---

## 🍎 macOS Setup

### What you need (free, install once)

| # | Tool | How to install | What it does |
|---|------|----------------|--------------|
| 1 | **Homebrew** | Run this in Terminal: `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"` | Package manager — needed for the others |
| 2 | **Docker Desktop** | `brew install --cask docker` (or [download from docker.com](https://docs.docker.com/desktop/install/mac-install/)) | Runs the bot in a container |
| 3 | **Python 3.11+** | `brew install python@3.11` (most macs have it already) | Required by the installer |
| 4 | **Git** | `brew install git` (most macs have it already) | Downloads the project |

After Homebrew + Docker install, **launch Docker Desktop** (Applications → Docker). It takes ~1 minute to boot; you'll see the whale icon in the menu bar say "Docker Desktop is running".

### Verify everything is ready

Open **Terminal** (Cmd+Space → "Terminal"), then:

```bash
docker --version          # 24+
python3 --version          # 3.11+
git --version
bash --version | head -1   # 3+ on macOS is fine; install.sh handles it
```

### Step 1 — Download the project

```bash
git clone https://github.com/your-username/99-root.git
cd 99-root
```

### Step 2 — Run the installer

```bash
bash install.sh --docker
```

(Same wizard as other OSes — see [What the wizard asks](#-what-the-wizard-asks) below.)

### Step 3 — Verify

```bash
docker compose ps
curl -s http://localhost:8010/health
curl -s http://localhost:8013/health
```

Both health endpoints should return JSON with `"status":"ok"`. Send a message to your bot to confirm it talks back.

### Common macOS problems

| Symptom | Fix |
|---------|-----|
| `Cannot connect to the Docker daemon` | Open Docker Desktop from Applications and wait for it to start. |
| `python3: command not found` | `brew install python@3.11` then restart Terminal. |
| Apple Silicon (M1/M2/M3) image build is slow | Normal — first build takes 10–15 min. Subsequent runs take seconds. |
| `xcrun: error: invalid active developer path` | Run `xcode-select --install`, accept the prompt. |
| Permission denied creating `/etc/...` | Don't use `sudo` — Docker mode doesn't need it on macOS. |

---

## 🐧 Linux Setup

### What you need (Ubuntu/Debian commands shown — adjust for Fedora/Arch)

```bash
# 1. Update package index
sudo apt update

# 2. Install Docker + Docker Compose
sudo apt install -y docker.io docker-compose-v2

# 3. Add yourself to the docker group (so you don't need sudo for docker commands)
sudo usermod -aG docker $USER
# ⚠ Log out and back in for this to take effect

# 4. Install Python 3.11+, git, curl, and the venv module
sudo apt install -y python3 python3-venv python3-pip git curl

# 5. (Optional but recommended) for terminal QR code rendering:
sudo apt install -y qrencode whiptail
```

For Fedora: `sudo dnf install docker docker-compose python3 python3-pip git curl qrencode newt`
For Arch: `sudo pacman -S docker docker-compose python python-pip git curl qrencode libnewt`

### Verify

```bash
docker --version
docker compose version
python3 --version          # 3.11+
git --version
```

If `docker info` complains about permissions, you forgot step 3 (log out/in after `usermod`).

### Step 1 — Make sure Docker is running

```bash
sudo systemctl start docker        # Ubuntu/Debian/Fedora
sudo systemctl enable docker       # so it starts on boot
docker info >/dev/null && echo "Docker OK"
```

### Step 2 — Download the project

```bash
git clone https://github.com/your-username/99-root.git
cd 99-root
```

### Step 3 — Run the installer

```bash
bash install.sh --docker
```

(See [What the wizard asks](#-what-the-wizard-asks) below for the questions.)

### Step 4 — Verify

```bash
docker compose ps
curl -s http://localhost:8010/health
curl -s http://localhost:8013/health
```

Then send a message to your bot.

### Native install (no Docker) — for advanced users with a dedicated server

If you have a Linux server and want native systemd services for best performance:

```bash
sudo bash install.sh
```

This installs into a Python virtualenv, sets up systemd units, and enables them on boot. See [Option B — systemd](#option-b--systemd-linux-only) below for details.

### Common Linux problems

| Symptom | Fix |
|---------|-----|
| `permission denied while trying to connect to the Docker daemon` | You forgot to log out/in after `usermod -aG docker`. Or use `sudo` for now. |
| `error: externally-managed-environment` (PEP 668) | The installer creates an ephemeral venv automatically. Make sure `python3-venv` is installed. |
| `qrencode not found` and Python `qrcode` missing | The installer auto-installs qrcode in an ephemeral venv. If it fails, you'll see an online QR URL — open it in a browser. |
| systemd-style errors in Docker mode | You ran `bash install.sh` (without `--docker`). Native mode tries systemd. Use `--docker` flag. |

---

## ❓ What the Wizard Asks

The installer is interactive: it asks ~6 questions, then builds. Here's what each one means and what to pick if you're unsure:

### Q1 — Language

```
Language / Dil:
  1) Türkçe (varsayılan / default)
  2) English
```

Pick whichever you read more comfortably. All later messages will be in that language.

### Q2 — Messenger Platform

```
Which platform will receive messages?
  whatsapp    WhatsApp (Meta Cloud API)
  telegram    Telegram (BotFather token)
  cli         CLI — Terminal output only (testing)
```

🎯 **Recommended: `telegram`** — easiest setup. You just need a free Telegram account (no business verification, no Meta developer account).

- WhatsApp requires a Meta Developer account, a phone number, and an approved business — much harder for first-time users.
- CLI mode is for testing the bot logic without messengers.

### Q3 — Telegram Setup (if you picked telegram)

The installer asks for:

1. **Bot Token** — from [@BotFather](https://t.me/BotFather):
   - Open Telegram, message @BotFather
   - Send `/newbot`
   - Pick any name
   - Pick a username ending in `bot` (e.g., `my_personal_agent_bot`)
   - BotFather replies with a token like `123456789:ABCdef...` — copy and paste it
2. **Chat ID** — auto-detected:
   - The installer says "send any message to your bot now"
   - Open your new bot in Telegram, send "hi"
   - The installer auto-grabs your chat ID. Done.

### Q4 — LLM Backend

```
Which AI model do you want to use?
  anthropic    Anthropic Claude (claude.ai API key)
  ollama       Ollama — Local, open-source model
  gemini       Google Gemini (AI Studio API key)
```

🎯 **Recommended: `anthropic`** with **Claude Login** (subscription) — best results, no API key to manage. Costs whatever your Claude.ai Pro/Max subscription costs (no per-message charge).

- Choose API Key if you don't have a subscription. Get one at [console.anthropic.com](https://console.anthropic.com).
- Choose Ollama if you want everything local and free (slower, less reliable for tool use).
- Choose Gemini if you want a free cloud option ([aistudio.google.com](https://aistudio.google.com) gives a free key).

### Q5 — Webhook Proxy

```
How will Meta/Telegram reach your server?
  none         No proxy
  ngrok        ngrok tunnel
  cloudflared  Cloudflare Tunnel
  external     Your own domain
```

🎯 **Recommended: `ngrok`** — gives you a free permanent public HTTPS URL. The bot needs an internet-reachable URL so Telegram/WhatsApp can deliver messages.

- Pick `none` only if your server already has a public IP and domain.
- Pick `cloudflared` if you have a Cloudflare account.
- Pick `external` if you have your own domain pointing at this server.

ngrok setup (if you pick it):
- Sign up free at [ngrok.com](https://ngrok.com)
- Dashboard → Your Authtoken → copy
- Dashboard → Domains → "+ New domain" → claim a free static domain (looks like `abc-def.ngrok-free.app`)
- Paste both into the wizard

### Q6 — Timezone

Pick the city closest to you. Default `Europe/Istanbul` works if you're in Turkey. This controls when reminders fire.

### Q7 — Capabilities

```
Select which capabilities to ENABLE.
[*] File access  [*] Network  [*] Shell  [*] Calendar  [*] Plans  ...
[ ] Desktop      [ ] Browser
```

🎯 **Recommended: keep defaults.** All but Desktop and Browser are on; that's what most people want. Desktop/Browser require GUI automation packages (~500 MB extra), turn them on only if you need them.

### Q8 — Anthropic Login (if you picked Claude Login)

A browser opens; sign in with your claude.ai account. The installer waits until you're done.

### Q9 — TOTP QR Codes

At the end, you'll see two QR codes (owner + admin). **Scan them with Google Authenticator (or any TOTP app).** These give you 6-digit codes for sensitive bot commands like `!restart` or `!shutdown`.

If your terminal can't render QR codes, you'll see an online URL instead — open it in a browser.

### Q10 — Webhook Setup

The installer prints a webhook URL. For Telegram with ngrok, it's auto-registered. For WhatsApp, you copy the URL into Meta Developer Console → WhatsApp → Configuration → Webhook URL.

---

## 🔧 Reference: Installation Modes

Below sections are detailed reference for the install modes — most users don't need this.

### Option A — Docker ✅ Recommended

> Best choice for most users. Works on Linux, macOS, and Windows (Git Bash + Docker Desktop). The host still needs `bash`, `python3` 3.11+, and `curl` to run the install wizard — see [Prerequisites](#prerequisites). Node.js is **not** needed on the host (the Bridge container ships it).

```bash
git clone https://github.com/your-username/99-root.git
cd 99-root
bash install.sh --docker
```

The wizard asks which messenger, LLM backend, webhook proxy, credentials, and capabilities you want. It then writes `.env`, generates a `docker-compose.override.yml` with a `CAPABILITIES` build-arg, builds the image with only the selected packages installed, and starts the containers.

Security keys (`API_KEY`, `TOTP_SECRET`) and webhook tokens are **auto-generated** by the wizard — no manual input needed. A TOTP QR code is shown at the end so you can scan it into Google Authenticator.

The compose file mounts `./data` and `./outputs/logs` as volumes so all data persists outside the containers.

To reconfigure capabilities and rebuild:

```bash
bash install.sh --docker --reconfigure-capabilities
```

> **Windows users:** PowerShell does not have `bash` — running `bash install.sh --docker` will fail. You need one of the following:
> - **Git Bash** (recommended): install [Git for Windows](https://git-scm.com/download/win), open Git Bash, then run the command above.
> - **WSL**: run `wsl --install -d Ubuntu` in PowerShell, open the Ubuntu terminal, then run the command.
> - **Without the wizard**: copy `.env.example` to `.env`, fill it in manually, then run `docker compose up -d --build` from PowerShell. All capabilities will be installed (larger image).

Check service health:

```bash
docker compose ps
curl -s http://localhost:8010/health
curl -s http://localhost:8013/health
```

View logs:

```bash
docker compose logs -f 99-api
docker compose logs -f 99-bridge
```

Restart:

```bash
docker compose restart
```

### Option B — systemd (Linux only)

> Best choice for a dedicated Linux server or Raspberry Pi where you want native performance and automatic startup.

```bash
git clone https://github.com/your-username/99-root.git
cd 99-root
sudo bash install.sh
```

`install.sh` runs an interactive wizard (messenger, LLM backend, webhook proxy, timezone, capabilities), creates the Python venv, installs only the packages required by the enabled capabilities (via pip-compile + pip-sync), installs Node dependencies, renders systemd unit files, and enables the services.

> Run with `sudo` to automatically install and enable the systemd units. Without `sudo`, the script still runs the wizard and installs dependencies — it prints the manual `systemctl` commands to finish the setup.

Check services:

```bash
sudo systemctl status personal-agent.service personal-agent-bridge.service
journalctl -u personal-agent.service -f
```

Other install flags:

```bash
bash install.sh --no-systemd             # install dependencies only, skip systemd
bash install.sh --pm2                    # start with PM2 instead of systemd
bash install.sh --reconfigure-capabilities  # re-run capability wizard and re-sync packages
```

> **Note:** After manually editing `DESKTOP_ENABLED`, `BROWSER_ENABLED`, or any `RESTRICT_*` flag in `.env`, run `bash install.sh --reconfigure-capabilities` so that the required Python packages are installed or removed.

### Option C — PM2 (Linux / macOS / Windows)

Use PM2 if you don't have systemd (macOS, Windows WSL, VPS without root).

```bash
git clone https://github.com/your-username/99-root.git
cd 99-root
bash install.sh --pm2
```

Check status and logs:

```bash
pm2 status
pm2 logs 99-api
pm2 logs 99-bridge
```

---

## Required Environment Variables

The wizard collects only the credentials you must obtain externally. Everything else is auto-generated.

**Auto-generated by wizard (no input needed):**
`API_KEY`, `TOTP_SECRET`, `WHATSAPP_VERIFY_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`

### WhatsApp

| Variable | Description |
|----------|-------------|
| `WHATSAPP_ACCESS_TOKEN` | Meta WhatsApp Cloud API access token (from Meta Developer Console) |
| `WHATSAPP_PHONE_NUMBER_ID` | Numeric phone number ID from Meta Developer Console |
| `WHATSAPP_APP_SECRET` | App secret for HMAC webhook signature verification |
| `WHATSAPP_OWNER` | Your WhatsApp number with country code (`+1...`) |

### Telegram

| Variable | Description |
|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather (`123456789:ABCdef...`) |
| `TELEGRAM_CHAT_ID` | Your personal Telegram chat ID — get it from [@userinfobot](https://t.me/userinfobot) |

> **Telegram + cloudflared:** When you pick Telegram, the wizard forces `WEBHOOK_PROXY=ngrok` — cloudflared isn't offered as a choice. To use cloudflared instead, finish the install, then edit `.env` to set `WEBHOOK_PROXY=cloudflared`, ensure the `cloudflared` binary is installed, and restart services. The `!wizard` command and the rest of the flow are proxy-agnostic — they work as long as the webhook is registered with a public URL.

> **Telegram command menu:** On every service start, the bot automatically registers all available commands with Telegram via `setMyCommands`. This means the `/` shortcut menu in Telegram is always in sync — no manual BotFather steps needed. Slash commands (`/help`, `/restart`, etc.) are equivalent to their `!` counterparts and work the same way. When you add a new command and restart (`git pull` + `docker compose restart` or `systemctl restart`), the menu updates automatically.

### LLM

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic API key (`sk-ant-api03-...`) — from [console.anthropic.com](https://console.anthropic.com) |
| `GEMINI_API_KEY` | Google Gemini API key — from [aistudio.google.com](https://aistudio.google.com) |
| `OLLAMA_BASE_URL` | Ollama base URL (default: `http://localhost:11434`) |
| `OLLAMA_MODEL` | Ollama model name (default: `llama3`) |

See [`scripts/backend/.env.example`](scripts/backend/.env.example) for all options including timezone and capability flags.

---

## Commands

| Command | Description | Auth |
|---------|-------------|------|
| `!help` | List all commands | Owner |
| `!history [N]` | Show last N messages or session summaries | Owner |
| `!project [id]` | Set / show active project context | Owner |
| `!root-project [name]` | Assign a project context to the root agent | Owner |
| `!root-exit` | Exit root project context | Owner |
| `!root-reset` | Reset Claude Code session | Owner |
| `!root-check` | Show Bridge status (active request or idle) | Owner |
| `!root-log` | Show last 5 entries of root_actions.log | Owner |
| `!schedule` | List / create / stop scheduled tasks | Owner |
| `!terminal [cmd]` | Run a shell command and send output (dangerous commands require owner TOTP) | Owner |
| `!model [name]` | Change LLM model at runtime (persists until restart) | Owner |
| `!tokens [24h\|7d\|30d]` | Show LLM token usage statistics | Owner |
| `!lang <tr\|en>` | Change interface language | Owner |
| `!timezone [IANA]` | Show or change the active timezone (reconfigures APScheduler) | Owner |
| `!cancel` | Cancel active TOTP flow, pending action, or in-progress query | Owner |
| `!lock` | Lock the application (TOTP required to unlock) | Owner + TOTP |
| `!unlock` | Unlock the application | Owner + TOTP |
| `!beta` | Exit project beta mode | Owner |
| `!project-delete` | Delete a project from the database | Math + Owner TOTP |
| `!restart` | Restart both services | Math + Owner TOTP |
| `!shutdown` | Stop the FastAPI service | Math + Owner TOTP |

**Auth levels:**
- **Owner** — message must come from the configured owner phone/chat ID
- **Owner + TOTP** — owner + 6-digit code from your authenticator app (`TOTP_SECRET`)
- **Math + Owner TOTP** — owner + simple math challenge + 6-digit code (`TOTP_SECRET`)

Non-command messages are forwarded to Claude Code for free-form conversation.

> **Telegram:** All commands are also available as native slash commands (`/help`, `/root_reset`, etc.). The bot registers them automatically on every startup — the `/` shortcut menu stays in sync without any BotFather configuration.

For capability flags, system requirements, and internal API endpoints, see [docs/skills.md](docs/skills.md).

---

## Webhook Proxy

The agent needs a public HTTPS URL so WhatsApp or Telegram can deliver messages to your server. The wizard offers four options:

| Option | When to use |
|--------|-------------|
| **None** | VPS with a static public IP or domain already pointing to the server |
| **ngrok** ✅ Recommended for local setup | Free account includes a permanent static domain; no binary install needed |
| **Cloudflare Tunnel** | Persistent free option — requires a Cloudflare account and DNS setup |
| **External URL** | You already have a domain pointing to this machine |

### ngrok setup

The agent manages ngrok through the `pyngrok` Python package — **no manual ngrok binary installation required**. pyngrok downloads and runs the ngrok binary automatically.

1. Create a free account at [ngrok.com](https://ngrok.com).
2. Claim your **free static domain**: ngrok Dashboard → Domains → New Domain → copy the domain (e.g. `yourname.ngrok-free.app`). This URL is permanent and never changes.
3. Copy your auth token: **ngrok Dashboard → Your Authtoken**.
4. Run `bash install.sh --docker` (or `install.sh`) and select **ngrok** as the proxy — the wizard will ask for your auth token and write it to `.env`.
5. After the service starts, ngrok automatically opens a tunnel on your static domain. The public URL is logged on startup and shown in the webhook info printed at the end of the wizard.
6. Register the webhook URL in Meta Developer Console (WhatsApp) or via `setWebhook` (Telegram) — the wizard prints the exact command.

> **Free accounts get one permanent static domain** — the URL does not change on restart as long as you use your static domain and auth token.
>
> **No account?** You can leave the auth token blank — ngrok works anonymously but the URL is random and changes on every restart.

---

## Messenger Selection

| Messenger | `.env` setting | Notes |
|-----------|---------------|-------|
| Telegram ✅ Recommended | `MESSENGER_TYPE=telegram` | Easiest setup — create a bot with @BotFather in 2 minutes, no business account needed. The wizard auto-detects your chat ID. |
| WhatsApp | `MESSENGER_TYPE=whatsapp` | Requires a Meta Business account, a verified app in Meta Developer Console, and HMAC webhook setup. |
| CLI (local testing) | `MESSENGER_TYPE=cli` | Writes to stdout; no account needed. |

**Telegram vs WhatsApp — quick guide:**

- Choose **Telegram** if you want the fastest setup. No business verification, no Meta account, bot is live in under 5 minutes.
- Choose **WhatsApp** if you specifically need to control the agent from WhatsApp (e.g. you don't use Telegram, or you want to share it with people who don't have Telegram).

For detailed Telegram setup steps, see [docs/deployment/telegram.md](docs/deployment/telegram.md).

---

## LLM Backend Selection

| Backend | `.env` setting | Cost | Privacy | Notes |
|---------|---------------|------|---------|-------|
| Anthropic ✅ Recommended | `LLM_BACKEND=anthropic` | Pay-per-token | Cloud | Set `ANTHROPIC_API_KEY`. Full tool use, scheduling, and all features work reliably. |
| Gemini | `LLM_BACKEND=gemini` | Free quota | Cloud | Set `GEMINI_API_KEY`; optionally `GEMINI_MODEL` (default: `gemini-2.0-flash`). Basic conversation works. |
| Ollama (local) | `LLM_BACKEND=ollama` | Free | Fully local | Set `OLLAMA_BASE_URL` and `OLLAMA_MODEL`. Run `ollama pull llama3` first. Complex tool use may be unreliable. |

> The `INTENT_CLASSIFIER_MODEL` setting only applies to the Anthropic backend.

See [docs/deployment/byok.md](docs/deployment/byok.md) for a full setup guide and comparison.

---

## Prerequisites

### Always required (every install mode)

| Tool | Why install.sh needs it |
|------|------------------------|
| `bash` 4+ | Script interpreter; `set -euo pipefail`, associative arrays |
| **`python3` 3.11+** | i18n locale loader, JSON parsing, .env helpers, messenger notifications, systemd template rendering, TOTP QR generation. install.sh exits with a fatal error if missing. |
| `curl` | Telegram/WhatsApp/ngrok API calls |
| Standard POSIX tools | `awk`, `sed`, `grep`, `mktemp`, `tr`, `cut` (preinstalled on every Linux/macOS, included with Git Bash) |

> ⚠️ Despite Docker mode handling everything inside containers, **install.sh itself runs on the host and requires Python 3.11+ on the host**. Earlier wording suggesting "no Python on host" was inaccurate.

### Mode-specific

| Mode | Extra requirements |
|------|--------------------|
| **Docker** (Option A) | Docker Engine + Docker Compose v2 (`docker compose version`); `claude` CLI on host (auto-installed via `npm` if missing) |
| **systemd** (Option B) | Node.js 18+; `sudo` access; `claude` CLI |
| **PM2** (Option C) | Node.js 18+; `claude` CLI; `npm install -g pm2` (script handles this) |

### Optional but recommended

| Tool | Effect if missing |
|------|-------------------|
| `whiptail` | Wizard falls back to plain-text prompts (still works, less friendly) |
| `qrencode` **or** `python3-venv` | TOTP QR rendered in terminal. Without **both**, you get an online QR URL + manual key entry instructions instead. On Debian/Ubuntu `python3-venv` is a separate package: `sudo apt install python3-venv` |
| `openssl` | Cryptographic random for `API_KEY` and TOTP secrets. Without it, falls back to `date +%s%N \| sha256sum` (lower entropy) |
| `node` + `npm` (Docker mode) | Auto-install of `claude` CLI; without these you must install Claude CLI manually before starting Bridge |

### Platform notes

- **Linux (Ubuntu 23.04+, Debian 12+, Fedora 38+, etc.)** — PEP 668 blocks `pip install --user`. install.sh creates an ephemeral venv automatically for QR rendering, so no action needed; just have `python3-venv` installed.
- **macOS** — `python3` from Homebrew or python.org both work. Same PEP 668 caveat.
- **Windows** — Native install is **not supported**; install.sh exits with a clear error. Use `bash install.sh --docker` from Git Bash with Docker Desktop running. Python 3.11+ must still be on PATH.
- **WSL** — Treat as Linux. systemd may need explicit enablement (`/etc/wsl.conf` → `[boot] systemd=true`) for Option B.

### External services / accounts

- A **Telegram bot token** (from [@BotFather](https://t.me/BotFather)) **or** a **Meta WhatsApp Cloud API** app
- An [Anthropic API key](https://console.anthropic.com) **or** a Claude Pro/Max subscription (for `claude auth login`); alternatively use Ollama (local) or Google Gemini
- A **public HTTPS URL** for the webhook — see [Webhook Proxy](#webhook-proxy) above (ngrok works without buying a domain)

### Quick check

```bash
bash --version | head -1
python3 --version    # must print 3.11+
curl --version | head -1
docker --version     # Docker mode only
node --version       # native modes only

# QR code support (optional)
command -v qrencode || python3 -c 'import venv'
```

---

## License

MIT — see [LICENSE](LICENSE)

Copyright © 2026 Emin Balcı. All rights reserved.
