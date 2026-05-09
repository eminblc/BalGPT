# VPS Kurulum Kılavuzu — Ubuntu 22.04

Bu kılavuz, kişisel ajanı bir VPS'e (DigitalOcean, Hetzner, Vultr vb.) kurarak
7/24 çalışır hale getirmeyi anlatır. Cloudflare Tunnel ile ücretsiz, statik bir
webhook URL'si elde edilir — ngrok gerekmez, port açmak gerekmez.

---

## Minimum Gereksinimler

| Kaynak | Minimum | Önerilen |
|--------|---------|----------|
| vCPU | 1 | 2 |
| RAM | 1 GB | 2 GB |
| Disk | 10 GB | 20 GB |
| OS | Ubuntu 22.04 LTS | Ubuntu 22.04 LTS |
| Ağ | Herhangi bir çıkış bağlantısı | — |

> **Not:** Bridge içinde Claude Code CLI çalıştığından RAM önemlidir.
> 1 GB RAM ile swap eklenmesi şiddetle tavsiye edilir (bkz. aşağıda).

---

## 1. Sunucu Hazırlığı

```bash
# Sistemi güncelle
sudo apt update && sudo apt upgrade -y

# Temel araçlar
sudo apt install -y git curl wget ca-certificates gnupg lsb-release

# Swap ekle (1 GB RAM varsa)
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

---

## 2. Docker Kurulumu

```bash
# Docker resmi GPG anahtarı
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Docker repository ekle
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Docker Engine + Compose plugin kur
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Sudo olmadan docker çalıştırabilmek için kullanıcıyı gruba ekle
sudo usermod -aG docker $USER
newgrp docker

# Kontrol
docker --version
docker compose version
```

---

## 3. Projeyi Kur

```bash
git clone https://github.com/your-username/99-root.git
cd 99-root

# .env dosyasını oluştur
cp scripts/backend/.env.example scripts/backend/.env
nano scripts/backend/.env
```

`.env` içinde doldurulması zorunlu değişkenler:

```
WHATSAPP_ACCESS_TOKEN=...
WHATSAPP_PHONE_NUMBER_ID=...
WHATSAPP_APP_SECRET=...
WHATSAPP_VERIFY_TOKEN=...
WHATSAPP_OWNER=+90...
ANTHROPIC_API_KEY=sk-ant-...
API_KEY=...          # rastgele güçlü string
TOTP_SECRET=...      # python3 -c "import pyotp; print(pyotp.random_base32())"
WEBHOOK_PROXY=cloudflared    # Cloudflare Tunnel kullanılacak
```

---

## 4. Cloudflare Tunnel Kurulumu (Ücretsiz)

Cloudflare Tunnel, VPS'te hiçbir port açmadan, kalıcı bir `https://` URL'si sağlar.

```bash
# cloudflared binary indir (x86_64)
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
  -o /usr/local/bin/cloudflared
chmod +x /usr/local/bin/cloudflared

# Doğrula
cloudflared --version
```

**Quick Tunnel (kalıcı olmayan, test için):**

`WEBHOOK_PROXY=cloudflared` ayarlandığında ajan startup'ında otomatik Quick Tunnel
açar; URL'yi WhatsApp'a bildirir. Her yeniden başlatmada URL değişir — Meta webhook
URL'sini güncellemeniz gerekir.

**Named Tunnel (kalıcı URL, önerilen):**

```bash
# Cloudflare hesabına giriş
cloudflared tunnel login

# Tünel oluştur
cloudflared tunnel create personal-agent

# config.yml yaz
mkdir -p ~/.cloudflared
cat > ~/.cloudflared/config.yml << 'EOF'
tunnel: personal-agent
credentials-file: /home/ubuntu/.cloudflared/<TUNNEL_ID>.json

ingress:
  - hostname: agent.yourdomain.com
    service: http://localhost:8010
  - service: http_status:404
EOF

# DNS kaydı ekle (Cloudflare DNS'de CNAME oluşturur)
cloudflared tunnel route dns personal-agent agent.yourdomain.com
```

Named Tunnel ile `WEBHOOK_PROXY=external` ve `PUBLIC_URL=https://agent.yourdomain.com`
kullanın; cloudflared'ı ayrı bir servis olarak başlatın.

---

## 5. Servisi Başlat

```bash
# Container'ları build et ve arka planda başlat
docker compose up -d --build

# Durum kontrol
docker compose ps

# Log izle
docker compose logs -f 99-api
docker compose logs -f 99-bridge
```

---

## 6. Systemd ile Otomatik Başlatma

Sunucu yeniden başladığında Docker Compose'un otomatik çalışması için:

```bash
# WorkingDirectory için önce projenin tam yolunu öğren:
#   pwd   →  örn. /home/ubuntu/99-root
# Aşağıdaki komutta /home/ubuntu/99-root kısmını kendi yolunla değiştir.

sudo tee /etc/systemd/system/personal-agent-docker.service > /dev/null << 'EOF'
[Unit]
Description=Personal Agent (Docker Compose)
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/home/ubuntu/99-root
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable personal-agent-docker.service
sudo systemctl start personal-agent-docker.service
```

---

## 7. Meta Webhook URL Kaydet

Servis başladıktan sonra WhatsApp'a gelen bildirimde veya log'da webhook URL'si görünür:

```
https://agent.yourdomain.com/whatsapp/webhook
```

Meta Developer → WhatsApp → Configuration → Webhook URL olarak bu URL'yi gir.

---

## Güncelleme

```bash
cd 99-root
git pull
docker compose up -d --build
```
