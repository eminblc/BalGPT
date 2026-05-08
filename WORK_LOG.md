# WORK_LOG.md — 99-root Kişisel AI Ajan

Geliştirme geçmişi bu dosyada tutulur.

---

### BACKUP-1..11 — Export/Import + Şifreleme + Otomatik Yedek + Rotasyon
**Tarih:** 2026-05-08 → 2026-05-09
**Dosya(lar):** `scripts/backend/features/backup/` (yeni paket), `scripts/backend/features/export_service.py`, `scripts/backend/features/import_service.py`, `scripts/backend/guards/commands/export_cmd.py`, `scripts/backend/guards/commands/import_cmd.py`, `scripts/backend/routers/_backup_import_handler.py`, `scripts/backend/routers/api/backup_api.py`, `scripts/backend/config.py`, `scripts/backend/app_types.py`, `scripts/backend/features/scheduler.py`, `scripts/backend/routers/_dispatcher.py`, `scripts/backend/routers/_media_handlers.py`, `scripts/backend/guards/commands/__init__.py`, `scripts/backend/locales/{tr,en}.json`, `scripts/tests/test_backup_*.py`, `scripts/tests/test_export_service.py`, `scripts/tests/test_import_service.py`

**Sorun:** Yedekleme yoktu; veritabanı hasarı veya taşıma durumunda tüm konuşma geçmişi, takvim, plan ve proje verileri kayboluyordu.

**Çözüm (11 aşama):**
- *BACKUP-1/2/3:* `backup/` paketi iskelet + msgpack tabanlı `BackupWriter`/`BackupReader` + `DbExporter`/`ExportService` (30 unit test).
- *BACKUP-4/5:* `DbImporter`/`ImportService` + `LocalFileExporter`/`LocalFileImporter` — path traversal koruması, `.bak` yedek mekanizması (43+37 unit test).
- *BACKUP-6:* REST API — `POST /agent/export`, `POST /agent/import`, `GET /agent/export/status` (23 unit test).
- *BACKUP-7:* `/export` + `/import` komutları; `_backup_import_handler.py`; Telegram document handler (OCP-MSG `_dispatcher`'a eklendi) (30 unit test).
- *BACKUP-8:* `DATA_DIR` env + `settings.resolved_data_dir` — fabrikalar artık dinamik veri dizini kullanıyor.
- *BACKUP-9:* AES-256-GCM şifreleme — `_cipher.py` (SRP), v2 format writer/reader, `BACKUP_ENCRYPTION_KEY` config (15 unit test, 904 toplam).
- *BACKUP-10:* `AutoBackupJob` + `scheduler.py` cron kaydı + `AUTO_BACKUP_ENABLED/CRON` config (7 unit test, 911 toplam).
- *BACKUP-11:* `BackupRotationManager` (`_rotation.py`) + `BACKUP_RETENTION_DAYS` config + `AutoBackupJob` entegrasyonu (15 unit test, 926 toplam).

**Mimari kararlar:**
- Tüm `backup/` modülleri Protocol tabanlı (SRP): `_protocol.py` (ExportScope, BackupManifest), `_writer.py`, `_reader.py`, `_cipher.py`, `_rotation.py`, `_auto_backup.py`.
- Şifreleme opsiyonel: anahtar yoksa düz msgpack, varsa AES-256-GCM v2 format (magic byte + nonce + ciphertext).
- Rotasyon tarih-tabanlı: `BACKUP_RETENTION_DAYS` gün öncesi yedekler silinir; `AutoBackupJob` her yedek sonrası çalıştırır.
- Telegram dosya indirme: `_dispatcher._download_telegram_file()` ile Bot API'den file_id'ye göre byte stream indirilir.
- `app_types.py`'e `pending_backup_import` alanı eklendi (`SessionState`).

**Test:** 926 test geçti (tamamı). Python import + Node syntax OK. CI uyumlu.

**Durum:** ✅ Tamamlandı

---

### MSG-UI-1/2 — WhatsApp/Telegram bildirim iyileştirmeleri
**Tarih:** 2026-05-09
**Dosya(lar):** `scripts/claude-code-bridge/server.js`, `scripts/backend/adapters/messenger/telegram_messenger.py`, `scripts/backend/adapters/messenger/__init__.py`, `scripts/backend/routers/_bridge_client.py`

**Sorun:** Telegram'da uzun yanıtlarda kullanıcı hiçbir geri bildirim alamıyordu; WhatsApp bildirim örnekleri teknik ve soğuktu.

**Çözüm:**
- *MSG-UI-2:* `TypingMessenger` protokolü (`__init__.py`), `TelegramMessenger.send_typing()` (Telegram `sendChatAction` API), `_typing_loop()` async görevi (`_bridge_client.forward()`'da `asyncio.create_task`) — Bridge yanıtı gelene kadar her 4 saniyede bir typing yenilenir.
- *MSG-UI-1:* `server.js` init_prompt'unda bildirim örnekleri "Dosyayı okuyorum…, Bakıyorum…, Düşünüyorum…, Test çalıştırıyorum…, Kodu güncelliyorum…" şeklinde güncellendi.

**Durum:** ✅ Tamamlandı

---

### TG-WIZ-1 — Telegram Stage-2 install wizard
**Tarih:** 2026-04-27
**Dosya(lar):** `install.sh`, `lib/wizard.sh`, `lib/steps.sh`, `lib/messenger.sh`, `locales/install_{tr,en}.json`, `scripts/backend/features/install_wizard/*`, `scripts/backend/store/repositories/install_wizard_repo.py`, `scripts/backend/store/sqlite_store.py`, `scripts/backend/guards/commands/{wizard_cmd,cancel_cmd}.py`, `scripts/backend/routers/{_dispatcher,_text_router}.py`, `scripts/backend/locales/{tr,en}.json`, `scripts/tests/test_install_wizard.py`

**Sorun:** `install.sh` Telegram dalı 6+ terminal sorusuyla uzundu; eski "in-bot wizard" install ortasında Python alt-süreci ile soruları Telegram'a iletip secret'lar için terminal-Python köprüsü kullanan kırılgan bir akıştı.

**Çözüm:** İki aşamalı tasarım:
- *Stage-1 (terminal):* Sadece bot token + ngrok auth token + ngrok domain. Validation eklendi (token alfanümerik 16+, domain'de nokta). `WEBHOOK_PROXY=ngrok` zorlanıyor; LLM/TZ/capabilities için sensible default'lar yazılıyor (Anthropic, Europe/Istanbul, core caps açık + desktop/browser kapalı).
- *Stage-2 (Telegram):* `install.sh` containerlar başladıktan sonra webhook kaydı başarılı olunca welcome mesajı atıyor. Kullanıcı `!wizard` ile inline-button akışını başlatıyor: LLM → (Anthropic auth | Ollama URL/model | Gemini key) → capabilities multi-select → timezone → finalize. Finalize: `.env`'i atomik yazıp TOTP QR PNG'lerini Telegram'a gönderiyor, "docker compose restart" diyor.

**Mimari kararlar:**
- State persistence: yeni `install_wizard_state` SQLite tablosu + `install_wizard_repo` (mevcut StoreProtocol/repositories desenine uyumlu — hiçbir modül `sqlite3`'ü doğrudan açmıyor).
- Routing entegrasyonu: `_dispatcher._route_interactive`'e `iw:` callback prefix early-return eklendi (OCP), `_text_router._route_text`'e wizard awaiting_text intercept eklendi. Webhook handler/menu.py değişmedi.
- env_writer: `lib/env.sh:_env_set` ile format-uyumlu (KEY=VAL satırları, comment/blank satır korunur, `os.replace` ile atomik).
- Eski in-bot wizard tamamen silindi: `setup_wizard_messenger.py`, `_run_messenger_wizard`, `_apply_wiz_to_env`, `_collect_terminal_secrets` ve ilgili `MSG_WIZ_TG_NOTIFY/STARTING/WAIT/DONE/FAIL/TIMEOUT_DEFAULTS` + `TXT_WIZ_*` locale anahtarları. WhatsApp akışı dokunulmadı.

**Test:** 20 yeni unit test (`test_install_wizard.py`), tüm 726 mevcut test geçti, locale parity OK, Python import + Node syntax OK. CI'da bats + shellcheck koşacak (TG-WIZ-3).

**Not:** Backlog'a TG-WIZ-2 (uçtan uca manuel test), TG-WIZ-3 (CI doğrulama), TG-WIZ-4 (ngrok regex iyileştirme) eklendi.

**Durum:** ✅ Tamamlandı

---

Format:
```
### [ID] — [Başlık]
**Tarih:** YYYY-MM-DD
**Dosya(lar):** `yol`
**Sorun:** ...
**Çözüm:** ...
**Durum:** ✅ Tamamlandı / ⏳ Yarım
```

---

### INIT — Proje iskelet kurulumu
**Tarih:** 2026-04-11  
**Yapılanlar:**
- [x] Dizin yapısı oluşturuldu
- [x] CLAUDE.md, AGENT.md, BACKLOG.md, WORK_LOG.md yazıldı
- [x] FastAPI iskelet (main.py, config.py, requirements.txt)
- [x] SQLite store şeması (sqlite_store.py)
- [x] guards/ modülleri
- [x] Claude Code Bridge
- [x] whatsapp_router.py iskelet
- [x] features/ iskelet dosyaları  
**Durum:** ✅ Tamamlandı

---

### S01 — Beta modu + WMA entegrasyonu (2026-04-11)

Bu oturumda yapılan tüm değişiklikler:

#### 1. Beta Modu Mimarisi — Yeniden Tasarlandı

**Sorun:** Beta modunda mesajlar 99-root bridge'ine gidiyor, Claude generic yanıt veriyordu.  
**Çözüm:** Beta modu artık doğrudan projenin kendi FastAPI'sine yönlendiriyor.

**Akış:**
```
WhatsApp → 99-root (8010)
  ├─ !beta-exit    → yerel (session temizle, ana moda dön)
  ├─ !<komut>      → yerel handler (99-root'un kendi butonları/listesi)
  └─ düz metin     → projenin FastAPI'si (WMA için: localhost:8000/whatsapp/internal/message)
       └─ WMA kendi pipeline'ını çalıştırır (!help, !ask, n8n, bridge...)
```

**Dosyalar:**
- `scripts/backend/routers/whatsapp_router.py` → `_route_text` ve `_forward_to_bridge` yeniden yazıldı
- Beta modunda proje metadata'sından `api` servisi bulunur, `http://localhost:{port}/whatsapp/internal/message` çağrılır

#### 2. WMA — `/internal/message` Endpoint Eklendi

**Dosya:** `10-base/whatsapp-memory-agent/scripts/backend/routers/whatsapp_router.py`

```python
@router.post("/internal/message")
async def internal_message(req: _InternalMessageRequest):
    """99-root beta modundan gelen direkt mesajlar — guard zinciri atlanır."""
```

- Guard'ları (dedup, blacklist, permission) atlar
- Doğrudan `_handle_message` çağırır
- `_OPEN_PATHS`'e eklendi (API key middleware'i atlar)

#### 3. WMA — `!root` Komutu Kaldırıldı

**Dosya:** `10-base/whatsapp-memory-agent/scripts/backend/guards/commands/__init__.py`

- `root.py` import'u kaldırıldı → `!root`, `!root-exit`, `!root-reset` artık çalışmaz
- 99-root bu görevi devraldı

#### 4. Bridge — `project_path` (CWD) Desteği

**Dosya:** `scripts/claude-code-bridge/server.js`

- `/query` endpoint'i artık `project_path` parametresi kabul ediyor
- Claude, projenin kendi dizininde (`cwd = project_path`) başlatılıyor
- Ana mod için geri uyumlu (project_path boşsa ROOT_DIR kullanılır)

#### 5. `!history` Komutu Eklendi

**Dosya:** `scripts/backend/guards/commands/history_cmd.py`

- `!history [N]` → son N mesaj (default 15)
- `!history özet` → session özetleri

#### 6. menu.py — Eksik Handler'lar Eklendi

**Dosya:** `scripts/backend/features/menu.py`

- `project_info_` → proje detayları (isim, yol, servisler)
- `menu_history` → son mesajlar
- `menu_task_add` → görev ekleme modu
- `menu_tasks` → aktif görevler listesi

#### 7. Hata Mesajı İyileştirmesi

Beta modunda proje servisleri kapalıysa:
> ⚠️ *WhatsApp Memory Agent* servisleri kapalı.  
> Başlatmak için: Projeler → WhatsApp Memory Agent → Başlat

#### 8. `start_project_services` Düzeltmesi

**Dosya:** `scripts/backend/features/projects.py`

**Sorunlar:**
1. Her "Başlat"ta yeni tmux penceresi açılıyordu (duplicate)
2. `cwd` metadata alanı kullanılmıyordu → komutlar yanlış dizinde çalışıyordu

**Çözüm:**
- Pencere varsa: C-c → yeniden başlat
- Pencere yoksa: yeni aç
- `work_dir = project_dir / svc["cwd"]` kullanılıyor

**WMA servis dizinleri:**
- API: `scripts/` (`backend/venv/bin/python3 -m uvicorn backend.main:app ...`)
- Bridge: `scripts/claude-code-bridge/` (`node server.js`)

#### 9. Temizlik

- Fazla açılmış tmux pencereleri (wma-api, wma-bridge duplikaları) kaldırıldı
- WMA `root.session` import'u kaldırıldı

---

---

### S02 — Beta mod routing düzeltmesi + MD güncelleme (2026-04-12)

#### 1. Beta Modunda `!` Komut Routing Düzeltmesi

**Sorun:** Beta modunda `!help`, `!ask` gibi komutlar 99-root'un yerel handler'larına gidiyordu; kullanıcı WMA'nın kendi menüsünü göremiyordu.  
**Çözüm:** `_route_text` yeniden yazıldı:
- Beta modunda: `!beta-exit` → yerel; diğer HER mesaj (`!` ile başlayanlar dahil) → projenin FastAPI'si
- Ana modda: `!` komutları yerel; düz metin → bridge (önceki davranış korundu)

**Dosya:** `scripts/backend/routers/whatsapp_router.py`

#### 2. `help_cmd.py` Güncelleme

- Beta modu bilgi satırı kaldırıldı (artık !help beta'ya ulaşmıyor)
- Fallback metin: `!project` eklendi, `!takvim`/`!status` kaldırıldı
- Liste menüsüne "📌 Proje Seç (`!project`)" satırı eklendi

#### 3. MD Dosyaları Güncellendi

- `AGENT.md` — Tüm özellik statüleri `🔴 Yapılacak` → `✅ Tamamlandı`; yeni özellikler eklendi
- `BACKLOG.md` — S01 ve S02 tamamlanan işler eklendi; OPS-3/4 açık eylemler güncellendi
- `WORK_LOG.md` — Bu giriş

#### 4. Bridge Path Traversal Fix (önceki oturumdan tamamlandı)

**Dosya:** `scripts/claude-code-bridge/server.js`  
`PROJECTS_DIR` altında olma kısıtı kaldırıldı; `..` segment + dizin varlık kontrolü yeterli.  
WMA ve diğer projeler için `project_path` artık geçerli sayılıyor.

**Durum:** ✅ Tamamlandı

---

---

### S03 — Bridge conv_history + WMA başlatma bug fix'leri (2026-04-12)

#### 1. Bridge — Yerel Konuşma Geçmişi (conv_history)

**Sorun:** Oturum sıfırlandıktan (`--resume` olmadan yeni süreç) sonra Claude önceki konuşmayı hatırlamıyordu.  
**Çözüm:** `server.js`'e `data/conv_history/{sessionId}.json` tabanlı hafif konuşma geçmişi eklendi.

- Her tur sonunda kullanıcı + asistan mesajı dosyaya yazılır (max `CONV_MAX_TURNS = 8` tur)
- Yeni sorgu başlarken `loadConvHistory` → `formatConvHistory` → `buildInitPrompt`'a eklenir
- Mesajlar 2000 karakter ile sınırlı (bağlam şişmesini önler)

**Dosya:** `scripts/claude-code-bridge/server.js`

#### 2. WMA Metadata — `2>&1` Kaldırıldı

**Sorun:** WMA servislerinin DB'deki komutları (`...port 8000 2>&1`) `_validate_service_cmd` regex'ini tetikliyordu.  
`>` ve `&` karakterleri tehlikeli shell operatörü olarak reddedilip `continue` ile atlanıyordu → "Başlat" sessizce çalışmıyordu.  
**Çözüm:** `data/personal_agent.db`'deki WMA metadata'sından her iki servis komutunun `2>&1` kısmı kaldırıldı.

**Dosya:** `data/personal_agent.db` (SQLite UPDATE — doğrudan DB)

#### 3. projects.py — Tmux `has-session` Fix

**Sorun:** `start_project_services` içinde `tmux new-window -t services -n wma-api` çağrılıyordu fakat `services` session yoksa `new-window` hata döndürüp duruyordu.  
**Çözüm:** Her servis döngüsüne `tmux has-session -t services` kontrolü eklendi:
- Session yoksa → `tmux new-session -d -s services -n {window}` ile session + ilk pencere birlikte oluşturuluyor
- Session varsa → pencere yoksa sadece `new-window`, pencere varsa sadece `C-c` + komut gönder

**Dosya:** `scripts/backend/features/projects.py`

**Durum:** ✅ Tamamlandı  
**Not:** Değişikliklerin devreye girmesi için `personal-agent.service` yeniden başlatılmalı.

---

---

### S04 — Güvenlik taraması bulgularının düzeltilmesi (2026-04-12)

#### Düzeltilen Bulgular (7 adet)

**SEC-C1 (Kritik) — Port integer doğrulaması**  
`features/projects.py` → `stop_project_services`: `port` değeri `fuser -k {port}/tcp`'ye geçmeden önce `int()` dönüşümü + 1-65535 aralık kontrolü eklendi.

**BUG-H1 (Yüksek) — `services` liste tipi doğrulaması (projects.py)**  
`start_project_services` ve `stop_project_services`: `meta.get("services")` sonucu `isinstance(list)` kontrolünden geçirilmeden döngüye girilmiyordu. Şimdi geçersiz tipte uyarı logu + erken dönüş var.

**BUG-H2 (Yüksek) — `services` liste tipi doğrulaması (menu.py)**  
`project_info_` branch: aynı kontrol + her eleman `isinstance(dict)` filtresi eklendi.

**SEC-H3 (Yüksek) — `/agent/*` rate limiting**  
`guards/api_rate_limiter.py` (yeni dosya): IP tabanlı 60 istek/dakika sliding window.  
`routers/personal_agent_router.py`: `Depends(require_api_rate_limit)` eklendi.

**BUG-M1 (Orta) — TOCTOU race condition (session.py)**  
`cleanup_expired`: Önce tüm key'ler `list()` ile alınıyor, döngüde her key için `_is_expired` tekrar kontrol ediliyor; bu sayede aradaki erişim sonrası aktif hale gelen session'lar temizlenmiyor.

**BUG-M2 (Orta) — `project_id` karakter doğrulaması (menu.py)**  
`reply_id`'den çıkarılan tüm `project_id` değerleri `^[a-zA-Z0-9_-]{1,64}$` regex'i ile doğrulanıyor.

**BUG-M3 (Orta) — JSON parse hatası (pdf_importer.py)**  
`json.JSONDecodeError` artık `logger.warning` ile loglanıyor; sessizce atlanmıyor.

**Durum:** ✅ Tamamlandı  
**Not:** Değişikliklerin devreye girmesi için `personal-agent.service` yeniden başlatılmalı.

---

### APR-14 — Büyük Güvenlik, Refactor ve Platform Genişletme Oturumu
**Tarih:** 2026-04-14
**Durum:** ✅ Tamamlandı

#### Güvenlik (SEC-A serisi)
- `config.py` — 7 hassas alan `SecretStr` yapıldı
- `_verify_signature` — production'da boş `app_secret` isteği reddediyor
- `_UNSAFE_CMD_RE` — `\n`, `\r`, `\x00` eklendi (tmux multi-line injection)
- TOTP sayacı SQLite'a taşındı (`totp_lockouts` tablosu)
- `output_filter.py` — 13 yeni kural
- `awaiting_admin_totp` + `awaiting_totp` iptal dalları lock altına alındı
- `tmux_window` adı `_WINDOW_NAME_RE` ile doğrulanıyor
- GUARDRAILS.md 46→49 kategori

#### Buglar (BUG-A serisi)
- `svc.get("tmux_window")` None skip, `isinstance(svc, dict)` per-eleman kontrolü
- Admin TOTP sonrası sonsuz döngü — registry'den direkt execute'a geçildi
- `cloud_api.py` syntax hatası düzeltildi (decorator yanlış konumdaydı)

#### Refactor (REF serisi)
- `whatsapp_router.py` 932 → 448 satır; `_bridge_client.py`, `_intent_classifier.py`, `_auth_flows.py`, `_media_handlers.py` çıkarıldı
- `TmuxServiceExecutor` + `ServiceValidator` izole edildi
- `STATUS_EMOJI` → `app_types.PROJECT_STATUS_EMOJI` SSOT

#### Platform Genişletme (G/PORT serisi)
- Docker Compose: `Dockerfile.api`, `Dockerfile.bridge`, `docker-compose.yml`
- Telegram adaptörü: `adapters/messenger/`; LLM factory: `adapters/llm/` (Anthropic/Ollama/Gemini)
- Webhook proxy: `features/webhook_proxy.py` (ngrok/cloudflared/external/none)
- `CONTRIBUTING.md` + GitHub Actions CI
- Railway/Render deploy şablonları; `byok.md`, `vps.md`, `raspberry-pi.md`

#### Bridge İyileştirmeleri (BR/RR serisi)
- `server.js` crash handler'ları + FastAPI watchdog (3 hata → otomatik restart)
- `restart_cmd.py` — `asyncio.create_subprocess_exec`
- Bridge ConnectError retry (2s + 4s, max 3 deneme)
- `DedupGuard` → SQLite kalıcılığı; çıkış oranı sınırlayıcı

---

---

### APR-16 — Kapsamlı Güvenlik ve Güvenilirlik Audit Düzeltmeleri
**Tarih:** 2026-04-16
**Durum:** ✅ Tamamlandı

Kaynak: `reports/full_audit_2026-04-15.md`

#### Düzeltilen Maddeler (24 adet)

**AUD-D1 — `/health` endpoint DB/scheduler kontrol**  
`main.py` — `db_ping()` + `_scheduler.running` alanları eklendi; health yanıtı artık `db` ve `scheduler` durumunu içeriyor.

**AUD-D6 — `cloud_api.py` outbound lock bellek sızıntısı**  
`_evict_outbound()` + `_OUTBOUND_TTL=3600s` eklendi; lock/last diktleri her çağrıda temizleniyor.

**AUD-D12 — `sqlite_store.py` proje ID doğrulaması yok**  
`_PROJECT_ID_RE = ^[a-z0-9][a-z0-9\-]{0,62}$`; geçersiz ID'de `ValueError` fırlatıyor.

**AUD-O5 — `api_rate_limiter.py` dict sınırsız büyüme**  
`RateLimiter._cleanup()` eklendi; `_CLEANUP_INTERVAL=300s`, `_ENTRY_TTL=120s` ile lazy eviction.

**AUD-O7 — `/agent/project/{id}/beta` sender doğrulanmıyor**  
`personal_agent_router.py` — `settings.whatsapp_owner` karşılaştırması; yetkisiz sender'a 403.

**AUD-O9 — `output_filter.py` eval/exec false positive**  
Broad pattern → obfuscation odaklı regex: `base64`, `__import__`, `compile`, `bytes`, `chr` içerenler engellenir.

**AUD-O11 — `personal_agent_router.py` Store doğrudan erişimi (DIP)**  
`features/projects.py`'ye `list_projects()` wrapper eklendi; router artık features katmanını kullanıyor.

**AUD-O12 — `chat.py` Bridge reset sessiz başarısız**  
`reset_bridge_session` → `bool` döndürür; `logger.error` + `!root-reset` hata mesajı WhatsApp'a iletiliyor.

**AUD-O13 — `scheduler.py` shutdown(wait=False) job kesiyor**  
`wait=True` + 5s timeout `asyncio.to_thread` ile; timeout'ta `wait=False` fallback.

**AUD-O17 — `whatsapp_router.py` yetkisiz sender mesaj önizlemesi**  
Kasıtlı güvenlik bildirimi olarak belgelendi; preview 100 karakter ile sınırlandı.

**AUD-O18 — `session.py` lock cleanup race condition**  
`lock.locked()` kontrolü eklendi; tutulu lock'lar cleanup sırasında silinmiyor.

**AUD-O19 — `runtime_state.py` `_last_status` sınırsız büyüme**  
`_maybe_evict()` + `_STATUS_TTL=1800s` + `_STATUS_CLEANUP_IV=300s` ile lazy eviction.

**AUD-O20 — Media indirmede bellek sınırı yok**  
`_MAX_MEDIA_BYTES=50MB`; metadata `file_size` + indirme sonrası çift kontrol.

**AUD-O21 — `menu.py` `s['name']` KeyError**  
`s.get('name','?')` ile korundu.

**AUD-O22 — `message_logger.py` msg_count semantik hatası**  
`_sync_message_count_since(sender, started_at)` eklendi; session başlangıcından itibaren sayıyor.

**AUD-O23 — `scheduler.py` resume_cron_job sessiz exception**  
İç try/except + `logger.error`; hata durumunda erken dönüş.

**AUD-O24 — `server.js` scheduler WhatsApp rate limit**  
`silent` parametresi eklendi; `_run_bridge_query(silent=True)` ile ⚙️ bildirimi scheduler çağrılarında atlanıyor.

Diğer (dokümantasyon):
- `AUD-D9`, `AUD-D10`, `AUD-D13` — yorum/belge ile açıklandı
- `DOC-*` serisi (V1, R1, C1, M1, B1, RT1, A1, W1, PI1) — ilgili .md dosyaları güncellendi

---

---

### APR-17 — i18n audit, .gitignore ve .md güncellemeleri
**Tarih:** 2026-04-17  
**Yapılanlar:**
- i18n audit tamamlandı: eksik alanlar bulunup giderildi
  - `whatsapp_router.py` — `session_mgr.get(sender)` `GuardContext` öncesine taşındı; `lang` artık guard zincirine doğru geçiyor
  - `_bridge_client.py` — `_error_message()` + `forward()` + `forward_document()`: `lang` parametresi eklendi, 4 hard-coded string `t()` ile değiştirildi
  - `chat.py` — `send_to_bridge()` `lang` parametresi aldı, hard-coded hata mesajları `t()` ile değiştirildi
  - `project_service.py` — `start_project_services()` + `stop_project_services()` `lang` parametresi aldı, ~10 f-string `t("project_svc.*")` ile değiştirildi
  - `wizard_steps.py` — ~25 hard-coded Turkish string `t("wizard.*")` ile değiştirildi
  - `wizard_core.py` — `cancel_wizard()` `t("wizard.cancelled")` kullanıyor
  - `menu_project.py` — `lang` session'dan okunarak servis fonksiyonlarına geçiriliyor
  - `tr.json` + `en.json` — `wizard.*`, `project_svc.*`, `bridge.*`, `chat.*` namespace'leri eklendi
- `.gitignore` güncellendi: `data/blacklist.json`, `**/__pycache__/`, `.pytest_cache/`, `.claude/`, `reports/` eklendi
- Tüm .md dosyaları audit edildi ve güncellendi (CLAUDE.md, README.md, README.tr.md, AGENT.md, BACKLOG.md, CHANGELOG.md, CONTRIBUTING.md)  
**Durum:** ✅ Tamamlandı

---

### APR-22 — SOLID/OOP İyileştirmeleri v2 (7 görev)
**Tarih:** 2026-04-22
**Durum:** ✅ Tamamlandı

Kaynak: `reports/oop_solid_analysis_2026-04-22.md` — Genel puan: 8.7/10 (A-).

#### Düzeltilen Maddeler

**SOLID-v2-1 — DIP ihlali: `_auth_flows.py`**
`routers/_auth_flows.py` — doğrudan `sqlite_store` import → `sqlite_wrapper.store` ile değiştirildi (2 yer).

**SOLID-v2-2 — DIP ihlali: `_bridge_client.py`**
`routers/_bridge_client.py` — 2 async yer `sqlite_wrapper.store` ile, 1 sync yer `project_repo._sync_project_get` ile değiştirildi.

**SOLID-v2-3 — SRP: Port keşfi tekrarı**
`_discover_project_api_port()` helper'ı `_bridge_client.py`'ye eklendi; `_dispatcher.py` ve `_bridge_client.py`'deki 3 tekrar kaldırıldı.

**SOLID-v2-4 — SRP: Feature startup hook'ları**
5 hook fonksiyonu `_registry.py`'den ilgili modüllere (`webhook_proxy`, `scheduler`, `browser`) `lifecycle_startup/shutdown` olarak taşındı; registry lazy import ile referans eder.

**SOLID-v2-5 — Encapsulation: SessionState wizard wrapper'ları**
`app_types.py` — 13 yeni wizard wrapper metot: `clear_wizard()`, `is_wizard_active()`, `set_wiz()`, `start/clear_wizard_path()`, `start/clear_wizard_service_name()`, `start/clear_wizard_service_cmd()`, `set_wizard_options()`, `add_wizard_service()`. Tüm `wiz_*` ve wizard `awaiting_*` anahtarları `_CONTROLLED_KEYS`'e alındı.

**SOLID-v2-6 — SRP: `desktop_router.py` bölünmesi**
Vision handler'ları (4 handler) → `_desktop_vision.py`; capture handler'ları (3 handler) → `_desktop_capture.py`. Ana dosya 995→726 satır.

**SOLID-v2-7 — ISP: `StoreProtocol` bölünmesi**
Monolitik `StoreProtocol` (199 satır) 9 domain-spesifik sub-protocol'e bölündü: `ProjectStoreProtocol`, `PlanStoreProtocol`, `EventStoreProtocol`, `TaskStoreProtocol`, `MessageStoreProtocol`, `SessionStoreProtocol`, `BridgeStoreProtocol`, `TotpStoreProtocol`, `DedupStoreProtocol`. `StoreProtocol` tümünden kalıtır (geriye uyumlu).

---

### APR-18 — Büyük Bug, Güvenlik ve Test Oturumu

**Tarih:** 2026-04-18

#### Güvenlik (SEC-H, SEC-M)
- Admin TOTP brute-force koruması (3 deneme → 15 dk kilit), rate limiter IP spoofing yaması, symlink path traversal, HMAC/Telegram secret dev bypass
- API key startup kontrolü, hata detay sızıntısı giderildi, Bridge mesaj sanitize, CORS startup doğrulaması

#### Bug Fix (BUG-H, BUG-M, BUG-C)
- Path traversal: `allowedRoots` kontrolü Bridge'e eklendi
- Math cancel sonrası session corruption giderildi
- Internal router timestamp bug, Telegram conv_history asimetri, Playwright kaynak sızıntısı, session TOCTOU
- `import time` eksik (NameError), bare `send_text` çöküşü (3 dosya)

#### Testler (TEST-1..11)
- Guard, command, adapter, feature, router, desktop, browser unit/entegrasyon testleri eklendi

**Durum:** ✅ Tamamlandı

---

### APR-19 — Büyük Refactor, Modüler Ajan ve Optimizasyon Oturumu

**Tarih:** 2026-04-19

#### Modüler Ajan (MOD-1, MOD-3..10)
- Router kayıtları koşullu hale getirildi (`DESKTOP_ENABLED`, `BROWSER_ENABLED`, `TERMINAL_ENABLED` flag'leri)
- Feature manifest / plugin registry sistemi: `features/_registry.py`, lifecycle startup/shutdown hook'ları

#### OOP/SOLID İlk Tur (SOLID-1..9)
- `GuardChain` + `MessageGuard` Protocol; `message_guards.py` dört concrete guard sınıfı
- `StoreProtocol` (runtime-checkable); `SqliteStoreWrapper` singleton (DIP)
- `_AUTH_FLOW_REGISTRY` dispatch tablosu (OCP); `BridgeMonitor` sınıfı `main.py`'den ayrıldı (SRP)

#### Performans (PERF-1..3, PERF-OPT-1..7)
- 556 Bridge çağrısı token analizi; `.claude-routes.json` 12→33 rota; init_prompt küçültme; Bridge timeout ayarı

#### Wizard LLM Scaffold (WIZ-LLM-1..9)
- 8 adımlı wizard (ask_description → confirm_create) tam LLM destekli mimari üretimi

#### Diğer
- i18n audit: 33 hardcode string `t()` ile değiştirildi; tr/en paritet
- DEP-1..3: Python + Node CVE taraması (0 CVE)
- `SensitiveHeaderFilter` — X-Api-Key/authorization header log sızıntısı kapatıldı
- Telegram `owner_id` eşleştirmesi düzeltildi (`whatsapp_owner` → `settings.owner_id`)
- BUG-DESK-SEND-1: Screenshot/video `/internal/send_media` üzerinden WhatsApp'a iletiliyor
- DOC-SKILL-1: Skill dokümantasyonu `docs/skills.md`'e taşındı

**Durum:** ✅ Tamamlandı

---

### APR-20 — Desktop Optimizasyon Oturumu

**Tarih:** 2026-04-20

#### Desktop Hız İyileştirmeleri (DESK-OPT-1..3)
- DESK-OPT-1: Async X11 race condition → `asyncio.Lock()` ile seri erişim
- DESK-OPT-2: `xdotool type` → python-xlib XTEST in-process giriş (Türkçe Unicode desteği)
- DESK-OPT-3: `scrot` subprocess → `python-mss` — sıfır disk I/O, bellekten Base64

#### Diğer
- LOG-DESK-1: Her desktop aksiyonu ayrı ve detaylı loglanıyor
- MOD-INSTALL-1a..1c: Modüler ajan kurulum adımları belgelendi

**Durum:** ✅ Tamamlandı

---

### APR-23 — Token İstatistikleri ve .md Güncelleme

**Tarih:** 2026-04-23

#### Token İstatistikleri (TOKEN-STATS-1, TOKEN-STATS-2)
- `store/repositories/token_stat_repo.py` — `token_usage` tablosu; her `complete()` çağrısı sonrası provider token bilgisi yazıyor
- `guards/commands/tokens_cmd.py` — `!tokens [24h|7d|30d]` komutu; model/backend dağılımı özeti
- `guards/commands/timezone_cmd.py` — `!timezone` komutu; çalışma zamanında APScheduler saat dilimi değişimi
- `guards/commands/terminal_cmd.py` — `!terminal` komutu; tehlikeli komutlar için admin TOTP akışı

#### Dokümantasyon Güncelliği
- Tüm .md dosyaları gerçek kod durumuyla karşılaştırıldı, eksiklikler giderildi

**Durum:** ✅ Tamamlandı

---

### Mevcut Servis Durumu (2026-04-11)

| Servis | Port | Pencere | Durum |
|--------|------|---------|-------|
| 99-root FastAPI | 8010 | `services:99-api` | ✅ |
| 99-root Bridge | 8013 | `services:99-bridge` | ✅ |
| ngrok | — | `services:ngrok` | ✅ |
| WMA FastAPI | 8000 | `services:wma-api` | Kullanıcı başlatacak |
| WMA Bridge | 8003 | `services:wma-bridge` | Kullanıcı başlatacak |

### Açık Konular

- WMA başlatma testi yapılmadı (`start_project_services` fix'i sonrası)
- Beta modu uçtan uca testi: WMA başlatılıp `/internal/message` endpoint'i doğrulanmalı
- WMA'nın `!root-check` komutu hâlâ var — root bridge URL'si güncellenmeli mi?
