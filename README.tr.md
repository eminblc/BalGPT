# Kişisel AI Ajan

WhatsApp veya Telegram üzerinden kontrol edilen kendi kendine barındırılan kişisel bir AI ajan. Mesaj gönder, işleri yaptır — proje oluştur, görevleri yönet, takvim hatırlatıcıları kur, shell komutları çalıştır, PDF içe aktar ve doğrudan telefonundan Claude Code ile sohbet et. Her şey kendi makinende çalışır; bulut servisleri yapılandırmadıkça veriler dışarı çıkmaz.

---

## Mimari

| Servis | Port | Açıklama |
|--------|------|----------|
| FastAPI (Uvicorn) | 8010 | Webhook alıcı, guard zinciri, komut yönlendirme |
| Claude Code Bridge | 8013 | Claude Code CLI'yi sarar, oturumları yönetir |

```
WhatsApp / Telegram → POST /whatsapp/webhook  veya  POST /telegram/webhook
                        └─ dedup → blacklist → permission → rate limit → capability
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
# .env dosyasını doldur (aşağıdaki Zorunlu Ortam Değişkenleri tablosuna bak)
docker compose up -d
```

Compose dosyası `./data` ve `./outputs/logs` dizinlerini volume olarak bağlar; tüm veriler konteyner dışında kalıcı olarak saklanır.

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

Yeniden başlat:

```bash
docker compose restart
```

### Seçenek B — systemd (yalnızca Linux)

```bash
git clone https://github.com/kullanici-adin/99-root.git
cd 99-root
cp scripts/backend/.env.example scripts/backend/.env
# .env dosyasını doldur (aşağıdaki Zorunlu Ortam Değişkenleri tablosuna bak)
sudo bash install.sh
```

`install.sh` etkileşimli bir sihirbaz çalıştırır (messenger, LLM backend, saat dilimi, yetenekler), Python sanal ortamını oluşturur, yalnızca etkin yeteneklerin gerektirdiği paketleri kurar (pip-compile + pip-sync), Node bağımlılıklarını kurar, systemd unit dosyalarını oluşturur ve servisleri etkinleştirir.

> `sudo` ile çalıştırılırsa systemd unit'leri otomatik olarak kurulur ve etkinleştirilir. `sudo` olmadan çalıştırılırsa sihirbaz ve bağımlılık kurulumu tamamlanır, ardından manuel `systemctl` komutları ekrana yazdırılır.

Servisleri kontrol et:

```bash
sudo systemctl status personal-agent.service personal-agent-bridge.service
journalctl -u personal-agent.service -f
```

Diğer kurulum seçenekleri:

```bash
bash install.sh --no-systemd             # sadece bağımlılıkları kur, systemd kurma
bash install.sh --pm2                    # systemd yerine PM2 ile başlat
bash install.sh --reconfigure-capabilities  # yetenek sihirbazını tekrar çalıştır ve paketleri güncelle
```

> **Not:** `.env` dosyasında `DESKTOP_ENABLED`, `BROWSER_ENABLED` veya herhangi bir `RESTRICT_*` flag'ini elle değiştirdikten sonra `bash install.sh --reconfigure-capabilities` çalıştır; aksi hâlde gerekli Python paketleri kurulmaz/kaldırılmaz.

### Seçenek C — PM2 (Linux / macOS / Windows)

Systemd yoksa PM2 kullan (macOS, Windows WSL, root'suz VPS).

```bash
git clone https://github.com/kullanici-adin/99-root.git
cd 99-root
cp scripts/backend/.env.example scripts/backend/.env
# .env dosyasını doldur (aşağıdaki Zorunlu Ortam Değişkenleri tablosuna bak)
bash install.sh --pm2
```

Durum ve log:

```bash
pm2 status
pm2 logs 99-api
pm2 logs 99-bridge
```

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

Telegram, Ollama, Gemini, saat dilimi ve yetenek flag'leri dahil tüm seçenekler için bkz. [`scripts/backend/.env.example`](scripts/backend/.env.example).

---

## Komutlar

| Komut | Açıklama | Yetki |
|-------|----------|-------|
| `!help` | Tüm komutları listele | Owner |
| `!history [N]` | Son N mesajı veya oturum özetlerini göster | Owner |
| `!project [id]` | Aktif proje bağlamını ayarla / göster | Owner |
| `!root-project [ad]` | Root ajana proje bağlamı ata | Owner |
| `!root-exit` | Root proje bağlamından çık | Owner |
| `!root-reset` | Claude Code oturumunu sıfırla | Owner |
| `!root-check` | Bridge durumunu göster (aktif istek mi yoksa boşta mı) | Owner |
| `!root-log` | root_actions.log'un son 5 girişini göster | Owner |
| `!schedule` | Zamanlanmış görevleri listele / oluştur / durdur | Owner |
| `!terminal [komut]` | Shell komutu çalıştır ve çıktıyı gönder (tehlikeli komutlar admin TOTP gerektirir) | Owner |
| `!model [ad]` | Çalışma zamanında LLM modelini değiştir (yeniden başlatmaya kadar geçerli) | Owner |
| `!tokens [24h\|7d\|30d]` | LLM token kullanım istatistiklerini göster | Owner |
| `!lang <tr\|en>` | Arayüz dilini değiştir | Owner |
| `!timezone [IANA]` | Aktif saat dilimini göster veya değiştir (APScheduler yeniden yapılandırılır) | Owner |
| `!cancel` | Aktif TOTP akışını, bekleyen işlemi veya Bridge sorgusunu iptal et | Owner |
| `!lock` | Uygulamayı kilitle (açmak için TOTP gerekir) | Owner TOTP |
| `!unlock` | Uygulamanın kilidini aç | Owner TOTP |
| `!beta-exit` | Proje beta modundan çık | Owner |
| `!project-delete` | Projeyi veritabanından sil | Math + Admin TOTP |
| `!restart` | Her iki servisi yeniden başlat | Math + Admin TOTP |
| `!shutdown` | FastAPI servisini durdur | Math + Admin TOTP |

Komut olmayan mesajlar serbest konuşma için Claude Code'a iletilir.

Yetenek flag'leri, sistem gereksinimleri ve dahili API endpoint'leri için bkz. [docs/skills.md](docs/skills.md).

---

## Messenger Seçimi

| Messenger | `.env` ayarı | Notlar |
|-----------|-------------|--------|
| WhatsApp (varsayılan) | `MESSENGER_TYPE=whatsapp` | Meta Cloud API uygulaması ve webhook URL'i gerektirir |
| Telegram | `MESSENGER_TYPE=telegram` | `TELEGRAM_BOT_TOKEN` ve `TELEGRAM_CHAT_ID` ayarla — bkz. [docs/deployment/telegram.md](docs/deployment/telegram.md) |
| CLI (yerel test) | `MESSENGER_TYPE=cli` | Stdout'a yazar; hesap gerekmez |

---

## LLM Backend Seçimi

| Backend | `.env` ayarı | Maliyet | Gizlilik | Notlar |
|---------|-------------|---------|----------|--------|
| Anthropic (varsayılan) | `LLM_BACKEND=anthropic` | Kullanım başına ücret | Bulut | `ANTHROPIC_API_KEY` gerekli. Birincil, test edilmiş backend. |
| Ollama (yerel) | `LLM_BACKEND=ollama` | Ücretsiz | Tamamen yerel | `OLLAMA_BASE_URL` ve `OLLAMA_MODEL` ayarla. Daha az test edildi — temel sohbet çalışır; karmaşık araç kullanımı güvenilmez olabilir. |
| Gemini | `LLM_BACKEND=gemini` | Ücretsiz kota | Bulut | `GEMINI_API_KEY` gerekli; `GEMINI_MODEL` opsiyonel (varsayılan: `gemini-2.0-flash`). Daha az test edildi — temel sohbet çalışır; uç durumlar farklı davranabilir. |

> `INTENT_CLASSIFIER_MODEL` ayarı yalnızca Anthropic backend için geçerlidir. Ollama veya Gemini kullanılırken intent sınıflandırıcı ilgili backend'in varsayılan modelini kullanır.

Ayrıntılar için bkz. [docs/deployment/byok.md](docs/deployment/byok.md).

---

## Ön Koşullar

- Python 3.11+
- Node.js 18+
- `claude` CLI kurulu ve kimliği doğrulanmış (`npm install -g @anthropic-ai/claude-code`)
- Webhook URL'i olan bir Meta WhatsApp Cloud API uygulaması (yerel kurulum için ngrok veya Cloudflare Tunnel) **veya** bir Telegram bot token'ı
- Systemd servis kurulumu için `sudo` erişimi

---

## Lisans

MIT — bkz. [LICENSE](LICENSE)
