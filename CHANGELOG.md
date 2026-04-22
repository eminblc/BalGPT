# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### Added
- Wizard SRP refactor: `wizard_core.py` (sabitler, yardımcılar, session temizleme) + `wizard_steps.py` (8 adım: ask_description → confirm_create); `project_wizard.py` shim olarak kaldı
- Menu SRP refactor: `menu_project.py` — project_select_*, project_start_*, project_stop_* vb. prefix handler'ları `menu.py`'den ayrıldı
- SOLID-OOP1: `SessionState` is now a `dict` subclass with typed auth-flow methods (`start_totp`, `start_admin_totp`, `start_math_challenge`, `start_guardrail` and their `clear_*` counterparts)
- SOLID-OCP3: Auth state dispatch in `_dispatcher.py` now uses `_AUTH_FLOW_REGISTRY` dict — new auth step = new function + registry entry, no dispatcher change required
- SOLID-DIP1: `store/protocol.py` — `StoreProtocol` runtime-checkable Protocol; `store/sqlite_wrapper.py` — `SqliteStoreWrapper` class + `store` singleton for dependency injection in tests
- SOLID-OCP1+DIP2: `guards/guard_chain.py` — `GuardChain` + `MessageGuard` Protocol; `guards/message_guards.py` — four concrete guard classes (`DedupMessageGuard`, `BlacklistMessageGuard`, `OwnerPermissionGuard`, `RateLimitMessageGuard`)
- SOLID-SRP1: `services/bridge_monitor.py` — `BridgeMonitor` class extracted from `main.py` lifespan; auto-restart after 3 consecutive health-check failures
- `routers/_dispatcher.py` — platform-independent dispatch module shared by WhatsApp and Telegram routers

### Changed
- `whatsapp_router.py` now delegates all common dispatch to `_dispatcher.handle_common_message()`

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
