# Personal AI Agent

A self-hosted personal AI agent controlled via WhatsApp. Send a message, get things done — create projects, manage tasks, set calendar reminders, import PDFs, and chat with Claude Code directly from your phone. Everything runs locally on your machine; no data leaves unless you configure cloud services.

---

## Architecture

| Service | Port | Description |
|---------|------|-------------|
| FastAPI (Uvicorn) | 8010 | Webhook receiver, guard chain, command routing |
| Claude Code Bridge | 8013 | Wraps Claude Code CLI, manages sessions |

```
WhatsApp → POST /whatsapp/webhook
              └─ dedup → blacklist → rate limit → permission
                    └─ "main"    → Claude Code Bridge → Claude Code CLI
                    └─ "project" → Project's own FastAPI (beta mode)
```

---

## Quick Start

### Option A — Docker (recommended, any OS)

```bash
git clone https://github.com/your-username/99-root.git
cd 99-root
cp scripts/backend/.env.example scripts/backend/.env
# Fill in .env (see table below)
docker compose up -d
```

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

### Option B — systemd (Linux only)

```bash
git clone https://github.com/your-username/99-root.git
cd 99-root
cp scripts/backend/.env.example scripts/backend/.env
# Fill in .env (see table below)
sudo ./install.sh
```

`install.sh` creates the Python venv, installs Node dependencies, renders systemd unit files, and enables the services. After it completes:

```bash
sudo systemctl status personal-agent.service personal-agent-bridge.service
```

### Option C — PM2 (Linux / macOS / Windows)

Use PM2 if you don't have systemd (macOS, Windows WSL, VPS without root).

```bash
git clone https://github.com/your-username/99-root.git
cd 99-root
cp scripts/backend/.env.example scripts/backend/.env
# Fill in .env (see table below)
./install.sh --pm2
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

See [`scripts/backend/.env.example`](scripts/backend/.env.example) for all options.

---

## WhatsApp Commands

| Command | Description | Auth |
|---------|-------------|------|
| `!help` | List all commands | Owner |
| `!history [N]` | Show last N messages or session summaries | Owner |
| `!project [id]` | Set active project context | Owner |
| `!schedule` | List / create / stop cron jobs | Owner |
| `!root-reset` | Reset Claude Code session | Owner |
| `!restart` | Restart both services via systemd | Admin TOTP |
| `!shutdown` | Stop FastAPI service | Admin TOTP |
| `!beta-exit` | Exit project beta mode | Owner |
| `!lang <tr\|en>` | Change interface language | Owner |

Non-command messages are forwarded to Claude Code for free-form conversation.

For the full command list, capability flags, system requirements, and internal API endpoints, see [docs/skills.md](docs/skills.md).

---

## Model Selection

Three LLM backends are supported. See [docs/deployment/byok.md](docs/deployment/byok.md) for full setup instructions and a comparison table.

| Backend | `.env` setting | Cost | Privacy | Notes |
|---------|---------------|------|---------|-------|
| Anthropic API (default) | `LLM_BACKEND=anthropic` | Pay-per-token | Cloud | Set `ANTHROPIC_API_KEY` |
| Ollama (local GPU) | `LLM_BACKEND=ollama` | Free | Fully local | Set `OLLAMA_BASE_URL`, `OLLAMA_MODEL` |
| Gemini Free Tier | `LLM_BACKEND=gemini` | Free quota | Cloud | Set `GEMINI_API_KEY`; optionally `GEMINI_MODEL` (default: `gemini-2.0-flash`). **Experimental** — intent classifier does not use Gemini. |

---

## Prerequisites

- Python 3.11+
- Node.js 18+
- `claude` CLI installed (`npm install -g @anthropic-ai/claude-code`)
- A Meta WhatsApp Cloud API app with a webhook URL (ngrok or Cloudflare Tunnel for local setup)
- `sudo` access for systemd service installation

---

## License

MIT — see [LICENSE](LICENSE)
