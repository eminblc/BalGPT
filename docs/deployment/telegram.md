# Telegram Setup Guide

Set up the agent with Telegram in about 5 minutes. No business account needed.

---

## Step 1 — Create a Bot

1. Open Telegram → search for **@BotFather** → tap **Start**
2. Send `/newbot`
3. Enter a display name (e.g. `My Agent`)
4. Enter a username — must end with `bot` (e.g. `myagent_bot`)
5. BotFather sends you a token:

```
123456789:ABCDefGhIJKlmNoPQRsTUVwxyZ
```

Keep this token — you'll enter it in the wizard.

---

## Step 2 — Find Your Chat ID

Your Chat ID is your personal Telegram account number. The agent uses it to know who is the owner.

**Easiest method — @userinfobot:**
1. Open Telegram → search **@userinfobot** → tap **Start**
2. It instantly replies with your ID:
   ```
   Id: 123456789
   ```

**Alternative — getUpdates API:**
1. Send any message to your new bot (e.g. "hello")
2. Run:
   ```bash
   curl -s "https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates" | python3 -m json.tool
   ```
3. Find `result[0].message.chat.id` in the output

> **Note:** The install wizard tries to auto-detect your Chat ID via `getUpdates` after you enter the bot token. Just send a message to your bot first, then press Enter when prompted.

---

## Step 3 — Run the Wizard

```bash
bash install.sh --docker   # Docker
# or
sudo bash install.sh       # systemd
```

Select **Telegram** when asked for the messenger. The wizard will:
- Ask for your Bot Token (hidden input)
- Auto-detect your Chat ID from `getUpdates` — or let you type it manually
- Auto-generate the webhook secret (no input needed)

---

## Step 4 — Register the Webhook

Telegram needs a public HTTPS URL to deliver messages to your bot.

**If you used ngrok, Cloudflare Tunnel, or an external URL:** the wizard auto-registers the webhook for you.

**If you're on a VPS with a static IP/domain:** run this after the services start:

```bash
curl -s -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://yourdomain.com/telegram/webhook",
    "secret_token": "<TELEGRAM_WEBHOOK_SECRET from .env>",
    "allowed_updates": ["message", "callback_query"]
  }'
```

Expected response:
```json
{"ok": true, "result": true, "description": "Webhook was set"}
```

Verify:
```bash
curl -s "https://api.telegram.org/bot<TOKEN>/getWebhookInfo" | python3 -m json.tool
```

---

## Step 5 — Test

Send a message to your bot. You should get a response from the agent.

Check service health:
```bash
curl -s http://localhost:8010/health
curl -s http://localhost:8013/health
```

Check logs:
```bash
# Docker
docker compose logs -f 99-api

# systemd
journalctl -u personal-agent.service -f
```

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `MESSENGER_TYPE` | Set to `telegram` |
| `TELEGRAM_BOT_TOKEN` | Token from @BotFather |
| `TELEGRAM_CHAT_ID` | Your personal chat ID (from @userinfobot) |
| `TELEGRAM_WEBHOOK_SECRET` | Auto-generated; used to verify webhook authenticity |

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Bot doesn't respond | Check webhook is registered (`getWebhookInfo`), check service logs |
| `{"ok":false,"description":"Unauthorized"}` | Bot token is wrong |
| Chat ID mismatch — bot responds to others | Make sure `TELEGRAM_CHAT_ID` is your own ID, not the bot's ID |
| Webhook returns 403 | `TELEGRAM_WEBHOOK_SECRET` mismatch — re-register webhook with correct secret |
| ngrok URL changed after restart | Re-run `step_show_webhook_url` or re-register manually |

---

## Remove Webhook (Reset)

```bash
curl -s "https://api.telegram.org/bot<TOKEN>/deleteWebhook"
```
