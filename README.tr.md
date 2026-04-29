# BalGPT

> _Sunucunuzda çalışan kişisel AI ajanı — WhatsApp veya Telegram üzerinden sohbet edin._

**BalGPT**, makinenizde çalışan ve WhatsApp veya Telegram'ı dinleyen kişisel bir asistandır. Mesaj gönderin; proje oluşturun, görevleri yönetin, takvim hatırlatıcıları kurun, shell komutları çalıştırın, PDF içe aktarın ve doğrudan telefonunuzdan Claude Code ile sohbet edin. Her şey kendi makinenizde çalışır; bulut servisleri yapılandırılmadıkça veriler dışarı çıkmaz.

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

## 🚀 Kurulum

İşletim sisteminizi seçin ve ilgili bölümdeki adımları uygulayın. Kurulum süresi tahminen 10–20 dakikadır (büyük bölümü Docker imajlarının indirilmesi).

| İşletim Sisteminiz | Bölüm |
|--------------------|-------|
| 🪟 **Windows 10 / 11** | [Windows Kurulumu](#-windows-kurulumu) |
| 🍎 **macOS** (Intel veya Apple Silicon) | [macOS Kurulumu](#-macos-kurulumu) |
| 🐧 **Linux** (Ubuntu / Debian / Fedora) | [Linux Kurulumu](#-linux-kurulumu) |

Kurulum tamamlandığında Telegram veya WhatsApp üzerinden dosya oluşturabilen, komut çalıştırabilen, hatırlatıcı kurabilen ve konuşma geçmişini saklayan bir bot kullanıma hazır olacak; tüm bunlar kendi makinenizde çalışacak.

---

## 🪟 Windows Kurulumu

### Gereksinimler

| # | Araç | İndirme | Açıklama |
|---|------|---------|----------|
| 1 | **Docker Desktop** | [docker.com/desktop](https://docs.docker.com/desktop/install/windows-install/) | Botu container içinde çalıştırır |
| 2 | **Git for Windows** | [git-scm.com/download/win](https://git-scm.com/download/win) | Git Bash terminalini sağlar |
| 3 | **Python 3.11+** | [python.org/downloads/windows](https://www.python.org/downloads/windows/) | Kurulum sihirbazı için gereklidir |

**Kurulum sırasında dikkat edilmesi gerekenler:**
- Docker Desktop: tüm varsayılanları işaretli bırakın. Kurulumdan sonra **uygulamayı başlatın** (sistem tepsisindeki balina simgesi ~1 dakika içinde hazır olur).
- Git for Windows: tüm varsayılanları kabul edin (özellikle "Git Bash Here" seçeneği).
- Python: ilk ekranda **"Add python.exe to PATH"** kutusunu işaretleyin — aksi hâlde kurulum scripti Python'u bulamaz.

### Bağımlılıkları Doğrulayın

**Git Bash**'i açın (Başlat → "Git Bash") ve aşağıdaki komutları çalıştırın:

```bash
docker --version
python3 --version   # ya da: python --version  /  py --version  (Windows)
bash --version | head -1
```

Çıktı: Docker 24+, Python 3.11+, Bash 4+ olmalıdır. Herhangi bir komut `command not found` hatası veriyorsa ilgili aracı yeniden kurun.

> **Windows notu:** `python3` komutu Windows'ta olmayabilir — `python --version` veya `py --version` da çalışır. `install.sh` bunu otomatik olarak algılar.

### 1. Adım — Docker'ın çalıştığından emin olun

Sistem tepsisini kontrol edin (sağ alt). Balina simgesi **"Docker Desktop is running"** durumunu göstermelidir; göstermiyorsa simgeye tıklayarak başlatın.

### 2. Adım — Projeyi indirin

Git Bash'te:

```bash
git clone https://github.com/your-username/99-root.git
cd 99-root
```

### 3. Adım — Kurulum scriptini çalıştırın

```bash
bash install.sh --docker
```

Sihirbaz ~6 soru sorar ve ardından kurulumu tamamlar. Her sorunun önerilen varsayılan yanıtı belirtilmiştir. Bkz. [Sihirbaz Soruları](#-sihirbaz-neyi-soruyor).

### 4. Adım — Doğrulayın

Kurulum tamamlandıktan sonra (ilk seferde 10–15 dakika):

```bash
docker compose ps
curl -s http://localhost:8010/health
curl -s http://localhost:8013/health
```

İki `curl` çıktısı da `"status":"ok"` içermelidir. Botunuza bir mesaj gönderin (Telegram veya WhatsApp) ve birkaç saniye içinde yanıt geldiğini doğrulayın.

### Windows'ta sık karşılaşılan sorunlar

| Belirti | Çözüm |
|---------|-------|
| `bash: install.sh: No such file or directory` | Proje klasöründe değilsiniz. Önce `cd 99-root` yazın. |
| `Docker daemon is not running` | Docker Desktop'ı açın, balina simgesinin animasyonu durana kadar bekleyin. |
| Sihirbaz PowerShell'de açıldı, görüntü bozuk | Script PowerShell'den çalıştırıldı. Kapatın; **Git Bash**'te açın. |
| `python3: command not found` | Python'u python.org'dan **Add to PATH** seçeneği işaretli olarak yeniden kurun. |
| `claude auth login` sırasında tarayıcı açılmıyor | Terminalde yazılan URL'yi kopyalayıp tarayıcıya manuel yapıştırın. |
| Kurulum "Public URL bekleniyor" satırında takılıyor | ngrok hesap problemi. [ngrok.com](https://ngrok.com)'da hesap oluşturup authtoken kopyalayın; `--reconfigure-capabilities` ile yeniden çalıştırın. |

---

## 🍎 macOS Kurulumu

### Gereksinimler

| # | Araç | Kurulum | Açıklama |
|---|------|---------|----------|
| 1 | **Homebrew** | `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"` | Paket yöneticisi |
| 2 | **Docker Desktop** | `brew install --cask docker` veya [docker.com](https://docs.docker.com/desktop/install/mac-install/) | Botu container içinde çalıştırır |
| 3 | **Python 3.11+** | `brew install python@3.11` (çoğu macOS kurulumunda mevcuttur) | Kurulum sihirbazı için gereklidir |
| 4 | **Git** | `brew install git` (çoğu macOS kurulumunda mevcuttur) | Projeyi indirir |

Homebrew ve Docker kurulumundan sonra **Docker Desktop'ı başlatın** (Uygulamalar → Docker). ~1 dakika içinde hazır olur.

### Bağımlılıkları Doğrulayın

**Terminal**'i açın (Cmd+Space → "Terminal"):

```bash
docker --version          # 24+
python3 --version          # 3.11+
git --version
bash --version | head -1
```

### 1. Adım — Projeyi indirin

```bash
git clone https://github.com/your-username/99-root.git
cd 99-root
```

### 2. Adım — Kurulum scriptini çalıştırın

```bash
bash install.sh --docker
```

Bkz. [Sihirbaz Soruları](#-sihirbaz-neyi-soruyor).

### 3. Adım — Doğrulayın

```bash
docker compose ps
curl -s http://localhost:8010/health
curl -s http://localhost:8013/health
```

Botunuza mesaj göndererek yanıt verdiğini doğrulayın.

### macOS'ta sık karşılaşılan sorunlar

| Belirti | Çözüm |
|---------|-------|
| `Cannot connect to the Docker daemon` | Uygulamalar'dan Docker Desktop'ı açıp başlamasını bekleyin. |
| `python3: command not found` | `brew install python@3.11`, ardından Terminal'i yeniden açın. |
| Apple Silicon (M1/M2/M3) image build yavaş | İlk build 10–15 dakika sürebilir. Sonraki çalıştırmalar saniyeler içinde tamamlanır. |
| `xcrun: error: invalid active developer path` | `xcode-select --install` çalıştırın ve gelen istemi onaylayın. |
| `/etc/...` oluşturmada permission denied | `sudo` kullanmayın — macOS'ta Docker modu gerektirmez. |

---

## 🐧 Linux Kurulumu

### Gereksinimler (Ubuntu/Debian)

```bash
# 1. Paket indeksini güncelleyin
sudo apt update

# 2. Docker + Docker Compose kurun
sudo apt install -y docker.io docker-compose-v2

# 3. Kullanıcıyı docker grubuna ekleyin (sudo olmadan docker komutları çalıştırmak için)
sudo usermod -aG docker $USER
# ⚠️ Değişikliğin etkili olması için oturumu kapatıp yeniden açın

# 4. Python 3.11+, git, curl ve venv modülünü kurun
sudo apt install -y python3 python3-venv python3-pip git curl

# 5. (İsteğe bağlı) Terminal QR kod desteği için:
sudo apt install -y qrencode whiptail
```

Fedora: `sudo dnf install docker docker-compose python3 python3-pip git curl qrencode newt`  
Arch: `sudo pacman -S docker docker-compose python python-pip git curl qrencode libnewt`

### Bağımlılıkları Doğrulayın

```bash
docker --version
docker compose version
python3 --version          # 3.11+
git --version
```

### 1. Adım — Docker'ın çalıştığından emin olun

```bash
sudo systemctl start docker
sudo systemctl enable docker
docker info >/dev/null && echo "Docker OK"
```

### 2. Adım — Projeyi indirin

```bash
git clone https://github.com/your-username/99-root.git
cd 99-root
```

### 3. Adım — Kurulum scriptini çalıştırın

```bash
bash install.sh --docker
```

### 4. Adım — Doğrulayın

```bash
docker compose ps
curl -s http://localhost:8010/health
curl -s http://localhost:8013/health
```

Botunuza mesaj göndererek doğrulayın.

### Native kurulum (Docker'sız)

```bash
sudo bash install.sh
```

### Linux'ta sık karşılaşılan sorunlar

| Belirti | Çözüm |
|---------|-------|
| `permission denied while trying to connect to the Docker daemon` | `usermod -aG docker` sonrası oturumu yenileyin. Geçici çözüm: komutlara `sudo` ekleyin. |
| `error: externally-managed-environment` (PEP 668) | Kurulum scripti otomatik ephemeral venv oluşturur. `python3-venv` paketinin kurulu olduğundan emin olun. |
| `qrencode not found` ve Python `qrcode` da yok | Ephemeral venv içinde qrcode kurulur. Başarısız olursa online QR URL gösterilir. |
| Docker modunda systemd hataları | `--docker` flag'ini ekleyerek çalıştırın. |

---

## ❓ Sihirbaz Neyi Soruyor

Kurulum scripti etkileşimlidir. ~6 soru sorar ve ardından kurulum/derleme işlemini tamamlar.

### S1 — Dil

```
Language / Dil:
  1) Türkçe (varsayılan / default)
  2) English
```

### S2 — Messenger Platformu

```
Hangi platform üzerinden mesaj alınacak?
  whatsapp    WhatsApp (Meta Cloud API)
  telegram    Telegram (BotFather token)
  cli         CLI — Sadece terminal çıktısı (test)
```

🎯 **Önerilen: `telegram`** — Yalnızca Telegram hesabı gerektirir; Meta Developer hesabı veya iş doğrulaması gerekmez.

- WhatsApp için Meta Developer hesabı, telefon numarası ve onaylı işletme kaydı gereklidir.
- CLI modu, messenger olmadan bot işlevini yerel olarak test etmek için kullanılır.

### S3 — Telegram Kurulumu (telegram seçildiyse)

1. **Bot Token** — [@BotFather](https://t.me/BotFather)'dan:
   - Telegram'ı açın, @BotFather'a mesaj gönderin.
   - `/newbot` komutunu gönderin.
   - Bot adı ve `bot` ile biten kullanıcı adı girin.
   - BotFather token'ı iletir; kopyalayın.
2. **Chat ID** — otomatik algılanır:
   - Sihirbaz bot'a mesaj göndermenizi ister.
   - Bot'a herhangi bir mesaj gönderin.
   - Sihirbaz chat ID'nizi otomatik algılar.

### S4 — LLM Backend

```
Hangi yapay zeka modelini kullanmak istiyorsunuz?
  anthropic    Anthropic Claude (claude.ai API key)
  ollama       Ollama — Yerel, açık kaynak model
  gemini       Google Gemini (AI Studio API key)
```

🎯 **Önerilen: `anthropic`** + **Claude Login** — En iyi performans; ayrı bir API anahtarı gerektirmez.

- Aboneliğiniz yoksa API Key seçeneğini tercih edin.
- Yerel ve ücretsiz bir çözüm için Ollama kullanılabilir; ancak yavaş çalışır ve araç kullanımı güvenilmez olabilir.
- Ücretsiz bulut seçeneği için Google Gemini tercih edilebilir ([aistudio.google.com](https://aistudio.google.com)).

### S5 — Webhook Proxy

```
Dış erişim için hangi yöntem kullanılacak?
  none         Yok
  ngrok        ngrok tüneli
  cloudflared  Cloudflare Tunnel
  external     Kendi domain'iniz
```

🎯 **Önerilen: `ngrok`** — Ücretsiz hesapla kalıcı public HTTPS URL sağlar.

ngrok kurulumu:
- [ngrok.com](https://ngrok.com)'da ücretsiz hesap oluşturun.
- Dashboard → Domains → "+ New domain" ile ücretsiz statik domain alın.
- Dashboard → Your Authtoken bölümünden token'ı kopyalayın.
- Her ikisini sihirbaza yapıştırın.

### S6 — Saat Dilimi

Size en yakın şehri seçin. Türkiye için `Europe/Istanbul`.

### S7 — Yetenekler

🎯 **Önerilen: Varsayılan seçimleri koruyun.** Desktop ve Browser yetenekleri varsayılan olarak kapalıdır; yalnızca gerektiğinde etkinleştirin (~500 MB ek paket).

### S8 — Anthropic Login (Claude Login seçildiyse)

Tarayıcı açılır; claude.ai hesabınızla giriş yapın.

### S9 — TOTP QR Kodları

İki QR kod gösterilir (owner + admin). **Google Authenticator ile tarayın.** Bu kodlar, `!restart` ve `!shutdown` gibi hassas komutlar için 6 haneli TOTP kimlik doğrulaması sağlar.

### S10 — Webhook Ayarı

Sihirbaz webhook URL'ini ekrana yazdırır. Telegram + ngrok kombinasyonunda otomatik kayıt yapılır. WhatsApp kullanıyorsanız URL'yi Meta Console'a yapıştırın.

---

## 🔧 Referans: Kurulum Modları

### Seçenek A — Docker ✅ Önerilen

> Çoğu kullanıcı için önerilen seçenektir. Linux, macOS ve Windows'ta (Git Bash + Docker Desktop) çalışır. Host'ta sihirbazı çalıştırmak için `bash`, `python3` 3.11+ ve `curl` gerekir — bkz. [Ön Koşullar](#ön-koşullar). Node.js host'ta **gerekmez** (Bridge container içinde gelir).

```bash
git clone https://github.com/kullanici-adin/99-root.git
cd 99-root
bash install.sh --docker
```

Sihirbaz messenger, LLM backend, webhook proxy, kimlik bilgileri ve yetenekleri yapılandırır. Ardından `.env` dosyasını yazar, `CAPABILITIES` build-arg içeren bir `docker-compose.override.yml` oluşturur, yalnızca seçili paketlerin kurulu olduğu image'ı derler ve container'ları başlatır.

Güvenlik anahtarları (`API_KEY`, `TOTP_SECRET`) ve webhook token'ları sihirbaz tarafından **otomatik üretilir**. TOTP QR kodu kurulum sonunda ekrana gösterilir; Google Authenticator ile taranabilir.

Compose dosyası `./data` ve `./outputs/logs` dizinlerini volume olarak bağlar; veriler container dışında kalıcı olarak saklanır.

Yetenekleri yeniden yapılandırmak ve image'ı yeniden derlemek için:

```bash
bash install.sh --docker --reconfigure-capabilities
```

> **Windows kullanıcıları:** PowerShell'de `bash` komutu yoktur — `bash install.sh --docker` çalışmaz. Aşağıdaki seçeneklerden birini kullanın:
> - **Git Bash** (önerilen): [Git for Windows](https://git-scm.com/download/win)'ı kurun, Git Bash'i açın ve komutu çalıştırın.
> - **WSL**: PowerShell'de `wsl --install -d Ubuntu` çalıştırın, Ubuntu terminalini açın ve komutu çalıştırın.
> - **Sihirbaz olmadan**: `.env.example`'ı `.env`'e kopyalayın, elle doldurun, ardından PowerShell'den `docker compose up -d --build` çalıştırın. Tüm yetenekler kurulur (daha büyük image).

Servis durumunu doğrulayın:

```bash
docker compose ps
curl -s http://localhost:8010/health
curl -s http://localhost:8013/health
```

Logları izleyin:

```bash
docker compose logs -f 99-api
docker compose logs -f 99-bridge
```

Yeniden başlatma:

```bash
docker compose restart
```

### Seçenek B — systemd (yalnızca Linux)

> Yerel performans ve otomatik başlatma gerektiren Linux sunucu veya Raspberry Pi kurulumları için önerilir.

```bash
git clone https://github.com/kullanici-adin/99-root.git
cd 99-root
sudo bash install.sh
```

`install.sh` etkileşimli bir sihirbaz çalıştırır (messenger, LLM backend, webhook proxy, saat dilimi, yetenekler), Python venv'i oluşturur, yalnızca etkin yeteneklerin gerektirdiği paketleri kurar (pip-compile + pip-sync), Node bağımlılıklarını kurar, systemd unit dosyalarını oluşturur ve servisleri etkinleştirir.

> `sudo` ile çalıştırılırsa systemd unit'leri otomatik kurulur ve etkinleştirilir. `sudo` olmadan çalıştırılırsa sihirbaz ve bağımlılık kurulumu tamamlanır, ardından gerekli `systemctl` komutları ekrana yazdırılır.

Servis durumunu kontrol edin:

```bash
sudo systemctl status personal-agent.service personal-agent-bridge.service
journalctl -u personal-agent.service -f
```

Diğer kurulum seçenekleri:

```bash
bash install.sh --no-systemd             # yalnızca bağımlılıkları kur, systemd kurma
bash install.sh --pm2                    # systemd yerine PM2 ile başlat
bash install.sh --reconfigure-capabilities  # yetenek sihirbazını tekrar çalıştır ve paketleri güncelle
```

> **Not:** `.env` dosyasında `DESKTOP_ENABLED`, `BROWSER_ENABLED` veya herhangi bir `RESTRICT_*` flag'ini değiştirdikten sonra `bash install.sh --reconfigure-capabilities` çalıştırın; aksi hâlde gerekli Python paketleri kurulmaz/kaldırılmaz.

### Seçenek C — PM2 (Linux / macOS / Windows)

Systemd kullanılamıyorsa PM2 tercih edin (macOS, Windows WSL, root'suz VPS).

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

Sihirbaz yalnızca dışarıdan alınması gereken kimlik bilgilerini sorar. Geri kalanı otomatik üretilir.

**Sihirbaz tarafından otomatik üretilir:**  
`API_KEY`, `TOTP_SECRET`, `WHATSAPP_VERIFY_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`

### WhatsApp

| Değişken | Açıklama |
|----------|----------|
| `WHATSAPP_ACCESS_TOKEN` | Meta WhatsApp Cloud API erişim tokeni (Meta Developer Console'dan) |
| `WHATSAPP_PHONE_NUMBER_ID` | Meta Developer Console'daki sayısal telefon numarası ID'si |
| `WHATSAPP_APP_SECRET` | Webhook HMAC imza doğrulaması için uygulama sırrı |
| `WHATSAPP_OWNER` | WhatsApp numaranız ülke koduyla (`+90...`) |

### Telegram

| Değişken | Açıklama |
|----------|----------|
| `TELEGRAM_BOT_TOKEN` | @BotFather'dan alınan bot token'ı (`123456789:ABCdef...`) |
| `TELEGRAM_CHAT_ID` | Kişisel Telegram chat ID'niz — [@userinfobot](https://t.me/userinfobot)'tan öğrenebilirsiniz |

> **Telegram + cloudflared:** Sihirbaz Telegram seçildiğinde proxy olarak ngrok'u zorlar; cloudflared seçeneği gösterilmez. Cloudflared kullanmak istiyorsanız kurulumu tamamlayın, ardından `.env` dosyasında `WEBHOOK_PROXY=cloudflared` yapın, `cloudflared` binary'sinin yüklü olduğundan emin olun ve servisleri yeniden başlatın. `!wizard` komutu ve genel akış proxy-bağımsızdır — webhook public URL'den kayıtlı olduğu sürece çalışır.

> **Telegram komut menüsü:** Servis her başladığında bot, `setMyCommands` API'si aracılığıyla mevcut tüm komutları Telegram'a otomatik olarak kaydeder. Bu sayede Telegram'daki `/` kısayol menüsü her zaman güncel kalır — BotFather'da manuel adım gerekmez. Slash komutları (`/help`, `/restart` vb.) `!` karşılıklarıyla birebir aynı şekilde çalışır. Yeni bir komut ekleyip servisi yeniden başlattığınızda (`git pull` + `docker compose restart` veya `systemctl restart`) menü otomatik güncellenir.

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
| `!terminal [komut]` | Shell komutu çalıştır ve çıktıyı gönder (tehlikeli komutlar owner TOTP gerektirir) | Owner |
| `!model [ad]` | Çalışma zamanında LLM modelini değiştir (yeniden başlatmaya kadar geçerli) | Owner |
| `!tokens [24h\|7d\|30d]` | LLM token kullanım istatistiklerini göster | Owner |
| `!lang <tr\|en>` | Arayüz dilini değiştir | Owner |
| `!timezone [IANA]` | Aktif saat dilimini göster veya değiştir (APScheduler yeniden yapılandırılır) | Owner |
| `!cancel` | Aktif TOTP akışını, bekleyen işlemi veya Bridge sorgusunu iptal et | Owner |
| `!lock` | Uygulamayı kilitle (açmak için TOTP gerekir) | Owner + TOTP |
| `!unlock` | Uygulamanın kilidini aç | Owner + TOTP |
| `!beta` | Proje beta modundan çık | Owner |
| `!project-delete` | Projeyi veritabanından sil | Math + Owner TOTP |
| `!restart` | Her iki servisi yeniden başlat | Math + Owner TOTP |
| `!shutdown` | FastAPI servisini durdur | Math + Owner TOTP |

**Yetki seviyeleri:**
- **Owner** — mesaj, yapılandırılmış sahip telefon/sohbet kimliğinden gelmelidir
- **Owner + TOTP** — sahip kimliği + kimlik doğrulayıcı uygulamadan 6 haneli kod (`TOTP_SECRET`)
- **Math + Owner TOTP** — sahip kimliği + basit matematik sorusu + `TOTP_SECRET` ile 6 haneli kod

Komut olmayan mesajlar serbest konuşma için Claude Code'a iletilir.

> **Telegram:** Tüm komutlar aynı zamanda native slash komut olarak da kullanılabilir (`/help`, `/root_reset` vb.). Bot her başlangıçta bunları otomatik kaydeder — `/` kısayol menüsü BotFather yapılandırması gerektirmeden güncel kalır.

Yetenek flag'leri, sistem gereksinimleri ve dahili API endpoint'leri için bkz. [docs/skills.md](docs/skills.md).

---

## Webhook Proxy

Ajanın çalışması için WhatsApp veya Telegram'ın sunucunuza mesaj gönderebileceği genel bir HTTPS URL gereklidir. Sihirbaz dört seçenek sunar:

| Seçenek | Ne zaman kullanılır |
|---------|---------------------|
| **Yok** | Sabit genel IP'si veya domain'i olan VPS |
| **ngrok** ✅ Yerel kurulum için önerilen | Ücretsiz hesapta kalıcı statik domain mevcuttur; binary kurulumu gerekmez |
| **Cloudflare Tunnel** | Kalıcı ücretsiz seçenek — Cloudflare hesabı ve DNS ayarı gerektirir |
| **Harici URL** | Bu makineye yönlendirilmiş kendi domain'iniz |

### ngrok kurulumu

Ajan ngrok'u `pyngrok` Python paketi aracılığıyla yönetir — **ngrok binary'sini manuel olarak kurmanız gerekmez**. pyngrok, binary'yi otomatik indirir ve çalıştırır.

1. [ngrok.com](https://ngrok.com)'da ücretsiz hesap oluşturun.
2. **Ücretsiz statik domain** alın: ngrok Dashboard → Domains → New Domain → domain'i kopyalayın (ör. `adınız.ngrok-free.app`). Bu URL kalıcıdır.
3. Auth token'ınızı kopyalayın: **ngrok Dashboard → Your Authtoken**.
4. `bash install.sh --docker` çalıştırın ve proxy olarak **ngrok**'u seçin — sihirbaz auth token'ını sorar ve `.env` dosyasına yazar.
5. Servis başladıktan sonra ngrok otomatik olarak statik domain üzerinde tünel açar. Public URL başlangıçta loglanır ve sihirbazın sonunda gösterilir.
6. Webhook URL'ini Meta Developer Console'a (WhatsApp için) veya `setWebhook` komutuyla (Telegram için) kaydedin — sihirbaz tam komutu ekrana yazdırır.

> **Ücretsiz hesaplarda bir adet kalıcı statik domain bulunur** — auth token ve statik domain kullanıldığı sürece URL her yeniden başlatmada değişmez.
>
> Auth token girilmezse ngrok anonim modda çalışır; ancak URL rastgele üretilir ve her yeniden başlatmada değişir.

---

## Messenger Seçimi

| Messenger | `.env` ayarı | Notlar |
|-----------|-------------|--------|
| Telegram ✅ Önerilen | `MESSENGER_TYPE=telegram` | @BotFather ile hızlı kurulum; iş hesabı gerekmez. Sihirbaz chat ID'yi otomatik algılar. |
| WhatsApp | `MESSENGER_TYPE=whatsapp` | Meta iş hesabı, Meta Developer Console'da doğrulanmış uygulama ve HMAC webhook kurulumu gerektirir. |
| CLI (yerel test) | `MESSENGER_TYPE=cli` | Stdout'a yazar; hesap gerekmez. |

**Telegram mı WhatsApp mı?**

- Hızlı kurulum için **Telegram** tercih edin. Meta hesabı veya iş doğrulaması gerektirmez.
- Ajanı özellikle WhatsApp üzerinden kullanmak istiyorsanız **WhatsApp**'ı tercih edin.

Ayrıntılı Telegram kurulum adımları için bkz. [docs/deployment/telegram.md](docs/deployment/telegram.md).

---

## LLM Backend Seçimi

| Backend | `.env` ayarı | Maliyet | Gizlilik | Notlar |
|---------|-------------|---------|----------|--------|
| Anthropic ✅ Önerilen | `LLM_BACKEND=anthropic` | Kullanım başına ücret | Bulut | `ANTHROPIC_API_KEY` gereklidir. Tam araç desteği, zamanlama ve tüm özellikler güvenilir çalışır. |
| Gemini | `LLM_BACKEND=gemini` | Ücretsiz kota | Bulut | `GEMINI_API_KEY` gereklidir; `GEMINI_MODEL` isteğe bağlıdır (varsayılan: `gemini-2.0-flash`). Temel sohbet çalışır. |
| Ollama (yerel) | `LLM_BACKEND=ollama` | Ücretsiz | Tamamen yerel | `OLLAMA_BASE_URL` ve `OLLAMA_MODEL` gereklidir. Önce `ollama pull llama3` çalıştırın. Karmaşık araç kullanımı güvenilmeyebilir. |

> `INTENT_CLASSIFIER_MODEL` ayarı yalnızca Anthropic backend için geçerlidir.

Ayrıntılar için bkz. [docs/deployment/byok.md](docs/deployment/byok.md).

---

## Ön Koşullar

### Her kurulum modunda zorunlu

| Araç | install.sh için neden gereklidir |
|------|----------------------------------|
| `bash` 4+ | Script yorumlayıcı; `set -euo pipefail`, ilişkisel diziler |
| **`python3` 3.11+** | i18n locale loader, JSON parsing, .env yardımcıları, messenger bildirimleri, systemd template render, TOTP QR üretimi. Eksikse install.sh fatal ile çıkar. |
| `curl` | Telegram/WhatsApp/ngrok API çağrıları |
| Standart POSIX araçlar | `awk`, `sed`, `grep`, `mktemp`, `tr`, `cut` (her Linux/macOS'ta mevcuttur, Git Bash ile gelir) |

> ⚠️ Docker modu her şeyi container içinde yönetse de **install.sh host'ta çalışır ve host'ta Python 3.11+ gerektirir.**

### Moda özgü

| Mod | Ek gereksinim |
|-----|---------------|
| **Docker** (Seçenek A) | Docker Engine + Docker Compose v2 (`docker compose version`); host'ta `claude` CLI (eksikse install.sh `npm` ile otomatik kurar) |
| **systemd** (Seçenek B) | Node.js 18+; `sudo` erişimi; `claude` CLI |
| **PM2** (Seçenek C) | Node.js 18+; `claude` CLI; `npm install -g pm2` (script tarafından kurulur) |

### İsteğe bağlı

| Araç | Eksikse ne olur |
|------|-----------------|
| `whiptail` | Sihirbaz düz metin moduna geçer (işlevsel olmaya devam eder) |
| `qrencode` **veya** `python3-venv` | TOTP QR terminalde gösterilir. Her ikisi de yoksa online QR URL + manuel anahtar talimatı gösterilir. Debian/Ubuntu'da `python3-venv` ayrı pakettir: `sudo apt install python3-venv` |
| `openssl` | Kriptografik rastgele anahtar üretimi için (`API_KEY`, TOTP secret). Eksikse `date +%s%N \| sha256sum` kullanılır (daha düşük entropi). |
| `node` + `npm` (Docker modu) | `claude` CLI otomatik kurulumu için. Yoksa Bridge başlamadan önce Claude CLI manuel olarak kurulmalıdır. |

### Platform notları

- **Linux (Ubuntu 23.04+, Debian 12+, Fedora 38+, vb.)** — PEP 668 `pip install --user`'ı kısıtlar. install.sh QR rendering için otomatik ephemeral venv oluşturur; yalnızca `python3-venv` paketinin kurulu olması yeterlidir.
- **macOS** — Homebrew veya python.org Python 3.11+ desteklenmektedir. PEP 668 uyarısı geçerlidir.
- **Windows** — Native kurulum **desteklenmemektedir**; install.sh açıklayıcı hata mesajıyla çıkar. Git Bash + Docker Desktop ile `bash install.sh --docker` kullanın. Python 3.11+ PATH'te mevcut olmalıdır.
- **WSL** — Linux olarak değerlendirin. Seçenek B için systemd'i `/etc/wsl.conf` → `[boot] systemd=true` ile etkinleştirmek gerekebilir.

### Harici servis / hesap

- Bir **Telegram bot token** ([@BotFather](https://t.me/BotFather)) **veya** **Meta WhatsApp Cloud API** uygulaması
- Bir [Anthropic API key](https://console.anthropic.com) **veya** Claude Pro/Max aboneliği (`claude auth login` için); alternatif olarak Ollama (yerel) ya da Google Gemini
- Webhook için **genel HTTPS URL** — bkz. [Webhook Proxy](#webhook-proxy)

### Hızlı kontrol

```bash
bash --version | head -1
python3 --version    # 3.11+ olmalıdır
curl --version | head -1
docker --version     # yalnızca Docker modu
node --version       # yalnızca native modlar

# QR kod desteği (isteğe bağlı)
command -v qrencode || python3 -c 'import venv'
```

---

## Lisans

MIT — bkz. [LICENSE](LICENSE)

Copyright © 2026 Emin Balcı. Tüm hakları saklıdır.
