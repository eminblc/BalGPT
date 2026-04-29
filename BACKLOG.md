# Backlog — 99-root Kişisel AI Ajan

---

## 🔴 KRİTİK

*(Şu an kritik açık görev yok)*

---

## 🟠 YÜKSEK

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
| MSG-UI-2 | Telegram'da 'yazıyor…' göstergesi ekle | `routers/telegram_router.py`, `adapters/messenger/telegram_messenger.py` | Telegram Bot API `sendChatAction("typing")` — Bridge `/query` başında ve her N saniyede bir tekrarla, sonuç gelince durdur. |

---

## 🟡 ORTA

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
| MSG-UI-1 | WhatsApp bildirim metni doğallaştır | `CLAUDE.md` | "⚙️ <ne yapıyorsun>" yerine "Yazıyor…", "Kontrol ediyorum…", "Düşünüyorum…" gibi daha samimi ifadeler kullan. |
| TG-WIZ-2 | TG-WIZ-1 uçtan uca manuel test | — | `.env` sil → `bash install.sh` → Telegram + bot token + ngrok creds → welcome ping → `!wizard` → 5 adım butonla → QR'lar gelsin → TOTP `.env` ile eşleşsin → `docker compose restart` → bot normal cevap versin. |
| TG-WIZ-3 | CI'da bats + shellcheck (TG-WIZ-1) | `.github/workflows/ci.yml` | Lokalde bats/shellcheck yoktu; CI çalıştırınca locale parity ve install.sh sözdizim doğrulanacak. İlk başarısız run'da düzeltme yap. |
| TG-WIZ-4 | ngrok token regex iyileştir | `lib/wizard.sh` | Mevcut: `[A-Za-z0-9_]{16,}` (gevşek). Gerçek ngrok token formatı dokümante değil — kullanım sırasında tipik uzunluk/karakter set ölçülüp regex sıkılaştırılabilir. |

---

## 🟢 DÜŞÜK

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
| DOC-API-1 | OpenAPI schema zenginleştirme | `routers/api/`, `routers/personal_agent_router.py`, `routers/internal_router.py` | Her endpoint için `summary`, `description`, `response_model`, örnek request/response ekle; FastAPI `/docs` sayfası kullanılabilir hale gelsin. |

---

## 🟡 Kullanıcı Eylemi Gereken

| # | Başlık | Not |
|---|--------|-----|
| CONFIG-TZ-2 | Uygulama saat ayarı kontrol edilecek | NTP durumu, sistem saati, timezone ayarlaması kontrol et. |
| OPS-4 | Beta modu uçtan uca test | WMA başlatılıp `/internal/message` endpoint doğrulanmalı. |
| OPS-9 | `API_KEY` .env'de boş — `/agent/*` endpointleri korumasız | `.env`'e `API_KEY=<güçlü-key>` ekle. Startup'ta "api_key tanımlı değil" uyarısı basıyor. |
| OPS-6 | WMA `.env` — `CHROMA_PATH` düzelt | Yoldaki `**agents**` kısmını `whatsapp-memory-agent` olarak düzelt; WMA FastAPI'yi yeniden başlat. Kayıt sayısı 0 → 553 olmalı. |

---

## 🟠 Ertelenmiş (Deferred / Out of Scope)

| # | Başlık | Not |
|---|--------|-----|
| TOKEN-WATCH-2 | %90 kota uyarı bildirimi | Otomatik monitoring + uyarı sistemi out-of-scope. Kullanıcı `!tokens` ile manuel kontrol etsin. |
| TOKEN-WATCH-4 | Provider-generic uyum testleri | Kompleks test suite out-of-scope; TOKEN-STATS-1/2 doğrulaması yeterli. |
| MSG-UI-3 | WhatsApp typing indicator araştırması | Cloud API'de native typing action yok; alternatif çözümler kompleks. DEFERRED — opsiyonel. |

---

## ✅ Tamamlanan

| # | Başlık | Tarih |
|---|--------|-------|
| TG-WIZ-1 | Telegram Stage-2 install wizard (`!wizard`): install.sh minimal terminal akışı + bot içi inline-button konfigürasyon (LLM/yetenekler/TZ/TOTP QR) | 2026-04-27 |
| DOC-MEM-1 | `.md` dosyaları tam audit: CONTRIBUTING.md CMD_PERMS düzeltmesi, MEMORY.md 2026-04-15~30 kayıtları, AGENT.md KPI + özellik güncellemesi, web-automation.md BROWSER-1 güncellenmesi | 2026-04-30 |
| TOKEN-STATS-1 | Session başına detaylı token takibi (`token_usage` tablosu, tüm provider'lar) | 2026-04-23 |
| TOKEN-STATS-2 | `!tokens [24h\|7d\|30d]` komutu — model/backend istatistikleri | 2026-04-23 |
| UX-MODEL-1 | `!model` komutu — butonlu model seçimi | 2026-04-22 |
| CLEAN-1..4 | Proje temizliği: yanlış konumlu raporlar, gereksiz DB/JSON/pycache dosyaları | 2026-04-22 |
| SOLID-v2-1..7 | OOP/SOLID v2: DIP ihlalleri, SRP hook/sub-router ayrımı, ISP (9 sub-protocol), encapsulation | 2026-04-22 |
| DESK-LOGIN-1..5 | Login görevleri Playwright-first strateji, `unlock_screen`/`is_locked` güçlendirme, vision fallback | 2026-04-22 |
| BROWSER-1 | Playwright DOM-first genişletme | 2026-04-22 |
| DESK-OPT-1 | Async X11 race condition — `asyncio.Lock()` ile seri erişim | 2026-04-20 |
| DESK-OPT-2 | `xdotool type` → python-xlib XTEST in-process giriş (Türkçe Unicode desteği) | 2026-04-20 |
| DESK-OPT-3 | `scrot` subprocess → `python-mss` — sıfır disk I/O, bellekten Base64 | 2026-04-20 |
| LOG-DESK-1 | Desktop işlem logları — her aksiyon ayrı ve detaylı loglanıyor | 2026-04-20 |
| MOD-1 | Router kayıtları koşullu hale getirildi (desktop/terminal/browser) | 2026-04-20 |
| BUG-VQ1 | `vision_query` — `ANTHROPIC_API_KEY` systemd ortamında eksik; erken key kontrolü eklendi | 2026-04-19 |
| MOD-3..9 | Modüler ajan: API gating, flag adlandırma, lifecycle hook'ları, registry | 2026-04-19 |
| MOD-10 | Feature manifest / plugin registry sistemi (`features/_registry.py`) | 2026-04-19 |
| SOLID-1..9 | OOP/SOLID ilk tur: dispatch tablosu, registry pattern, DI, singleton, store protocol | 2026-04-19 |
| REFAC-1..19 | Büyük OOP/SOLID refactor: SRP modül bölme, credential store ayrımı, DI, TypedDict | 2026-04-18–19 |
| PERF-1..3 | Token tüketimi + endpoint latency + guard zinciri profiling (556 Bridge çağrısı analizi) | 2026-04-19 |
| PERF-OPT-1..7 | `.claude-routes.json` genişletme (12→33 rota), init_prompt küçültme, Bridge timeout, CLAUDE.md boyut izleme | 2026-04-19 |
| TEST-1..11 | Guard, command, adapter, feature, router, desktop, browser unit/entegrasyon testleri | 2026-04-18–19 |
| SEC-NIGHT-1 | Yeni router'lar güvenlik taraması (desktop, terminal, internal) — 3 bulgu giderildi | 2026-04-19 |
| I18N-1..2 | `tr.json` ↔ `en.json` paritet kontrolü + hardcode string taraması (33 string `t()` ile değiştirildi) | 2026-04-19 |
| DEP-1..3 | Python + Node CVE taraması (0 CVE), sürüm karşılaştırması | 2026-04-19 |
| GR-1..2 | GUARDRAILS yeni kategoriler + `guardrails_loader.py` token listesi doğrulama | 2026-04-19 |
| SEC-H1..5 | Admin TOTP brute-force, rate limiter spoofing, symlink path, HMAC/Telegram secret dev bypass | 2026-04-18 |
| SEC-M1..5 | API key startup kontrolü, hata detay sızıntısı, Bridge mesaj sanitize, CORS startup doğrulama | 2026-04-18 |
| SEC-L1 | `X-Api-Key` / `authorization` header log sızıntısı — `SensitiveHeaderFilter` eklendi | 2026-04-19 |
| BUG-H1..2 | Path traversal (`allowedRoots` kontrolü), math cancel lock dışında session corruption | 2026-04-18 |
| BUG-M1..4 | Internal router timestamp, Telegram conv_history asimetri, Playwright kaynak sızıntısı, session TOCTOU | 2026-04-18 |
| BUG-C1..2 | `import time` eksik (NameError), bare `send_text` çöküşü (3 dosya) | 2026-04-18 |
| BUG-TG1..2 | Telegram `owner_id` eşleştirmesi (`whatsapp_owner` → `settings.owner_id`) | 2026-04-19 |
| BUG-DESK-SEND-1 | Desktop screenshot/video WhatsApp'a gönderilmiyordu — `/internal/send_media` eklendi | 2026-04-19 |
| DESK-OPT-4..8 | Playwright domcontentloaded+CSS, CDP click, `_NET_ACTIVE_WINDOW`, batch endpoint, X11 event popup izleme | 2026-04-19 |
| OPT-2..3 | Region screenshot, bounding box önbelleği (TTL tabanlı) | 2026-04-18 |
| LOG-2..5 | Telegram/desktop/terminal/dispatcher logging_config eksiklikleri | 2026-04-19 |
| MOD-INSTALL-1a..1c | Modüler ajan kurulum adımları | 2026-04-19 |
| DOC-SKILL-1 | Skill dokümantasyonu `docs/skills.md`'e taşındı | 2026-04-19 |
| WIZ-LLM-1..9 | Wizard LLM-destekli mimari üretimi (8 adım: ask_description → confirm_create) | 2026-04-19 |
| FEAT-3..18 | Yetenek kısıtlamaları, medya gönderimi, i18n, model seçimi, TOTP, timezone, Playwright, desktop | 2026-04-17–22 |
| G2..10, PORT-1..6 | GitHub dağıtımı, Telegram adapter, Docker, PM2, deployment kılavuzları | 2026-04-13–14 |
| SEC-1..10 | Webhook HMAC, prompt injection, TOTP, GUARDRAILS (49 kategori), output filter | 2026-04-11–14 |
| AUD-* | Tam audit serisi — güvenlik, bug, kod kalitesi (40+ madde) | 2026-04-15–16 |
| F1..F7, S01-* | İlk kurulum, temel özellikler (chat, plan, takvim, proje, PDF, scheduler, beta modu) | 2026-04-11–12 |
