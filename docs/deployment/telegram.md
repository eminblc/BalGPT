# Telegram Kurulum Kılavuzu

Bu kılavuz ajanı WhatsApp yerine Telegram üzerinden çalıştırmak için gereken adımları açıklar.

---

## Mevcut Durum

| Özellik | Durum |
|---------|-------|
| Giden mesajlar (`send_text`, `send_buttons`, `send_list`) | ✅ Hazır |
| Gelen mesajlar (kullanıcıdan bot'a) | ❌ Eksik — Telegram webhook router yazılmadı |

**Şu an `MESSENGER_TYPE=telegram` yapılandırması yalnızca ajanın göndereceği mesajları Telegram üzerinden iletir.** Kullanıcıdan gelen mesajları almak için `routers/telegram_router.py` ve `main.py`'ye router kaydı eklenmesi gerekiyor (bkz. [Eksik Parça](#eksik-parça)).

---

## Adım 1 — Bot Oluştur

1. Telegram'da [@BotFather](https://t.me/BotFather) ile sohbet başlat
2. `/newbot` komutunu gönder
3. Bot adı ve kullanıcı adı gir (kullanıcı adı `bot` ile bitmeli, ör. `benimajan_bot`)
4. BotFather'ın verdiği token'ı kopyala:
   ```
   123456789:ABCDefGhIJKlmNoPQRsTUVwxyZ
   ```

---

## Adım 2 — Chat ID'ni Bul

Bot'un mesaj göndereceği hedef chat_id'yi öğrenmek için:

```bash
# Bot token'ını kullanarak getUpdates çağır
# (önce bota herhangi bir mesaj gönder)
curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates" | python3 -m json.tool
```

Yanıt içindeki `result[0].message.chat.id` değeri senin `chat_id`'n.

Alternatif: [@userinfobot](https://t.me/userinfobot) veya [@RawDataBot](https://t.me/RawDataBot) ile chat_id'ni öğren.

---

## Adım 3 — `.env` Ayarları

```env
MESSENGER_TYPE=telegram
TELEGRAM_BOT_TOKEN=123456789:ABCDefGhIJKlmNoPQRsTUVwxyZ
TELEGRAM_CHAT_ID=123456789
```

`TELEGRAM_CHAT_ID`, ajanın bildirim göndereceği varsayılan hedef (owner chat_id'si).

---

## Adım 4 — Webhook URL Ayarla

Telegram'a gelen mesajları iletmek için bot'un webhook URL'sini kaydetmesi gerekir. Webhook endpoint'i hazır olduğunda (bkz. [Eksik Parça](#eksik-parça)) aşağıdaki komutla kaydet:

```bash
curl -s -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://yourdomain.com/telegram/webhook", "allowed_updates": ["message", "callback_query"]}'
```

Başarılı yanıt:
```json
{"ok": true, "result": true, "description": "Webhook was set"}
```

Webhook'u kaldırmak için:
```bash
curl -s "https://api.telegram.org/bot<TOKEN>/deleteWebhook"
```

---

## Adım 5 — Servisi Yeniden Başlat

```bash
sudo systemctl restart personal-agent.service
```

Kontrol:
```bash
curl -s http://localhost:8010/health | python3 -m json.tool
```

---

## WhatsApp ile Farklar

| Özellik | WhatsApp | Telegram |
|---------|----------|----------|
| Buton tipi | Reply button (max 3) | InlineKeyboard |
| Liste menüsü | Native `send_list` | Markdown düz metin (fallback) |
| Mesaj limiti | 4096 karakter | 4096 karakter |
| Webhook doğrulama | HMAC-SHA256 imza | Telegram'ın kendi mekanizması |
| Medya mesajları | `_media_handlers.py` ile işleniyor | Henüz desteklenmiyor |

---

## Eksik Parça

Telegram'dan **gelen** mesajları (kullanıcı → bot) işlemek için iki adım gerekiyor:

### 1. `routers/telegram_router.py` oluştur

`whatsapp_router.py` modelinde, gelen Telegram güncellemelerini (`message` ve `callback_query`) alıp mevcut guard zincirine yönlendiren bir router. Temel yapı:

```python
# POST /telegram/webhook
# Payload: Telegram Update objesi
# sender: str(update["message"]["from"]["id"])
# text:   update["message"]["text"]
```

Guard zinciri (`dedup → blacklist → rate_limit → permission`) değişmeden kullanılabilir; sadece payload parse etme ve `sender` çıkarma değişir.

### 2. `main.py`'ye router kaydı ekle

```python
from backend.routers.telegram_router import router as telegram_router
app.include_router(telegram_router)
```

Bu iki adım tamamlanana kadar Telegram yalnızca **çıkış kanalı** olarak çalışır; kullanıcıdan gelen mesajlar işlenmez.
