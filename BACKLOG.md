# Backlog — 99-root Kişisel AI Ajan

---

## 🔴 KRİTİK

*(Şu an kritik açık görev yok)*

---

## 🟠 YÜKSEK

*(Şu an yüksek öncelikli açık görev yok)*

---

## 🟡 ORTA

*(Şu an orta öncelikli açık görev yok)*

---

## 🟢 DÜŞÜK

*(Şu an düşük öncelikli açık görev yok)*

---

## 🟡 Kullanıcı Eylemi Gereken

*(Şu an kullanıcı eylemi gereken görev yok)*

---

## 🟠 Ertelenmiş (Deferred / Out of Scope)

*(Şu an ertelenmiş görev yok)*

---

## ✅ Tamamlanan

| # | Başlık | Tarih |
|---|--------|-------|
| BACKUP-11 | Tarih bazlı yedek rotasyonu: `BackupRotationManager`, `BACKUP_RETENTION_DAYS` config | 2026-05-09 |
| BACKUP-10 | Otomatik periyodik yedekleme: `AutoBackupJob`, `AUTO_BACKUP_ENABLED/CRON` config | 2026-05-08 |
| BACKUP-9 | AES-256-GCM şifreleme: `_cipher.py`, v2 format, `BACKUP_ENCRYPTION_KEY` config | 2026-05-08 |
| BACKUP-8 | `settings.data_dir` — `DATA_DIR` env; `resolved_data_dir` property | 2026-05-08 |
| BACKUP-7 | `/export` + `/import` komutları; Telegram document handler | 2026-05-08 |
| BACKUP-6 | REST API: `POST /agent/export`, `POST /agent/import`, `GET /agent/export/status` | 2026-05-08 |
| BACKUP-5 | `LocalFileExporter` + `LocalFileImporter` — path traversal koruması, .bak yedek | 2026-05-08 |
| BACKUP-4 | `DbImporter` + `ImportService` + 43 unit test | 2026-05-08 |
| BACKUP-3 | `DbExporter` + `ExportService` + 30 unit test | 2026-05-08 |
| BACKUP-2 | `BackupWriter`, `BackupReader`, `MsgpackSerializer` | 2026-05-08 |
| BACKUP-1 | Export/Import paket iskeleti: protokoller, `ExportScope`, `BackupManifest` | 2026-05-08 |
| MSG-UI-2 | Telegram typing indicator: `TypingMessenger` protokolü, `send_typing()` | 2026-05-09 |
| MSG-UI-1 | WhatsApp bildirim metni doğallaştırma | 2026-05-09 |
| DOC-MEM-1 | WORK_LOG denetimi ve güncelleme | 2026-05-09 |
| TG-WIZ-4 | ngrok token regex `{16,}` → `{40,}` | 2026-05-09 |
| DOC-API-1 | OpenAPI schema zenginleştirme: tüm API endpoint'leri | 2026-05-09 |
| TG-WIZ-1 | Telegram Stage-2 install wizard (`!wizard`) | 2026-04-27 |
| TOKEN-STATS-1 | Session bazında token takibi (`token_usage` tablosu) | 2026-04-23 |
| TOKEN-STATS-2 | `!tokens [24h\|7d\|30d]` komutu | 2026-04-23 |
| UX-MODEL-1 | `!model` komutu — butonlu model seçimi | 2026-04-22 |
| SOLID-v2-1..7 | OOP/SOLID v2: DIP, SRP, ISP (9 sub-protocol), encapsulation | 2026-04-22 |
| DESK-LOGIN-1..5 | Login stratejisi Playwright-first, `unlock_screen`/`is_locked` güçlendirme | 2026-04-22 |
| BROWSER-1 | Playwright DOM-first genişletme | 2026-04-22 |
| DESK-OPT-1..8 | Desktop optimizasyonlar, async X11, XTEST, python-mss, CDP click | 2026-04-20 |
| TEST-1..11 | Guard, command, adapter, feature, router, desktop, browser testleri | 2026-04-18–19 |
| SEC-1..10 | Webhook HMAC, prompt injection, TOTP, GUARDRAILS (49+ kategori) | 2026-04-11–22 |
| SOLID-1..9 | OOP/SOLID ilk tur: dispatch tablosu, registry pattern, DI, singleton | 2026-04-19 |
| FEAT-3..18 | Yetenek kısıtlamaları, medya, i18n, TOTP, timezone, Playwright, desktop | 2026-04-17–22 |
| G2..10, PORT-1..6 | GitHub dağıtımı, Telegram adapter, Docker, PM2, deployment kılavuzları | 2026-04-13–14 |
| F1..F7 | İlk kurulum, temel özellikler (chat, plan, takvim, proje, PDF, scheduler) | 2026-04-11–12 |
