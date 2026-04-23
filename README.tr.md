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

### Seçenek A — Docker ✅ Önerilen

> Çoğu kullanıcı için en iyi seçenek. Her işletim sisteminde çalışır, host'ta Python/Node gerekmez.

```bash
git clone https://github.com/kullanici-adin/99-root.git
cd 99-root
bash install.sh --docker
```

Sihirbaz hangi messenger, LLM backend, webhook proxy, kimlik bilgileri ve yeteneklerin istediğini sorar. Ardından `.env` dosyasını yazar, `CAPABILITIES` build-arg içeren bir `docker-compose.override.yml` oluşturur, yalnızca seçili paketlerin kurulu olduğu image'ı build eder ve container'ları başlatır.

Güvenlik anahtarları (`API_KEY`, `TOTP_SECRET`, `TOTP_SECRET_ADMIN`) ve webhook token'ları sihirbaz tarafından **otomatik üretilir** — elle giriş gerekmez. TOTP QR kodları kurulum sonunda ekrana gösterilir; Google Authenticator'a okutabilirsin.

Compose dosyası `./data` ve `./outputs/logs` dizinlerini volume olarak bağlar; tüm veriler container dışında kalıcı olarak saklanır.

Yetenekleri yeniden yapılandırmak ve image'ı rebuild etmek için:

```bash
bash install.sh --docker --reconfigure-capabilities
```

> **Windows kullanıcıları:** PowerShell'de `bash` komutu yoktur — `bash install.sh --docker` çalışmaz. Şu seçeneklerden birini kullanmanız gerekir:
> - **Git Bash** (önerilen): [Git for Windows](https://git-scm.com/download/win) kur, Git Bash'i aç, komutu çalıştır.
> - **WSL**: PowerShell'de `wsl --install -d Ubuntu` çalıştır, Ubuntu terminalini aç, komutu çalıştır.
> - **Sihirbaz olmadan**: `.env.example`'ı `.env`'e kopyala, elle doldur, ardından PowerShell'den `docker compose up -d --build` çalıştır. Tüm yetenekler kurulur (daha büyük image).

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

> Yerel performans ve otomatik başlatma istediğiniz Linux sunucu veya Raspberry Pi için en iyi seçenek.

```bash
git clone https://github.com/kullanici-adin/99-root.git
cd 99-root
sudo bash install.sh
```

`install.sh` etkileşimli bir sihirbaz çalıştırır (messenger, LLM backend, webhook proxy, saat dilimi, yetenekler), Python venv'i oluşturur, yalnızca etkin yeteneklerin gerektirdiği paketleri kurar (pip-compile + pip-sync), Node bağımlılıklarını kurar, systemd unit dosyalarını oluşturur ve servisleri etkinleştirir.

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

Sihirbaz yalnızca dışarıdan alman gereken kimlik bilgilerini sorar. Geri kalanı otomatik üretilir.

**Sihirbaz tarafından otomatik üretilir (giriş gerekmez):**
`API_KEY`, `TOTP_SECRET`, `TOTP_SECRET_ADMIN`, `WHATSAPP_VERIFY_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`

### WhatsApp

| Değişken | Açıklama |
|----------|----------|
| `WHATSAPP_ACCESS_TOKEN` | Meta WhatsApp Cloud API erişim tokeni (Meta Developer Console'dan) |
| `WHATSAPP_PHONE_NUMBER_ID` | Meta Developer Console'daki sayısal telefon numarası ID'si |
| `WHATSAPP_APP_SECRET` | Webhook HMAC imza doğrulaması için uygulama sırrı |
| `WHATSAPP_OWNER` | Kendi WhatsApp numaranız ülke koduyla (`+90...`) |

### Telegram

| Değişken | Açıklama |
|----------|----------|
| `TELEGRAM_BOT_TOKEN` | @BotFather'dan alınan bot token'ı (`123456789:ABCdef...`) |
| `TELEGRAM_CHAT_ID` | Kişisel Telegram chat ID'n — [@userinfobot](https://t.me/userinfobot)'tan öğren |

### LLM

| Değişken | Açıklama |
|----------|----------|
| `ANTHROPIC_API_KEY` | Anthropic API key (`sk-ant-api03-...`) — [console.anthropic.com](https://console.anthropic.com)'dan |
| `GEMINI_API_KEY` | Google Gemini API key — [aistudio.google.com](https://aistudio.google.com)'dan |
| `OLLAMA_BASE_URL` | Ollama base URL (varsayılan: `http://localhost:11434`) |
| `OLLAMA_MODEL` | Ollama model adı (varsayılan: `llama3`) |

Saat dilimi ve yetenek flag'leri dahil tüm seçenekler için bkz. [`scripts/backend/.env.example`](scripts/backend/.env.example).

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
| `!lock` | Uygulamayı kilitle (açmak için TOTP gerekir) | Owner + TOTP |
| `!unlock` | Uygulamanın kilidini aç | Owner + TOTP |
| `!beta-exit` | Proje beta modundan çık | Owner |
| `!project-delete` | Projeyi veritabanından sil | Math + Admin TOTP |
| `!restart` | Her iki servisi yeniden başlat | Math + Admin TOTP |
| `!shutdown` | FastAPI servisini durdur | Math + Admin TOTP |

**Yetki seviyeleri:**
- **Owner** — mesaj, yapılandırılmış sahip telefon/sohbet kimliğinden gelmeli
- **Owner + TOTP** — sahip + kimlik doğrulayıcı uygulamadan 6 haneli kod (`TOTP_SECRET`)
- **Math + Admin TOTP** — sahip + basit matematik sorusu + 6 haneli admin kodu (`TOTP_SECRET_ADMIN`)

Komut olmayan mesajlar serbest konuşma için Claude Code'a iletilir.

Yetenek flag'leri, sistem gereksinimleri ve dahili API endpoint'leri için bkz. [docs/skills.md](docs/skills.md).

---

## Webhook Proxy

Ajanın çalışması için WhatsApp veya Telegram'ın sunucuna mesaj gönderebileceği genel HTTPS URL'e ihtiyacı var. Sihirbaz dört seçenek sunar:

| Seçenek | Ne zaman kullanılır |
|---------|---------------------|
| **Yok** | Sabit genel IP'si veya domain'i olan VPS |
| **ngrok** ✅ Yerel kurulum için önerilen | Ücretsiz hesapta kalıcı static domain mevcut; binary kurulumu gerekmez |
| **Cloudflare Tunnel** | Kalıcı ücretsiz seçenek — Cloudflare hesabı ve DNS ayarı gerektirir |
| **Harici URL** | Bu makineye yönlendirilmiş kendi domain'in var |

### ngrok kurulumu

Ajan ngrok'u `pyngrok` Python paketi aracılığıyla yönetir — **ngrok binary'sini manuel kurman gerekmez**. pyngrok binary'yi otomatik indirir ve çalıştırır.

1. [ngrok.com](https://ngrok.com)'da ücretsiz hesap oluştur.
2. **Ücretsiz static domain** al: ngrok Dashboard → Domains → New Domain → domain'i kopyala (ör. `adın.ngrok-free.app`). Bu URL kalıcıdır, hiç değişmez.
3. Auth token'ını kopyala: **ngrok Dashboard → Your Authtoken**.
4. `bash install.sh --docker` (veya `install.sh`) çalıştır, proxy olarak **ngrok** seç — sihirbaz auth token'ını sorar ve `.env`'e yazar.
5. Servis başladıktan sonra ngrok otomatik olarak static domain'inde tünel açar. Public URL başlangıçta loglanır ve sihirbazın sonunda webhook bilgisinde gösterilir.
6. Webhook URL'ini Meta Developer Console'a (WhatsApp) veya `setWebhook` ile (Telegram) kaydet — sihirbaz tam komutu yazdırır.

> **Ücretsiz hesaplarda bir adet kalıcı static domain bulunur** — auth token ve static domain kullandığın sürece URL her yeniden başlatmada değişmez.
>
> **Hesabın yok mu?** Auth token alanını boş bırakabilirsin — ngrok anonim çalışır ancak URL rastgele üretilir ve her yeniden başlatmada değişir.

---

## Messenger Seçimi

| Messenger | `.env` ayarı | Notlar |
|-----------|-------------|--------|
| Telegram ✅ Önerilen | `MESSENGER_TYPE=telegram` | En kolay kurulum — @BotFather ile 2 dakikada bot oluştur, iş hesabı gerekmez. Sihirbaz chat ID'yi otomatik algılar. |
| WhatsApp | `MESSENGER_TYPE=whatsapp` | Meta iş hesabı, Meta Developer Console'da doğrulanmış uygulama ve HMAC webhook kurulumu gerektirir. |
| CLI (yerel test) | `MESSENGER_TYPE=cli` | Stdout'a yazar; hesap gerekmez. |

**Telegram mı WhatsApp mı?**

- Hızlı kurulum istiyorsan **Telegram** seç. İş doğrulaması yok, Meta hesabı yok, 5 dakikada çalışır.
- Ajanı özellikle WhatsApp'tan kontrol etmen gerekiyorsa (örn. Telegram kullanmıyorsan) **WhatsApp** seç.

Ayrıntılı Telegram kurulum adımları için bkz. [docs/deployment/telegram.md](docs/deployment/telegram.md).

---

## LLM Backend Seçimi

| Backend | `.env` ayarı | Maliyet | Gizlilik | Notlar |
|---------|-------------|---------|----------|--------|
| Anthropic ✅ Önerilen | `LLM_BACKEND=anthropic` | Kullanım başına ücret | Bulut | `ANTHROPIC_API_KEY` gerekli. Tam araç desteği, zamanlama ve tüm özellikler güvenilir çalışır. |
| Gemini | `LLM_BACKEND=gemini` | Ücretsiz kota | Bulut | `GEMINI_API_KEY` gerekli; `GEMINI_MODEL` opsiyonel (varsayılan: `gemini-2.0-flash`). Temel sohbet çalışır. |
| Ollama (yerel) | `LLM_BACKEND=ollama` | Ücretsiz | Tamamen yerel | `OLLAMA_BASE_URL` ve `OLLAMA_MODEL` gerekli. Önce `ollama pull llama3` çalıştır. Karmaşık araç kullanımı güvenilmeyebilir. |

> `INTENT_CLASSIFIER_MODEL` ayarı yalnızca Anthropic backend için geçerlidir.

Ayrıntılar için bkz. [docs/deployment/byok.md](docs/deployment/byok.md).

---

## Ön Koşullar

**Docker (Seçenek A):**
- Docker Engine + Docker Compose v2 (`docker compose version`)
- Host'ta kurulu ve kimliği doğrulanmış `claude` CLI (`npm install -g @anthropic-ai/claude-code`)

**systemd / PM2 (Seçenek B & C):**
- Python 3.11+
- Node.js 18+
- Kurulu ve kimliği doğrulanmış `claude` CLI (`npm install -g @anthropic-ai/claude-code`)
- systemd servis kurulumu için `sudo` erişimi (yalnızca Seçenek B)

**Tüm seçenekler:**
- Telegram bot token'ı **veya** Meta WhatsApp Cloud API uygulaması
- Webhook için genel HTTPS URL — yukarıdaki [Webhook Proxy](#webhook-proxy) bölümüne bak

---

## Lisans

MIT — bkz. [LICENSE](LICENSE)
