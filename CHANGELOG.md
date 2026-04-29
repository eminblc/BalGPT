# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### Added

**Desktop Automation (APR-18–20)**
- Desktop automation modüler yapısı: `desktop_atspi.py`, `desktop_capture.py`, `desktop_popup.py`, `desktop_recording.py`, `desktop_system.py` (SRP bölünmesi)
- `desktop_router.py` SRP split: `_desktop_capture.py` (capture handler'ları) + `_desktop_vision.py` (vision/OCR handler'ları)
- DESK-OPT-1: `asyncio.Lock()` ile X11 race condition giderildi
- DESK-OPT-2: `xdotool type` → python-xlib XTEST in-process giriş (Türkçe Unicode)
- DESK-OPT-3: `scrot` → `python-mss` (sıfır disk I/O, bellekten Base64)
- `/internal/send_media` endpoint — screenshot/video WhatsApp/Telegram'a iletme (BUG-DESK-SEND-1)
- Desktop per-action structured logging

**Browser Automation (APR-18–22)**
- `features/browser/` paketi — Playwright DOM-first otomasyon: `_actions`, `_lifecycle`, `_paths`, `_persistence`, `_session_store`, `_validation`
- `routers/browser_router.py` — `/internal/browser/*` endpoint'leri (goto, click, fill, eval, screenshot, get_credential, save/load_session)
- `features/credential_store.py` — site bazlı kimlik bilgisi deposu

**Terminal (APR-18)**
- `features/terminal.py` + `routers/terminal_router.py` — `/internal/terminal` endpoint
- `guards/commands/terminal_cmd.py` — `!terminal` komutu (tehlikeli komutlar için admin TOTP)

**Token İstatistikleri (APR-23)**
- `store/repositories/token_stat_repo.py` — `token_usage` tablosu; Anthropic/Gemini/Ollama provider'lardan token bilgisi kaydedilir
- `guards/commands/tokens_cmd.py` — `!tokens [24h|7d|30d]` komutu; model/backend dağılım özeti

**Diğer Komutlar (APR-18–23)**
- `guards/commands/timezone_cmd.py` — `!timezone` komutu; APScheduler'ı çalışma zamanında yeniden yapılandırır
- `guards/commands/lock_cmd.py` + `unlock_cmd.py` — uygulama kilidi/kilit açma (TOTP gerekli)

**OOP/SOLID (APR-18–22)**
- Wizard SRP refactor: `wizard_core.py` + `wizard_steps.py` + `wizard_validator.py`; `project_wizard.py` shim olarak kaldı
- Menu SRP refactor: `menu_project.py` — project_select_*, project_start_*, project_stop_* handler'ları ayrıldı
- Project SRP: `project_crud.py` + `project_service.py` `projects.py`'den ayrıldı
- SOLID-OOP1: `SessionState` typed auth-flow metodları (`start_totp`, `start_admin_totp`, `start_math_challenge`, 13 wizard wrapper)
- SOLID-OCP3: `_AUTH_FLOW_REGISTRY` dispatch tablosu
- SOLID-DIP1: `StoreProtocol` + `SqliteStoreWrapper` singleton
- SOLID-OCP1+DIP2: `GuardChain` + `MessageGuard` Protocol (4 concrete guard)
- SOLID-SRP1: `BridgeMonitor` `main.py`'den ayrıldı
- SOLID-ISP: `StoreProtocol` 9 domain-spesifik sub-protocol'e bölündü
- `routers/_dispatcher.py` — platform-agnostic dispatch

**Altyapı (APR-18–19)**
- Koşullu router kaydı (`DESKTOP_ENABLED`, `BROWSER_ENABLED`, `TERMINAL_ENABLED`)
- Feature manifest / plugin registry: `features/_registry.py`
- `routers/_localhost_guard.py` — localhost-only FastAPI dependency (shared)
- `adapters/media/` — WhatsApp medya indirme adaptör katmanı
- `adapters/llm/result.py` — `LLMResult` typed wrapper
- `constants.py` — proje geneli string sabitleri
- `.claude-routes.json` 12→33 rota; init_prompt küçültme
- `SensitiveHeaderFilter` — API key/authorization header log sızıntısı kapatıldı

**Güvenlik (APR-18)**
- Admin TOTP brute-force koruması (3 deneme → 15 dk kilit)
- Symlink path traversal ve Bridge `allowedRoots` kontrolü
- API key startup kontrolü, CORS startup doğrulaması

### Changed
- `whatsapp_router.py` tüm ortak dispatch'i `_dispatcher.handle_common_message()`'a devreder
- Telegram `owner_id` eşleştirmesi `settings.owner_id` üzerinden (platform-agnostic)
- i18n: 33 hardcode string `t()` ile değiştirildi; tr/en tam paritet

---

## [0.1.0] — 2026-04-16

First tagged release. Core features complete and stable.

### Added

**i18n & Yerelleştirme**
- `!lang tr|en` komutu — kullanıcı arayüz dilini değiştirir; `session["lang"]` olarak saklanır
- i18n sistemi — `backend/i18n.py` (`t()` helper, LRU cache, tr fallback), `locales/tr.json` + `locales/en.json`
- Yetenek kısıtlamaları (FEAT-3) — `guards/capability_guard.py`; filesystem, network, shell vb. toggle

**Core**
- FastAPI backend (port 8010) + Claude Code Bridge (port 8013)
- WhatsApp webhook with HMAC verification, dedup, blacklist, rate limit, permission guards
- Telegram messenger adapter (`MESSENGER_TYPE=telegram`)
- CLI messenger for local testing without a WhatsApp/Telegram account (`MESSENGER_TYPE=cli`)
- LLM abstraction layer: Anthropic (default), Ollama, Google Gemini (`LLM_BACKEND=…`)

**Features**
- Natural language chat via Claude Code CLI
- Work plans (CRUD + priority)
- Calendar events with NLP date parsing and reminders
- Project management with 8-step wizard (WhatsApp form flow)
- PDF import → project scaffold via Claude Code analysis
- Scheduled tasks with cron expressions (APScheduler + SQLiteJobStore)
- Beta mode: redirect all messages to a project's own FastAPI instance

**Security**
- Two-factor destructive commands: math challenge → admin TOTP
- Owner TOTP for sensitive commands
- Guardrail system: LLM-based destructive intent detection before execution
- Output filter: blocks obfuscated code in Bridge responses
- Dynamic guardrail loader from `GUARDRAILS.md`
- API key guard for `/agent/*` endpoints
- Prompt injection protection: external content wrapped in `[BELGE]` tags

**Infrastructure**
- `install.sh` — interactive setup wizard (whiptail TUI + plain-text fallback)
  - Messenger, LLM backend, webhook proxy, deployment method selection
  - Auto-generates `API_KEY`, `TOTP_SECRET`, `TOTP_SECRET_ADMIN` with `openssl`
- Docker Compose support (`Dockerfile.api`, `Dockerfile.bridge`, `docker-compose.yml`)
- PM2 support (`ecosystem.config.js`)
- systemd service files (rendered by `install.sh`)
- GitHub Actions CI: Python syntax + import check, pytest, Node syntax check
- Webhook proxy manager: ngrok, cloudflared, external URL, or none
- Render.com Blueprint (`render.yaml`) and Railway config (`railway.json`)

**Deployment docs**
- `docs/deployment/byok.md` — BYOK/BYOM with PM2
- `docs/deployment/vps.md` — VPS + systemd + Cloudflare Tunnel
- `docs/deployment/raspberry-pi.md` — Raspberry Pi local setup

**Developer experience**
- `setup.py` — Python interactive setup wizard (alternative to `install.sh`)
- Unit tests: `tests/` — dedup, rate limiter, slugify, sqlite store (37 tests)
- `.github/ISSUE_TEMPLATE/` — bug report and feature request templates
- MIT License, `CONTRIBUTING.md`, bilingual README (`README.md` + `README.tr.md`)

### Security fixes (audit 2026-04-15 / 2026-04-16)
- API key comparison uses `secrets.compare_digest()` (timing-attack safe)
- All SQLite calls wrapped in `asyncio.to_thread()` (no event loop blocking)
- Gemini API key moved to header (`x-goog-api-key`), removed from URL query string
- TOTP `record_failure` uses atomic `ON CONFLICT DO UPDATE` (race-condition safe)
- `task_find_by_prefix` escapes `%`, `_`, `\` in LIKE queries
- `/agent/project/{id}/beta` verifies sender against `whatsapp_owner`
- Session lock cleanup skips locked locks (prevents race on concurrent messages)
- `_last_status` / `_windows` dicts have TTL-based eviction (unbounded growth fix)
- Media download capped at 50 MB; double-checked after download
- Path traversal blocked via `Path.relative_to()` in project file access
- Prompt injection: 4 vectors patched (visual/video captions, location, document filename, conv history)

---

[Unreleased]: https://github.com/your-username/99-root/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/your-username/99-root/releases/tag/v0.1.0
