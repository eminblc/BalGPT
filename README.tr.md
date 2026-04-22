# Kişisel AI Ajan

WhatsApp üzerinden kontrol edilen kendi kendine barındırılan kişisel bir AI ajan. Mesaj gönder, işleri yaptır — proje oluştur, görevleri yönet, takvim hatırlatıcıları kur, PDF içe aktar ve doğrudan telefonundan Claude Code ile sohbet et. Her şey kendi makinende çalışır; bulut servisleri yapılandırmadıkça veriler dışarı çıkmaz.

---

## Mimari

| Servis | Port | Açıklama |
|--------|------|----------|
| FastAPI (Uvicorn) | 8010 | Webhook alıcı, guard zinciri, komut yönlendirme |
| Claude Code Bridge | 8013 | Claude Code CLI'yi sarar, oturumları yönetir |

```
WhatsApp → POST /whatsapp/webhook
              └─ dedup → blacklist → rate limit → permission
                    └─ "main"    → Claude Code Bridge → Claude Code CLI
                    └─ "proje"   → Projenin kendi FastAPI'si (beta modu)
```

---

## Hızlı Başlangıç

### Seçenek A — Docker (önerilen, her işletim sisteminde çalışır)

```bash
git clone https://github.com/kullanici-adin/99-root.git
cd 99-root
cp scripts/backend/.env.example scripts/backend/.env
# .env dosyasını doldur (aşağıdaki tabloya bak)
docker compose up -d
```

Servis sağlığını kontrol et:

```bash
docker compose ps
curl -s http://localhost:8010/health
curl -s http://localhost:8013/health
```

Logları izle:

```bash
docker compose logs -f 99-api
docker compose logs -f 99-bridge
```

### Seçenek B — systemd (yalnızca Linux)

```bash
git clone https://github.com/kullanici-adin/99-root.git
cd 99-root
cp scripts/backend/.env.example scripts/backend/.env
# .env dosyasını doldur (aşağıdaki tabloya bak)
sudo ./install.sh
```

`install.sh` Python sanal ortamını oluşturur, Node bağımlılıklarını kurar, systemd unit dosyalarını oluşturur ve servisleri etkinleştirir. Tamamlandıktan sonra:

```bash
sudo systemctl status personal-agent.service personal-agent-bridge.service
```

### Seçenek C — PM2 (Linux / macOS / Windows)

Systemd yoksa PM2 kullan (macOS, Windows WSL, root'suz VPS).

```bash
git clone https://github.com/kullanici-adin/99-root.git
cd 99-root
cp scripts/backend/.env.example scripts/backend/.env
# .env dosyasını doldur (aşağıdaki tabloya bak)
./install.sh --pm2
```

Durum ve log:

```bash
pm2 status
pm2 logs 99-api
pm2 logs 99-bridge
```

---

## LLM Backend Seçimi

Üç LLM backend desteklenmektedir. Ayrıntılar için bkz. [docs/deployment/byok.md](docs/deployment/byok.md).

| Backend | `.env` ayarı | Maliyet | Gizlilik | Notlar |
|---------|-------------|---------|----------|--------|
| Anthropic API (varsayılan) | `LLM_BACKEND=anthropic` | Kullanım başına ücret | Bulut | `ANTHROPIC_API_KEY` gerekli |
| Ollama (yerel GPU) | `LLM_BACKEND=ollama` | Ücretsiz | Tamamen yerel | `OLLAMA_BASE_URL`, `OLLAMA_MODEL` ayarla |
| Gemini Free Tier | `LLM_BACKEND=gemini` | Ücretsiz kota | Bulut | `GEMINI_API_KEY` gerekli; `GEMINI_MODEL` opsiyonel (varsayılan: `gemini-2.0-flash`). **Deneysel** — intent sınıflandırıcı Gemini kullanmaz. |

---

## Zorunlu Ortam Değişkenleri

| Değişken | Açıklama |
|----------|----------|
| `WHATSAPP_ACCESS_TOKEN` | Meta WhatsApp Cloud API erişim tokeni |
| `WHATSAPP_PHONE_NUMBER_ID` | Meta Developer'dan WhatsApp telefon numarası ID'si |
| `WHATSAPP_APP_SECRET` | Webhook HMAC doğrulaması için uygulama sırrı |
| `WHATSAPP_VERIFY_TOKEN` | Webhook doğrulaması için kendin belirlediğin string |
| `WHATSAPP_OWNER` | Ülke koduyla WhatsApp numaran (`+90...`) |
| `ANTHROPIC_API_KEY` | Anthropic API anahtarı (`sk-ant-...`) |
| `API_KEY` | `/agent/*` endpoint'leri için dahili API anahtarı |
| `TOTP_SECRET` | Base32 TOTP sırrı — `python -c "import pyotp; print(pyotp.random_base32())"` |
| `TOTP_SECRET_ADMIN` | Yıkıcı komutlar için ayrı TOTP (`!restart`, `!shutdown`) |

Tüm seçenekler için bkz. [`scripts/backend/.env.example`](scripts/backend/.env.example).

---

## WhatsApp Komutları

| Komut | Açıklama | Yetki |
|-------|----------|-------|
| `!help` | Tüm komutları listele | Owner |
| `!history [N]` | Son N mesajı veya oturum özetlerini göster | Owner |
| `!project [id]` | Aktif proje bağlamını ayarla | Owner |
| `!schedule` | Cron job'ları listele / oluştur / durdur | Owner |
| `!root-reset` | Claude Code oturumunu sıfırla | Owner |
| `!restart` | Her iki servisi systemd ile yeniden başlat | Admin TOTP |
| `!shutdown` | FastAPI servisini durdur | Admin TOTP |
| `!beta-exit` | Proje beta modundan çık | Owner |
| `!lang <tr\|en>` | Arayüz dilini değiştir | Owner |

Komut olmayan mesajlar serbest konuşma için Claude Code'a iletilir.

---

## Ön Koşullar

- Python 3.11+
- Node.js 18+
- `claude` CLI kurulu (`npm install -g @anthropic-ai/claude-code`)
- Webhook URL'i olan bir Meta WhatsApp Cloud API uygulaması (yerel kurulum için ngrok veya Cloudflare Tunnel)
- Systemd servis kurulumu için `sudo` erişimi

---

## Lisans

MIT — bkz. [LICENSE](LICENSE)
