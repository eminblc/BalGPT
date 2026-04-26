#!/usr/bin/env python3
"""
scripts/setup_wizard_messenger.py — Messenger-based setup wizard for install.sh.

Called by install.sh after collecting messenger credentials (Phase 1).
Conducts the remaining setup wizard (LLM, proxy, timezone, capabilities)
via Telegram inline keyboard buttons and text replies.

Environment variables (set by install.sh):
  WIZARD_MESSENGER  — "telegram"  (whatsapp not yet supported for interactive)
  WIZARD_TG_TOKEN   — Telegram bot token
  WIZARD_TG_CHAT_ID — Telegram chat ID (numeric)
  INSTALL_LANG      — "tr" or "en"  (default: "tr")

Output:
  JSON object on stdout on success.
  Status/error messages on stderr.
  Exit 0 on success, 1 on failure/timeout.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

LANG: str = os.environ.get("INSTALL_LANG", "tr")

# Temp directories for terminal secret IPC (set by install.sh monitoring loop)
_REQ_DIR: str = os.environ.get("WIZARD_REQ_DIR", "")
_ANS_DIR: str = os.environ.get("WIZARD_ANS_DIR", "")

# ── Localised strings ─────────────────────────────────────────────────────────

_STR: dict[str, dict[str, str]] = {
    "tr": {
        "setup_start": (
            "🚀 <b>Kurulum Sihirbazı</b>\n\n"
            "Messenger bağlantısı kuruldu ✓\n"
            "Kalan adımları buradan tamamlayın."
        ),
        "llm_q": "🤖 <b>AI Modeli</b>\nHangi yapay zeka modelini kullanmak istiyorsunuz?",
        "llm_anthropic": "Anthropic Claude (önerilen)",
        "llm_ollama": "Ollama (yerel, ücretsiz)",
        "llm_gemini": "Google Gemini",
        "anthropic_q": (
            "🔑 <b>Anthropic — Kimlik Doğrulama</b>\n\n"
            "Claude Pro/Max aboneliğiniz varsa <b>Claude Login</b> önerilir.\n"
            "Ücretli kullanım için API Anahtarı seçin."
        ),
        "anthropic_login": "Claude Login (önerilen)",
        "anthropic_apikey": "API Anahtarı (ücretli)",
        "anthropic_key_terminal": (
            "🔒 <b>Anthropic API Anahtarı — Terminal Gerekli</b>\n\n"
            "Bu bilgi güvenlik nedeniyle mesajlaşma üzerinden alınmaz.\n"
            "Kurulum terminaline geçin — API anahtarını orada gireceksiniz.\n\n"
            "Format: <code>sk-ant-api03-...</code>"
        ),
        "ollama_info": (
            "ℹ️ <b>Ollama</b>\n\n"
            "Ollama yerel olarak çalışıyor olmalıdır.\n"
            "Varsayılan: <code>http://localhost:11434</code>, model: <code>llama3</code>\n\n"
            "Devam ediliyor..."
        ),
        "gemini_key_terminal": (
            "🔒 <b>Google Gemini API Anahtarı — Terminal Gerekli</b>\n\n"
            "Bu bilgi güvenlik nedeniyle mesajlaşma üzerinden alınmaz.\n"
            "Kurulum terminaline geçin — API anahtarını orada gireceksiniz.\n\n"
            "Format: <code>AIza...</code>"
        ),
        "proxy_q": (
            "🌐 <b>Webhook Proxy</b>\n\n"
            "Sunucunuza nasıl erişilecek?\n"
            "<i>(WhatsApp/Telegram mesajlarınızın ulaşması için)</i>"
        ),
        "proxy_none": "Yok — Statik IP / yerel test",
        "proxy_ngrok": "ngrok — Ücretsiz statik domain",
        "proxy_cf": "Cloudflare Tunnel",
        "proxy_ext": "Harici URL — Kendi domainim",
        "ext_url_q": (
            "🌐 Public URL'nizi girin.\n"
            "<code>https://</code> ile başlamalı\n\n"
            "Örnek: <code>https://example.com</code>"
        ),
        "ngrok_token_q": (
            "🔑 <b>ngrok Auth Token</b>\n\n"
            "ngrok.com → Dashboard → Your Authtoken\n"
            "Anonim mod için <code>-</code> yazın."
        ),
        "ngrok_domain_q": (
            "🌐 <b>ngrok Static Domain</b>\n\n"
            "ngrok Dashboard → Domains\n"
            "Örnek: <code>abc.ngrok-free.app</code>\n"
            "Domain yoksa <code>-</code> yazın."
        ),
        "tz_q": "🕐 <b>Saat Dilimi</b>\nAPScheduler ve cron için kullanılacak saat dilimi:",
        "tz_ist": "🇹🇷 Istanbul (UTC+3)",
        "tz_lon": "🇬🇧 London (UTC+0/+1)",
        "tz_par": "🇫🇷 Paris (UTC+1/+2)",
        "tz_nyc": "🗽 New York (UTC-5/-4)",
        "tz_lax": "🌉 Los Angeles (UTC-8/-7)",
        "tz_tyo": "🗼 Tokyo (UTC+9)",
        "tz_utc": "🌍 UTC",
        "tz_other": "⌨️ Diğer (manuel gir)",
        "tz_other_q": (
            "IANA saat dilimi adı girin.\n"
            "Örnek: <code>America/Chicago</code>"
        ),
        "caps_q": "⚙️ <b>Yetenekler</b>\nHangi yetenek setini etkinleştirmek istiyorsunuz?",
        "caps_basic": "🔹 Temel (önerilen)",
        "caps_full": "🔷 Tam (masaüstü dahil)",
        "caps_custom": "🔧 Özel seçim",
        "caps_desktop": "🖥️ Masaüstü otomasyonu [BETA]",
        "caps_browser": "🌐 Tarayıcı otomasyonu (Playwright)",
        "caps_media": "📸 Medya mesajları (fotoğraf, ses)",
        "caps_shell": "💻 Terminal komutları (!terminal)",
        "caps_scheduler": "⏰ Zamanlayıcı / cron görevleri",
        "caps_pdf": "📄 PDF içe aktarma",
        "caps_intent": "🧠 Intent sınıflandırıcı (mesaj başına 1 ek API çağrısı)",
        "caps_yes": "✅ Evet",
        "caps_no": "❌ Hayır",
        "caps_basic_ok": (
            "✅ <b>Temel yetenekler</b> seçildi:\n"
            "Sohbet, takvim, planlama, medya, terminal, zamanlayıcı, PDF, intent"
        ),
        "caps_full_ok": (
            "✅ <b>Tüm yetenekler</b> seçildi:\n"
            "Temel + masaüstü otomasyonu + tarayıcı otomasyonu"
        ),
        "ngrok_token_terminal": (
            "🔒 <b>ngrok Auth Token — Terminal Gerekli</b>\n\n"
            "Bu bilgi güvenlik nedeniyle mesajlaşma üzerinden alınmaz.\n"
            "Kurulum terminaline geçin — token'ı orada gireceksiniz."
        ),
        "secret_received": "✅ Alındı. Devam ediliyor…",
        "done": (
            "✅ <b>Kurulum tamamlandı!</b>\n\n"
            "Tüm seçimler kaydedildi.\n"
            "Terminal kurulumu devam ediyor…"
        ),
        "timeout": "⏰ Bekleme süresi doldu. Kurulum terminal modunda devam edecek.",
    },
    "en": {
        "setup_start": (
            "🚀 <b>Setup Wizard</b>\n\n"
            "Messenger connected ✓\n"
            "Complete the remaining steps here."
        ),
        "llm_q": "🤖 <b>AI Model</b>\nWhich AI model do you want to use?",
        "llm_anthropic": "Anthropic Claude (recommended)",
        "llm_ollama": "Ollama (local, free)",
        "llm_gemini": "Google Gemini",
        "anthropic_q": (
            "🔑 <b>Anthropic — Authentication</b>\n\n"
            "If you have a Claude Pro/Max subscription, <b>Claude Login</b> is recommended.\n"
            "Choose API Key for pay-per-use."
        ),
        "anthropic_login": "Claude Login (recommended)",
        "anthropic_apikey": "API Key (pay-per-use)",
        "anthropic_key_terminal": (
            "🔒 <b>Anthropic API Key — Terminal Required</b>\n\n"
            "For security, API keys are not collected over messaging.\n"
            "Switch to your install terminal — enter the key there.\n\n"
            "Format: <code>sk-ant-api03-...</code>"
        ),
        "ollama_info": (
            "ℹ️ <b>Ollama</b>\n\n"
            "Ollama must be running locally.\n"
            "Default: <code>http://localhost:11434</code>, model: <code>llama3</code>\n\n"
            "Continuing..."
        ),
        "gemini_key_terminal": (
            "🔒 <b>Google Gemini API Key — Terminal Required</b>\n\n"
            "For security, API keys are not collected over messaging.\n"
            "Switch to your install terminal — enter the key there.\n\n"
            "Format: <code>AIza...</code>"
        ),
        "proxy_q": (
            "🌐 <b>Webhook Proxy</b>\n\n"
            "How will your server be accessible?\n"
            "<i>(Required for WhatsApp/Telegram to deliver messages)</i>"
        ),
        "proxy_none": "None — Static IP / local test",
        "proxy_ngrok": "ngrok — Free static domain",
        "proxy_cf": "Cloudflare Tunnel",
        "proxy_ext": "External URL — I have my own domain",
        "ext_url_q": (
            "🌐 Enter your public URL.\n"
            "Must start with <code>https://</code>\n\n"
            "Example: <code>https://example.com</code>"
        ),
        "ngrok_token_terminal": (
            "🔒 <b>ngrok Auth Token — Terminal Required</b>\n\n"
            "For security, tokens are not collected over messaging.\n"
            "Switch to your install terminal — enter the token there."
        ),
        "ngrok_domain_q": (
            "🌐 <b>ngrok Static Domain</b>\n\n"
            "ngrok Dashboard → Domains\n"
            "Example: <code>abc.ngrok-free.app</code>\n"
            "Type <code>-</code> if you have no domain."
        ),
        "tz_q": "🕐 <b>Timezone</b>\nTimezone used by APScheduler and cron:",
        "tz_ist": "🇹🇷 Istanbul (UTC+3)",
        "tz_lon": "🇬🇧 London (UTC+0/+1)",
        "tz_par": "🇫🇷 Paris (UTC+1/+2)",
        "tz_nyc": "🗽 New York (UTC-5/-4)",
        "tz_lax": "🌉 Los Angeles (UTC-8/-7)",
        "tz_tyo": "🗼 Tokyo (UTC+9)",
        "tz_utc": "🌍 UTC",
        "tz_other": "⌨️ Other (type manually)",
        "tz_other_q": (
            "Enter an IANA timezone name.\n"
            "Example: <code>America/Chicago</code>"
        ),
        "caps_q": "⚙️ <b>Capabilities</b>\nWhich capability set do you want to enable?",
        "caps_basic": "🔹 Basic (recommended)",
        "caps_full": "🔷 Full (incl. desktop)",
        "caps_custom": "🔧 Custom selection",
        "caps_desktop": "🖥️ Desktop automation [BETA]",
        "caps_browser": "🌐 Browser automation (Playwright)",
        "caps_media": "📸 Media messages (photos, audio)",
        "caps_shell": "💻 Terminal commands (!terminal)",
        "caps_scheduler": "⏰ Scheduler / cron tasks",
        "caps_pdf": "📄 PDF import",
        "caps_intent": "🧠 Intent classifier (1 extra API call per message)",
        "caps_yes": "✅ Yes",
        "caps_no": "❌ No",
        "caps_basic_ok": (
            "✅ <b>Basic capabilities</b> selected:\n"
            "Chat, calendar, planning, media, terminal, scheduler, PDF, intent"
        ),
        "caps_full_ok": (
            "✅ <b>All capabilities</b> selected:\n"
            "Basic + desktop automation + browser automation"
        ),
        "ngrok_token_q": (
            "🔑 <b>ngrok Auth Token</b>\n\n"
            "ngrok.com → Dashboard → Your Authtoken\n"
            "Type <code>-</code> for anonymous mode."
        ),
        "secret_received": "✅ Received. Continuing…",
        "done": (
            "✅ <b>Setup complete!</b>\n\n"
            "All choices saved.\n"
            "Terminal setup continuing…"
        ),
        "timeout": "⏰ Timeout. Setup will continue in terminal mode.",
    },
}


def t(key: str) -> str:
    lang = LANG if LANG in _STR else "tr"
    return _STR[lang].get(key, _STR["tr"].get(key, key))


def _request_terminal_secret(key: str) -> str:
    """Signal the install.sh monitoring loop to prompt for a secret in the terminal.

    Creates a sentinel file in REQ_DIR; polls ANS_DIR for the answer written by the shell.
    Falls back to empty string if IPC dirs are not set or timeout (5 min) expires.
    """
    if not _REQ_DIR or not _ANS_DIR:
        return ""
    req_path = os.path.join(_REQ_DIR, key)
    ans_path = os.path.join(_ANS_DIR, key)
    try:
        open(req_path, "w").close()  # signal: terminal input needed for this key
    except OSError as exc:
        print(f"[warn] could not write req file: {exc}", file=sys.stderr)
        return ""
    deadline = time.time() + 300  # 5-minute window for user to type
    while time.time() < deadline:
        if os.path.exists(ans_path):
            try:
                with open(ans_path) as f:
                    val = f.read().strip()
                os.remove(ans_path)
                return val
            except OSError:
                pass
        time.sleep(0.3)
    print(f"[warn] terminal secret '{key}' timed out", file=sys.stderr)
    return ""


# ── Capability presets ────────────────────────────────────────────────────────

_ALWAYS_ON = [
    "fs", "network", "service_mgmt", "calendar", "project_wizard",
    "screenshot", "conv_history", "plans", "wizard_llm_scaffold",
]

_BASIC_CAPS = _ALWAYS_ON + [
    "shell", "media", "scheduler", "pdf_import", "intent_classifier",
]

_FULL_CAPS = _BASIC_CAPS + ["desktop", "browser"]


def _caps_str(keys: list[str]) -> str:
    return " ".join(f'"{k}"' for k in keys)


# ── Telegram Bot helper ───────────────────────────────────────────────────────

class TelegramBot:
    def __init__(self, token: str, chat_id: str) -> None:
        self.token = token
        self.chat_id = int(chat_id)
        self.offset = 0
        self._base = f"https://api.telegram.org/bot{token}"

    # ── low-level ────────────────────────────────────────────────────────────

    def _post(self, method: str, body: dict, timeout: int = 15) -> dict:
        url = f"{self._base}/{method}"
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())

    def _get_updates(self, poll_timeout: int) -> list[dict]:
        body = {
            "offset": self.offset,
            "limit": 10,
            "timeout": poll_timeout,
        }
        try:
            result = self._post("getUpdates", body, timeout=poll_timeout + 8)
            return result.get("result", [])
        except Exception as exc:
            print(f"[warn] getUpdates: {exc}", file=sys.stderr)
            time.sleep(2)
            return []

    # ── public ───────────────────────────────────────────────────────────────

    def flush(self) -> None:
        """Discard all pending updates so only new ones are processed."""
        try:
            result = self._post("getUpdates", {"limit": 100, "timeout": 1}, timeout=10)
            updates = result.get("result", [])
            if updates:
                self.offset = updates[-1]["update_id"] + 1
        except Exception:
            pass

    def send(self, text: str, buttons: list[list[tuple[str, str]]] | None = None) -> int:
        """Send a message. *buttons* is a list of rows; each row is [(label, callback_data), …]."""
        body: dict = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
        }
        if buttons:
            body["reply_markup"] = {
                "inline_keyboard": [
                    [{"text": lbl, "callback_data": dat} for lbl, dat in row]
                    for row in buttons
                ]
            }
        try:
            result = self._post("sendMessage", body)
            return result.get("result", {}).get("message_id", 0)
        except Exception as exc:
            print(f"[warn] sendMessage: {exc}", file=sys.stderr)
            return 0

    def _answer_cb(self, cb_id: str) -> None:
        try:
            self._post("answerCallbackQuery", {"callback_query_id": cb_id}, timeout=8)
        except Exception:
            pass

    def wait(self, deadline: float) -> tuple[str | None, str | None]:
        """
        Block until a callback_query or text message arrives, or *deadline* passes.
        Returns (kind, value): kind is "cb" or "text", value is the data/text string.
        Returns (None, None) on timeout.
        """
        while time.time() < deadline:
            poll_secs = min(30, max(1, int(deadline - time.time())))
            for upd in self._get_updates(poll_secs):
                self.offset = upd["update_id"] + 1
                cb = upd.get("callback_query")
                msg = upd.get("message")
                if cb:
                    self._answer_cb(cb["id"])
                    return ("cb", cb["data"])
                if msg:
                    txt = msg.get("text", "").strip()
                    if txt:
                        return ("text", txt)
        return (None, None)

    # ── wizard helpers ───────────────────────────────────────────────────────

    def ask_buttons(
        self,
        question: str,
        options: list[tuple[str, str]],
        timeout: int = 300,
    ) -> str | None:
        """Send *question* with inline keyboard; return the chosen callback_data."""
        rows: list[list[tuple[str, str]]] = []
        for i in range(0, len(options), 2):
            rows.append(options[i : i + 2])
        self.send(question, rows)

        deadline = time.time() + timeout
        while time.time() < deadline:
            poll_secs = min(30, max(1, int(deadline - time.time())))
            for upd in self._get_updates(poll_secs):
                self.offset = upd["update_id"] + 1
                cb = upd.get("callback_query")
                if cb:
                    self._answer_cb(cb["id"])
                    return cb["data"]
                # ignore plain text while waiting for a button press
        return None

    def ask_text(self, question: str, timeout: int = 300) -> str | None:
        """Send *question* and wait for a text reply. Returns "" for "-", None on timeout."""
        self.send(question)

        deadline = time.time() + timeout
        while time.time() < deadline:
            poll_secs = min(30, max(1, int(deadline - time.time())))
            for upd in self._get_updates(poll_secs):
                self.offset = upd["update_id"] + 1
                msg = upd.get("message")
                if msg:
                    txt = msg.get("text", "").strip()
                    if txt:
                        return "" if txt == "-" else txt
                # ignore callback_query while waiting for text
        return None


# ── Wizard logic ──────────────────────────────────────────────────────────────

def _bail(bot: TelegramBot, key: str = "timeout") -> None:
    bot.send(t(key))


def run_wizard(token: str, chat_id: str) -> dict | None:
    bot = TelegramBot(token, chat_id)
    bot.flush()

    result: dict = {}

    bot.send(t("setup_start"))

    # ── LLM ──────────────────────────────────────────────────────────────────
    llm = bot.ask_buttons(t("llm_q"), [
        (t("llm_anthropic"), "anthropic"),
        (t("llm_ollama"),    "ollama"),
        (t("llm_gemini"),    "gemini"),
    ])
    if llm is None:
        _bail(bot)
        return None
    result["llm"] = llm

    if llm == "anthropic":
        method = bot.ask_buttons(t("anthropic_q"), [
            (t("anthropic_login"),  "login"),
            (t("anthropic_apikey"), "apikey"),
        ])
        if method is None:
            _bail(bot)
            return None
        result["anthropic_method"] = method
        if method == "apikey":
            bot.send(t("anthropic_key_terminal"))
            key = _request_terminal_secret("anthropic_key")
            if key:
                bot.send(t("secret_received"))
            result["anthropic_key"] = key
        else:
            result["anthropic_key"] = ""

    elif llm == "ollama":
        bot.send(t("ollama_info"))
        result["ollama_url"]   = "http://localhost:11434"
        result["ollama_model"] = "llama3"

    elif llm == "gemini":
        bot.send(t("gemini_key_terminal"))
        key = _request_terminal_secret("gemini_key")
        if key:
            bot.send(t("secret_received"))
        result["gemini_key"]   = key
        result["gemini_model"] = "gemini-2.0-flash"

    # ── Proxy ─────────────────────────────────────────────────────────────────
    proxy = bot.ask_buttons(t("proxy_q"), [
        (t("proxy_none"), "none"),
        (t("proxy_ngrok"), "ngrok"),
        (t("proxy_cf"),   "cloudflared"),
        (t("proxy_ext"),  "external"),
    ])
    if proxy is None:
        _bail(bot)
        return None
    result["proxy"] = proxy

    if proxy == "external":
        url = bot.ask_text(t("ext_url_q"))
        if url is None:
            _bail(bot)
            return None
        result["public_url"] = url
        result["ngrok_token"]  = ""
        result["ngrok_domain"] = ""

    elif proxy == "ngrok":
        result["public_url"] = ""
        bot.send(t("ngrok_token_terminal"))
        ngrok_tok = _request_terminal_secret("ngrok_token")
        if ngrok_tok:
            bot.send(t("secret_received"))
        result["ngrok_token"] = ngrok_tok

        ngrok_dom = bot.ask_text(t("ngrok_domain_q"))
        if ngrok_dom is None:
            _bail(bot)
            return None
        result["ngrok_domain"] = ngrok_dom

    else:
        result["public_url"]   = ""
        result["ngrok_token"]  = ""
        result["ngrok_domain"] = ""

    # ── Timezone ──────────────────────────────────────────────────────────────
    tz = bot.ask_buttons(t("tz_q"), [
        (t("tz_ist"), "Europe/Istanbul"),
        (t("tz_lon"), "Europe/London"),
        (t("tz_par"), "Europe/Paris"),
        (t("tz_nyc"), "America/New_York"),
        (t("tz_lax"), "America/Los_Angeles"),
        (t("tz_tyo"), "Asia/Tokyo"),
        (t("tz_utc"), "UTC"),
        (t("tz_other"), "other"),
    ])
    if tz is None:
        _bail(bot)
        return None

    if tz == "other":
        tz_val = bot.ask_text(t("tz_other_q")) or "Europe/Istanbul"
    else:
        tz_val = tz
    result["timezone"] = tz_val

    # ── Capabilities ──────────────────────────────────────────────────────────
    caps_mode = bot.ask_buttons(t("caps_q"), [
        (t("caps_basic"),  "basic"),
        (t("caps_full"),   "full"),
        (t("caps_custom"), "custom"),
    ])
    if caps_mode is None:
        _bail(bot)
        return None

    if caps_mode == "basic":
        bot.send(t("caps_basic_ok"))
        result["caps_selected"] = _caps_str(_BASIC_CAPS)

    elif caps_mode == "full":
        bot.send(t("caps_full_ok"))
        result["caps_selected"] = _caps_str(_FULL_CAPS)

    else:  # custom
        custom_keys = list(_ALWAYS_ON)

        def _ask_cap(label_key: str, default: bool = True) -> bool:
            choice = bot.ask_buttons(
                f"⚙️ {t(label_key)}?",
                [(t("caps_yes"), "yes"), (t("caps_no"), "no")],
            )
            if choice is None:
                return default
            return choice == "yes"

        if _ask_cap("caps_shell"):
            custom_keys.append("shell")
        if _ask_cap("caps_media"):
            custom_keys.append("media")
        if _ask_cap("caps_scheduler"):
            custom_keys.append("scheduler")
        if _ask_cap("caps_pdf"):
            custom_keys.append("pdf_import")
        if _ask_cap("caps_intent"):
            custom_keys.append("intent_classifier")
        if _ask_cap("caps_browser", default=False):
            custom_keys.append("browser")
        if _ask_cap("caps_desktop", default=False):
            custom_keys.append("desktop")

        result["caps_selected"] = _caps_str(custom_keys)

    # ── Done ─────────────────────────────────────────────────────────────────
    bot.send(t("done"))
    return result


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    messenger = os.environ.get("WIZARD_MESSENGER", "")

    if messenger != "telegram":
        print(
            f"Messenger '{messenger}' does not support interactive wizard (only telegram).",
            file=sys.stderr,
        )
        sys.exit(1)

    token   = os.environ.get("WIZARD_TG_TOKEN", "").strip()
    chat_id = os.environ.get("WIZARD_TG_CHAT_ID", "").strip()

    if not token or not chat_id:
        print("WIZARD_TG_TOKEN or WIZARD_TG_CHAT_ID not set.", file=sys.stderr)
        sys.exit(1)

    try:
        result = run_wizard(token, chat_id)
    except Exception as exc:
        print(f"[error] Wizard failed: {exc}", file=sys.stderr)
        sys.exit(1)

    if result is None:
        sys.exit(1)

    print(json.dumps(result))


if __name__ == "__main__":
    main()
