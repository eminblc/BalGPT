# Personal AI Agent

A self-hosted personal AI agent controlled via WhatsApp or Telegram. Send a message, get things done — create projects, manage tasks, set calendar reminders, run shell commands, import PDFs, and chat with Claude Code directly from your phone. Everything runs locally on your machine; no data leaves unless you configure cloud services.

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

## Quick Start

### Option A — Docker ✅ Recommended

> Best choice for most users. Works on any OS, no Python/Node required on the host.

```bash
git clone https://github.com/your-username/99-root.git
cd 99-root
bash install.sh --docker
```

The wizard asks which messenger, LLM backend, webhook proxy, credentials, and capabilities you want. It then writes `.env`, generates a `docker-compose.override.yml` with a `CAPABILITIES` build-arg, builds the image with only the selected packages installed, and starts the containers.

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

| Variable | Description |
|----------|-------------|
| `WHATSAPP_ACCESS_TOKEN` | Meta WhatsApp Cloud API access token |
| `WHATSAPP_PHONE_NUMBER_ID` | WhatsApp phone number ID from Meta Developer |
| `WHATSAPP_APP_SECRET` | App secret for HMAC webhook verification |
| `WHATSAPP_VERIFY_TOKEN` | Self-chosen string for webhook verification |
| `WHATSAPP_OWNER` | Your WhatsApp number with country code (`+90...`) |
| `ANTHROPIC_API_KEY` | Anthropic API key (`sk-ant-...`) |
| `API_KEY` | Internal API key for `/agent/*` endpoints |
| `TOTP_SECRET` | Base32 TOTP secret — `python -c "import pyotp; print(pyotp.random_base32())"` |
| `TOTP_SECRET_ADMIN` | Separate TOTP for destructive commands (`!restart`, `!shutdown`) |

See [`scripts/backend/.env.example`](scripts/backend/.env.example) for all options including Telegram, Ollama, Gemini, timezone, and capability flags.

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
| `!terminal [cmd]` | Run a shell command and send output (dangerous commands require admin TOTP) | Owner |
| `!model [name]` | Change LLM model at runtime (persists until restart) | Owner |
| `!tokens [24h\|7d\|30d]` | Show LLM token usage statistics | Owner |
| `!lang <tr\|en>` | Change interface language | Owner |
| `!timezone [IANA]` | Show or change the active timezone (reconfigures APScheduler) | Owner |
| `!cancel` | Cancel active TOTP flow, pending action, or in-progress query | Owner |
| `!lock` | Lock the application (TOTP required to unlock) | Owner TOTP |
| `!unlock` | Unlock the application | Owner TOTP |
| `!beta-exit` | Exit project beta mode | Owner |
| `!project-delete` | Delete a project from the database | Math + Admin TOTP |
| `!restart` | Restart both services | Math + Admin TOTP |
| `!shutdown` | Stop the FastAPI service | Math + Admin TOTP |

**Auth levels:**
- **Owner** — message must come from the configured owner phone/chat ID
- **Owner TOTP** — owner + 6-digit TOTP code (via authenticator app, `TOTP_SECRET`)
- **Math + Admin TOTP** — owner + simple math challenge + 6-digit admin TOTP code (`TOTP_SECRET_ADMIN`)

Non-command messages are forwarded to Claude Code for free-form conversation.

For capability flags, system requirements, and internal API endpoints, see [docs/skills.md](docs/skills.md).

---

## Webhook Proxy

The agent needs a public HTTPS URL so WhatsApp or Telegram can reach your server. The wizard offers four options:

| Option | When to use |
|--------|-------------|
| **None** | VPS with a static public IP or domain |
| **ngrok** ✅ Recommended for local setup | Easiest — free account, single binary, wizard asks for your auth token |
| **Cloudflare Tunnel** | Persistent free option — requires a Cloudflare account and DNS setup |
| **External URL** | You already have a domain pointing to this machine |

### ngrok setup

The agent manages ngrok through the `pyngrok` Python package — **no manual ngrok binary installation required**. pyngrok downloads and runs the ngrok binary automatically.

1. Create a free account at [ngrok.com](https://ngrok.com).
2. Copy your auth token: **ngrok Dashboard → Your Authtoken**.
3. Run `bash install.sh --docker` (or `install.sh`) and select **ngrok** as the proxy — the wizard will ask for your auth token and write it to `.env`.
4. After the service starts, ngrok automatically opens a tunnel. The public URL is logged on startup and shown in the webhook info printed at the end of the wizard.
5. Register the webhook URL in Meta Developer Console (WhatsApp) or via `setWebhook` (Telegram) — the wizard prints the exact command.

> **Note:** Free ngrok URLs change on every restart. For a stable URL, use a paid ngrok plan, Cloudflare Tunnel, or a VPS with a static IP.
>
> **No account?** You can leave the auth token blank — ngrok works anonymously but with tighter rate limits and the URL still changes on restart.

---

## Messenger Selection

| Messenger | `.env` setting | Notes |
|-----------|---------------|-------|
| Telegram ✅ Recommended | `MESSENGER_TYPE=telegram` | Easiest setup — create a bot with @BotFather in 2 minutes, no business account needed. Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. |
| WhatsApp | `MESSENGER_TYPE=whatsapp` | Requires a Meta Business account, a verified app in Meta Developer Console, and HMAC webhook setup. More involved but works well if you already have a Meta app. |
| CLI (local testing) | `MESSENGER_TYPE=cli` | Writes to stdout; no account needed. |

**Telegram vs WhatsApp — quick guide:**

- Choose **Telegram** if you want the fastest setup. No business verification, no Meta account, bot is live in under 5 minutes. Works on any phone that has Telegram.
- Choose **WhatsApp** if you specifically need to control the agent from WhatsApp (e.g. you don't use Telegram, or you want to share it with non-technical people who already use WhatsApp).

---

## LLM Backend Selection

| Backend | `.env` setting | Cost | Privacy | Notes |
|---------|---------------|------|---------|-------|
| Anthropic ✅ Recommended | `LLM_BACKEND=anthropic` | Pay-per-token | Cloud | Set `ANTHROPIC_API_KEY`. Primary tested backend — full tool use, scheduling, and all features work reliably. |
| Gemini | `LLM_BACKEND=gemini` | Free quota | Cloud | Set `GEMINI_API_KEY`; optionally `GEMINI_MODEL` (default: `gemini-2.0-flash`). Basic conversation works; edge cases may behave differently. |
| Ollama (local) | `LLM_BACKEND=ollama` | Free | Fully local | Set `OLLAMA_BASE_URL` and `OLLAMA_MODEL`. Basic conversation works; complex tool use may be unreliable. |

> The `INTENT_CLASSIFIER_MODEL` setting only applies to the Anthropic backend. When using Ollama or Gemini, the intent classifier uses the backend's default model.

See [docs/deployment/byok.md](docs/deployment/byok.md) for a full setup guide and comparison.

---

## Prerequisites

**Docker (Option A):**
- Docker Engine + Docker Compose v2 (`docker compose version`)
- `claude` CLI installed and authenticated on the host (`npm install -g @anthropic-ai/claude-code`)

**systemd / PM2 (Options B & C):**
- Python 3.11+
- Node.js 18+
- `claude` CLI installed and authenticated (`npm install -g @anthropic-ai/claude-code`)
- `sudo` access for systemd service installation (Option B only)

**All options:**
- A Meta WhatsApp Cloud API app **or** a Telegram bot token
- A public HTTPS URL for the webhook — see [Webhook Proxy](#webhook-proxy) above

---

## License

MIT — see [LICENSE](LICENSE)
