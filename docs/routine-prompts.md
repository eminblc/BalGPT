# Rutin Promptlar

Sık kullanılan Claude Code görev promptları. Kopyala → yapıştır.

Placeholder'lar `<BÜYÜK_HARF>` formatında — kullanmadan önce doldur.

---

## İçindekiler

1. [`.md` Senkronizasyonu](#1-md-senkronizasyonu)
2. [Backlog — Belirli Öncelik Düzeyini Uygula](#2-backlog--belirli-öncelik-düzeyini-uygula)
3. [Güvenlik + Kod Kalitesi Audit Raporu](#3-güvenlik--kod-kalitesi-audit-raporu)
4. [OOP / SOLID Analizi](#4-oop--solid-analizi)
5. [Yeni `!komut` Ekleme](#5-yeni-komut-ekleme)
6. [Yeni LLM / Messenger Adaptörü Ekleme](#6-yeni-llm--messenger-adaptörü-ekleme)
7. [Yeni Feature Modülü Ekleme](#7-yeni-feature-modülü-ekleme)
8. [Bağımlılık Güncelleme Raporu](#8-bağımlılık-güncelleme-raporu)
9. [WORK_LOG.md Güncelleme](#9-work_logmd-güncelleme)
10. [Rapor Temizleme (done/)](#10-rapor-temizleme-done)
11. [GUARDRAILS Boşluk Araştırması](#11-guardrails-boşluk-araştırması)

---

## 1. `.md` Senkronizasyonu

Tüm dokümantasyon dosyalarını birbirleriyle ve kodla senkronize eder.
Ne zaman: büyük geliştirme oturumu bittikten sonra; haftada bir rutin.

```
Sen bir teknik editörsün. 99-root projesinin tüm .md dosyalarını inceleyip
birbirleriyle ve mevcut kodla senkronize edeceksin.

## Görev

1. Tüm .md dosyalarını tara:
   - README.md, README.tr.md
   - CLAUDE.md, AGENT.md, WORK_LOG.md, MEMORY.md, BACKLOG.md
   - docs/deployment/byok.md, docs/deployment/vps.md, docs/deployment/raspberry-pi.md
   - docs/routine-prompts.md (bu dosya — placeholder'lar hâlâ geçerli mi?)
   - CONTRIBUTING.md, GUARDRAILS.md
   - data/projects/ altındaki proje CLAUDE.md dosyaları (varsa)

2. Her dosya için kontrol et:
   a. **Kodla tutarsızlık** — bahsedilen komut/değişken/dosya/port/servis adı
      gerçekten var mı? (Glob/Grep ile doğrula)
   b. **Çapraz referans hataları** — "bkz. BACKLOG.md → X" gibi atıflar hâlâ geçerli mi?
   c. **Eksik güncelleme** — son geliştirme dönemindeki değişiklikler (adapters/,
      yeni komutlar, config alanları, port/servis isimleri) ilgili .md'lere yansımış mı?
   d. **BACKLOG.md senkronizasyonu** — ✅ Tamamlanan maddeler WORK_LOG.md'de kayıtlı mı?
   e. **Çelişkili bilgi** — aynı konuda iki .md farklı şey söylüyor mu?
      (ör. model adı, komut yetki seviyesi, port numarası)
   f. **TR ↔ EN eşitsizliği** — README.tr.md ile README.md arasında bölüm farkı var mı?

3. Bulgularını şu formatta raporla:

   ### <dosya-adı>
   | Alan | Sorun | Önerilen Düzeltme |
   |------|-------|-------------------|

   Sorun yoksa: "✅ Güncel"

4. Düzeltmeleri uygula (önce Read, sonra Edit).
   Kodu değiştirme — yalnızca .md dosyaları.

5. Her dosyayı güncelledikten sonra syntax kontrolü çalıştır:
   cd scripts && backend/venv/bin/python -c "from backend.main import app; print('OK')"
   node --check scripts/claude-code-bridge/server.js

6. Tamamlandığında özet tablo yaz:
   Kaç dosya incelendi | Kaç dosyada değişiklik yapıldı | En kritik 3 bulgu

## Kısıtlar
- .env dosyalarına dokunma, içeriğini okuma
- Yeni .md dosyası oluşturma — yalnızca mevcutları güncelle
- Kod/config dosyalarını değiştirme
```

---

## 2. Backlog — Belirli Öncelik Düzeyini Uygula

BACKLOG.md'deki seçili öncelik grubunu uygular ve tamamlanan maddeleri işaretler.
Ne zaman: planlı geliştirme seansı öncesi.

```
BACKLOG.md'deki <ÖNCELİK> öncelikli tüm açık maddeleri uygula.

Hazırlık:
1. BACKLOG.md'yi oku. <ÖNCELİK> bölümündeki maddeleri listele ve onayla.
2. Her madde için: önce ilgili dosyayı oku → değişikliği uygula → syntax kontrolü yap.
3. Maddeyi tamamlar tamamlamaz BACKLOG.md'de ✅ Tamamlanan bölümüne taşı
   (tarihi ve kısa notu ekle). Bitişleri biriktirme.
4. Tüm maddeler bitince kısa özet yaz.

Syntax kontrolü (her Python dosyası değişikliğinden sonra):
  cd scripts && backend/venv/bin/python -c "from backend.main import app; print('OK')"
  node --check scripts/claude-code-bridge/server.js

Kısıtlar:
- .env dosyalarına dokunma
- Geçici scriptler /tmp/ altına yaz, işin bitince sil
- BACKLOG.md kuralı: ✅ Tamamlanan bölümü daima dosyanın en altında kalır;
  yeni maddeler buraya en alta eklenir
- !restart çağrı zincirindeki dosyaları değiştirince syntax kontrolü zorunlu
  (whatsapp_router.py, cloud_api.py, guards/__init__.py, restart_cmd.py)
```

> `<ÖNCELİK>` yerine `🔴 KRİTİK`, `🟠 YÜKSEK`, `🟡 ORTA` veya `🟢 DÜŞÜK` yaz.

---

## 3. Güvenlik + Kod Kalitesi Audit Raporu

Projeyi tarayıp bulgular raporu üretir. Düzeltme yapmaz — sadece rapor.
Ne zaman: büyük özellik eklendikten sonra; aylık rutin.

```
99-root projesini güvenlik ve kod kalitesi açısından tara.
Yalnızca rapor üret — hiçbir dosyayı değiştirme.

Tara:
  scripts/backend/guards/
  scripts/backend/features/
  scripts/backend/routers/
  scripts/backend/store/
  scripts/backend/adapters/
  scripts/backend/whatsapp/
  scripts/claude-code-bridge/server.js

Kontrol edilecek alanlar:

1. **Güvenlik**
   - Auth bypass / izin atlama riski
   - Injection: SQL (format string ile query), komut (shell=True, f-string interpolation),
     prompt (dış içerik doğrudan LLM'e gidiyorsa)
   - Hassas veri sızıntısı: log, hata mesajı, API yanıtında secret/token
   - Race condition / TOCTOU
   - Bellek sızıntısı: sınırsız büyüyen dict/list (eviction yok)
   - Timing attack: string karşılaştırması `==` ile yapılıyorsa

2. **Güvenilirlik**
   - Async event loop bloklayan senkron I/O (`subprocess.run`, `open`, `sqlite3`)
   - Sessiz exception yutma (`except: pass`, `except Exception: pass`)
   - Bool yerine None dönen fonksiyonlarda eksik kontrol
   - Graceful shutdown eksikliği (scheduler, DB bağlantısı)
   - Retry/timeout olmayan dış HTTP çağrıları

3. **Kod kalitesi**
   - DIP ihlali (router → store doğrudan erişim; store → features)
   - Dead code / kullanılmayan import / ölü değişken
   - Hardcoded değer (port, yol, model adı, zaman sabiti) — config'e taşınmalı
   - Tekrar eden mantık — ortak helper olabilir mi?

Rapor formatı:
  ## <Kategori>
  | # | Önem | Dosya:Satır | Sorun | Öneri |
  |---|------|-------------|-------|-------|

Önem: 🔴 KRİTİK | 🟠 YÜKSEK | 🟡 ORTA | 🟢 DÜŞÜK

Raporu reports/audit_<YYYY-MM-DD>.md dosyasına yaz.
Düzeltme yapma — rapor bitince dur.
```

---

## 4. OOP / SOLID Analizi

Mimarinin OOP prensipleri ve SOLID uyumunu analiz eder; bulgular rapor olarak kaydedilir.
Ne zaman: yeni adapter/feature eklendikten sonra; çeyrek dönem rutin.

```
99-root projesinin nesne yönelimli tasarımını ve SOLID prensip uyumunu analiz et.
Yalnızca rapor üret — hiçbir dosyayı değiştirme.

Analiz kapsamı:
  scripts/backend/guards/
  scripts/backend/features/
  scripts/backend/routers/
  scripts/backend/store/
  scripts/backend/adapters/
  scripts/backend/guards/commands/

Her SOLID prensibi için sistemin mevcut durumunu değerlendir:

**S — Single Responsibility Principle**
- Her modül/sınıf tek bir sorumluluğa sahip mi?
- Birden fazla "neden değişir?" sorusuna cevap veren sınıf/modül var mı?
- Özellikle: routers/ içinde iş mantığı var mı? features/ içinde doğrudan store erişimi var mı?

**O — Open/Closed Principle**
- Yeni komut/platform/LLM eklemek mevcut kodu değiştirmeyi gerektiriyor mu?
- Registry/factory/protocol desenleri nerede uygulanmış, nerede uygulanmamış?
- if/elif zinciri yerine registry kullanılabilecek yer var mı?

**L — Liskov Substitution Principle**
- AbstractMessenger ve AbstractLLMProvider implementasyonları birbirinin yerine
  geçebiliyor mu? Bir implementasyon özel davranış gerektiriyorsa neden?
- Protocol sözleşmesi ihlali: implement edilen metodlar farklı exception mı fırlatıyor,
  farklı dönüş tipi mi kullanıyor?

**I — Interface Segregation Principle**
- AbstractMessenger ve AbstractLLMProvider protokolleri şişman mı?
  (Implementasyonların kullanmadığı metod var mı?)
- Command Protocol'ü (cmd_id, execute) yeterince küçük mü?

**D — Dependency Inversion Principle**
- Yüksek seviye modüller (router, feature) doğrudan düşük seviye modüllere (store, cloud_api)
  bağımlı mı, yoksa soyutlamalar üzerinden mi?
- Bağımlılık yönü: Router → Guards → Features → Store — ihlal var mı?
- Factory dışından doğrudan concrete class oluşturulan yer var mı?

**Ekstra: Genel OOP**
- God class / God module: tek başına çok fazla şey bilen modül var mı?
- Primitive obsession: dict/tuple yerine TypedDict/dataclass kullanılabilecek yer?
- Feature envy: bir modül başka modülün verisine çok sık erişiyorsa

Rapor formatı:

  ## <Prensip>
  **Genel Değerlendirme:** İyi / Orta / Zayıf
  
  | # | Önem | Dosya:Satır | İhlal / Gözlem | Öneri |
  |---|------|-------------|----------------|-------|

Önem: 🔴 Ciddi ihlal | 🟡 İyileştirme fırsatı | 🟢 Gözlem

Sonunda bir **Özet Skorkart** ekle:
  | Prensip | Durum | En Kritik Bulgu |
  |---------|-------|-----------------|
  | S | ✅/⚠️/❌ | ... |
  | O | ... | ... |
  | L | ... | ... |
  | I | ... | ... |
  | D | ... | ... |

Raporu reports/solid_analysis_<YYYY-MM-DD>.md dosyasına yaz.
Düzeltme yapma — rapor bitince dur.
```

---

## 5. Yeni `!komut` Ekleme

Yeni bir WhatsApp komutu iskeleti oluşturur ve tüm bağlantı noktalarını günceller.
Ne zaman: yeni operasyonel komut gerektiğinde.

```
99-root projesine "<KOMUT_ADI>" adında yeni bir !komut ekle.

Davranış: <KOMUTUN NE YAPACAĞINI AÇIKLA>
Yetki: Owner  (veya: Owner TOTP — yıkıcı işlemlerde)
Argüman: <VAR MI? varsa formatı>

Adımlar:
1. scripts/backend/guards/commands/<komut_adi>_cmd.py oluştur:
   - cmd_id = "!<komut-adi>"
   - label, description, usage alanlarını Türkçe doldur
   - async execute(sender: str, arg: str, session: dict) -> None implement et
   - Dosyanın sonunda registry.register(KomutSinifi()) çağır
2. guards/commands/__init__.py'ye import satırı ekle
   (mevcut satırların arasına alfabetik sıraya koy)
3. CLAUDE.md'deki komut tablosunu güncelle
4. Yetki Owner TOTP gerektiriyorsa komut sınıfına `perm = Perm.OWNER_TOTP` ekle
5. Syntax kontrolü:
   cd scripts && backend/venv/bin/python -c "from backend.main import app; print('OK')"

Kısıtlar:
- main.py veya mevcut komut dosyalarına dokunma
- .env dosyalarına dokunma
- Yetki: Owner için is_owner() zaten guards'ta kontrol ediliyor;
  TOTP gerektiren yıkıcı komutlar için Perm.OWNER_TOTP kullan (restart_cmd.py örnek al)
```

> `<KOMUT_ADI>` (örn. `status`) ve davranış açıklamasını doldur.

---

## 6. Yeni LLM / Messenger Adaptörü Ekleme

OCP uyumlu yeni platform/model adaptörü ekler.
Ne zaman: yeni LLM veya mesajlaşma platformu desteklenecekse.

```
99-root projesine yeni bir <TİP> adaptörü ekle.
TİP: LLM  (veya: Messenger)
Platform/Model adı: <PLATFORM_ADI>

## LLM adaptörü ise:
1. scripts/backend/adapters/llm/<platform>_provider.py oluştur
   - AbstractLLMProvider Protocol'ünü karşılayan sınıf yaz
   - async complete(messages, model, max_tokens) -> str implement et
   - anthropic_provider.py'yi referans al (hata yönetimi, timeout, SecretStr)
2. llm_factory.py'ye elif dalı ekle
3. config.py'ye yeni env alanları ekle (SecretStr kullan, hassas alanlar için)
4. scripts/backend/.env.example'a alanları ekle (değer yerine örnek/açıklama)
5. CLAUDE.md adaptör tablosunu güncelle
6. byok.md'ye yeni seçeneği ekle

## Messenger adaptörü ise:
1. scripts/backend/adapters/messenger/<platform>_messenger.py oluştur
   - AbstractMessenger Protocol'ünü karşılayan sınıf yaz
   - send_text, send_buttons, send_list implement et
   - telegram_messenger.py'yi referans al
2. messenger_factory.py'ye elif dalı ve singleton cache ekle
3. config.py'ye yeni env alanları ekle
4. scripts/backend/.env.example'a ekle
5. CLAUDE.md adaptör tablosunu güncelle

Her iki tip için ortak:
- Syntax kontrolü:
  cd scripts && backend/venv/bin/python -c "from backend.main import app; print('OK')"
- Kısıt: mevcut adaptör dosyalarına dokunma (OCP)
- Kısıt: .env dosyalarına dokunma
```

---

## 7. Yeni Feature Modülü Ekleme

Bağımlılık yönünü koruyarak yeni bir feature modülü ve opsiyonel endpoint ekler.
Ne zaman: yeni iş mantığı gerektiğinde.

```
99-root projesine "<ÖZELLIK_ADI>" adında yeni bir feature modülü ekle.

Açıklama: <ÖZELLIĞIN NE YAPTIĞINI AÇIKLA>
WhatsApp endpoint gerekiyor mu? <EVET / HAYIR>
/agent/* endpoint gerekiyor mu? <EVET / HAYIR>

Adımlar:
1. scripts/backend/features/<ozellik_adi>.py oluştur
   - Tüm iş mantığı burada; doğrudan sqlite3 açma — store üzerinden eriş
   - Dış HTTP gerekiyorsa httpx.AsyncClient kullan (timeout belirt)
   - Logger: logging.getLogger(__name__)
2. Gerekirse scripts/backend/store/sqlite_store.py'ye yeni tablo/sorgu ekle
   (_sync_* senkron, public async ile wrap — mevcut pattern'i izle)
3. WhatsApp endpoint gerekiyorsa whatsapp_router.py'ye minimal bağlantı ekle
   (sadece çağrı; iş mantığı features/'da kalır)
4. /agent/* endpoint gerekiyorsa personal_agent_router.py'ye ekle
   (API key kontrolü Depends(require_api_key) ile zaten var)
5. main.py'de gerekirse startup'a başlatma çağrısı ekle
6. AGENT.md özellik tablosuna ekle
7. CLAUDE.md Temel Modüller bölümüne kısa açıklama ekle
8. Syntax kontrolü:
   cd scripts && backend/venv/bin/python -c "from backend.main import app; print('OK')"

Kısıtlar:
- Bağımlılık yönü: Feature → Store (Store → Feature yasak)
- Router içinde iş mantığı yazma (DIP)
- .env dosyalarına dokunma
```

---

## 8. Bağımlılık Güncelleme Raporu

Python ve Node bağımlılıklarını tarar, güncelleme önerileri rapor olarak sunar.
Ne zaman: aylık rutin; güvenlik açığı duyurulduğunda.

```
99-root projesinin bağımlılıklarını tara ve güncelleme raporu üret.
Hiçbir dosyayı değiştirme — sadece rapor.

1. Python bağımlılıkları:
   cd scripts && backend/venv/bin/pip list --outdated 2>/dev/null

2. Node bağımlılıkları:
   cd scripts/claude-code-bridge && npm outdated 2>/dev/null

3. Her bağımlılık için değerlendir:
   - Mevcut sürüm vs. güncel sürüm
   - Major / minor / patch fark
   - Kritik güvenlik açığı var mı? (CVE varsa belirt)
   - Güncelleme kırıcı değişiklik içeriyor mu? (BREAKING CHANGE)

Rapor formatı:
  ## Python
  | Paket | Mevcut | Güncel | Fark | Risk | Not |
  |-------|--------|--------|------|------|-----|

  ## Node
  | Paket | Mevcut | Güncel | Fark | Risk | Not |

  Risk: 🔴 Güvenlik açığı | 🟠 Major (kırıcı) | 🟡 Minor | 🟢 Patch

  ## Önerilen Eylemler
  Öncelik sırasına göre güncelleme adımları.

Raporu reports/deps_<YYYY-MM-DD>.md dosyasına yaz.
```

---

## 9. WORK_LOG.md Güncelleme

Tamamlanan geliştirme oturumunu WORK_LOG'a ekler.
Ne zaman: her geliştirme oturumu sonunda.

```
Bu oturumda yapılan değişiklikleri WORK_LOG.md'ye kaydet.

Format:
  ### <ID> — <Başlık>
  **Tarih:** <YYYY-MM-DD>
  **Durum:** ✅ Tamamlandı

  #### <Alt başlık>
  **Sorun:** ...
  **Çözüm:** ...
  **Dosya(lar):** `...`

Yerleştirme kuralı:
- Yeni giriş en son oturum girişinin hemen altına, "Mevcut Servis Durumu"
  bölümünün üstüne ekle.
- Kronolojik sıra korunmalı.

İçerik kuralları:
- "Ne yapıldı" değil, "neden yapıldı / ne sorunu çözdü" odaklı yaz
- Kodda zaten görünen teknik detayları tekrarlama
- .env içeriğine, secret değerlerine değinme
- Her alt başlık bağımsız okunabilir olmalı
```

---

## 11. GUARDRAILS Boşluk Araştırması

Mevcut GUARDRAILS.md'yi inceler; henüz kapsanmamış özgün yıkıcı komut vektörlerini araştırır.
Ne zaman: yeni saldırı teknikleri duyurulduğunda; 3 ayda bir rutin.

```
GUARDRAILS.md'yi derinlemesine incele ve henüz kapsanmamış özgün yıkıcı komut
vektörlerini araştır. Yalnızca rapor üret — GUARDRAILS.md'yi değiştirme.

## Adım 1 — Mevcut kapsam haritası
GUARDRAILS.md'yi oku. Her kategoriyi bir cümleyle özetle:
  KATEGORİ N → "Ne tür tehdidi kapsıyor?"

## Adım 2 — Araştırma alanları
Aşağıdaki her vektör için "mevcut kategorilerde karşılığı var mı?" sorusunu sor.
Yoksa veya yetersizse boşluk olarak işaretle:

1. **Dolaylı yürütme**
   - Alias / shell fonksiyon override: `alias rm='rm -rf /'`
   - PATH manipülasyonu: `export PATH=/tmp/evil:$PATH`
   - `.bashrc` / `.profile` / `.bash_profile` kalıcı enjeksiyonu
   - Shebang inject: `#!/bin/bash\n<yıkıcı komut>` içeren script oluşturma

2. **Ortam değişkeni manipülasyonu**
   - `LD_PRELOAD` ile kütüphane enjeksiyonu
   - `PYTHONSTARTUP` ile Python başlangıç kod enjeksiyonu
   - `SUDO_ASKPASS` ile şifre yakalama

3. **Disk tükenmesi**
   - `dd if=/dev/urandom of=/bigfile bs=1M` (sınırsız yazma)
   - `fallocate -l 100G /tmp/fill`
   - Sembolik döngü: `ln -s / /tmp/loop`

4. **Kernel / donanım doğrudan erişimi**
   - `modprobe` / `insmod` — kernel modül yükleme
   - `/dev/mem` / `/dev/kmem` okuma/yazma
   - `perf` / `bpftrace` — kernel tracing (veri sızdırma)
   - `sysctl -w` — kernel parametresi değiştirme

5. **Süreç enjeksiyonu**
   - `ptrace` ile çalışan sürece inject
   - `/proc/<PID>/mem` yazma

6. **Ağ altyapısı manipülasyonu**
   - ARP spoofing: `arpspoof`, `arping`
   - DNS zehirleme: `/etc/hosts` override
   - Gizli veri sızdırma: `curl --data @/etc/shadow`, `nc -e /bin/bash`
   - Tünel: `ssh -R`, `socat`, `ngrok` yetkisiz tüneller

7. **Zamanlama tabanlı kalıcılık**
   - `at` komutu ile tek seferlik zamanlama
   - `crontab -e` ile kalıcı arka kapı
   - `systemd --user` ile kullanıcı seviyesi servis kurma

8. **Swap / bellek manipülasyonu**
   - `swapoff -a` → bellek baskısı
   - `swapon /tmp/swapfile` → rastgele alan swap olarak işaretleme
   - `/proc/sys/vm/drop_caches` ile disk önbellek temizleme

9. **Container/sandbox kaçış** (Docker/LXC ortamında çalışıyorsa)
   - `--privileged` ile container dışı erişim
   - `/proc/1/ns/` namespace geçişi
   - `docker.sock` üzerinden ana makinede container başlatma

10. **Obfuscation / encoding bypass**
    - `$(echo 'cm0gLXJm' | base64 -d)` tarzı encode
    - Hex escape: `$'\x72\x6d'`
    - Boşluk inject: `r''m -rf`
    - `$IFS` ile alan ayracı bypass

## Adım 3 — GUARDRAILS.md'yi güncelle
Her boşluk için doğrudan GUARDRAILS.md'ye yeni kategori ekle:

- Mevcut son KATEGORİ numarasını bul (GUARDRAILS.md sonuna bak).
- Her yeni vektör için bir `## KATEGORİ N — <Başlık>` bloğu yaz:
  ```
  ## KATEGORİ N — <Başlık>

  > Blast radius: <etki alanı>

  \`\`\`bash
  <örnek komutlar>
  \`\`\`

  **Neden tehlikeli:** <1-2 cümle açıklama>

  ---
  ```
- Zaten kapsanan vektörleri tekrar ekleme — önce mevcut kategorileri Grep ile tara.
- ÖZET TABLOSU bölümü varsa oraya da yeni satır ekle.

Ekleme bittikten sonra sadece kaç kategori eklendiğini ve başlıklarını yaz. Rapor dosyası oluşturma.
```

---

## 10. Rapor Temizleme (done/)

Giderilmiş veya BACKLOG'a aktarılmış raporları arşivler.
Ne zaman: BACKLOG maddeleri tamamlandıktan sonra.

```
reports/ dizinindeki raporları incele ve arşivlenecekleri belirle.

Kural: Bir rapordaki TÜM bulgular şu koşullardan birini sağlıyorsa arşivle:
  a. BACKLOG.md'de ✅ Tamamlanan'a taşındı
  b. GUARDRAILS.md veya CLAUDE.md'ye kural olarak eklendi
  c. Bilinçli olarak "kabul edildi / yapılmayacak" kararı verildi

Adımlar:
1. reports/ içindeki .md dosyalarını oku (done/ hariç)
2. Her dosya için BACKLOG.md ✅ Tamamlanan bölümüyle karşılaştır
3. Arşivlenecek dosyaları listele ve onay iste
4. Onay gelirse: dosyayı reports/done/ altına taşı
   (Bash: mv reports/<dosya>.md reports/done/<dosya>.md)
5. Kısmen tamamlanmış raporlar için: tamamlanan bulgular rapordan silinebilir,
   kalanlar yerinde kalır

Kısıtlar:
- Onaysız taşıma yapma
- done/ altındaki dosyalara dokunma
```
