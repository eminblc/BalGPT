# Done — 99-root Kişisel AI Ajan

Tamamlanan tüm görevler. BACKLOG.md'deki `✅ Tamamlanan` bölümünden taşındı.

---

| # | Başlık | Tarih |
|---|--------|-------|
| SCAN-NOTIF-1 | `ReviewerAgent.run(notify=)` + `ScannerAgent.run(notify_on_review=)` — `AllScansRunner` artık `notify_on_review=False` geçiyor; N scan = N mesaj spam giderildi | 2026-05-18 |
| SEC-SCAN2 (28 madde) | 5 paralel agent ile 28 güvenlik açığı düzeltmesi (SQL injection, SSRF, race condition, symlink, shell injection, path traversal vb.) | 2026-05-17 |
| EXEC-1..4 | Backlog executor: started_at fix, max_items=0 (tümü), httpx timeout 1800s, asyncio.Lock race condition; scan iptal + ilerleme loglaması | 2026-05-18 |
| BUG-SCAN-1 | 8 paralel agent ile 87 maddelik bug+iyileştirme taraması ve toplu düzeltme | 2026-05-17 |
| BUG-CORE-1 | `/health` endpoint `r.json()` JSONDecodeError koruması | 2026-05-17 |
| BUG-GUARD-1 | `clear_backup_import()` çift-yazma hatası (işlevsiz False atama kaldırıldı) | 2026-05-17 |
| BUG-GUARD-2 | `api_rate_limiter` anonim IP biriktirme — X-Forwarded-For/X-Real-IP fallback | 2026-05-17 |
| BUG-ROUTER-1 | `_dispatcher.py` silent exception handler → logger.exception + kullanıcı bildirimi | 2026-05-17 |
| BUG-ROUTER-3 | `_bridge_client.py` `r.json()` hata koruması | 2026-05-17 |
| BUG-FEAT-1 | Scheduler startup timezone fallback (`settings.timezone`) | 2026-05-17 |
| BUG-FEAT-4 | PDF import null JSON schema fallback doğrulaması | 2026-05-17 |
| BUG-BRIDGE-1 | Bridge child process SIGTERM sonrası `proc.unref()` + double-kill önlemi | 2026-05-17 |
| BUG-BRIDGE-2 | `loadConvHistory()` CONV_MAX_TURNS enforce — ilk save'de de limit uygulanıyor | 2026-05-17 |
| BUG-DESK-1 | Screenshot temp dosyası `try/finally` ile temizleme (crash-safe) | 2026-05-17 |
| BUG-DESK-2 | Vision rate limiter `asyncio.Lock` ile thread-safe yapıldı | 2026-05-17 |
| BUG-DESK-4 | `xdotool type` `window_id` hex format doğrulaması | 2026-05-17 |
| BUG-INST-1 | `steps.sh` `step_proxy_binary` `$ENV_FILE` tanımsız değişken düzeltmesi | 2026-05-17 |
| IMP-CORE-1 | TOTP lockout atomic INSERT+UPDATE (TOCTOU race kaldırıldı) | 2026-05-17 |
| IMP-CORE-2..4 | Config production uyarısı güçlendirme, i18n LRU maxsize=10, repo TypedDict comment | 2026-05-17 |
| IMP-GUARD-2..3 | OwnerPermissionGuard + RateLimitGuard exception → logger.warning (audit trail) | 2026-05-17 |
| IMP-GUARD-4 | TOTP `_TOTP_VALID_WINDOW` modül sabiti (saat kayması için ayarlanabilir) | 2026-05-17 |
| IMP-GUARD-5..13 | export_cmd file check, root_check_cmd i18n, blacklist logging, cancel feedback, root_log TOCTOU, project_delete truncation | 2026-05-17 |
| IMP-ROUTER-2..3 | Telegram JSON parse 200 döndür (retry loop önleme), backup_api UploadFile guard | 2026-05-17 |
| IMP-ROUTER-5..6 | Schedule run_at UTC açıklaması, Telegram download UX hata mesajı | 2026-05-17 |
| IMP-ROUTER-9..10 | Bridge retry `httpx.TransportError` genişletme, intent classifier 1 retry | 2026-05-17 |
| IMP-FEAT-1 | `apply_timezone()` rollback mekanizması (cron reload başarısız → eski tz restore) | 2026-05-17 |
| IMP-FEAT-3..5 | Wizard clear_wizard try/finally, project status update try/except, scheduler job 30s timeout | 2026-05-17 |
| IMP-FEAT-6..7 | chat.py hata prefix sabiti, terminal truncation başlangıç+son stratejisi | 2026-05-17 |
| IMP-FEAT-9..11 | Media max size doğrulaması, project_scaffold İngilizce başlık, wizard boş desc kontrolü | 2026-05-17 |
| IMP-FEAT-13 | `shlex.split` ValueError → `is_dangerous=True` (safe fallback) | 2026-05-17 |
| IMP-FEAT-17 | Bridge HTTP timeout 300s → configurable (BRIDGE_HTTP_TIMEOUT env, 90s default) | 2026-05-17 |
| IMP-ADAP-1 | Tüm LLM provider'larda 3 deneme + exponential backoff | 2026-05-17 |
| IMP-ADAP-2..6 | Bridge monitor backoff, telegram_downloader token maskeleme, LLM factory async kontrolü, send_list label parametresi, cloud_api ok/error dönüşü | 2026-05-17 |
| IMP-BRIDGE-2..8 | buildContextHint word-boundary match, setInterval .catch, cancel sessionReadCounts cleanup, saveConvTurn bool dönüşü, retry sessionFile fix, CLAUDE.md + routes mtime cache | 2026-05-17 |
| IMP-DESK-3..11 | Playwright storage_state JSON validation, vision cache session_id key, TOTP gate clock rollback koruması, popup watcher shutdown_all_watchers, vision API boyut double-resize, xdotool killpg, OCR temp cleanup, Wayland X11 check, xlib keysym try/finally | 2026-05-17 |
| IMP-INST-2..7 | CI flake8 (warn-only), Docker healthcheck, PM2 retry loop, Node version numeric guard, PM2 log rotation | 2026-05-17 |
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
| CTX-LOSS-3 | `currentDate` ve dinamik alanlar statik prefix'in sonuna taşındı (cache miss azaltma) | 2026-05-09 |
| CTX-LOSS-2 | `buildInitPrompt` resumed session'da yalnızca dinamik bölümleri gönderir | 2026-05-09 |
| TG-WIZ-4 | ngrok token regex `{16,}` → `{40,}` | 2026-05-09 |
| DOC-API-1 | OpenAPI schema zenginleştirme: tüm API endpoint'leri | 2026-05-09 |
| TG-WIZ-1 | Telegram Stage-2 install wizard (`!wizard`) | 2026-04-27 |
| TOKEN-STATS-1 | Session bazında token takibi (`token_usage` tablosu, tüm provider'lar) | 2026-04-23 |
| TOKEN-STATS-2 | `!tokens [24h\|7d\|30d]` komutu — model/backend istatistikleri | 2026-04-23 |
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
| CLAUDE_MD_SIZE_WARN | CLAUDE.md 1004→734 satıra indirildi; installer-sync + desktop-api ayrı dosyalara taşındı | 2026-05-19 |
| TG-WIZ-3 | CI'da bats + shellcheck: locale parity false positive (lib/i18n.sh comment) düzeltildi; comment satırları filtreleniyor | 2026-05-19 |
