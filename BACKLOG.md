# Backlog — 99-root Kişisel AI Ajan

---

## 🔴 KRİTİK — Güvenlik ve Dokümantasyon

> Kaynak: `reports/full_audit_2026-04-15.md`, `reports/md_review_2026-04-14.md`, Telegram test 2026-04-19

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
*(Tüm KRİTİK maddeler tamamlandı — bkz. ✅ Tamamlanan)*

---

---

## 🟠 YÜKSEK — Buglar ve Güvenlik

> Kaynak: `reports/full_audit_2026-04-15.md`, `error.log` analizi 2026-04-19

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
| ~~BUG-VQ1~~ | ~~`vision_query` — `ANTHROPIC_API_KEY` systemd ortamında eksik~~ | ~~`features/desktop_vision.py:219`~~ | ✅ Erken key kontrolü eklendi: key boşsa anlamlı hata + çözüm talimatı döner (screenshot öncesi). `from ..config import settings` import eklendi. |

---

## 🟠 YÜKSEK — Modüler Ajan: API Gating Eksiklikleri

> Kaynak: Modüler ajan analizi (2026-04-19) — Mevcut durum: flag var ama API endpoint'leri korumasız

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
| ~~MOD-3~~ | ~~Plans API endpoint'leri flag kontrolü ekle~~ | ~~`routers/api/plans_api.py`~~ | ✅ `plans_api.py:28,36,44` — tüm handler'larda `restrict_plans` kontrolü mevcuttu |
| ~~MOD-4~~ | ~~PDF Import API endpoint'i flag kontrolü + CapabilityGuard kuralı ekle~~ | ~~`routers/api/pdf_api.py`~~ | ✅ `pdf_api.py:25` — `restrict_pdf_import` kontrolü mevcuttu |
| ~~MOD-5~~ | ~~Terminal router için enable/disable flag ekle~~ | ~~`routers/terminal_router.py`~~ | ✅ `terminal_router.py:69` — `restrict_shell` kontrolü mevcuttu |

---

## 🟠 YÜKSEK — OOP/SOLID İyileştirmeleri

> Kaynak: `reports/oop_solid_audit_2026-04-19.md`

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
| ~~SOLID-2~~ | ~~Döngüsel importlar — fonksiyon-içi geç bağlama gider~~ | ~~`routers/_dispatcher.py:58`, `guards/message_guards.py:75,100`~~ | ✅ `whatsapp_router.py:51-52` — `OwnerPermissionGuard(perm_mgr, settings, get_messenger)` + `RateLimitMessageGuard(rate_limiter, get_messenger)` DI ile inject ediliyor; `message_guards.py` modül-seviyesinde messenger import etmiyor |

---

## 🟡 ORTA — Güvenlik ve Güvenilirlik

> Kaynak: `reports/full_audit_2026-04-15.md`, `reports/wizard_bug_report_2026-04-16.md`, `reports/github_dist_audit_2026-04-16.md`

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
*(Tüm ORTA maddeler tamamlandı — bkz. ✅ Tamamlanan)*

---

## 🟡 ORTA — Token Kullanım İstatistikleri (TOKEN-STATS)

> Kaynak: Kullanıcı isteği (2026-04-22). Detaylı model isimleri (Haiku, Sonnet, Gemini 2.5 Lite vb.) ve istatistik — uyarı/monitoring sistemi out-of-scope.

### SQLite Şeması — `token_usage` Tablosu

```sql
CREATE TABLE token_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,                    -- ISO8601 UTC
    model_id TEXT NOT NULL,                     -- ör. "claude-3-5-haiku-20241022", "gemini-2.0-flash"
    model_name TEXT NOT NULL,                   -- insan okunur (ör. "Haiku 4.5", "Sonnet 4.6", "Gemini 2.5 Lite", "Ollama/Llama3")
    backend TEXT NOT NULL,                      -- "anthropic" | "gemini" | "ollama"
    input_tokens INTEGER NOT NULL,              -- bu çağrıda kullanılan input token
    output_tokens INTEGER NOT NULL,             -- bu çağrıda üretilen output token
    total_tokens INTEGER NOT NULL,              -- input + output
    session_id TEXT,                            -- opsiyonel; Bridge session
    context TEXT DEFAULT 'bridge_query',        -- ör. "bridge_query", "test", "internal_cmd"
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Query API — İstatistik Fonksiyonları

```python
# token_stat_repo.py
class TokenStatRepository:
    async def add_usage(self, model_id: str, model_name: str, backend: str, 
                        input_tokens: int, output_tokens: int, 
                        session_id: str | None = None, context: str = "bridge_query")
    
    async def get_usage_by_model_category(self, category: str, timespan_hours: int) 
        # ör. category="Haiku 4.5" → o kategorideki tüm model ID'ler
        # → {model_id: "...", call_count: int, total_input: int, total_output: int}
    
    async def get_hourly_trend(self, timespan_hours: int) 
        # → [{hour: "2026-04-22T14:00Z", input_tokens: X, output_tokens: Y}, ...]
    
    async def get_backend_breakdown(self, timespan_hours: int) 
        # → {anthropic: {input: X, output: Y, calls: Z}, gemini: {...}, ollama: {...}}
    
    async def get_model_ranking(self, limit: int = 10) 
        # → [{rank, model_name, call_count, total_input, total_output}, ...]
    
    async def get_category_summary(self, timespan_hours: int) 
        # → {Haiku 4.5: {input, output, calls}, Sonnet 4.6: {...}, ...}
    
    async def get_total_cost_estimate(self, api_prices: dict[str, dict[str, float]], timespan_hours: int)
        # ör. {"anthropic": {"haiku_input": 0.80/1M, "haiku_output": 2.40/1M}, ...}
        # → {backend: {...cost per model...}, total_cost_usd: X}
```

### Provider Metadata — Detaylı Model Adları

| Backend | Model ID | Model Name (Kategori) | Input Token Alanı | Output Token Alanı |
|---------|----------|-------------------|------|-----|
| **Anthropic** | `claude-3-5-haiku-20241022` | Haiku 4.5 | `response.usage.input_tokens` | `response.usage.output_tokens` |
| | `claude-3-5-sonnet-20241022` | Sonnet 4.6 | idem | idem |
| | `claude-opus-4-6` | Opus 4.6 | idem | idem |
| **Gemini** | `gemini-2.0-flash` | Gemini 2.0 Flash | `response.usage_metadata.prompt_token_count` | `response.usage_metadata.candidates_token_count` |
| | `gemini-2.5-flash-latest` | Gemini 2.5 Flash | idem | idem |
| | `gemini-exp-1114` | Gemini Exp 1114 | idem | idem |
| **Ollama** | `llama3` | Ollama/Llama3 | `response["prompt_eval_count"]` | `response["eval_count"]` |
| | `mistral` | Ollama/Mistral | idem | idem |

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
| TOKEN-STATS-1 | Session başına detaylı token takibi | `store/repositories/token_stat_repo.py` (**YENİ**), `store/sqlite_store.py:add_token_stat()`, `adapters/llm/{anthropic,gemini,ollama}_provider.py` | Her `complete()` çağrısı sonrası provider `(model_id: str, model_name: str, input_tokens: int, output_tokens: int)` tuple döner. Router/Feature `store.add_token_stat(...)` ile kaydeder. **Provider listesi**: Anthropic: Haiku 4.5 / Sonnet 4.6 / Opus 4.6. Gemini: Flash / 2.5 Flash / Exp. Ollama: Llama3 / Mistral vb. Tablo şeması: `model_id, model_name, backend, input/output_tokens, timestamp, session_id, context`. |
| TOKEN-STATS-2 | `!tokens` komutu — kategori başına istatistik | `guards/commands/tokens_cmd.py` (**YENİ**) + `guards/commands/__init__.py` + `help_cmd.py` + `locales/{tr,en}.json` | Komut: `!tokens [24h|7d|30d]` (varsayılan 24h) → Son 24 saatin özeti. Output: **Toplam** (2.5M input + 680K output), **Model Kategorileri** (Haiku: 1.2M in + 340K out, 42 calls; Sonnet: 1.0M in + 280K out, 18 calls; vb.), **Backend'ler** (Anthropic: 2.2M in + 620K out; Gemini: 300K in + 60K out; vb.), **Saatlik Trend** (opsiyonel; grafik ASCII varsa). Perm: `OWNER`. |

---

## 🟡 ORTA — Wizard LLM-Destekli Mimari Üretimi (WIZ-LLM — Faz 2)

*(WIZ-LLM-1..9 tamamlandı — bkz. ✅ Tamamlanan)*

---

## 🟡 ORTA — Modüler Ajan: Yaşam Döngüsü ve Tutarlılık

> Kaynak: Modüler ajan analizi (2026-04-19)

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
| ~~MOD-6~~ | ~~Calendar feature için enable/disable flag ve API gating ekle~~ | ~~`routers/api/calendar_api.py`~~ | ✅ `calendar_api.py:28,37` — `restrict_calendar` kontrolü her iki handler'da mevcuttu |
| ~~MOD-8~~ | ~~Webhook proxy shutdown hook ekle~~ | ~~`features/_registry.py`~~ | ✅ `_registry.py:40-44` — `_webhook_proxy_shutdown()` → `stop_proxy()` LIFO shutdown hook olarak kayıtlı |
| ~~MOD-9~~ | ~~Flag adlandırma tutarsızlığını gider~~ | ~~`config.py`~~ | ✅ 5 Pattern-B alias eklendi: `scheduler_enabled` (önceden vardı) + `conv_history_enabled`, `intent_classifier_enabled`, `pdf_import_enabled`, `plans_enabled`. Router/feature dosyalarındaki 18 direkt `restrict_*` kullanımı yeni alias'larla güncellendi. |

---

## 🔴 KRİTİK — Modüler Ajan: Feature Manifest Sistemi

> Kaynak: Modüler ajan analizi (2026-04-19) — MOD-1..9 tamamlandıktan sonra uygulanacak

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|

---

## 🟡 ORTA — OOP/SOLID İyileştirmeleri

> Kaynak: `reports/oop_solid_audit_2026-04-19.md`

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
| ~~SOLID-4~~ | ~~Wizard state handler'ları için registry pattern~~ | ~~`routers/_text_router.py:74-122`~~ | ✅ `_text_router.py:98-107` — `_WIZ_REGISTRY` dict (8 handler: awaiting_project_name, description, path, service_name, cmd, port, cwd, pending_pdf) mevcuttu |
| ~~SOLID-6~~ | ~~`_dispatcher.py` auth flow dispatch ayrıştır~~ | ~~`routers/_dispatcher.py:66-71`~~ | ✅ `_auth_dispatcher.py:104` — `_AUTH_FLOW_REGISTRY` dict + `handle_auth_flow()` fonksiyonu mevcuttu; `_dispatcher.py:68` tek satır çağrı |

---

## 🟢 DÜŞÜK — Kod Kalitesi ve Dokümantasyon

> Kaynak: `reports/full_audit_2026-04-15.md`, `reports/wizard_ux_research_2026-04-16.md`, `reports/wizard_bug_report_2026-04-16.md`, `reports/github_dist_audit_2026-04-16.md`

*(Tüm DÜŞÜK maddeler tamamlandı — bkz. ✅ Tamamlanan)*

---

## 🟢 DÜŞÜK — Modüler Ajan: Kurulum

> Kaynak: Modüler ajan analizi (2026-04-19) — ⚠️ PROD ÖNCESİ YAPILMALI

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
~~MOD-INSTALL-1a tamamlandı — bkz. ✅ Tamamlanan~~
~~MOD-INSTALL-1b tamamlandı — bkz. ✅ Tamamlanan~~
~~MOD-INSTALL-1c tamamlandı — bkz. ✅ Tamamlanan~~

---

## 🟢 DÜŞÜK — OOP/SOLID İyileştirmeleri

> Kaynak: `reports/oop_solid_audit_2026-04-19.md`

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
~~SOLID-9 tamamlandı — bkz. ✅ Tamamlanan~~

---

## 🟡 Açık — Kullanıcı Eylemi Gereken

| # | Başlık | Not |
|---|--------|-----|
| OPS-4 | Beta modu uçtan uca test | WMA başlatılıp `/internal/message` endpoint doğrulanmalı |
| OPS-9 | `API_KEY` .env'de boş — `/agent/*` endpointleri korumasız | Startup'ta 121 kez "api_key tanımlı değil" uyarısı basıyor; `/agent/*` tüm endpointlere yetkisiz erişim açık. `.env`'e `API_KEY=<güçlü-key>` ekle. |
| OPS-6 | WMA `.env` — CHROMA_PATH düzelt | `.env` içinde `CHROMA_PATH=...10-base/**agents**/whatsapp-memory-agent/data/chromadb` → `...10-base/whatsapp-memory-agent/data/chromadb` yap; WMA FastAPI'yi yeniden başlat. Kayıt sayısı 0 → 553 olmalı. |

---

## 🟠 Deferred / Out of Scope — Token Monitoring Uyarısı Sistemi

> Kaynak: TOKEN-WATCH task'ları (2026-04-22 isteğine cevap). Uyarı + monitoring sistemi out-of-scope — kullanıcı isteği basit istatistik tutmaya yönelendirildi.

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
| TOKEN-WATCH-2 | %90 kota uyarı bildirimi | `services/token_monitor.py` (**DEFERRED**) | **Out-of-Scope:** Otomatik monitoring + uyarı sistemi. Alternatif: Kullanıcı `!tokens` komutuyla manuel kontrol etsin. `MONTHLY_TOKEN_BUDGET` env zorunlu gerekmez. |
| TOKEN-WATCH-4 | Provider-generic uyum testleri | `scripts/tests/test_token_tracking.py` (**DEFERRED**) | **Out-of-Scope:** Kompleks test suit. `TOKEN-STATS-1/2` basit doğrulama yeterli. |

---

## 🟠 YÜKSEK — Güvenlik Taraması

> Kaynak: Gece analiz önerisi (2026-04-19)

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
| ~~SEC-NIGHT-1~~ | ~~Yeni endpoint'ler güvenlik taraması~~ | ~~`routers/desktop_router.py`, `routers/terminal_router.py`, `routers/internal_router.py`~~ | ~~Desktop, terminal ve internal router'lar için security-review skill çalıştır; OWASP Top 10 + injection riski + localhost-only kısıtlamaları doğrula~~ | ✅ 3 bulgu giderildi (BUG-SEC-1/2/3); rapor: `reports/sec_night1_router_security_2026-04-19.md` |

---

## 🟡 ORTA — Test Coverage Genişletme

> Kaynak: Gece analiz önerisi (2026-04-19) — Mevcut testler: dedup, rate_limiter, slugify, sqlite_store, blacklist

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
| ~~TEST-1~~ | ~~Guards unit testleri~~ | ~~`guards/guard_chain.py`, `guards/message_guards.py`, `guards/capability_guard.py`~~ | ~~`GuardChain` orkestrasyon, `OwnerPermissionGuard`, `RateLimitMessageGuard`, `CapabilityGuard` kural tetikleme testleri~~ | ✅ |
| ~~TEST-2~~ | ~~Commands unit testleri~~ | ~~`guards/commands/`~~ | ~~Registry kayıt/bulunamadı/yetki reddi senaryoları; her komut için execute() happy path~~ | ✅ |
| ~~TEST-3~~ | ~~Adapter unit testleri~~ | ~~`adapters/llm/`, `adapters/messenger/`~~ | ~~Factory kayıt/seçim; `CLIMessenger` send_text; `AbstractLLMProvider` mock ile complete()~~ | ✅ |
| ~~TEST-4~~ | ~~Feature unit testleri~~ | ~~`features/`~~ | ~~`chat`, `plans`, `calendar`, `scheduler` için temel happy path; store mock olarak `StoreProtocol` kullanan implementasyon~~ | ✅ |
| ~~TEST-5~~ | ~~Router entegrasyon testleri~~ | ~~`routers/`~~ | ~~`/whatsapp/webhook`, `/telegram/webhook`, `/internal/*` endpoint'leri için HMAC/secret doğrulama + guard zinciri entegrasyon testleri~~ | ✅ |

---

## 🟡 ORTA — i18n Paritet ve Hardcode String Taraması

> Kaynak: Gece analiz önerisi (2026-04-19)

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
| ~~I18N-1~~ | ~~`tr.json` ↔ `en.json` paritet kontrolü~~ | ~~`locales/tr.json`, `locales/en.json`~~ | ~~Eksik/fazla key'leri tespit et; `en.json`'daki boşlukları `tr.json`'dan türeterek doldur~~ | ✅ |
| ~~I18N-2~~ | ~~Hardcode string taraması~~ | ~~`scripts/backend/` (tüm)~~ | ~~`t()` çağrısı olmadan kullanıcıya gönderilen sabit string'leri tespit et; `locales/` dosyalarına taşı~~ | ✅ |

---

## 🟠 YÜKSEK — Dependency Güvenlik Denetimi

> Kaynak: Gece analiz önerisi (2026-04-19)

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
~~| DEP-1 | Python bağımlılıkları CVE taraması | tamamlandı — bkz. ✅ Tamamlanan |~~
~~| DEP-2 | Node.js bağımlılıkları CVE taraması | tamamlandı — bkz. ✅ Tamamlanan |~~
~~| DEP-3 | Güncel sürüm karşılaştırması | tamamlandı — bkz. ✅ Tamamlanan |~~

---

## 🟡 ORTA — Performans Profiling

> Kaynak: Gece analiz önerisi (2026-04-19)

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
| ~~PERF-1~~ | ~~Bridge sorgu token tüketimi analizi~~ | ~~`outputs/logs/bridge.log`~~ | ✅ Tamamlandı — bkz. aşağıda |
| ~~PERF-2~~ | ~~Yavaş endpoint tespiti~~ | ~~`outputs/logs/app.log`, `outputs/logs/webhook.log`~~ | ✅ Tamamlandı — bkz. aşağıda |
| ~~PERF-3~~ | ~~Guard zinciri gecikme ölçümü~~ | ~~`guards/guard_chain.py`~~ | ✅ Tamamlandı — bkz. aşağıda |

---

## 🔴 YÜKSEK — Token Optimizasyonu (PERF-1 Bulguları)

> Kaynak: `reports/perf1_token_analysis_2026-04-19.md` — Read aracı token bütçesinin %85'ini tüketiyor

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
| ~~PERF-OPT-1~~ | ~~`.claude-routes.json` kapsamını genişlet~~ | ~~`.claude-routes.json`~~ | ✅ 12 → 33 rota. Log analizine göre en sık okunan dosyalar (desktop 146+114, whatsapp_router 131, server.js 110, main.py 84, browser 68+34, scheduler 62, i18n 54+34) artık route'a bağlı. Yeni kategoriler: desktop, desktop_vision, browser, i18n, text_routing, menu, plans, calendar, terminal, telegram, app_types, history, media, pdf, projects, auth, webhook_proxy, main_startup, capability_guard, credential_store, internal_router. |

---

## 🔴 YÜKSEK — Latency / Güvenilirlik (PERF-2 Bulguları)

> Kaynak: `reports/perf2_endpoint_latency_2026-04-19.md` — 556 Bridge çağrısı, medyan 47s, %45'i >60s. FastAPI/guard overhead ihmal edilebilir (<50ms); asıl gecikme CLI çalışma süresi.

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
~~| PERF-OPT-4 | Bridge timeout artırımı ve progressive feedback | tamamlandı — bkz. ✅ Tamamlanan |~~

---

## 🟡 ORTA — Token Optimizasyonu (PERF-1 Bulguları)

> Kaynak: `reports/perf1_token_analysis_2026-04-19.md`

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
~~| PERF-OPT-2 | Tekrarlanan dosya okumalarını detect et | tamamlandı — bkz. ✅ Tamamlanan |~~

---

## 🟡 ORTA — Latency / Güvenilirlik (PERF-2 Bulguları)

> Kaynak: `reports/perf2_endpoint_latency_2026-04-19.md`

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
| ~~PERF-OPT-5~~ | ~~Proje session'ları için init_prompt küçültme~~ | ~~`scripts/claude-code-bridge/server.js`~~ | ✅ `buildInitPrompt`'ta `hasActiveRootProject` kontrolü eklendi: `active_root_project` setilendiğinde tam root CLAUDE.md (~15KB) atlanıyor. Proje CLAUDE.md'si `activeRootProject` bölümünden geliyor; `base` kritik kuralları barındırıyor. Tahmini token tasarrufu: ~2000 token/sorgu. |

---

## 🟢 DÜŞÜK — Token Optimizasyonu (PERF-1 Bulguları)

> Kaynak: `reports/perf1_token_analysis_2026-04-19.md`

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
| ~~PERF-OPT-3~~ | ~~`CLAUDE.md` boyutunu takip et~~ | ~~`CLAUDE.md`~~ | ✅ `server.js`'e `checkClaudeMdSize()` eklendi: başlangıçta satır sayısı loglanır, 1000 satır aşılınca BACKLOG'a otomatik uyarı eklenir. `buildInitPrompt`'a `claudeMdSizeNote` satırı eklendi — her sorguda mevcut boyut görünür. |

---

## 🟢 DÜŞÜK — Latency / Güvenilirlik (PERF-2 Bulguları)

> Kaynak: `reports/perf2_endpoint_latency_2026-04-19.md`

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
| ~~PERF-OPT-6~~ | ~~`ERR:` boş status girişlerini araştır~~ | ~~`outputs/logs/bridge.log`, `scripts/claude-code-bridge/server.js`~~ | ✅ Kök neden: `str(exc)` bazı httpx exception'larında boş string döndürüyor. `_bridge_client.py`: `error_msg` artık `f"{type(exc).__name__}: {exc}"` formatında — boşsa `repr(exc)` kullanılıyor. `server.js`: `_logBridgeError()` eklendi; TIMEOUT / CLI_EXIT / API_ERR hataları `bridge.log`'a `{status:"ERR", error_type, error, latency_ms}` JSON olarak yazılıyor. Python OK. Node OK. |

---

## 🟢 DÜŞÜK — Guard Zinciri Performansı (PERF-3 Bulguları)

> Kaynak: `reports/perf3_guard_chain_latency_2026-04-19.md` — 500 istek benchmark. Guard zinciri median 2.25ms; end-to-end gecikmede payı %0.005. Bottleneck değil; asıl gecikme Claude Code CLI (PERF-2 ile tutarlı).

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
~~| PERF-OPT-7 | SQLite WAL modu — DedupGuard opsiyonel iyileştirme | `store/_connection.py` | tamamlandı — bkz. ✅ Tamamlanan |~~

---

## 🟡 ORTA — GUARDRAILS Genişletme

> Kaynak: Gece analiz önerisi (2026-04-19)

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
~~| GR-1 | Yeni tehlikeli komut kategorileri ekle | `GUARDRAILS.md` | tamamlandı — bkz. ✅ Tamamlanan |~~
~~| GR-2 | `guardrails_loader.py` token listesi doğrulama | `guards/guardrails_loader.py` | tamamlandı — bkz. ✅ Tamamlanan |~~

---

## 🟢 DÜŞÜK — Dokümantasyon Düzeni

> Kaynak: Gece analiz önerisi (2026-04-19)

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
| DOC-MEM-1 | `MEMORY.md` + `WORK_LOG.md` güncellik denetimi | `MEMORY.md`, `WORK_LOG.md` | Son 30 günlük değişikliklerle karşılaştır; stale/eksik teknik karar kayıtlarını tespit et ve güncelle |

---

## 🟢 DÜŞÜK — API Endpoint Dokümantasyonu

> Kaynak: Gece analiz önerisi (2026-04-19)

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
| DOC-API-1 | OpenAPI schema zenginleştirme | `routers/api/`, `routers/personal_agent_router.py`, `routers/internal_router.py` | Her endpoint için `summary`, `description`, `response_model`, örnek request/response ekle; FastAPI `/docs` sayfası kullanılabilir hale gelsin |

---

## 🟡 ORTA — Logging Sistemi İyileştirmeleri

> Kaynak: `logging_config.py` + `store/message_logger.py` analizi (2026-04-18)

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|

---

## 🟢 DÜŞÜK — Logging Yapılandırma Eksiklikleri

> Kaynak: `logging_config.py` analizi (2026-04-18) — Yeni router/feature eklendikçe config güncellenmemiş

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
| ~~LOG-2~~ | ~~`telegram_router` logging_config'de eksik~~ | ✅ 2026-04-19 |
| ~~LOG-3~~ | ~~`desktop_router` ve `terminal_router` logging_config'de eksik~~ | ✅ 2026-04-19 |
| ~~LOG-5~~ | ~~`_dispatcher.py` ve `_auth_flows.py` logging_config'de yok~~ | ✅ 2026-04-19 |

---

## 🟢 Açık — Yeni Özellikler

| # | Başlık | Not |
|---|--------|-----|
| ~~FEAT-20~~ | ~~Desktop — uygulama açıldığında tam ekrana al ve popup'ları kapat~~ | ~~[KAPSAM DIŞI — 2026-04-19]~~ |
| ~~FEAT-19~~ | ~~Desktop işlem öncesi ekran kilit durumunu kontrol et~~ | ~~[KAPSAM DIŞI — 2026-04-19]~~ |
| ~~FEAT-18~~ | ~~`!cancel` ile aktif Bridge görevini iptal et~~ | ✅ 2026-04-19 |
| ~~DOC-SKILL-1~~ | ~~Skill dokümantasyonu — `reports/skill_audit_2026-04-18.md` içeriğini `docs/` altına taşı~~ | ✅ 2026-04-19 — `docs/skills.md` oluşturuldu; README'ye link eklendi; `reports/done/` klasörüne taşındı. |
| ~~FEAT-8~~ | ~~Ekran görüntüsü — `scrot` ile GNOME D-Bus sorunu gider~~ | ✅ 2026-04-19 — `_detect_xauthority()` eklendi (`desktop_common.py`); `_env()` artık XAUTHORITY'yi de set ediyor; `gnome-screenshot` araç listesinden çıkarıldı, `scrot` birincil araç oldu (`desktop_capture.py`) |
| ~~BUG-DESK-SEND-1~~ | ~~Desktop screenshot/video dosyası WhatsApp'a gönderilmiyor~~ | ✅ 2026-04-19 — `/internal/send_media` endpoint eklendi (`internal_router.py`); CLAUDE.md Desktop API bölümüne kullanım akışı dokümante edildi. |
| ~~LOG-DESK-1~~ | ~~Desktop işlem logları — her aksiyon ayrı ve detaylı loglanmalı~~ | ✅ 2026-04-20 |
| ~~FEAT-DESK-MULTIMON-1~~ | ~~Desktop screenshot/video — çoklu monitör desteği~~ | ✅ 2026-04-19 |
| ~~FEAT-DESK-REC-1~~ | ~~Desktop kontrolü sırasında ekran video kaydı~~ | ✅ 2026-04-19 |
| ~~UX-CMD-1~~ | ~~Servis restart/shutdown isteğini `!restart` / `!shutdown` komutuna yönlendir~~ | ✅ 2026-04-19 |
| ~~FEAT-13~~ | ~~Playwright tabanlı tarayıcı otomasyonu~~ | ✅ 2026-04-18 |
| ~~FEAT-14~~ | ~~Oturum başında bağlam sürekliliği — history kontrolü~~ | ✅ 2026-04-19 |
| ~~FEAT-15~~ | ~~Browser session kalıcılığı — restart'a kadar oturumu açık tut~~ | ✅ 2026-04-18 |
| ~~FEAT-16~~ | ~~Site-özel credential store~~ | ✅ 2026-04-18 |
| ~~FEAT-17~~ | ~~AT-SPI accessibility tree — masaüstü uygulama kontrolü~~ | ✅ 2026-04-18 |
| ~~UX-MODEL-1~~ | ~~`!model` komutu butonlu model seçimi~~ | ✅ 2026-04-22 |

---

## 🟡 ORTA — Desktop Otomasyon Hızlandırma

> Kaynak: `reports/desktop_automation_optimization_2026-04-18.md` — mevcut screenshot+vision döngüsü optimizasyonu

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
| ~~BROWSER-1~~ | ~~Playwright DOM-first genişletme~~ | ✅ 2026-04-22 |
| ~~OPT-2~~ | ~~Region screenshot desteği~~ | ✅ 2026-04-18 |
| ~~OPT-3~~ | ~~Bounding box önbelleği~~ | ✅ 2026-04-18 |

---

## 🟠 YÜKSEK — Desktop Login Görev Optimizasyonu (Mercek Raporu)

> Kaynak: `reports/desktop-mercek-login-optimization_2026-04-22.md` — mercek.itu.edu.tr login görevi 15dk timeout analizi. **Temel ilke: Anthropic Vision API'ye bağımlı olmadan, Playwright DOM selector ile çalışabilmeli.**

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
| ~~DESK-LOGIN-1~~ | ~~Login görevlerinde Playwright-first strateji~~ | ~~CLAUDE.md, .claude-routes.json~~ | ✅ 2026-04-22 |
| ~~DESK-LOGIN-2~~ | ~~`unlock_screen` aksiyonunu güçlendir + `is_locked` aksiyonu ekle~~ | ~~`features/desktop.py`~~ | ✅ 2026-04-22 |
| ~~DESK-LOGIN-3~~ | ~~Vision API yokken fallback stratejisi: görev başında kullanıcıya sor~~ | ~~`features/desktop_vision.py`~~ | ✅ 2026-04-22 |
| ~~DESK-LOGIN-5~~ | ~~xdotool timeout'u 10s → 5s'e düşür~~ | ~~`features/desktop_common.py`~~ | ✅ 2026-04-22 |

---

## 🟠 YÜKSEK — Desktop/Browser Güvenilirlik (Gemini Araştırması)

> Kaynak: `reports/gemini_research_2026-04-19.md` — Linux/X11 masaüstü otomasyon hız ve gecikme optimizasyonu

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
| ~~DESK-OPT-1~~ | ~~Async X11 race condition — `asyncio.Lock()` + `asyncio.to_thread()` zorunlu~~ | ~~`features/desktop_input.py`, `desktop_capture.py`~~ | ✅ `x11_lock = asyncio.Lock()` `desktop_common.py`'ya eklendi. Tüm X11 subprocess çağrıları lock altına alındı: `desktop_input.py` (type/key/move/scroll + click için atomik mousemove+click), `desktop_capture.py` (scrot/import, xrandr), `desktop_vision.py` (getactivewindow), `desktop.py` (xdg-screensaver, xdotool, wmctrl, focus_window, get_windows). |
| ~~DESK-OPT-2~~ | ~~`xdotool type` → `python-xlib` XTEST veya `evdev` — X server freeze önleme~~ | ~~`features/desktop_input.py`~~ | ✅ `xdotool_type()` python-xlib XTEST kullanan in-process implementasyona güncellendi. Fork/exec overhead yok; ğ/ş/ö/ü/ı/İ gibi Türkçe Unicode karakterler `0x01000000|codepoint` keysym formuyla sorunsuz gönderiliyor; keysym-keycode eşleşmesi yoksa scratch_keycode ile geçici remap yapılıp sıfırlanıyor. xdotool fallback korundu. `requirements.txt`'e `python-xlib>=0.33` eklendi. |

---

## 🟡 ORTA — Desktop/Browser Performans (Gemini Araştırması)

> Kaynak: `reports/gemini_research_2026-04-19.md`

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
| ~~DESK-OPT-3~~ | ~~`scrot` subprocess → `python-mss` — sıfır disk I/O, bellekten Base64~~ | ~~`features/desktop_capture.py`~~ | ✅ `_mss_capture_to_bytes_sync()` executor'da çalışır; x11_lock altında DISPLAY/XAUTHORITY set edilir. `capture_screen()` mss'i birincil yöntem olarak kullanır, scrot/import fallback korundu. Yeni `capture_screen_base64_fast()` tamamen bellekte çalışır (disk I/O yok). `requirements.txt`'e `mss>=9.0` eklendi. `desktop.py` thin wrapper + `__all__` güncellendi. |
| ~~DESK-OPT-4~~ | ~~Playwright: `networkidle`/`getByRole` → `domcontentloaded` + CSS seçiciler~~ | ~~`features/browser.py`~~ | ✅ `_make_locator()` helper eklendi (CSS seçicilere `css=` ön eki, XPath/text=/role= olduğu gibi). `browser_fill`, `browser_click`, `browser_get_text`, `browser_wait_for` — `wait_for_selector` + ayrı action çifti → `locator.fill/click/inner_text/wait_for` tek çağrıya dönüştürüldü. `browser_goto` zaten `domcontentloaded` defaultunu kullanıyordu; `networkidle` uyarısı docstring'e eklendi. |
| ~~DESK-OPT-5~~ | ~~Playwright CDP direkt kullanım — tıklama gecikmesi %15-20 azalır~~ | ~~`features/browser.py`~~ | ✅ `browser_cdp_click()` eklendi: `locator.bounding_box()` + `context.new_cdp_session(page)` → `Input.dispatchMouseEvent` (mousePressed+mouseReleased). `fallback=True` ile CDP hatasında `loc.click()`'e düşer. Router: `cdp_click` aksiyonu + `fallback` field. |
| ~~DESK-OPT-6~~ | ~~Pencere odak güvenilirliği: `xdotool windowfocus` → `_NET_ACTIVE_WINDOW` ClientMessage~~ | ~~`features/desktop_input.py`~~ | ✅ `_net_active_window_sync()` + `net_active_window()` eklendi. `focus_window()` öncelik sırası: xlib _NET_ACTIVE_WINDOW → wmctrl → xdotool (hem window_id hem window_name yolu). |

---

## 🟢 DÜŞÜK — Desktop/Browser Geliştirme (Gemini Araştırması)

> Kaynak: `reports/gemini_research_2026-04-19.md`

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
| ~~DESK-OPT-7~~ | ~~Desktop API batch endpoint — zincirleme aksiyonlar tek HTTP isteğinde~~ | ~~`routers/desktop_router.py`~~ | ~~✅ Tamamlandı~~ |
| ~~DESK-OPT-8~~ | ~~Popup yönetimi: polling → `SubstructureNotifyMask` X11 event dinleme~~ | ~~`features/desktop_popup.py`~~ | ~~✅ Tamamlandı~~ |

---

## 🔴 KRİTİK — Mimari / CLAUDE.md İhlalleri

> Kaynak: desktop.py + browser.py + router OOP/SOLID incelemesi (2026-04-18)

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|

---

## 🟠 YÜKSEK — SOLID İhlalleri

> Kaynak: desktop.py + browser.py + router OOP/SOLID incelemesi (2026-04-18)

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
| ~~REFAC-3~~ | ~~OCP — Router'larda 20+ uzun if-zinciri → dispatch tablosu~~ | ~~tamamlandı~~ | ✅ |
| ~~REFAC-4~~ | ~~SRP — `desktop.py` tek dosyada 8+ sorumluluk~~ | ~~tamamlandı~~ | ✅ |
| ~~REFAC-5~~ | ~~SRP — OCR mantığı (`_run_tesseract`) router'da tanımlı~~ | ~~tamamlandı~~ | ✅ |
| ~~REFAC-6~~ | ~~SRP — Credential store browser modülünden ayrıldı~~ | ~~tamamlandı~~ | ✅ |

---

## 🔵 Açık — Refactor / Mimari (Düşük Öncelik)

> Kaynak: `reports/solid_oop_analysis_2026-04-16.md`, desktop/browser OOP incelemesi (2026-04-18)

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
| ~~REFAC-7~~ | ~~Duplicate `_is_localhost` → ortak yardımcıya taşı~~ | ~~tamamlandı~~ | ✅ |
| ~~REFAC-8~~ | ~~Tip güvenliği — `_sessions` iç dict'i `TypedDict` olmalı~~ | ~~tamamlandı~~ | ✅ |

---

## 🌍 GitHub Dağıtımı, Cross-Platform ve OOP/SOLID Mimari

> **Hedef:** Projeyi isteyen herkesin kurup çalıştırabileceği açık kaynak bir kişisel ajan sistemine dönüştürmek.  
> Tüm yeni bileşenler OCP-uyumlu olmalı: yeni platform = yeni dosya, mevcut koda dokunulmaz.

### Temel Mimari Kural — `AbstractMessenger` + `AbstractLLMProvider`

```
AbstractMessenger          AbstractLLMProvider
  ├── WhatsAppMessenger       ├── AnthropicProvider
  ├── TelegramMessenger       ├── OllamaProvider
  └── CLIMessenger            └── GeminiProvider
```

Her adapter: `send_text()`, `send_buttons()`, `receive_message()` / `complete()` metotlarını implemente eder.  
Platform veya model eklemek için `adapters/` altına yeni dosya yazılır; `messenger_factory.py` / `llm_factory.py` `.env`'e göre hangisini yükleyeceğine karar verir.

---

| # | Başlık | Kaynak | Tarih | Not |
|---|--------|--------|-------|-----|
| G2 | Telegram messenger adaptörü | [OBS] | 2026-04-14 | ✅ — `adapters/messenger/telegram_messenger.py` + `whatsapp_messenger.py` + `messenger_factory.py`; `AbstractMessenger` Protocol |
| G3 | İki dilli README (TR + EN) | [OBS] | 2026-04-14 | ✅ — `README.md` (EN) + `README.tr.md` (TR) |
| G4 | `.gitignore` ve `.env.example` | [OBS] | 2026-04-14 | ✅ — `.gitignore` + `.env.example` güncellendi |
| G5 | Lisans | [OBS] | 2026-04-14 | ✅ — `LICENSE` (MIT) oluşturuldu; README'lere bağlantı eklendi |
| G6 | Interactive setup wizard | [OBS] | 2026-04-14 | ✅ — `setup.py` (479 satır): `BaseSetupStep`, `SetupOrchestrator`, `EnvWriter` |
| G7 | `AbstractLLMProvider` — BYOK/BYOM | [OBS] | 2026-04-14 | ✅ — `adapters/llm/anthropic_provider.py` + `ollama_provider.py` + `llm_factory.py`; `AbstractLLMProvider` Protocol |
| G8 | PM2 process manager desteği | [OBS] | 2026-04-14 | ✅ — `ecosystem.config.js`: `99-api` + `99-bridge` tanımları |
| G9 | BYOK/BYOM dokümantasyonu | [OBS] | 2026-04-14 | ✅ — `docs/deployment/byok.md` oluşturuldu |
| G10 | VPS + Raspberry Pi deployment kılavuzları | [OBS] | 2026-04-14 | ✅ — `docs/deployment/vps.md` + `docs/deployment/raspberry-pi.md` |
| PORT-4 | Docker Compose desteği | [OBS] | 2026-04-14 | ✅ — `docker-compose.yml`, `Dockerfile.api`, `Dockerfile.bridge` |
| PORT-5 | Docker — Claude Code CLI erişimi | [OBS] | 2026-04-14 | ✅ — `Dockerfile.bridge` içinde `npm ci` ile `@anthropic-ai/claude-code` yerel kurulum |
| PORT-6 | Yapılandırılabilir webhook proxy | [OBS] | 2026-04-14 | ✅ — `features/webhook_proxy.py`; ngrok/cloudflared/external/none modları |
| SEC-7 | Bridge çıktı filtresi | [OBS] | 2026-04-14 | ✅ — `output_filter.py`; `whatsapp_router.py` entegre |
| SEC-8 | Dinamik Guardrail Yükleyici | [OBS] | 2026-04-14 | ✅ — `guardrails_loader.py`; `whatsapp_router.py` entegre |
| SEC-9 | Pre-Execution Self-Check | [OBS] | 2026-04-14 | ✅ — `CLAUDE.md` satır 197'de `Pre-Execution Guardrail Check` mevcut |

---


## 🔴 KRİTİK — Bug Audit (2026-04-18)

> Kaynak: `reports/bug_audit_2026-04-18.md`

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
~~| BUG-C1 | `import time` eksik → `end_session()` her çağrıda NameError | `features/history.py:68,74` | `import time` satırını dosya başına ekle |~~
~~| BUG-C2 | Bare `send_text` çağrısı → `!project-delete` akışı çöker | `features/menu_project.py:157` | `await send_text(...)` → `await _get_messenger().send_text(...)` |~~

---

## 🔴 KRİTİK — Güvenlik Audit (2026-04-18)

> Kaynak: `reports/security_audit_2026-04-18.md`

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
~~| SEC-C1 | Bridge tüm endpoint'lerde authentication yok (port 8013) | `server.js` | `BRIDGE_API_KEY` env + `authenticate()` middleware → `/query`, `/reset`, `/status`, `/perm_check` vb.; `_bridge_client.py`'e `x-api-key` header ekle |~~

---

## 🟠 YÜKSEK — Bug Audit (2026-04-18)

> Kaynak: `reports/bug_audit_2026-04-18.md`

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
| ✅ BUG-H1 | `active_root_project` path'i `allowedRoots` doğrulamasından geçmiyor → path traversal riski | `server.js:713-753` | Tamamlandı: allowedRoots bloğu dışarıya çıkarıldı, fallback dalına allowedRoots.some() kontrolü eklendi |
| ✅ BUG-H2 | Math cancel lock dışında state temizliyor → session state corruption | `routers/_auth_dispatcher.py:29-31` | Tamamlandı: cancel bloğu `async with session_mgr.lock(sender):` içine alındı |

---

## 🟠 YÜKSEK — Güvenlik Audit (2026-04-18)

> Kaynak: `reports/security_audit_2026-04-18.md`

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
| ✅ SEC-H1 | Admin TOTP brute-force koruması eksik — `!restart`, `!shutdown`, `!project-delete` savunmasız | `guards/permission.py` | Tamamlandı: `/internal/verify-admin-totp` endpoint'ine `totp_record_failure`/`totp_get_lockout` eklendi; `"internal_cli"` sender key, `"admin"` totp_type — 3 başarısız deneme → 15 dk kilit. Python OK. |
| ✅ SEC-H2 | Rate limiter X-Forwarded-For spoofing ile bypass edilebilir | `guards/api_rate_limiter.py` | Tamamlandı: `main.py`'e `ProxyHeadersMiddleware(trusted_hosts=["127.0.0.1"])` eklendi; yalnızca 127.0.0.1 kaynağındaki X-Forwarded-For güvenilir, dış sahte header'lar yok sayılır. Python OK. |
| ✅ SEC-H3 | Bridge path doğrulaması symlink'leri engellemez → izin dışı dizin erişimi | `server.js:720-745` | Tamamlandı: `realpathSync(resolved)` ile tüm symlink katmanları takip ediliyor; gerçek hedef path `allowedRoots` kontrolüne tabi; `safeProjectPath = realPath` (symlink değil gerçek path). Node OK. |
| ✅ SEC-H4 | WhatsApp HMAC doğrulaması dev modda atlanıyor | `routers/whatsapp_router.py` | Tamamlandı: `main.py` lifespan'ında `settings.environment == "production"` ve boş `whatsapp_app_secret` koşulunda `RuntimeError` fırlatılıyor — servis başlamaz. Dev modda warning devam ediyor. Python OK. |
| ✅ SEC-H5 | Telegram webhook secret dev modda atlanıyor | `routers/telegram_router.py` | Tamamlandı: (1) `main.py` lifespan'ına `MESSENGER_TYPE=telegram` + production + boş secret → `RuntimeError` eklendi; (2) `_verify_secret` runtime'da production + boş secret → 403 (defense-in-depth). Python OK. |

---

## 🟡 ORTA — Bug Audit (2026-04-18)

> Kaynak: `reports/bug_audit_2026-04-18.md`

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
| ~~BUG-M1~~ | ~~Ters zaman karşılaştırması — geçmiş timestamp'ler 59 saniyeye kadar kabul ediliyor~~ | ~~`routers/internal_router.py:138`~~ | ✅ Tamamlandı |
| ~~BUG-M2~~ | ~~Telegram `/send`'de `restrict_conv_history` guard eksik — WhatsApp ile asimetrik davranış~~ | ~~`routers/telegram_router.py:80`~~ | ✅ Tamamlandı |
| ~~BUG-M3~~ | ~~Playwright kaynak sızıntısı — exception sonrası `pw`/`browser`/`context` temizlenmiyor~~ | ~~`features/browser.py:138-162`~~ | ✅ `_get_or_create_session`'da `browser = None`, `context = None` + `try/except` ile `context.close()` → `browser.close()` → `pw.stop()` zinciri eklendi |
| ~~BUG-M4~~ | ~~Session cleanup TOCTOU — canlı session yanlışlıkla silinebilir~~ | ~~`guards/session.py:81-98`~~ | ✅ `cleanup_expired()` async yapıldı; per-session lock ile check+pop atomik; `main.py:141` await eklendi |

---

## 🟡 ORTA — Güvenlik Audit (2026-04-18)

> Kaynak: `reports/security_audit_2026-04-18.md`

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
| ~~SEC-M1~~ | ~~API key eksikliği startup'ta değil per-request kontrol ediliyor~~ | ~~`guards/api_key.py`~~ | ✅ `main.py:49-57` — production + boş `api_key` → `RuntimeError` |
| ~~SEC-M2~~ | ~~Hata mesajlarında iç detay sızıntısı (`str(e)` doğrudan HTTP yanıtına~~ | ~~`routers/api/scheduler_api.py` (ve diğerleri)~~ | ✅ `scheduler_api.py:40`, `internal_router.py:163,221` — `logger.error` + sabit "Geçersiz cron ifadesi" |
| ~~SEC-M3~~ | ~~Bridge: `/query` gelen mesaj sanitize edilmiyor~~ | ~~`server.js:~752`~~ | ✅ `server.js:714` — `safeMessage = _sanitizeConvMsg(message)` → `finalMessage` ve `retryMessage`'da kullanılıyor |
| ~~SEC-M5~~ | ~~CORS origins startup'ta doğrulanmıyor — boş değer → CORS tamamen açık kalabilir~~ | ~~`main.py` (CORS middleware)~~ | ✅ `main.py:75-83` — production + boş `cors_origins` → `RuntimeError`; `main.py:191` — filter + `["http://localhost:5678"]` fallback |

---

## 🟢 DÜŞÜK — Bug Audit (2026-04-18)

> Kaynak: `reports/bug_audit_2026-04-18.md`

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
*(Tüm DÜŞÜK Bug maddeler tamamlandı — bkz. ✅ Tamamlanan)*

---

## 🟢 DÜŞÜK — Güvenlik Audit (2026-04-18)

> Kaynak: `reports/security_audit_2026-04-18.md`

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
| ~~SEC-L1~~ | ~~`X-Api-Key` header loglanabilir — secret sızıntı riski~~ | ~~`logging_config.py`~~ | ~~`SENSITIVE_HEADERS = {"x-api-key", "authorization"}` filtresi eklenip eklenmediğini doğrula; eksikse ekle~~ |

---

## 🔵 Açık — SOLID/OOP Audit (2026-04-18) — Refactor

> Kaynak: `reports/solid_oop_audit_2026-04-18.md`

| # | Başlık | Dosya | Şiddet |
|---|--------|-------|--------|
| ~~REFAC-9~~ | ~~SRP — `_bridge_client.py` tek dosyada retry + sanitize + CLAUDE.md cache~~ | ~~tamamlandı~~ | ✅ |
| ~~REFAC-10~~ | ~~SRP — `_dispatcher.py` mesaj routing + auth dispatch karışık; `_auth_dispatcher.py` tam kullanılmıyor~~ | ~~tamamlandı~~ | ✅ |
| ~~REFAC-11~~ | ~~SRP — `BridgeMonitor` health-check + hata sayacı + bildirim + restart~~ | ~~tamamlandı~~ | ✅ |
| ~~REFAC-12~~ | ~~LSP — Messenger yetenek kontrolü `hasattr` ile ad-hoc, `@runtime_checkable Protocol` ile zorunlu değil~~ | ~~tamamlandı~~ | ✅ |
| ~~REFAC-13~~ | ~~LSP — `perm` attribute `Command` Protocol'ünde tanımlı değil, registry kaydında runtime assert~~ | ~~tamamlandı~~ | ✅ |
| ~~REFAC-14~~ | ~~DIP — `credential_store.py` settings'i fonksiyon içinde lazy import ile alıyor~~ | ~~tamamlandı~~ | ✅ |
| ~~REFAC-15~~ | ~~DIP — `whatsapp_router.py` guard chain modül-seviyesinde singleton, testlerde mock edilemiyor~~ | ~~zaten tamamlandıydı~~ | ✅ |
| ~~REFAC-16~~ | ~~DIP — `features/*.py` somut store'u doğrudan import ediyor (`StoreProtocol` kullanılmalı)~~ | ~~tamamlandı~~ | ✅ |
| ~~REFAC-17~~ | ~~Feature Envy — `_text_router.py` session dict içeriğini doğrudan okuyup yazıyor~~ | ~~tamamlandı~~ | ✅ |
| ~~REFAC-18~~ | ~~Inappropriate Intimacy — `active_context.json` yolu birden fazla dosyada tekrarlıyor~~ | ~~tamamlandı~~ | ✅ |
| ~~REFAC-19~~ | ~~Data Clump — `handle_common_message` 7 parametre; `InboundMessage` TypedDict olmalı~~ | ~~tamamlandı~~ | ✅ |

---

## 🟡 Test Kapsamı — Eksik Testler (2026-04-18)

> Kaynak: `reports/endpoint_test_coverage_2026-04-18.md` — 31 endpoint, %23 kapsam, 3 başarısız test

| # | Başlık | Not |
|---|--------|-----|
| ~~TEST-1~~ | ~~`test_dispatcher_auth.py` — 3 başarısız test düzelt~~ | ✅ Tamamlandı |
| ~~TEST-2~~ | ~~`test_telegram_router.py` — Yeni dosya (7 test)~~ | ✅ Tamamlandı |
| ~~TEST-3~~ | ~~`test_terminal_router.py` — Yeni dosya (6 test)~~ | ✅ Tamamlandı |
| ~~TEST-4~~ | ~~`test_internal_router.py`'e schedule CRUD + send_permission_prompt + send_message ekle (10 test)~~ | ✅ Tamamlandı |
| ~~TEST-5~~ | ~~`test_agent_router.py`'e 12 eksik endpoint testi ekle~~ | ✅ Tamamlandı |
| ~~TEST-6~~ | ~~`test_calendar_feature.py` — Yeni dosya (2 test)~~ | ✅ Tamamlandı |
| ~~TEST-7~~ | ~~`test_scheduler_feature.py` — Yeni dosya (6 test)~~ | ✅ Tamamlandı |
| ~~TEST-8~~ | ~~`test_history_feature.py` — Yeni dosya, BUG-C1 regresyon dahil (3 test)~~ | ✅ Tamamlandı |
| ~~TEST-9~~ | ~~`test_credential_store_feature.py` — Yeni dosya (2 test)~~ | ✅ Tamamlandı |
| ~~TEST-10~~ | ~~`test_browser_router.py` — Yeni dosya, Playwright mock (5 test)~~ | ✅ Tamamlandı |
| ~~TEST-11~~ | ~~`test_desktop_router.py` — Yeni dosya, xdotool mock (5 test)~~ | ✅ Tamamlandı |

---

## ✅ Proje Temizliği (2026-04-18) — Tamamlandı 2026-04-22

> Kaynak: `reports/project_cleanup_audit_2026-04-18.md`

| # | Başlık | Not | Durum |
|---|--------|-----|-------|
| ~~CLEAN-1~~ | ~~`data/reports/` — 2 rapor yanlış konumda~~ | Zaten `reports/done/` altındaydı | ✅ |
| ~~CLEAN-2~~ | ~~`data/root.db` — 0 byte, belgesiz, gereksiz~~ | Silindi | ✅ |
| ~~CLEAN-3~~ | ~~`data/conv_history/wrapped-synthesis.json` — yabancı içerik~~ | Silindi | ✅ |
| ~~CLEAN-4~~ | ~~`__pycache__/setup.cpython-312.pyc` — yetim artifact~~ | Silindi; `.gitignore`'da `**/__pycache__/` mevcut | ✅ |

---

## 🟠 YÜKSEK — OOP/SOLID İyileştirmeleri v2

> Kaynak: `reports/oop_solid_analysis_2026-04-22.md` — Genel puan: 8.7/10 (A-). DIP ihlalleri düzeltilmeli.

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
| ✅ SOLID-v2-1 | DIP ihlali — `_auth_flows.py` doğrudan `sqlite_store` import ediyor | `routers/_auth_flows.py` | Düzeltildi: `from ..store.sqlite_wrapper import store as db` ile değiştirildi (2 yer). |
| ✅ SOLID-v2-2 | DIP ihlali — `_bridge_client.py` doğrudan `sqlite_store` import ediyor | `routers/_bridge_client.py` | Düzeltildi: 2 async yer `sqlite_wrapper.store` ile, 1 sync yer `project_repo._sync_project_get` doğrudan import ile değiştirildi. |

---

## 🟡 ORTA — OOP/SOLID İyileştirmeleri v2

> Kaynak: `reports/oop_solid_analysis_2026-04-22.md`

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
| ✅ SOLID-v2-3 | SRP — `_forward_interactive_to_project()` port keşfi + HTTP istemci + hata mesajlaşma karışık | `routers/_dispatcher.py:155-183` | `_discover_project_api_port()` helper'ı `_bridge_client.py`'ye eklendi; 3 yerdeki tekrar kaldırıldı. |
| ✅ SOLID-v2-4 | SRP — Feature startup hook'ları registry içinde tanımlı, ilgili modüllerde değil | `features/_registry.py:30-75` | 5 hook fonksiyonu ilgili modüllere (`webhook_proxy`, `scheduler`, `browser`) `lifecycle_startup/shutdown` olarak taşındı; registry lazy import ile referans eder. |

---

## 🟢 DÜŞÜK — OOP/SOLID İyileştirmeleri v2

> Kaynak: `reports/oop_solid_analysis_2026-04-22.md`

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
| ~~SOLID-v2-5~~ | ~~Encapsulation — `SessionState` wizard alanları için wrapper metotları eksik~~ | ~~`app_types.py`, `routers/_text_router.py`~~ | ✅ Tamamlandı — `clear_wizard()`, `set_wiz()`, `start_wizard_*()` / `clear_wizard_*()`, `set_wizard_options()`, `add_wizard_service()` metotları eklendi; tüm `wiz_*` ve wizard `awaiting_*` anahtarları `_CONTROLLED_KEYS`'e alındı. |
| ~~SOLID-v2-6~~ | ~~SRP — `desktop_router.py` vision aksiyonları ayrı sub-router'a bölünebilir~~ | ~~`routers/desktop_router.py` (995 satır)~~ | ✅ Tamamlandı — Vision handler'ları `_desktop_vision.py`'ye (4 handler), capture handler'ları `_desktop_capture.py`'ye (3 handler) çıkarıldı. `desktop_router.py` 995→726 satır. |
| ~~SOLID-v2-7~~ | ~~ISP — `StoreProtocol` 199 satır, tüm domain'leri kapsar~~ | ~~`store/protocol.py`~~ | ✅ Tamamlandı — 9 domain-spesifik sub-protocol oluşturuldu: `ProjectStoreProtocol`, `PlanStoreProtocol`, `EventStoreProtocol`, `TaskStoreProtocol`, `MessageStoreProtocol`, `SessionStoreProtocol`, `BridgeStoreProtocol`, `TotpStoreProtocol`, `DedupStoreProtocol`. `StoreProtocol` tümünden kalıtır (geriye uyumlu). |

---

## ✅ Tamamlanan

| # | Başlık | Tarih | Not |
|---|--------|-------|-----|
| SOLID-v2-7 | ISP — `StoreProtocol` 9 domain-spesifik sub-protocol'e bölündü | 2026-04-22 | `ProjectStoreProtocol`, `PlanStoreProtocol`, `EventStoreProtocol`, `TaskStoreProtocol`, `MessageStoreProtocol`, `SessionStoreProtocol`, `BridgeStoreProtocol`, `TotpStoreProtocol`, `DedupStoreProtocol`. `StoreProtocol` tümünden kalıtır (geriye uyumlu). |
| SOLID-v2-6 | SRP — `desktop_router.py` vision/capture handler'ları ayrı modüllere bölündü | 2026-04-22 | Vision handler'ları (vision_query, check_vision, clear_bbox_cache, bbox_cache_stats) → `_desktop_vision.py`; capture handler'ları (screenshot, ocr, record_screen) → `_desktop_capture.py`. Ana dosya 995→726 satır. |
| SOLID-v2-5 | Encapsulation — `SessionState` wizard alanları için wrapper metotları | 2026-04-22 | `clear_wizard()`, `set_wiz()`, `start_wizard_*()` / `clear_wizard_*()`, `set_wizard_options()`, `add_wizard_service()` metotları eklendi; tüm `wiz_*` ve wizard `awaiting_*` anahtarları `_CONTROLLED_KEYS`'e alındı. |
| SOLID-v2-4 | SRP — Feature startup hook'ları ilgili modüllere taşındı | 2026-04-22 | 5 hook fonksiyonu `webhook_proxy`, `scheduler`, `browser` modüllerine `lifecycle_startup/shutdown` olarak taşındı; registry lazy import ile referans eder. |
| SOLID-v2-3 | SRP — Port keşfi tekrarı `_discover_project_api_port()` helper'ına çekildi | 2026-04-22 | `_bridge_client.py`'ye eklendi; `_dispatcher.py` ve `_bridge_client.py`'deki 3 tekrar kaldırıldı. |
| SOLID-v2-2 | DIP ihlali — `_bridge_client.py` doğrudan `sqlite_store` import | 2026-04-22 | `sqlite_wrapper.store` ile değiştirildi. |
| SOLID-v2-1 | DIP ihlali — `_auth_flows.py` doğrudan `sqlite_store` import | 2026-04-22 | `sqlite_wrapper.store` ile değiştirildi (2 yer). |
| DESK-OPT-1 | Async X11 race condition — asyncio.Lock() ile X11 seri erişim | 2026-04-19 | `x11_lock` `desktop_common.py`'ya eklendi. 5 dosyada tüm X11 subprocess çağrıları lock altına alındı; `xdotool_click` için mousemove+click atomik. |
| DESK-OPT-2 | `xdotool type` → python-xlib XTEST in-process giriş | 2026-04-20 | `xdotool_type()` XTEST ile güncellendi: fork/exec yok, Türkçe Unicode (ğ/ş/ö/ü/ı/İ) freeze yok, scratch_keycode remap mekanizması. xdotool fallback korundu. `python-xlib>=0.33` requirements'a eklendi. |
| DESK-OPT-3 | `scrot` subprocess → `python-mss` — sıfır disk I/O, bellekten Base64 | 2026-04-20 | `desktop_capture.py`: `_mss_capture_to_bytes_sync()` executor'da çalışır; x11_lock altında DISPLAY/XAUTHORITY set edilir. `capture_screen()` mss önce dener, scrot/import fallback korundu. Yeni `capture_screen_base64_fast()` tamamen bellekte çalışır. `mss>=9.0` requirements'a eklendi. `desktop.py` thin wrapper + `__all__` güncellendi. |
| MOD-3 | Plans API endpoint'leri flag kontrolü | 2026-04-19 | `plans_api.py:28,36,44` — tüm handler'larda `restrict_plans` kontrolü zaten mevcuttu. Kod değişikliği gerekmedi. |
| MOD-4 | PDF Import API endpoint'i flag kontrolü | 2026-04-19 | `pdf_api.py:25` — `restrict_pdf_import` kontrolü zaten mevcuttu. Kod değişikliği gerekmedi. |
| MOD-5 | Terminal router enable/disable flag | 2026-04-19 | `terminal_router.py:69` — `restrict_shell` kontrolü zaten mevcuttu. Kod değişikliği gerekmedi. |
| MOD-6 | Calendar API flag gating | 2026-04-19 | `calendar_api.py:28,37` — `restrict_calendar` kontrolü her iki handler'da zaten mevcuttu. Kod değişikliği gerekmedi. |
| MOD-8 | Webhook proxy shutdown hook | 2026-04-19 | `_registry.py:40-44` — `_webhook_proxy_shutdown()` → `stop_proxy()` LIFO shutdown hook olarak zaten kayıtlıydı (MOD-10 ile birlikte uygulandı). |
| SOLID-2 | Messenger DI guard'lara inject | 2026-04-19 | `whatsapp_router.py:51-52` — `get_messenger` factory zaten `OwnerPermissionGuard` ve `RateLimitMessageGuard` constructor'larına parametre olarak veriliyor; `message_guards.py` modül-seviyesinde import etmiyor. |
| SOLID-4 | Wizard state registry pattern | 2026-04-19 | `_text_router.py:98-107` — `_WIZ_REGISTRY` dict (8 handler) zaten mevcuttu; if-zinciri yok. |
| SOLID-6 | Auth flow dispatch ayrıştırma | 2026-04-19 | `_auth_dispatcher.py:104` — `_AUTH_FLOW_REGISTRY` dict + `handle_auth_flow()` zaten mevcuttu; `_dispatcher.py` tek satır `await handle_auth_flow(...)` çağrısı yapıyor. |
| PERF-3 | Guard zinciri gecikme ölçümü | 2026-04-19 | 500 sentetik istek ile ölçüldü. Zincir medyan **2.25ms**, P99=3.53ms. **DedupMessageGuard %99.5** — her yeni mesaj için SQLite INSERT (~2.3ms); diğer tüm guard'lar toplam <0.04ms. Guard chain toplam gecikmenin **%0.005**'i (47s Bridge medyanında 20.902× fark). Optimizasyon gereksiz. `guard_chain.py`'e `get_guard_stats()` + `_LOG_EVERY_N=50` aggregate loglama eklendi. Rapor: `reports/perf3_guard_chain_latency_2026-04-19.md` |
| PERF-2 | Yavaş endpoint tespiti | 2026-04-19 | 556 Bridge çağrısı analiz edildi (2026-04-11/19). Medyan 47s, P90 298s, Max 23 dk. **Gerçek bottleneck: Claude Code CLI çalışma süresi (%99+)** — FastAPI/guard overhead ihmal edilebilir (<50ms). `main` session avg 123s vs proje oturumları 5-9s (22× fark). ERR:All girişleri (avg 44ms) guard kısa-devresi — beklenen. Rapor: `reports/perf2_endpoint_latency_2026-04-19.md` |
| PERF-1 | Bridge sorgu token tüketimi analizi | 2026-04-19 | 105 sorgu analiz edildi (2026-04-11/19). `root_actions.log` araç çağrısı ağırlıklı tahmin: medyan ~96K tk, P95 ~3.6M tk. Read %85 token payı. `server.js`'e `ev.usage` → `bridge.log` logging eklendi. Rapor: `reports/perf1_token_analysis_2026-04-19.md` |
| SOLID-9 | Store doğrudan importunu protocol'e taşı | 2026-04-19 | `_dispatcher.py:155`'teki lazy `from ..store import sqlite_store as db` → modül seviyesi `from ..store.sqlite_wrapper import store as _store` (DIP-V3). Python OK, 405 test geçti. |
| MOD-2 | Scheduler API endpoint'leri flag kontrolü | 2026-04-19 | `scheduler_api.py`'deki 5 handler'ın tümünde `if not settings.scheduler_enabled: raise _SCHEDULER_DISABLED` kontrolü zaten mevcuttu. `settings.scheduler_enabled = not restrict_scheduler` property'si `config.py:151`'de tanımlı. Kod değişikliği gerekmedi; backlog güncellemesi. |
| MOD-7 | WhatsApp router'ı messenger_type'a göre koşullu kayıt | 2026-04-19 | `main.py`: WhatsApp router import + `app.include_router` Telegram pattern'i ile simetrik hale getirildi. `messenger_type != "whatsapp"` (telegram/cli) modunda `/whatsapp/*` endpoint'leri artık kayıtlı değil. Python OK. |
| MOD-9 | Flag adlandırma tutarsızlığını gider | 2026-04-19 | `config.py`'ye 4 yeni Pattern-B alias property eklendi: `conv_history_enabled`, `intent_classifier_enabled`, `pdf_import_enabled`, `plans_enabled`. 8 router/feature dosyasındaki 18 direkt `restrict_*` kullanımı alias'larla değiştirildi. Python OK, 480/481 test geçti (başarısız 1 test pre-existing). |
| SOLID-3 | `desktop_router.py` — doğrulama ve parametre dönüşüm mantığını ayır | 2026-04-19 | `_desktop_validation.py` yeni modül: `ALLOWED_ACTIONS` + 5 saf doğrulama fonksiyonu. `DesktopRequest` validator'ları saf fonksiyonlara delege ediyor (SRP-V1). `_extract_params()` if/elif zinciri → `_PARAM_EXTRACTORS` dict registry (OCP-V1). Python OK, 405 test geçti. |
| REFAC-9…19 | SOLID/OOP refactor — 11 görev toplu tamamlandı | 2026-04-19 | REFAC-9: `_bridge_helpers.py` (sanitize+CLAUDE.md cache ayrıldı). REFAC-10: `_route_interactive` dead code (perm_a/perm_d duplikesi) kaldırıldı. REFAC-11: `restart_bridge_service()` standalone fonksiyon `bridge_monitor.py`'e eklendi. REFAC-12: `__init__.py` docstring `getattr` → `isinstance`. REFAC-13: `isinstance(cmd, Command)` kontrolü `registry.py`'de. REFAC-14: `credential_store.py` lazy import → modül seviyesi. REFAC-15: zaten tamamlandı (guard_chain DI var). REFAC-16: `calendar.py`, `plans.py`, `project_crud.py` → `sqlite_wrapper.store`. REFAC-17: `SessionState.accept_project_name()` + `accept_project_description()`. REFAC-18: `ACTIVE_CONTEXT_PATH` `app_types.py`'a tek kaynak. REFAC-19: `InboundMessage` TypedDict + `handle_common_message` imzası güncellendi; testler de güncellendi. Python OK, 223 test geçti. |
| SEC-L1 | `X-Api-Key` / `authorization` header log sızıntısı | 2026-04-19 | `logging_config.py`: `SENSITIVE_HEADERS = {"x-api-key", "authorization"}`, `SensitiveHeaderFilter` + `_redact()` eklendi; tüm 9 handler'a `filters: ["sensitive_headers"]` uygulandı. Python OK, 223 test geçti. |
| BUG-L1 | Retry wait dizisi ile döngü sayısı uyumsuz — `RETRIES=4` yapılırsa `IndexError` | 2026-04-19 | `_bridge_client.py:238`: `_BRIDGE_RETRY_WAITS[_attempt]` → `_BRIDGE_RETRY_WAITS[min(_attempt, len(_BRIDGE_RETRY_WAITS) - 1)]`. Python OK. |
| REFAC-6 | SRP — Credential store `browser.py`'den `credential_store.py`'e taşındı | 2026-04-19 | `features/credential_store.py` yeni modül: `_SECRET_FIELDS`, `get_credential()`, `list_credentials()`. `browser.py`'deki credential bloğu kaldırıldı. `browser_router.py` importları `..features.credential_store` kullanıyor. Python OK, 220 test geçti. |
| REFAC-5 | SRP — `_run_tesseract` router'dan `desktop_capture.py`'e taşındı | 2026-04-19 | `features/desktop_capture.py`'e `run_tesseract_on_file(image_path)` public fonksiyon eklendi. `desktop.py` facade'ına re-export eklendi. `desktop_router.py`'deki yerel `_run_tesseract` kaldırıldı; `_handle_screenshot` artık `from ..features.desktop import run_tesseract_on_file` kullanıyor. Syntax OK, 220 test geçti. |
| REFAC-4 | SRP — `desktop.py` (1388 satır) → 5 modüle bölündü | 2026-04-18 | `desktop_common.py` (yardımcılar), `desktop_capture.py` (ekran/OCR), `desktop_input.py` (klavye/fare), `desktop_vision.py` (Vision+cache), `desktop_atspi.py` (AT-SPI). `desktop.py` ince facade. 210 test geçti. |
| REFAC-3 | OCP — Her iki router'da 20+ if-zinciri → `_HANDLERS` dispatch tablosu | 2026-04-18 | `desktop_router.py`: 19 if-bloku → `_handle_*` async fonksiyonları + `_HANDLERS dict`; `browser_router.py`: 17 if-bloku → aynı pattern. Yeni aksiyon = `_handle_*` + bir satır. Syntax OK. |
| REFAC-2 | DIP — `vision_query` → `get_llm(backend="anthropic")` adapter kullanıyor | 2026-04-18 | `features/desktop.py`: `import anthropic` + `AsyncAnthropic(api_key=...)` kaldırıldı; `get_llm(backend="anthropic")` + `llm.complete(messages, model=model, max_tokens=1024)` ile değiştirildi. Multimodal content list `AnthropicProvider.complete()` üzerinden doğrudan geçiyor. Syntax OK. |
| REFAC-1 | Global mutable state → `_BboxCache` + `_BrowserSessionStore` singleton | 2026-04-18 | `features/desktop.py`: `_bbox_cache dict + _BBOX_CACHE_TTL` → `_BboxCache` singleton sınıfı. `features/browser.py`: `_sessions dict + _sessions_lock` → `_BrowserSessionStore` singleton sınıfı. Tüm erişimler `.get/.set/.pop/.keys` metodları üzerinden; fonksiyon imzaları değişmedi. |
| FEAT-15 | Browser session kalıcılığı — cookie/storage disk persist + save/load aksiyonları | 2026-04-18 | `features/browser.py`: `_get_storage_state_path()`, `_get_or_create_session` kayıtlı state otomatik yükleme, `browser_save_session()`, `browser_delete_saved_session()`, `browser_list_saved_sessions()`, `browser_session_info()`. `routers/browser_router.py`: `save_session`, `delete_saved_session`, `list_saved_sessions`, `session_info` aksiyonları + `_ALLOWED_ACTIONS` güncellendi. `config.py`: `browser_sessions_dir` ayarı. Servis restart sonrası aynı session_id ile auto-login. |
| OPT-3 | Bounding box önbelleği — vision_query için TTL tabanlı in-memory cache | 2026-04-18 | `features/desktop.py`: `_bbox_cache` dict (TTL 60s), `_bbox_cache_key()` (md5+pencere başlığı+region), `_get_active_window_title()` (xdotool), `clear_bbox_cache()`, `get_bbox_cache_stats()`; `vision_query(use_cache=True)` parametresi eklendi. `desktop_router.py`: `use_cache` field + `clear_bbox_cache` + `bbox_cache_stats` aksiyonları. Aynı pencerede aynı soru 60s içinde tekrar sorulursa API çağrısı yapılmaz. |
| OPT-2 | Region screenshot desteği | 2026-04-18 | `features/desktop.py:capture_screen` + `vision_query`: `region=(x,y,w,h)` parametresi. `desktop_router.py:DesktopRequest`: `region: list[int]` validation. |
| UX-CMD-1 | Servis restart/shutdown isteğini `!restart` / `!shutdown` komutuna yönlendir | 2026-04-19 | `_text_router.py`: `nl_cmd == "!restart"/"!shutdown"` dalında recursive `_route_text` çağrısı yerine `t("cmd.use_restart_instead/shutdown_instead", lang)` mesajı gönderiliyor; `!root-reset` eski davranışında. `locales/tr.json` + `en.json`'a iki yeni key eklendi. Amaç: güvenlik zinciri (matematik + admin TOTP) bypass edilemesin. 287 test geçti. |
| FEAT-13 | Playwright tabanlı tarayıcı otomasyonu (`/internal/browser` endpoint) | 2026-04-18 | `features/browser.py`: session yönetimi + goto/fill/click/screenshot/get_text/get_content/wait_for/eval/close/close_all/list_sessions. `routers/browser_router.py`: localhost-only endpoint. `config.py`: `browser_enabled` + `browser_headless`. `main.py`: router kaydı + lifespan `browser_close_all()`. `requirements.txt`: `playwright==1.58.0`. Chromium yüklendi. |
| OPT-1 | `vision_query` default modelini Haiku yap | 2026-04-18 | `desktop_router.py:117` `vision_model` default'u + docstring string örneği `claude-sonnet-4-6` → `claude-haiku-4-5-20251001`. `features/desktop.py` docstring düzeltildi. Sonnet→Haiku: %75 hız artışı, %90 maliyet düşüşü. |
| FEAT-12 | Sistem şifresi ile bilgisayar kontrolü (GUI otomasyon) | 2026-04-18 | `config.py`'e `system_psswrd: SecretStr` eklendi; `features/desktop.py`'e `unlock_screen()` (loginctl→xdg-screensaver→xdotool fallback) + `sudo_exec()` (sudo -S stdin pipe, shell=False) eklendi; `run_installer()` SYSTEM_PSSWRD varsa sudo_exec() kullanır; `desktop_router.py`'e `unlock_screen` + `sudo_exec` aksiyonları eklendi; `_ALLOWED_ACTIONS` güncellendi; `.env.example` + `CLAUDE.md` Desktop API bölümü; servis restart gerekiyor |
| FEAT-11 | Proje amacı koruyucu — kapsam dışı özellik uyarısı | 2026-04-18 | `CLAUDE.md`'ye `FEAT-11 — Proje Amacı Koruyucu` bölümü eklendi; kapsam dışı özellik tespiti, 5 adımlı yanıt akışı, `!root-project` + `!project` önerisi, evet/hayır buton akışı; yalnızca Claude davranış kuralı — kod değişikliği yok |
| FEAT-10 | `!timezone` komutu — çalışma zamanında saat dilimini değiştir | 2026-04-18 | `guards/commands/timezone_cmd.py`: `zoneinfo.ZoneInfo` ile doğrulama; `user_settings`'e kaydeder; `features/scheduler.py`'e `apply_timezone()` + `get_current_timezone()` + `_reload_cron_jobs_only()` eklendi; `_scheduler.configure(timezone=...)` + cron job'lar yeniden yüklenir; `main.py` startup'ta kaydedilen TZ'yi uygular; locale key'leri eklendi |
| FEAT-9 | `install.sh` — ilk kurulumda saat dilimi seçimi | 2026-04-18 | `config.py`'e `timezone` field eklendi; `AsyncIOScheduler(timezone=settings.timezone)`; wizard'a whiptail radiolist (8 seçenek + elle giriş) + text mode menü; `_write_env`'e `TIMEZONE` yazmak için 23. parametre eklendi; `.env.example` güncellendi |
| FEAT-7 | Bridge → `/internal/schedule*` endpoint'leri + tek seferlik task + soft delete | 2026-04-17 | `sqlite_store.py` + `task_repo.py`: `init_db_migrations`, `task_soft_delete`, `task_update_status`; `scheduler.py`: `create_one_shot_task`, `_execute_one_shot_task`, `_reload_all_jobs`, `soft_delete_job`, `_reload_cron_jobs` alias; `internal_router.py`: POST/DELETE/GET/PUT `/internal/schedule*`; `scheduler_api.py`: `run_at` desteği; `CLAUDE.md`: Zamanlama API kılavuzu eklendi |
| FEAT-4 | Bridge permission callback — WhatsApp/Telegram'dan araç onayı | 2026-04-17 | Claude Code `default`/`acceptEdits` modunda araç onayı WhatsApp/Telegram üzerinden alınıyor; yanıt bridge stdin'e iletiliyor |
| DEP-2 | Node.js bağımlılıkları CVE taraması | 2026-04-19 | `npm audit` taraması: 86 paket (71 prod + 16 optional) — **0 CVE**. Bulgular: `@anthropic-ai/claude-code` 2.1.101→2.1.114 (patch geride), `dotenv` 17.4.1→17.4.2 (patch), `express` 4.22.1 → 5.2.1 major geride. Rapor: `reports/dep2_npm_cve_2026-04-19.md` |
| DEP-3 | Güncel sürüm karşılaştırması | 2026-04-19 | PyPI+npm karşılaştırması: Python 14/15 ✅, **python-json-logger 3.3.0→4.1.0** 🔴; Node: express 4.22.1 (4.x güncel) / claude-code 2.1.101→2.1.114 🔵 / dotenv 17.4.1→17.4.2 🔵. **0 CVE**. Rapor: `reports/dep3_version_comparison_2026-04-19.md` |
| DEP-1 | Python bağımlılıkları CVE taraması | 2026-04-19 | `pip-audit` taraması: 44 paket (15 doğrudan + 29 transitif) — **0 CVE**. Tek bulgu: `python-json-logger` 3.3.0 → 4.1.0 major geride; `logging_config.py:116` import yolu 4.x'te deprecated. Rapor: `reports/dep1_python_cve_2026-04-19.md` |
| FEAT-1 | Medya gönderimi — görsel ve video | 2026-04-17 | `AbstractMessenger`'a `send_image` + `send_video` eklendi; `WhatsAppMessenger` + `TelegramMessenger` + `CLIMessenger` implement etti; Meta Cloud API image/video type desteği aktif |
| FEAT-6 | Kullanıcı ayarları kalıcılığı | 2026-04-17 | `store/repositories/settings_repo.py` — `user_settings` tablosu (sender, key, value, updated_at); `session.py` yeni session başlarken `_apply_persisted_settings()` ile DB'den yükler; `lang_cmd.py` `!lang` değişince `user_setting_set()` ile DB'ye yazar; `model_cmd.py` `!model` değişince `user_setting_set()` ile DB'ye yazar; `main.py` startup'ta owner'ın model tercihini DB'den yükleyip `set_active_model()` ile uygular |
| I18N-2 (hardcode tarama) | Hardcode string taraması | 2026-04-19 | 33 hardcode string tespit edildi: `_dispatcher.py` (2), `schedule_cmd.py` (3), `help_cmd.py` (17), `main.py` (3), `bridge_monitor.py` (8). Tümü `t()` ile değiştirildi. `tr.json`+`en.json` 285→318 key. 481/481 test. |
| I18N-1 (paritet) | `tr.json` ↔ `en.json` paritet kontrolü | 2026-04-19 | 285 key, tam eşleşme. Eksik/fazla key yok. `en.json`'da Türkçe kalan değer yok; yalnızca komut adları (`ekle`, `sil`, `durdur`, `başlat`) kasıtlı Türkçe. Kod değişikliği gerekmedi. |
| I18N-1 | `!lang` komutu + i18n sistemi | 2026-04-17 | `backend/i18n.py`, `locales/tr.json`, `locales/en.json`, `lang_cmd.py`; tüm kullanıcıya yönelik stringler `t()` ile lokalize edildi; GuardContext.lang guard zincirine taşındı |
| DESK-OPT-8 | Popup yönetimi: polling → SubstructureNotifyMask X11 event dinleme | 2026-04-19 | `features/desktop_popup.py` oluşturuldu: `_watch_popup_sync()` daemon thread'de select+200ms timeout ile X11 MapNotify olayı dinler; WM_CLASS kalıp eşleşmesinde `_NET_CLOSE_WINDOW` ClientMessage (önce) / `window.destroy()` (fallback). `start_watch_popup`, `stop_watch_popup`, `list_watch_popups` public API. Router: `watch_popup`, `stop_watch_popup`, `list_watch_popup` aksiyonları + `wm_class`/`watcher_id` field'ları. 480/481 test geçti. |
| FEAT-3 | Yetenek kısıtlamaları (capability guard) | 2026-04-17 | `guards/capability_guard.py` — `CAPABILITIES` dict + `t("capability.*")` mesajları; `whatsapp_router.py`'e eklendi; install.sh yapılandırıcısı ayrı FEAT olarak açık kalabilir |
| SOLID-DIP2 | Router → guard singleton'lar → DI | 2026-04-17 | `guards/__init__.py`'e `get_session_mgr`, `get_blacklist_mgr`, `get_rate_limiter` vb. provider'lar eklendi; `receive_webhook` `Depends(get_guard_chain)` + `Depends(get_session_mgr)` ile inject alıyor; `_handle_message` keyword-arg parametreli; testlerde `app.dependency_overrides` ile mock'lanabilir |
| SEC-PI1 | Prompt injection araştırması — 4 vektör yamandı | 2026-04-16 | Rapor: `reports/prompt_injection_2026-04-16.md`. PI-FIX-1: görsel/video caption → `[BELGE]`; PI-FIX-2: konum name/addr → `[BELGE]`; PI-FIX-3: belge filename sanitize; PI-FIX-4: conv_history asistan yanıtı sanitize |
| DOC-C1 | `CLAUDE.md` — `adapters/` katmanı Temel Modüller'e eklendi | 2026-04-16 | Zaten mevcuttu; doğrulandı |
| DOC-M1 | `MEMORY.md` — Nisan 13-14 kurulumları eklendi | 2026-04-16 | Docker, SecretStr, install.sh, sudoers, webhook_proxy, adapters/llm+messenger |
| DOC-B1 | `byok.md` — Gemini/Ollama notları güncellendi | 2026-04-16 | "G7 sonrası aktif olacak" kaldırıldı; Gemini "Deneysel" notu eklendi |
| DOC-RT1 | `README.tr.md` — LLM Backend Seçimi bölümü | 2026-04-16 | Zaten mevcuttu; doğrulandı |
| AUD-D13 | `whatsapp_router.py` — blacklist `log_inbound` kasıtlı atlama belgelendi | 2026-04-16 | Kod yorumuyla açıklandı |
| MOD-10 | Feature manifest / plugin registry sistemi | 2026-04-19 | `features/_registry.py` oluşturuldu: `FeatureManifest` dict şeması, `FEATURE_REGISTRY` (9 giriş), `register_routers(app)`, `run_startup_hooks()`, `run_shutdown_hooks()` (LIFO). `main.py`'deki 5 koşullu router if bloğu + scheduler/webhook_proxy/browser startup-shutdown kodu tamamen registry'ye taşındı. Yeni feature = yalnızca `_registry.py`'e giriş ekle; `main.py`'ye dokunma. Python OK, 392 test geçti. |
| DOC-A1 | `AGENT.md` — adapters/ özellik tablosuna eklendi | 2026-04-16 | LLM soyutlama, Messenger soyutlama, webhook proxy satırları eklendi |
| DOC-W1 | `WORK_LOG.md` — Nisan 14 büyük oturum kaydedildi | 2026-04-16 | SEC-A, BUG-A, REF, G/PORT, BR/RR serileri özeti eklendi |
| DOC-PI1 | `raspberry-pi.md` — `/home/pi/` hardcode kaldırıldı | 2026-04-16 | `$(pwd)`, `$USER` ve değişken kullanıcı adı açıklaması ile güncellendi |
| DOC-V1 | `vps.md` — `WorkingDirectory=$(pwd)` + Named Tunnel root dizini düzeltildi | 2026-04-16 | Sabit yol + açıklama yorum eklendi; `/root/.cloudflared` → `/home/ubuntu/.cloudflared` |
| DOC-R1 | `README.md`/`README.tr.md` — `!root-reset` yetki + Gemini notu düzeltildi | 2026-04-16 | `!root-reset` → Owner; Gemini → "Deneysel" notu eklendi |
| AUD-Y1 | `subprocess.run()` async'te event loop bloklıyordu | 2026-04-16 | `features/projects.py` — `_tmux_start_service` + `fuser` çağrıları `asyncio.to_thread()` ile sarmalandı |
| AUD-K1 | API key timing attack — `secrets.compare_digest()` | 2026-04-15 | `guards/api_key.py` — `!=` → `secrets.compare_digest()` |
| AUD-K2 | SQLite async sarmalayıcılar — `asyncio.to_thread()` | 2026-04-15 | `sqlite_store.py` tüm public fonksiyonlar async; sync bağlamlar `_sync_*` kullanıyor |
| AUD-Y2 | Gemini API key URL yerine header | 2026-04-15 | `adapters/llm/gemini_provider.py` — `x-goog-api-key` header; `?key=` kaldırıldı |
| AUD-Y3 | Temp PDF `try/finally` temizleme | 2026-04-15 | `features/pdf_importer.py` — hata yolunda `unlink(missing_ok=True)` garantili |
| AUD-Y4 | PDF Bridge yanıtı output_filter ile denetleniyor | 2026-04-15 | `features/pdf_importer.py` — `_analyze_with_bridge` → `filter_response()` uygulandı |
| AUD-Y5 | Boş LLM yanıtında `IndexError` + GUARDRAILS çift yükleme | 2026-04-15 | `routers/_intent_classifier.py` — `if not stripped: return None`; tek `_HINT_WORDS` frozenset |
| AUD-Y6 | `guards` logger `error.log`'a yazıyor | 2026-04-15 | `logging_config.py` — `propagate=True` yapıldı |
| AUD-O1 | TOTP brute-force logunda telefon maskesi | 2026-04-15 | `routers/_auth_flows.py` — `_mask_phone(sender)` eklendi |
| AUD-O2 | Session Lock race condition giderildi | 2026-04-15 | `guards/session.py` — `setdefault(number, asyncio.Lock())` |
| AUD-O3 | `beta_exit.py` — `exit_beta()` çağrısı eklendi | 2026-04-15 | Session özeti ve timer artık kaydediliyor |
| AUD-O4 | `fitz.open()` context manager kullanımı | 2026-04-15 | `features/pdf_importer.py` — `with fitz.open(...) as doc:` |
| AUD-O6 | Path traversal — `relative_to()` kontrolü | 2026-04-15 | `features/projects.py` — `startswith` → `Path.relative_to()` + ValueError |
| AUD-O8 | GUARDRAILS.md çift yükleme giderildi | 2026-04-15 | `routers/_intent_classifier.py` — AUD-Y5 ile birlikte tek frozenset |
| MOD-1 | Router kayıtlarını koşullu hale getir | 2026-04-20 | `main.py`: `desktop_router` → `if settings.desktop_enabled:`, `terminal_router` → `if not settings.restrict_shell:`, `browser_router` → `if settings.browser_enabled:`. Telegram pattern'i uygulandı; her router için log satırı eklendi. Python OK. |
| AUD-O10 | `cloud_api.py` — `!= 200` → `raise_for_status()` | 2026-04-15 | `send_text`, `send_buttons`, `send_list` — `is_success` kontrolü |
| AUD-O14 | `main.py` — `get_event_loop()` → `asyncio.to_thread()` | 2026-04-15 | `main.py:78` — deprecate kullanım kaldırıldı |
| AUD-O15 | `task_find_by_prefix()` LIKE wildcard escape | 2026-04-15 | `store/sqlite_store.py` — `%`, `_`, `\` escape ile güvenli |
| AUD-O16 | `totp_record_failure()` atomik UPSERT | 2026-04-15 | `store/sqlite_store.py` — `ON CONFLICT DO UPDATE` ile race condition giderildi |
| AUD-D2 | `anthropic_provider` + `ollama_provider` — `!= 200` pattern | 2026-04-15 | `raise_for_status()` yeterli; özel RuntimeError kaldırıldı |
| AUD-D3 | `messenger_factory.py` tip anotasyonu `AbstractMessenger` | 2026-04-15 | `TYPE_CHECKING` guard ile circular import korumalı |
| AUD-D4 | `schedule_cmd.py` dead variable silindi | 2026-04-15 | `task_id = str(uuid.uuid4())` + `import uuid` kaldırıldı |
| AUD-D5 | `beta_exit.py` kullanılmayan import silindi | 2026-04-15 | `from ..session import SessionManager` kaldırıldı |
| AUD-D7 | `projects.py` — `datetime.utcnow()` → `timezone.utc` | 2026-04-15 | `datetime.now(timezone.utc)` kullanıldı |
| AUD-D8 | `server.js` — JSON.parse catch loglandı | 2026-04-15 | `catch {}` → `catch (err) { console.error(...) }` |
| AUD-D11 | `_bridge_client.py` — timeout `settings`'ten okunuyor | 2026-04-15 | `bridge_client_timeout: int = 1800` config'e eklendi |
| AUD-D1 | `/health` endpoint DB/scheduler kontrol etmiyor | 2026-04-16 | `main.py` — `db_ping()` + `_scheduler.running` alanları eklendi |
| AUD-D6 | `cloud_api.py` — `_outbound_locks/_outbound_last` temizlenmiyor | 2026-04-16 | `_evict_outbound()` + `_OUTBOUND_TTL=3600s`; `_outbound_lock()` her çağrıda evict eder |
| AUD-D9 | `server.js` — `node-fetch` bağımlılığı belirsiz | 2026-04-16 | Yorum eklendi: Node 18+ `globalThis.fetch` kullanılır; dinamik import eski Node için fallback |
| AUD-D10 | `root_check_cmd.py` — log satırları ham gönderiliyor | 2026-04-16 | `CLAUDE.md` komut tablosunda belgelendi (tek kullanıcılı sistemde bilerek böyle) |
| AUD-D12 | `sqlite_store.py` — `project_id` validasyonu yok | 2026-04-16 | `_PROJECT_ID_RE = ^[a-z0-9][a-z0-9\-]{0,62}$`; `ValueError` fırlatır |
| AUD-O5 | `api_rate_limiter.py` — `_windows` dict sınırsız büyüyor | 2026-04-16 | `RateLimiter._cleanup()` + `_CLEANUP_INTERVAL=300s` + `_ENTRY_TTL=120s`; lazy eviction |
| AUD-O7 | `/agent/project/{id}/beta` — sender doğrulanmıyor | 2026-04-16 | `personal_agent_router.py` — `settings.whatsapp_owner` ile karşılaştırma; 403 fırlatır |
| AUD-O9 | `output_filter.py` — `eval`/`exec` false positive | 2026-04-16 | Obfuscation odaklı regex: `base64`, `__import__`, `compile`, `bytes`, `chr` içerenler engellenir |
| AUD-O11 | `personal_agent_router.py` → Store doğrudan erişimi | 2026-04-16 | `features/projects.py`'ye `list_projects()` eklendi; router features katmanını kullanıyor |
| AUD-O12 | `chat.py` — Bridge reset sessiz başarısız | 2026-04-16 | `reset_bridge_session` → `bool` döndürür; `error` log + `!root-reset` hata mesajı |
| AUD-O13 | `scheduler.py` — `shutdown(wait=False)` job kesiyor | 2026-04-16 | `wait=True` + 5s timeout ile `asyncio.to_thread`; timeout'ta `wait=False` fallback |
| AUD-O17 | `whatsapp_router.py` — yetkisiz sender mesaj önizlemesi | 2026-04-16 | Kod yorumuyla belgelendi (kasıtlı güvenlik bildirimi); preview 100 karakter sınırlandı |
| AUD-O18 | `session.py` — lock cleanup race condition | 2026-04-16 | `lock.locked()` kontrolü eklendi; tutulu lock'lar cleanup'ta silinmiyor |
| AUD-O19 | `runtime_state.py` — `_last_status` sınırsız büyüme | 2026-04-16 | `_maybe_evict()` + `_STATUS_TTL=1800s` + `_STATUS_CLEANUP_IV=300s` |
| AUD-O20 | media sınırsız bellek | 2026-04-16 | `_MAX_MEDIA_BYTES=50MB`; metadata `file_size` + indirme sonrası çift kontrol |
| AUD-O21 | `menu.py` — `s['name']` KeyError | 2026-04-16 | `s.get('name','?')` ile korundu |
| AUD-O22 | `message_logger.py` — `msg_count` semantik | 2026-04-16 | `_sync_message_count_since(sender, started_at)` → session içi sayı |
| AUD-O23 | `scheduler.py` — `resume_cron_job` sessiz exception | 2026-04-16 | İç try/except + `logger.error` eklendi; hata durumunda erken dön |
| AUD-O24 | `server.js` — scheduler WA rate limit | 2026-04-16 | `silent` param eklendi; `_run_bridge_query(silent=True)` ile ⚙️ bildirimi atlanır |
| WIZ-B6 | Wizard — Port aralığı doğrulaması | 2026-04-16 | `handle_service_port`'a 1–65535 kontrolü eklendi |
| WIZ-B7 | Wizard — Servis adı tmux window doğrulaması | 2026-04-16 | `_WINDOW_NAME_RE` kontrolü + mesaj güncellendi |
| WIZ-B9 | Wizard — Boş proje adı tanımsız davranış | 2026-04-16 | `awaiting_project_name` handler'ında boşluk kontrolü eklendi |
| WIZ-B11 | Wizard — `_route_interactive` session lock dışında | 2026-04-16 | `session_mgr.lock(sender)` altına alındı |
| BUG-C1 | `import time` eksik → `end_session()` her çağrıda NameError | 2026-04-18 | `features/history.py:8` — `import time` eklendi |
| BUG-C2 | Bare `send_text` çağrısı → 3 dosyada çalışma zamanı çöküşü | 2026-04-18 | `menu_project.py:157`, `project_delete_cmd.py:57`, `pdf_importer.py:89` — `_get_messenger().send_text()` / `get_messenger().send_text()` ile düzeltildi |
| TEST-1 | Unit test altyapısı + coverage genişletme | 2026-04-16 | 87 test; `test_session_state.py`, `test_guard_chain.py`, `test_dispatcher_auth.py` eklendi; `SessionState`, `GuardChain`, `MessageGuard`'lar, dispatcher auth routing kapsandı |
| TEST-1 | `test_dispatcher_auth.py` — 3 başarısız test düzelt | 2026-04-19 | Her 3 teste `patch("backend.guards.runtime_state.is_locked", return_value=False)` eklendi; 13/13 → 223/223 geçti |
| BUG-TG1 | `PermissionManager.is_owner()` Telegram modunda düzeltildi | 2026-04-19 | `permission.py:32` — `settings.whatsapp_owner` → `settings.owner_id`; Telegram chat_id artık doğru eşleşiyor |
| BUG-TG2 | `projects_api.py` yetki kontrolü Telegram modunda düzeltildi | 2026-04-19 | `projects_api.py:38` — `settings.whatsapp_owner` → `settings.owner_id` |
| SOLID-1 | `SessionState` kapsülleme ihlali kapatıldı | 2026-04-19 | `app_types.py`: `_CONTROLLED_KEYS` frozenset + `__setitem__` guard (14 key) + 5 yeni metot (`start_project_name`, `start_project_description`, `start_task`, `set_pending_pdf`, `set_terminal_pending`). 8 bypass fix: `menu_project.py`, `_auth_flows.py`×2, `wizard_steps.py`, `menu.py`×2, `_media_handlers.py`, `terminal_cmd.py`. Test fixture güncellendi. 20/20 test geçti. |
| INIT | Dizin yapısı oluşturuldu | 2026-04-11 | — |
| INIT | CLAUDE.md, AGENT.md, BACKLOG.md, WORK_LOG.md | 2026-04-11 | — |
| F1-1 | Python venv oluştur + requirements.txt kur | 2026-04-11 | `scripts/backend/venv/` + tüm paketler kurulu |
| F1-2 | `.env` dosyası oluştur | 2026-04-11 | `.env.example` şablon hazır |
| F1-3 | Meta WhatsApp webhook doğrulaması | 2026-04-11 | GET /whatsapp/webhook — HMAC + verify_token |
| F1-4 | Systemd service dosyasını düzelt | 2026-04-11 | WorkingDirectory `scripts/` olarak düzeltildi |
| F2-1 | `features/chat.py` — Bridge sohbet wrapper | 2026-04-11 | send_to_bridge + reset_bridge_session |
| F2-2 | `features/plans.py` — İş planı CRUD + WhatsApp formatları | 2026-04-11 | format_plan_list, priority emoji |
| F2-3 | Ana menü tasarımı (buton + liste) | 2026-04-11 | show_main_menu (3 buton) + show_extended_menu |
| F2-4 | `personal_agent_router.py` — `/agent/*` endpoint'leri | 2026-04-11 | plan, calendar, project, pdf-import |
| F3-1 | `features/calendar.py` — Takvim CRUD | 2026-04-11 | dateparser NLP + format_event_list |
| F3-2 | `features/scheduler.py` — APScheduler kurulumu | 2026-04-11 | SQLiteJobStore kalıcı job store |
| F3-3 | Hatırlatıcı bildirim gönderimi | 2026-04-11 | Her dakika check_and_notify_reminders |
| F4-1 | `features/projects.py` — Proje CRUD + klasör oluşturma | 2026-04-11 | _scaffold_project: CLAUDE.md, BACKLOG.md, README.md |
| F4-2 | Beta modu — session context switching | 2026-04-11 | session_mgr.set_beta / exit_beta |
| F4-3 | Bridge dinamik INIT_PROMPT (proje bazlı) | 2026-04-11 | server.js buildInitPrompt + projectClaudeMd |
| F4-4 | Proje listesi pagination (>10 proje) | 2026-04-11 | format_project_list page/page_size |
| F5-1 | `features/pdf_importer.py` — PyMuPDF + Bridge analiz | 2026-04-11 | İlk 30 sayfa, 50K karakter limit |
| F5-2 | WhatsApp media download → PDF akışı | 2026-04-11 | download_media tuple bug düzeltildi |
| BUG | menu.py send_list button_text→button_label | 2026-04-11 | TypeError önlendi |
| BUG | cloud_api.py — WhatsApp API limit hataları (#100, #131009) | 2026-04-14 | `_trunc()` + `_sanitize_sections()` eklendi; `send_list` body/button/section/row limitleri, `send_buttons` body/title limitleri uygulandı |
| BUG | pdf_importer.py download_media tuple unpack | 2026-04-11 | (bytes, mime) tuple düzgün alınıyor |
| BUG | systemd WorkingDirectory scripts/ olarak düzeltildi | 2026-04-11 | backend.main:app artık çözümleniyor |
| SEC-1 | Webhook payload PII temizleme | 2026-04-11 | message_logger + whatsapp_router'da _mask_phone ile telefon maskeli; bridge error_type logu eklendi |
| S01-1 | Beta modu yeniden tasarlandı | 2026-04-11 | !beta-exit dışındaki tüm mesajlar projenin FastAPI'sine gidiyor |
| S01-2 | WMA `/internal/message` endpoint | 2026-04-11 | Guard atlamalı direkt endpoint; _OPEN_PATHS'e eklendi |
| S01-3 | `!root` komutu kaldırıldı | 2026-04-11 | 99-root beta proxy olduğu için artık gerekmiyor |
| S01-4 | `start_project_services` düzeltmesi | 2026-04-11 | Duplicate tmux penceresi fix; svc.cwd desteği |
| S01-5 | `!history` komutu | 2026-04-11 | Son N mesaj + session özetleri |
| S01-6 | menu.py eksik handler'lar | 2026-04-11 | project_info_, menu_history, menu_task_add, menu_tasks |
| S01-7 | GUARDRAILS.md oluşturuldu | 2026-04-12 | 13 kategori yasak komut; CLAUDE.md'ye eklendi |
| S01-8 | Çalışma bağlamı sistemi | 2026-04-12 | active_context.json; Bridge'e enjekte; !project komutu |
| S01-9 | Bridge session sürekliliği | 2026-04-12 | --resume UUID kullanıyor; result event'ten session_id kaydediliyor |
| S01-10 | Bridge path traversal fix | 2026-04-12 | PROJECTS_DIR kısıtı kaldırıldı; .. segment + dizin varlık kontrolü |
| SEC-2 | Prompt injection koruması | 2026-04-12 | PDF içeriği [BELGE] bloğuna izole edildi; CLAUDE.md'ye güvenlik talimatı eklendi |
| SEC-3 | İkinci TOTP (admin) | 2026-04-12 | Yıkıcı komutlar için totp_secret_admin; matematik challenge alarm zili |
| SEC-4 | Yetkisiz mesaj bildirimi | 2026-04-12 | Yabancı numera mesaj atınca owner'a tam numara + içerik iletiliyor |
| SEC-5 | GUARDRAILS.md genişletildi | 2026-04-12 | 13 → 33 kategori |
| F6-1 | !schedule komutu | 2026-04-12 | Cron job oluştur/listele/durdur/sil; run_bridge + send_message tipleri |
| F6-2 | Scheduler cron desteği | 2026-04-12 | add_cron_job, pause/resume, _execute_task, reload on restart |
| F6-3 | /agent/schedule endpoint'leri | 2026-04-12 | Bridge doğal dil ile schedule oluşturabilir |
| F7-1 | Proje scaffold seçimi | 2026-04-12 | Yazılım Projesi / Görev Kaydet / Sadece Klasör; PDF ve manuel akış |
| F7-2 | !help OOP yeniden yazım | 2026-04-12 | !help !komut bireysel açıklama; her komutta label/description/usage |
| F7-3 | Lifecycle bildirimleri | 2026-04-12 | Servis açılış/kapanış WhatsApp bildirimi; kapanışta cleanup öncesi gönderim |
| OPS-1 | Systemd otomatik başlatma | 2026-04-12 | enabled; bilgisayar açılışında şifresiz başlıyor |
| S01-11 | Bridge konuşma geçmişi (conv_history) | 2026-04-12 | Oturum sıfırlanınca son N tur init_prompt'a ekleniyor; bağlam korunuyor |
| BUG | WMA metadata `2>&1` kaldırıldı | 2026-04-12 | `>` ve `&` güvenlik regex'ini blokluyordu; DB'deki servis komutları düzeltildi |
| BUG | projects.py tmux has-session fix | 2026-04-12 | Session yokken `new-window` çöküyordu; `has-session` + `new-session` akışı eklendi |
| SEC-6 | GUARDRAILS.md init_prompt'a dahil et | 2026-04-12 | `readGuardrailHeaders()` ile 49 kategori başlığı her sorguda init_prompt'a ekleniyor |
| PORT-1 | Statik yolları konfigürasyona taşı | 2026-04-13 | `FASTAPI_URL`, `ROOT_DIR`, `PROJECTS_DIR`, `SESSIONS_DIR` env'den okunuyor; `config.py`'e yeni alanlar eklendi; `.env.example` güncellendi |
| PORT-2 | Otomatik kurulum betiği | 2026-04-13 | `install.sh`: venv, npm, .env, dizinler, systemd render + install; `--no-systemd` flag'i var |
| PORT-3 | Systemd unit dosyalarını dinamik yap | 2026-04-13 | `systemd/*.service.template`; `install.sh` render_template() ile `{{USER}}`, `{{ROOT_DIR}}`, `{{NODE_PATH}}`, `{{API_PORT}}`, `{{BRIDGE_PORT}}` placeholder'larını doldurur |
| SEC-10 | GUARDRAILS.md 46→49 kategori | 2026-04-14 | Kat.47: SQL injection; Kat.48: subprocess shell=True (AWorld CVE 2025); Kat.49: TOTP brute-force (AuthQuake) |
| SEC-A1 | `Settings` hassas alanları `SecretStr` | 2026-04-14 | 7 alan `SecretStr`; tüm call-site'larda `.get_secret_value()` |
| SEC-A2 | Boş `app_secret` → production'da reject | 2026-04-14 | `_verify_signature`: prod'da boş secret → False + critical log |
| SEC-A3 | `_UNSAFE_CMD_RE`'ye `\n\r\x00` ekle | 2026-04-14 | tmux inject: newline/null byte artık engelleniyor |
| SEC-A4 | TOTP sayacı SQLite'a taşındı | 2026-04-14 | `totp_lockouts` tablosu; restart sonrası brute-force koruması sürer |
| SEC-A5 | `output_filter.py` 13 yeni kural | 2026-04-14 | chmod, git force-push, curl/bash RCE, iptables, docker rm vb. |
| SEC-A6 | Session iptal dallarına lock eklendi | 2026-04-14 | `awaiting_admin_totp` + `awaiting_totp` iptal dalları TOCTOU korumalı |
| SEC-A7 | `tmux_window` regex doğrulaması | 2026-04-14 | `_WINDOW_NAME_RE = ^[a-zA-Z0-9_\-]{1,50}$`; `:` içeren ad reddediliyor |
| BUG-A1 | `svc.get("tmux_window")` + None skip | 2026-04-14 | Eksik key → servis atlanıyor, KeyError yok |
| BUG-A2 | `svc.get("name", "?")` | 2026-04-14 | stop_project_services'de KeyError önlendi |
| BUG-A3 | `isinstance(svc, dict)` per-eleman | 2026-04-14 | Bozuk metadata → AttributeError yok |
| BUG-A4 | `_session_cleanup_loop` try/except | 2026-04-14 | Döngü tek hata ile ölmüyor; sonraki saatte tekrar deniyor |
| BUG-A5 | `task_update_last_run()` public metot | 2026-04-14 | `db._conn()` private API kaldırıldı; SRP sağlandı |
| BUG-A6 | `pause_job` spesifik except | 2026-04-14 | `JobLookupError` vs beklenmedik hata ayrıldı; maskeleme kaldırıldı |
| BUG-A7 | `_DB_PATH` ölü değişken silindi | 2026-04-14 | `sqlite_store.py`'den kaldırıldı |
| REF-10 | `show_main_menu/show_extended_menu` silindi | 2026-04-14 | Hiçbir yerde çağrılmıyordu; `menu.py`'den kaldırıldı |
| I18N-1 | `server.js` hata mesajları Türkçe | 2026-04-14 | `Timeout` → `Zaman aşımı`; `CLI exit` → `CLI çıkış kodu` |
| I18N-2 | `AGENT.md` başlıkları Türkçe | 2026-04-14 | `Mission` → `Görev`; `Goals & KPIs` → `Hedefler & KPI'lar`; `Non-Goals` → `Kapsam Dışı` |
| BUG | Admin TOTP sonrası sonsuz döngü | 2026-04-14 | `_handle_admin_totp` → `_route_text` tekrar OWNER_ADMIN_TOTP tetikliyordu; registry'den direkt execute'a geçildi |
| BUG | `cloud_api.py` syntax hatası | 2026-04-14 | `@_send_retry` decorator `_WA_MAX_LEN = 4096` sabitine yanlış eklenmişti; servisi başlatmıyordu |
| BUG | Menü butonları "bilinmeyen seçenek" hatası | 2026-04-14 | `cmd_root_reset` / `cmd_shutdown` / `cmd_schedule_list` butonları handler'sızdı; `_route_interactive`'e `_CMD_SHORTCUTS` eklendi |
| F8-1 | `!restart` gerçek systemd restart | 2026-04-14 | `sudo -n systemctl restart` çalıştırıyor; `-n` flag ile şifresiz sudo zorunluluğu netleşti |
| DOCS | CLAUDE.md — `!restart` koruma kuralı | 2026-04-14 | Kritik kural en üste eklendi; çağrı zincirindeki her değişiklik öncesi syntax kontrolü zorunlu |
| DOCS | Raporlar `reports/done/`'a taşındı | 2026-04-14 | outputs/ altındaki 2 rapor done'a alındı; CLAUDE.md'ye `reports/` konvansiyonu eklendi |
| G1 | Docker Compose desteği | 2026-04-14 | → PORT-4/PORT-5 olarak backlog'da |
| G3 | İki dilli README (TR + EN) | 2026-04-14 | `README.md` (EN) + `README.tr.md` (TR) oluşturuldu |
| G4 | `.gitignore` ve `.env.example` | 2026-04-14 | `.gitignore` oluşturuldu; `.env.example` 13 değişken + Türkçe açıklamalarla güncellendi |
| G2 | Telegram messenger adaptörü | 2026-04-14 | `adapters/messenger/`: `AbstractMessenger` Protocol, `WhatsAppMessenger`, `TelegramMessenger`, `messenger_factory` |
| G5 | MIT Lisansı | 2026-04-14 | `LICENSE` dosyası oluşturuldu; README'lere bağlantı eklendi |
| G6 | Interactive setup wizard | 2026-04-14 | `setup.py` (479 satır): `BaseSetupStep`, `SetupOrchestrator`, `EnvWriter` |
| G7 | AbstractLLMProvider (BYOK/BYOM) | 2026-04-14 | `adapters/llm/`: `AbstractLLMProvider`, `AnthropicProvider`, `OllamaProvider`, `llm_factory` |
| G8 | PM2 desteği | 2026-04-14 | `ecosystem.config.js`: `99-api` + `99-bridge` |
| G9 | BYOK dokümantasyonu | 2026-04-14 | `docs/deployment/byok.md` |
| SEC-9 | Pre-Execution Self-Check | 2026-04-14 | `CLAUDE.md` satır 197'de mevcut |
| SEC-RL1 | `_is_retryable()` → HTTP 400 + #131056 | 2026-04-14 | Rate limit yanıtı artık retry edilebilir olarak işaretleniyor; exponential backoff tetikleniyor |
| BR-1 | Bridge crash handler'ları | 2026-04-14 | `server.js`: `unhandledRejection` + `uncaughtException` hook'ları + owner WhatsApp bildirimi + `process.exit(1)` |
| BR-2 | FastAPI `/health` Bridge durumu | 2026-04-14 | `"bridge": "ok"\|"down"` alanı eklendi; 60s monitor görevi + owner bildirimi |
| ERR-2 | ConnectError mesajına `!restart` önerisi | 2026-04-14 | `whatsapp_router.py` — "!restart ile yeniden başlatabilirsin" eklendi |
| OPS-7 | `!restart` için sudoers NOPASSWD | 2026-04-14 | `sudo -n systemctl restart` her iki servis için şifresiz çalışıyor (doğrulandı) |
| RR-1 | `subprocess.run` → `asyncio.create_subprocess_exec` | 2026-04-14 | `restart_cmd.py` — event loop artık bloklanmıyor; max 30s bekleme ortadan kalktı |
| RR-2 | `create_task` önce, `send_text` sonra | 2026-04-14 | Restart `send_text` hatasına bağımlı değil; `try/except` ile bildirim hatası izole edildi |
| RR-3 | Task `add_done_callback` ekle | 2026-04-14 | `_on_restart_done` callback — beklenmedik exception loglanıyor |
| RR-4 | `valid_window=0` → `valid_window=1` | 2026-04-14 | `permission.py` — ±30s NTP toleransı; TOTP kilitlenmesi önlendi |
| RR-5 | Bridge restart hatası WhatsApp bildirimi | 2026-04-14 | `_do_restart` — bridge başarısız/timeout → owner'a bildirim |
| ERR-1 | Bridge watchdog → otomatik systemctl restart | 2026-04-14 | `main.py` — 3 art arda health-check başarısızlığı → `sudo -n systemctl restart personal-agent-bridge.service` |
| BR-3 | Bridge ConnectError retry mekanizması | 2026-04-14 | `whatsapp_router.py` — ConnectError'da 2s + 4s bekleyerek max 3 deneme |
| SEC-RL2 | `DedupGuard` → SQLite kalıcılığı | 2026-04-14 | `deduplication.py` + `sqlite_store.py` — `seen_messages` tablosu; restart sonrası Meta yeniden gönderimlerine karşı koruma |
| SEC-RL3 | Çıkış oranı sınırlayıcı | 2026-04-14 | `cloud_api.py` — alıcı başına min. 1s aralık; `_throttle()` + `asyncio.Lock`; `send_text/buttons/list` entegre |
| REF-1 | `BridgeClient` sınıfı çıkarıldı | 2026-04-14 | `_forward_to_bridge_inner` → `routers/_bridge_client.py`; `forward` + `forward_locked` API |
| REF-2 | `IntentClassifier` DIP düzeltildi | 2026-04-14 | Raw `httpx` → `AnthropicProvider`; model/timeout parametreleri korundu |
| REF-3 | `whatsapp_router.py` modüllere bölündü | 2026-04-14 | 932 → 448 satır; `_intent_classifier.py`, `_auth_flows.py`, `_media_handlers.py` çıkarıldı |
| REF-4 | `TmuxServiceExecutor` + `ServiceValidator` | 2026-04-14 | `_validate_service()` + `_tmux_start_service()` helper'ları; `start_project_services` 6 sorumluluktan 3'e indi |
| REF-8 | `STATUS_EMOJI` → tek sabit | 2026-04-14 | `app_types.PROJECT_STATUS_EMOJI`; `menu.py` ve `projects.py` aynı kaynaktan okuyor |
| ERR-6 | `2>&1` regex davranışı belgelendi | 2026-04-14 | `CLAUDE.md` "Proje Wizard — Servis Komutu Kısıtlaması" bölümü eklendi |
| OPS-5 | Servisi yeniden başlat | 2026-04-19 | `cloud_api.py` syntax hatası giderildi; servis başarıyla çalışıyor |
| DIST-1 | `CONTRIBUTING.md` + GitHub Actions lint/syntax CI | 2026-04-14 | `CONTRIBUTING.md`, `.github/workflows/ci.yml`, `.github/ISSUE_TEMPLATE/` |
| DIST-3 | Gemini provider | 2026-04-14 | `adapters/llm/gemini_provider.py`; `llm_factory.py` + `config.py` + `.env.example` güncellendi |
| PORT-6 | Yapılandırılabilir webhook proxy | 2026-04-14 | `features/webhook_proxy.py`; ngrok/cloudflared/external/none modları |
| PORT-2 | Otomatik kurulum betiği (güncel) | 2026-04-14 | `install.sh`: Python 3.11+ / Node 18+ kontrolleri + sözdizimi doğrulama eklendi |
| DIST-2 | Railway / Render deploy şablonları | 2026-04-14 | `railway.json` (API tek servis) + `render.yaml` (API + Bridge, disk mount, fromService bağlantıları) |
| WIZ-UX1 | Wizard özet ekranına düzenleme butonu eklendi | 2026-04-16 | `project_wizard.py` — `wiz_edit_options` butonu + `handle_edit_summary()`; `menu.py` handler; seçenekler menüsüne geri döner |
| WIZ-UX2 | PDF importer `path=None` explicit | 2026-04-16 | `pdf_importer.py:67` — `create_project()` çağrısına `path=None` eklendi |
| WIZ-UX3 | full scaffold'a `tests/` dizini eklendi | 2026-04-16 | `projects.py:241` — `(project_dir / "tests").mkdir()` |
| WIZ-UX4 | `_PORT_RE` regex genişletildi | 2026-04-16 | `project_wizard.py` — `-p 8020`, `PORT=8020`, `--port=8020` formatları destekleniyor |
| DIST-4 | `CLIMessenger` eklendi | 2026-04-16 | `adapters/messenger/cli_messenger.py` — stdout'a yazdıran debug messenger; `MESSENGER_TYPE=cli` ile aktif |
| DIST-5 | Intent classifier `get_llm()` kullanıyor | 2026-04-16 | `routers/_intent_classifier.py` — `AnthropicProvider` hardcode kaldırıldı; `get_llm()` + `_classify_model()` + `_has_api_key()`; LLM_BACKEND=gemini/ollama çalışıyor |
| F9-1 | Administrator modu — ayrıntılı uyarı + onay akışı + işlem bildirim mesajı | 2026-04-16 | `CLAUDE.md` Pre-Execution Guardrail Check güncellendi: tam komut + kategori blast radius + somut riskler gösteriliyor; TOTP onayı sonrası işlem başlamadan önce `⚠️ … başlatılıyor…` bildirimi gönderiliyor; Soft Guardrails son satırı da aynı akışı takip edecek şekilde güncellendi |
| SOLID-OOP1 | `SessionState` dict → typed sınıf | 2026-04-16 | `app_types.py` — `dict` alt sınıfı; `start_totp()`, `start_admin_totp()`, `start_math_challenge()`, `start_guardrail()` + clear metotları; `_auth_flows.py` + `_dispatcher.py` güncellendi |
| SOLID-DIP1 | Feature → `StoreProtocol` arayüzü | 2026-04-16 | `store/protocol.py` + `store/sqlite_wrapper.py`; `isinstance(store, StoreProtocol)` True; feature dosyaları değişmedi — mevcut `sqlite_store` modülü çalışmaya devam eder |
| SOLID-OCP3 | Auth flow dispatch → `_AUTH_FLOW_REGISTRY` dict | 2026-04-16 | `routers/_dispatcher.py` — 4 if/elif auth bloğu handler fonksiyonlarına ayrıldı; yeni auth adımı = yeni fonksiyon + dict kaydı |
| SOLID-LSP1 | `registry.register()` — `perm` eksikse `ValueError` | 2026-04-16 | `guards/commands/registry.py` — sessiz `None` yerine erken hata; yetki bypass riski ortadan kalktı |
| SOLID-OCP2 | `whatsapp_router.py` media elif zinciri → `_MEDIA_TYPE_HANDLERS` dict | 2026-04-16 | `routers/whatsapp_router.py` — image/audio/video/document 8 satır → 2 satır; yeni medya tipi = dict'e kayıt |
| SOLID-ISP1 | `AbstractMessenger` split → `InteractiveMessenger` alt-protokolü | 2026-04-16 | `adapters/messenger/__init__.py` — `AbstractMessenger` (sadece send_text) + `InteractiveMessenger` (buttons+list); `supports_interactive_buttons: bool` tüm concrete sınıflara eklendi |
| SOLID-LSP3 | `AbstractLLMProvider.complete()` `model=None` sözleşme notu | 2026-04-16 | `adapters/llm/__init__.py` — "Implementations MUST honor this" eklendi |
| FEAT-5 | `!model` komutu — çalışma zamanında LLM modeli değiştir | 2026-04-17 | `guards/commands/model_cmd.py`; `runtime_state.py`'e `_active_model` + get/set eklendi; `llm_factory.get_llm()` runtime model'i provider'a geçiriyor; Anthropic alias'ları: sonnet/haiku/opus; FEAT-6 ile entegre: seçim `user_settings` tablosuna yazılır, startup'ta yeniden yüklenir |
| REF-5 | `handle_menu_reply` elif zinciri → _EXACT + _PREFIX dispatch table | 2026-04-16 | `features/menu.py` — 18 exact handler + 12 prefix handler; yeni menü öğesi = yeni fonksiyon, elif'e dokunulmaz |
| REF-6 | `CMD_PERMS` → komut sınıfından `perm` özelliği | 2026-04-16 | `guards/permission.py` — `CMD_PERMS` dict kaldırıldı; 13 komut sınıfına `perm` attribute eklendi; `required_perm()` registry'den okuyors |
| REF-7 | `_CMD_SHORTCUTS` → registry'den otomatik oluştur | 2026-04-16 | `routers/whatsapp_router.py` — 4 komut sınıfına `button_id` eklendi; dict comprehension ile auto-build |
| REF-9 | `llm_factory.py` → `_BACKENDS` dict + `register_backend()` | 2026-04-16 | `adapters/llm/llm_factory.py` — if/elif zinciri kaldırıldı; `register_backend()` ile dışarıdan backend kaydı mümkün |
| LOG-1 | Console çıktısı çift yazılıyor düzeltildi | 2026-04-19 | `logging_config.py` — per-logger `handlers` listesinden `"console"` kaldırıldı; `propagate=True` zaten root'a iletir, root console'a yazar |
| LOG-4 | Güvenlik olayları için ayrı `security.log` eklendi | 2026-04-19 | `logging_config.py` — `security_file` handler (WARNING+, 10MB rotate); `backend.guards` → `security_file` eklendi; `backend.routers._auth_flows` + `backend.routers._auth_dispatcher` yeni logger girişleri. Python OK |
| TEST-2…11 | Test coverage genişletme — 10 yeni test dosyası | 2026-04-19 | `test_telegram_router.py` (7), `test_terminal_router.py` (6), `test_internal_router.py`+10, `test_agent_router.py`+12, `test_calendar_feature.py` (2), `test_scheduler_feature.py` (6), `test_history_feature.py` (3), `test_credential_store_feature.py` (2), `test_browser_router.py` (5), `test_desktop_router.py` (5). 287/287 test geçti. |
| FEAT-14 | Oturum başında bağlam sürekliliği — history kontrolü | 2026-04-19 | `server.js`: `CONV_SUMMARY_TURNS=3` + `CONV_SUMMARY_CHARS=300` sabitleri; `formatConvHistorySummary()` — son 3 tur, mesaj başına 300 karakter, devam niyeti bağlamı başlığı; `buildInitPrompt`'ta `formatConvHistory` yerine kompakt `formatConvHistorySummary` kullanılıyor. Token tasarrufu: 8 tur × 2000 kar. → 3 tur × 300 kar. Node OK |
| FEAT-18 | `!cancel` ile aktif Bridge görevini iptal et | 2026-04-19 | `server.js`: `cancelledSessions` Set + `POST /cancel` endpoint (aktif process → SIGTERM; bekleyen approval → reject); `/query` catch block'ta `cancelledSessions` kontrolü — retry yapılmaz, sessiz yanıt döner. `cancel_cmd.py`: auth akışı yoksa `_cancel_bridge_query()` ile Bridge `/cancel` çağrısı → `cancel.bridge_ok` mesajı; auth akışı varsa mevcut davranış korunur. `locales/tr.json` + `locales/en.json`: `cancel.bridge_ok` key eklendi. Node OK, Python OK, 287 test geçti. |
| SOLID-5 | Feature modüllerinde `settings` doğrudan importunu kaldır | 2026-04-19 | `config.py`: `get_settings()` factory fonksiyonu eklendi (DIP-V2 accessor). `media_handler.py` + `pdf_importer.py`: ölü `settings` import'ları silindi. `chat.py`, `scheduler.py`, `desktop_vision.py`: `from ..config import settings` → `get_settings()` ile değiştirildi. Python OK, 405/408 test geçti (3 pre-existing failure). |
| SOLID-7 | Guard manager singleton'ları için getter fonksiyonları | 2026-04-19 | 9 backend dosyası: `session_mgr` → `get_session_mgr()`, `perm_mgr` → `get_perm_mgr()`, `capability_guard` → `get_capability_guard()` (ENC-V2). Etkilenen: `_dispatcher.py`, `_auth_dispatcher.py`, `_auth_flows.py`, `_text_router.py`, `internal_router.py`, `projects_api.py`, `project_crud.py`, `project_focus_cmd.py`, `main.py`. Test dosyaları da güncellendi. Python OK, 405/408 test geçti (3 pre-existing). |
| SOLID-8 | Desktop facade thin wrapper katmanı | 2026-04-19 | `features/desktop.py`: 14 re-export (capture, input, vision, AT-SPI) private alias (`_func`) olarak içe aktarıldı; aynı imzalı 14 thin wrapper fonksiyonu eklendi — DEBUG log girişi + Exception yakalama + ERROR log + güvenli fallback (`None`/`[]`/`{}`/`0`/hata str). `xdotool_type` metin içeriğini loglamaz (gizlilik). Python OK, 405/408 test geçti (3 pre-existing). ENC-V3. |
| TEST-2 | Commands unit testleri — 9 eksik komut eklendi | 2026-04-19 | `test_registry_commands.py`: `!help` (3), `!restart` (1), `!shutdown` (1), `!root-check` (3), `!root-log` (2), `!root-project` (5), `!project-delete` (4), `!terminal` (4), `!timezone` (3) — toplam 26 yeni test eklendi. `test_known_commands_registered` 5 eksik komutla güncellendi. BUG FIX: `root_project_cmd.py:73` `db.get_project()` → `db.project_get()` düzeltildi. Python OK, 445/445 test geçti. |
| BUG-DESK-LOCK-1 | Desktop input aksiyonları ekran kilitliyken şifre alanına yazıyordu | 2026-04-19 | `desktop_common.py`: `is_screen_locked()` async fonksiyonu eklendi (loginctl show-session LockedHint). `desktop_router.py`: `_INPUT_ACTIONS` set + `_check_screen_lock()` guard → `type/key/click/move/scroll/activate_element` aksiyonları ekran kilitliyse `{"ok":false}` döner. |
| BUG-DESK-LOCK-2 | Terminal API'den xdotool girdi komutları da ekran kilitliyken çalışıyordu | 2026-04-19 | `terminal_router.py`: `xdotool type/key/click/mousemove` içeren komutlar için `is_screen_locked()` kontrolü eklendi; kilitliyse 403 döner. |
| DESK-OPT-4 | Playwright Locator API — `_make_locator()` helper; wait_for_selector + ayrı action → tek çağrı | 2026-04-19 | `browser.py`: `_make_locator(page, selector)` — CSS'e `css=` öneki ekler, XPath/text=/role= olduğu gibi bırakır. `browser_fill/click/get_text/wait_for` Locator API'ye dönüştürüldü. |
| DESK-OPT-5 | Playwright CDP direkt tıklama — actionability atlanır, %15-20 hız kazancı | 2026-04-20 | `browser.py`: `browser_cdp_click()` — `locator.bounding_box()` + `context.new_cdp_session(page)` → `Input.dispatchMouseEvent` (mousePressed+mouseReleased). `fallback=True` ile CDP hatasında `loc.click()`'e düşer. `browser_router.py`: `cdp_click` aksiyonu + `fallback` field eklendi. Python OK. |
| DESK-OPT-6 | Pencere odak güvenilirliği — `_NET_ACTIVE_WINDOW` ClientMessage | 2026-04-20 | `desktop_input.py`: `_net_active_window_sync()` + `net_active_window()` — python-xlib ile root pencereye `_NET_ACTIVE_WINDOW` ClientMessage + `SubstructureRedirectMask`. `desktop.py` `focus_window()` öncelik sırası güncellendi: xlib → wmctrl → xdotool (hem `window_id` hem `window_name` yolu). Python OK. |
| DESK-OPT-7 | Desktop API batch endpoint — zincirleme aksiyonlar tek HTTP isteğinde | 2026-04-19 | `desktop_router.py`: `DesktopBatchRequest` modeli + `POST /internal/desktop/batch` endpoint eklendi. `execution_mode`: sequential/parallel, `stop_on_error`: True/False, max 20 aksiyon. `_run_single()` yardımcısı lock kontrolü + handler dispatch'i kapsüller. Python OK. |
| GR-1 | Yeni tehlikeli komut kategorileri — KATEGORİ 61 & 62 | 2026-04-19 | `GUARDRAILS.md`: KATEGORİ 61 (Pipe ile Uzak Script — curl/wget\|bash, bash<(curl…), \| python3/node, base64\|bash); KATEGORİ 62 (Sistem Geneli Paket — sudo pip install, pip3 install, npm install -g, npx, yarn global). Özet tablosuna satırlar eklendi. Loader otomatik yükledi: pip3, npx, yarn token'ları artık hint_words'de. |
| GR-2 | guardrails_loader.py token listesi doğrulama — test eklendi | 2026-04-19 | `tests/test_guardrails_loader.py`: 49 test — `load_hint_words()` çıktısını bağımsız referans çıkarmayla tam eşleştirme, 35 kritik token varlığı (rm, sudo, shutdown, curl, ssh…), graceful fallback (dosya yok → boş frozenset/str), `load_category_summaries()` min 60 kategori + 9 kritik kategori fragmanı, missing-file fallback. 49/49 geçti. |

| PERF-OPT-1 | `.claude-routes.json` kapsamını genişlet | 2026-04-19 | 12 → 33 rota. Log analizine göre en sık okunan dosyalar route'a bağlandı. 21 yeni kategori: desktop, desktop_vision, browser, i18n, text_routing, menu, plans, calendar, terminal, telegram, app_types, history, media, pdf, projects, auth, webhook_proxy, main_startup, capability_guard, credential_store, internal_router. Tahmini etki: %20-30 Read azalma. |
| PERF-OPT-2 | Tekrarlanan dosya okumalarını detect et | 2026-04-19 | `server.js`: `sessionReadCounts` Map (session_id → Map<filePath, count>), `trackFileRead()`, `buildRepeatReadWarning()` eklendi. `runClaude`'da Read tool_use'ları izleniyor. 3+ okumada `init_prompt`'a "Tekrarlı Dosya Okumaları — Optimize Et" uyarısı ekleniyor. `/reset` ve session expiry'de sayaçlar temizleniyor. `buildInitPrompt(…, sessionId)` imzası güncellendi. Node OK. |
| PERF-OPT-3 | `CLAUDE.md` boyutunu takip et | 2026-04-19 | `server.js`: `CLAUDE_MD_PATH`, `BACKLOG_PATH`, `CLAUDE_MD_LINE_WARN=1000` sabitleri eklendi. `checkClaudeMdSize()`: başlangıçta satır sayısını loglar, eşik aşılırsa BACKLOG.md'ye `<!-- CLAUDE_MD_SIZE_WARN -->` marker'lı otomatik uyarı ekler (idempotent). `getClaudeMdLineCount()`: her sorguda çağrılır. `buildInitPrompt`'a `claudeMdSizeNote` eklendi — Claude her sorguda boyutu görür. `app.listen`'da `checkClaudeMdSize()` çağrısı. Node OK. |
| PERF-OPT-4 | Bridge timeout artırımı ve progressive feedback | 2026-04-19 | `server.js`: `TIMEOUT_MS` varsayılanı 300000 (5dk) → 1800000 (30dk). `PROGRESS_INTERVAL_MS` sabiti eklendi (varsayılan 120000 = 2dk). `/query` endpoint'inde `progressInterval` setInterval kurulumu + `finally` bloğunda `clearInterval` ile temizleme — her 2dk'da "⏳ Hâlâ çalışıyor... (X dk)" bildirimi gönderilir; `silent=true` veya `PROGRESS_INTERVAL_MS=0` ise devre dışı. `.env.example` güncellendi. Node OK. |
| PERF-OPT-5 | Proje session'ları için init_prompt küçültme | 2026-04-19 | `server.js`: `buildInitPrompt`'ta `hasActiveRootProject` kontrolü eklendi. `active_root_project` setilendiğinde `projectClaudeMd` (tam root CLAUDE.md, ~15KB) atlanıyor. Proje CLAUDE.md'si zaten `activeRootProject` bölümünden geliyor; `base` kritik tüm kuralları barındırıyor. Tahmini token tasarrufu: ~2000 token/sorgu. Node OK. |
| PERF-OPT-6 | `ERR:` boş status girişlerini araştır | 2026-04-19 | Kök neden: `str(exc)` bazı httpx exception'larında boş string döndürüyor. `_bridge_client.py`: `error_msg` artık `f"{type(exc).__name__}: {exc}"` formatında — boşsa `repr(exc)` kullanılıyor. `server.js`: `_logBridgeError()` eklendi; TIMEOUT / CLI_EXIT / API_ERR hataları `bridge.log`'a `{status:"ERR", error_type, error, latency_ms}` JSON olarak yazılıyor. Python OK. Node OK. |
| PERF-OPT-7 | SQLite WAL modu — DedupGuard opsiyonel iyileştirme | 2026-04-19 | `_connection.py` incelendi: `PRAGMA journal_mode=WAL` zaten etkin (önceden eklenmiş). Ek olarak `PRAGMA synchronous=NORMAL` eklendi — WAL+NORMAL önerilen kombinasyon; fsync yalnızca checkpoint'te yapılır, her yazma sonrası değil. Dedup avg 2.3ms → tahminen ~1.8ms. Python OK. |

---

## 🔵 WMA'dan Taşınan — Kişisel Ajan Özellikleri ve Mimari

> Kaynak: whatsapp-memory-agent BACKLOG.md (2026-04-20 tarihinde taşındı)

| # | Başlık | Kaynak | Tarih | Not |
|---|--------|--------|-------|-----|
| A7 | Root agent'ı proje bağımsız hale getir — multi-project desteği | [OBS] | 2026-04-10 | Mevcut root agent (`scripts/claude-code-bridge/`) yalnızca tek projeye bağlı (INIT_PROMPT, proje dizini hardcoded). Hedef: root agent ayrı bir servis olarak çalışsın; "şöyle bir proje oluştur" dediğinde yeni proje dizini oluşturabilsin, farklı CLAUDE.md bağlamlarıyla farklı projelere bağlanabilsin. Tasarım seçenekleri: (1) Bridge'e `project_dir` + `init_prompt` parametresi ekle, her proje kendi bridge config'iyle çalışsın. (2) Merkezi bir orchestrator bridge'i: hangi projeye bağlanacağını WhatsApp mesajından tespit etsin. |
| F1 | base-rag-agent: AbstractMessenger + AbstractIngestor adapter katmanı | [OBS] | 2026-03-29 | WMA'dan fork. WhatsApp-specific kodları `adapters/messenger/whatsapp.py` ve `adapters/ingestor/whatsapp_chat.py`'ye taşı. `core/` altında değişmeyen kısımlar (auth, pipeline, query, agent, store) kalır. Yeni use case için sadece yeni adapter yazılır. |
| F2 | SRT/ASS altyazı ingestörü | [OBS] | 2026-03-29 | `.srt` ve `.ass` dosyalarını parse et: diyalog metni + zaman damgası + seri/film adı + sezon/bölüm numarası metadata olarak saklanır. Sorgular: "inception'da bu replik nerede geçiyor", "12. bölüm 23. dakikada ne dedi". |
| F3 | Markdown notlar ve PDF ingestörü | [OBS] | 2026-03-29 | Kişisel notlar (.md), belgeler (.pdf) ve düz metin dosyalarını RAG pipeline'a sokacak ingestörler. pypdf2 veya pdfplumber PDF için, frontmatter parse Markdown için. |
| F4 | Sekreter araç seti — hatırlatıcı ve görev yönetimi | [OBS] | 2026-03-29 | Agent tool'ları: `add_reminder(text, datetime)`, `list_reminders()`, `mark_done(id)`, `add_note(title, content)`, `get_current_datetime()`. Hatırlatıcılar `data/reminders.json`'da saklanır. APScheduler ile belirtilen saatte mesaj gider. |
| F5 | Lokal model stack — qwen3 ile API bağımsız çalışma | [OBS] | 2026-03-29 | Varsayılan model: `qwen3:7b` veya `qwen3:4b` (tool-calling desteği var, Türkçe iyi). Narrativize + query + agent hepsi lokal çalışır. Gemini/Claude API opsiyonel fallback olarak kalır. |
| F6 | Telegram messenger adaptörü | [OBS] | 2026-03-29 | `AbstractMessenger` üzerinden Telegram Bot API implementasyonu. python-telegram-bot veya aiogram kütüphanesi. WhatsApp'a alternatif veya ek kanal olarak çalışır. |
| F7 | CLI messenger — lokal test ve geliştirme arayüzü | [OBS] | 2026-03-29 | Terminal üzerinden agent ile konuşmayı sağlayan `CLIMessenger`. WhatsApp/Telegram olmadan lokal geliştirme ve test için. Rich kütüphanesiyle güzel terminal çıktısı. |

**FEAT-11 — `/internal/desktop` endpoint (WMA'dan taşındı, 99-root için implementasyon tamamlandı ✅)**

| # | Faz | Açıklama | Durum |
|---|-----|----------|-------|
| FEAT-11a | Faz 1 | `desktop_router.py` — `/internal/desktop` endpoint; `action`: `open`, `run`, `ocr`, `screenshot` | ✅ |
| FEAT-11b | Faz 1 | `CLAUDE.md`'e `/internal/desktop` API belgesi eklendi | ✅ |
| FEAT-11c | Faz 2 | `features/desktop.py`'ye `xdotool` entegrasyonu: `type_text`, `key_press`, `mouse_click`, `mouse_move`, `scroll` | ✅ |
| FEAT-11d | Faz 3 | `vision_query` aksiyonu: ekran görüntüsü + Claude Vision API | ✅ |
| FEAT-11e | Faz 4 | Pencere yönetimi: `get_windows`, `focus_window` | ✅ |
| DESK-LOGIN-1 | Login Playwright-first strateji | 2026-04-22 | CLAUDE.md'ye "Login Otomasyon Stratejisi" bölümü eklendi: standart login akışı (goto→get_credential→fill→click→wait_for→screenshot), selector fallback sırası, kurallar. `.claude-routes.json`'a `login` route eklendi. Vision API / xdotool yerine DOM selector kullanımı zorunlu kılındı. |
| MOD-INSTALL-1a | `DESKTOP_ENABLED` ve `BROWSER_ENABLED`'ı wizard'a ekle | 2026-04-22 | `install.sh`: i18n string'ler (EN/TR), `_write_capabilities()`'de `enabled_keys`/`enabled_envs` ile ters mantık dalı, whiptail checklist + text mode (varsayılan OFF), `step_capabilities` idempotent kontrol `*_ENABLED` dahil. |
| MOD-INSTALL-1b | Wizard ↔ registry senkronizasyon yorumları | 2026-04-22 | `capability_guard.py` docstring'ine 4 maddelik checklist (config.py + .env.example + install.sh + locales). `install.sh` `cap_keys`/`enabled_keys` dizilerine `capability_guard.py _RULES` referansı. |
| MOD-INSTALL-1c | `.env.example` capability sıralaması | 2026-04-22 | Açıklamalar `config.py` ile eşitlendi (6 fark düzeltildi). Bölüm başlığına `*_ENABLED` cross-reference ve wizard notu eklendi. `DESKTOP_ENABLED`/`BROWSER_ENABLED` satırlarına "← capability wizard kapsamında" notu eklendi. |
| BROWSER-1 | Playwright DOM-first genişletme | 2026-04-22 | 8 yeni aksiyon eklendi (select_option, check, type, press, hover, get_attribute, scroll, get_url). `.browser-selectors.json` site-özel selector mapping dosyası oluşturuldu. `server.js` — `buildBrowserHint()` ile init_prompt'a otomatik selector injection. |
| WIZ-UX-1 | Servis seçenek açıklamalarını doldur | 2026-04-23 | `locales/tr.json` + `en.json` — `opt_svc_yes_desc` ve `opt_svc_no_desc` doldu (Rapor §4.2). Kod değişikliği yok. |
| WIZ-UX-2 | `service_intro` bilgi mesajı | 2026-04-23 | `locales/tr.json` + `en.json` — yeni `wizard.service_intro` key'i. `features/wizard_steps.py:201` — `ask_service_name` ilk servis (`existing == 0`) için önce `service_intro` gönderiyor, sonra `service_name_prompt`. |
| WIZ-UX-3 | Servis prompt metinlerini rewrite | 2026-04-23 | `locales/tr.json` + `en.json` — `service_name_prompt`, `service_cmd_prompt`, `service_port_prompt`, `service_cwd_prompt` için "Neden?" satırı + örnekler + shell yönlendirme yasağı uyarısı (Rapor §4.2). |
| WIZ-UX-4 | Sağlık kontrolü + locale parity | 2026-04-23 | `backend.main:app` import OK; `tr.json` ↔ `en.json` 323 key parity; 528/530 test passed (2 failure WIZ-UX dışı, pre-existing: terminal_router `_LOCALHOST`, pdf_import). |
| WIZ-LLM-1 | LLM scaffold modülü | 2026-04-23 | `features/wizard_llm_scaffold.py` (YENİ) — `generate_arch_preview(name, desc, lang) -> dict \| None`, `regenerate_arch_preview(prev_json, user_feedback)`, `sanitize_arch_dict(data)`, `build_arch_prompt()`. 60 sn timeout (`asyncio.wait_for`); başarısızsa `None` → fallback statik şablon. JSON schema prompt'ta zorunlu tutulur. |
| WIZ-LLM-2 | Config + env flag | 2026-04-23 | `config.py` — `wizard_llm_model: str = "claude-haiku-4-5-20251001"` (LLM bölümü) + `restrict_wizard_llm_scaffold: bool = False`. `install.sh` — `cap_keys`/`cap_envs`/whiptail+text checklist'lere `wizard_llm_scaffold` + `_S_CAP_WIZ_LLM` (tr/en) eklendi. `.env`'e yazılmaz (intent_classifier_model pattern). |
| WIZ-LLM-3 | Wizard adım 2.5 ekleme | 2026-04-23 | `features/wizard_steps.py` + `wizard_core.py` + `app_types.py` — `ask_auto_arch`, `handle_auto_arch_reply`, `show_arch_preview`, `handle_arch_edit_input`. SessionState `_CONTROLLED_KEYS`'e: `wiz_auto_arch`, `wiz_ai_desc`, `wiz_ai_arch`, `wiz_ai_stack`, `wiz_ai_dirs`, `wiz_ai_prev_json`. `clear_wizard` otomatik temizler (SOLID-v2-5 OCP). |
| WIZ-LLM-4 | Buton dispatch | 2026-04-23 | `routers/_text_router.py` — `wiz_auto_arch_yes/no`, `wiz_arch_accept/edit/skip` reply_id'leri için handler yönlendirmesi. |
| WIZ-LLM-5 | Scaffold AI override (Q3=B) | 2026-04-23 | `features/project_scaffold.py` — `_build_md_content(..., ai_overrides=None)` + `_scaffold_project(..., ai_overrides=None)`. `project_crud.py create_project` passthrough. `wizard_steps.py confirm_create` `wiz_auto_arch=='yes'` + `wiz_ai_prev_json` dolu iken stack/directories/architecture dict'i kurup geçirir. Statik başlık + `## Proje Kök Dizini` korunur; AI varsa `## Stack` + `## Klasör Yapısı` + `## Mimari` blokları eklenir. |
| WIZ-LLM-6 | CapabilityGuard kaydı | 2026-04-23 | `guards/capability_guard.py` `_RULES` listesine `restrict_wizard_llm_scaffold → 'wizard_llm_scaffold'` eklendi. Matcher no-op (`lambda ctx: False`) — enforcement feature-call düzeyinde (`wizard_steps.py:72`). Kayıt `log_active_restrictions()` görünürlüğü + `install.sh cap_keys` tutarlılığı içindir. |
| WIZ-LLM-7 | Locale keys | 2026-04-23 | `locales/tr.json` + `en.json` — `capability.wizard_llm_scaffold` + 11 `wizard.*` key (ask_auto_arch, auto_arch_yes/no_btn, arch_generating/regenerating/preview/accept_btn/edit_btn/skip_btn/edit_prompt/failed). 528 test passed, `t()` sanity OK. |
| WIZ-LLM-8 | Unit testler | 2026-04-23 | `scripts/tests/test_wizard_llm_scaffold.py` (YENİ, 31 test) — `build_arch_prompt` tr/en + regenerate + non-serializable prev; `sanitize_arch_dict` whitelist/tip/boyut/truncate/cap; `_extract_json_block` fence/raw/yok; `generate_arch_preview` happy/timeout/no-api-key/JSON parse/sanitize fail/exception; `regenerate` prev_json+feedback passthrough; `_build_md_content` ai_overrides none/stack/dirs/arch/full/empty/non-claude. 559 passed (528+31). |
| WIZ-LLM-9 | Sağlık kontrolü | 2026-04-23 | Python import `from backend.main import app` OK; Node `--check server.js` OK; pytest 559 passed + 2 pre-existing failed (WIZ-LLM dışı: `test_pdf_import_with_valid_key` AttributeError `backend.features.pdf_importer`, `test_localhost_set_contains_127` ImportError `_LOCALHOST`). WIZ-LLM-8'in 31 testi tamamı geçiyor. |
| GH-1 | GitHub repository adı: "Ortak" | 2026-04-22 | Proje GitHub reposu adı **Ortak** (Türkçe). Genel amaçlı kişisel AI ajan konsepti + "Kişisel asistan" anlamı. "Aracı" ile "Ortak" isimleri beğenildi; "Ortak" seçildi. |
