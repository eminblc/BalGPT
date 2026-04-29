# Raspberry Pi 4 Kurulum Kılavuzu

Bu kılavuz, kişisel ajanı evdeki Raspberry Pi 4'e kurarak
7/24 çalışır hale getirmeyi anlatır.

---

## Gereksinimler

| Bileşen | Minimum | Not |
|---------|---------|-----|
| Model | Raspberry Pi 4 Model B | Pi 5 de çalışır |
| RAM | 2 GB | 1 GB RAM ile swap şart |
| Depolama | 16 GB microSD veya USB SSD | SSD tercih edilir (SD kart aşınır) |
| OS | Raspberry Pi OS Lite 64-bit | Desktop gerekmez |
| Ağ | İnternet bağlantısı | Cloudflare Tunnel için dışa çıkış yeterli |

---

## 1. İşletim Sistemi Kurulumu

[Raspberry Pi Imager](https://www.raspberrypi.com/software/) ile
**Raspberry Pi OS Lite (64-bit)** yaz. Imager'da "Advanced options" ile:
- SSH etkinleştir
- Kullanıcı adı ve şifre belirle
- Wi-Fi veya Ethernet yapılandır

---

## 2. Sistem Hazırlığı

```bash
# SSH ile bağlan (kullanıcı adını Imager'da ne ayarladıysan onu kullan)
ssh <kullanici-adi>@<raspberry-pi-ip>

# Sistemi güncelle
sudo apt update && sudo apt upgrade -y

# Temel araçlar
sudo apt install -y git curl wget ca-certificates gnupg
```

### Swap Ekle (1 GB RAM ise zorunlu, 2 GB RAM ise tavsiye)

```bash
# Mevcut swap'ı durdur
sudo dphys-swapfile swapoff
sudo dphys-swapfile uninstall

# 2 GB swap dosyası oluştur
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# Swap kullanım eşiğini optimize et (SD kart yazma azaltır)
echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

---

## 3. Docker Kurulumu (arm64 uyumlu)

```bash
# Resmi Docker install script (arm64 destekler)
curl -fsSL https://get.docker.com | sudo sh

# Kullanıcıyı docker grubuna ekle
sudo usermod -aG docker $USER
newgrp docker

# Compose plugin
sudo apt install -y docker-compose-plugin

# Kontrol
docker --version
docker compose version
```

---

## 4. Sabit İç IP Yapılandırması

Pi'nin ev ağında her zaman aynı IP'yi alması için:

**Seçenek A — dhcpcd (Raspberry Pi OS varsayılanı):**

```bash
sudo nano /etc/dhcpcd.conf
```

Dosyanın sonuna ekle:

```
interface eth0
static ip_address=192.168.1.100/24
static routers=192.168.1.1
static domain_name_servers=1.1.1.1 8.8.8.8
```

`eth0` yerine Wi-Fi kullanıyorsan `wlan0` yaz.

```bash
sudo systemctl restart dhcpcd
ip addr show eth0   # sabit IP doğrula
```

**Seçenek B — Router DHCP Reservation (daha kolay):**

Router yönetim panelinde Pi'nin MAC adresine sabit IP ata.
Pi'de herhangi bir yapılandırma gerekmez.

---

## 5. Projeyi Kur

```bash
git clone https://github.com/your-username/99-root.git
cd 99-root

cp scripts/backend/.env.example scripts/backend/.env
nano scripts/backend/.env
```

`.env` içinde doldurulması zorunlu değişkenler aynıdır (bkz. [VPS kılavuzu](vps.md#3-projeyi-kur)).

Webhook proxy için:
```
WEBHOOK_PROXY=cloudflared
```

---

## 6. Cloudflare Tunnel Kurulumu

```bash
# cloudflared arm64 binary indir
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64 \
  -o /usr/local/bin/cloudflared
chmod +x /usr/local/bin/cloudflared

cloudflared --version
```

Devamı için [VPS kılavuzundaki Cloudflare Tunnel adımlarını](vps.md#4-cloudflare-tunnel-kurulumu-ücretsiz) takip et.

---

## 7. Servisi Başlat

```bash
cd 99-root

# İlk build (arm64 imajları indirilir; birkaç dakika sürebilir)
docker compose up -d --build

# Durum
docker compose ps

# Log izle
docker compose logs -f 99-api
```

---

## 8. Otomatik Başlatma

Pi her açıldığında Docker Compose otomatik başlasın:

```bash
# WorkingDirectory için projenin tam yolunu öğren:
#   pwd   →  örn. /home/pi/99-root   veya   /home/emin/99-root
# Aşağıdaki komutta /home/pi/99-root kısmını kendi yolunla değiştir.
# Not: $(pwd) heredoc içinde çalışmaz — sabit yol zorunlu.

sudo tee /etc/systemd/system/personal-agent-docker.service > /dev/null << 'EOF'
[Unit]
Description=Personal Agent (Docker Compose)
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/home/pi/99-root
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable personal-agent-docker.service
```

---

## SD Kart Ömrünü Uzatmak

SD kartlar sık yazma işlemlerine dayanıklı değildir. Log ve DB yazmaları
SD kart ömrünü kısaltabilir:

```bash
# Harici USB SSD bağla ve veri dizinini oraya taşı
sudo mkfs.ext4 /dev/sda1
sudo mkdir /mnt/ssd
echo '/dev/sda1 /mnt/ssd ext4 defaults,noatime 0 2' | sudo tee -a /etc/fstab
sudo mount -a

# docker-compose.yml volume'lerini /mnt/ssd/data ve /mnt/ssd/outputs olarak düzenle
```

Veya docker-compose.yml'de `tmpfs` ile log dizinini RAM'e taşı (reboot'ta silinir):

```yaml
volumes:
  - type: tmpfs
    target: /app/outputs/logs
    tmpfs:
      size: 52428800   # 50 MB
```

---

## Güncelleme

```bash
cd 99-root
git pull
docker compose up -d --build
```
