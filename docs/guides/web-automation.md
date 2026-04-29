# Web / GUI Otomasyon Rehberi

Bu rehber Claude Code'un (bridge üzerinden) web ve GUI otomasyon görevlerinde hangi aracı ne zaman seçeceğini anlatır. Asıl motivasyon: `reports/done/desktop_automation_analysis_2026-04-19.md` — tek bir HepsiBurada giriş + sepet akışında 14-20 screenshot + her biri `vision_query` ile işlem görev ortasında API boyut limitine çarptı.

## Karar Ağacı

```
Görev web sitesinde mi?
├─ Evet → DOM tabanlı araçlar mevcut mu?
│   ├─ Yapısal veri yeterli (HTML parse, REST endpoint) → curl/requests
│   ├─ Selector'lar kararlı → Playwright (FEAT-13, /internal/browser/*)
│   └─ Yukarıdakiler çalışmaz → xdotool blind navigation + TEK doğrulama screenshot
└─ Hayır (masaüstü uygulaması):
    ├─ Kısayol/accelerator var (Ctrl+S, Alt+F) → xdotool key
    ├─ Accessibility API (AT-SPI) yeterli → desktop_atspi
    └─ Son çare → vision_query
```

## Sert Sınırlar (Unutma)

| Sınır | Değer | Nerede? |
|-------|-------|---------|
| `vision_query` max | 15 / 5dk | `settings.desktop_vision_max_per_session` |
| Screenshot width | 1280px auto-resize | `settings.desktop_screenshot_max_width` |
| Vision cache TTL | 60s | `desktop_vision._BboxCache` |
| Bridge timeout | 5 dk | `CLAUDE_CODE_TIMEOUT_MS` |

## Örnek 1 — HepsiBurada Blind Login (Önerilen)

```bash
# 1. Tarayıcıyı profil ile aç (tek sefer, kullanıcı elle)
# 2. URL bar'a git ve hepsiburada.com'u yaz
curl -s -X POST http://localhost:8010/internal/desktop \
  -H "Content-Type: application/json" \
  -d '{"action":"key","key":"ctrl+l"}'
curl -s -X POST http://localhost:8010/internal/desktop \
  -H "Content-Type: application/json" \
  -d '{"action":"type","text":"https://hepsiburada.com"}'
curl -s -X POST http://localhost:8010/internal/desktop \
  -H "Content-Type: application/json" \
  -d '{"action":"key","key":"Return"}'

# 3. Sayfa yüklenmesini bekle (screenshot YOK)
sleep 3

# 4. Giriş butonunu Tab ile bul — site layout'una göre Tab sayısı
curl -s -X POST http://localhost:8010/internal/desktop \
  -d '{"action":"key","key":"Tab Tab Tab Return"}'

# 5. Email/şifre gir (credential store kullan)
# FEAT-16: settings.get_site_credential("hepsiburada", "user")
curl -s -X POST http://localhost:8010/internal/desktop \
  -d '{"action":"type","text":"user@example.com"}'
curl -s -X POST http://localhost:8010/internal/desktop \
  -d '{"action":"key","key":"Tab"}'
curl -s -X POST http://localhost:8010/internal/desktop \
  -d '{"action":"type","text":"<PASSWORD>"}'
curl -s -X POST http://localhost:8010/internal/desktop \
  -d '{"action":"key","key":"Return"}'

sleep 5

# 6. TEK doğrulama screenshot — giriş başarılı mı?
curl -s -X POST http://localhost:8010/internal/desktop \
  -d '{"action":"vision_query","question":"Giriş yapıldı mı? Sadece evet/hayır.","session_id":"hb_task"}'
```

Toplam: **1 vision_query**, **0 screenshot dosyası**.

## Örnek 2 — Playwright ile DOM-based Akış

`browser_enabled=true` ve Playwright endpoint'leri aktifse (FEAT-13):

```bash
# (Playwright endpoint şeması proje içinde; tam detay için desktop_router yerine browser_router'a bak)
curl -s -X POST http://localhost:8010/internal/browser/goto \
  -d '{"url":"https://hepsiburada.com","session":"hb"}'

curl -s -X POST http://localhost:8010/internal/browser/click \
  -d '{"selector":"[data-test-id=login-button]","session":"hb"}'

curl -s -X POST http://localhost:8010/internal/browser/type \
  -d '{"selector":"#email","text":"user@example.com","session":"hb"}'
```

Vision çağrısı **sıfır**. Tüm navigasyon DOM üzerinden.

## Başarısızlık Senaryoları

### Captcha / Cloudflare
Vision ile çözülemez. `vision_query` ile durumu tespit et, kullanıcıya bildir, dur:
```bash
curl -X POST http://localhost:8010/internal/send_media \
  -d '{"path":"/tmp/wa_screenshot.png","caption":"Captcha görüldü — manuel müdahale gerekli"}'
```

### SMS/2FA
Aynı yaklaşım: bildir, bekle. `!cancel` ile akış iptal edilebilir.

### Rate Limit Uyarısı
Mesaj:
```
⚠️ Vision query limiti aşıldı (15/15 — 5 dk penceresi)...
```
→ DOM/xdotool moduna geç, 5 dk bekle veya `reset_vision_limiter()` çağır (yalnızca test).

## Yararlı Dahili Fonksiyonlar

| Modül | Fonksiyon | Amaç |
|-------|-----------|------|
| `features/desktop_capture.py` | `capture_screen()` | Ekran yakalama, auto-resize |
| `features/desktop_capture.py` | `_resize_png_bytes()` | Manuel PNG ölçekleme |
| `features/desktop_vision.py` | `vision_query()` | Cache + rate limit dahil |
| `features/desktop_vision.py` | `clear_bbox_cache()` | Cache temizle |
| `features/desktop_vision.py` | `reset_vision_limiter()` | Sayaç sıfırla (test) |
| `features/desktop_atspi.py` | AT-SPI erişilebilirlik ağacı | DOM olmayan GUI'de |

## Tamamlanan İyileştirmeler

- **BROWSER-1** (2026-04-22): Playwright paketi SRP modüllerine bölündü; `cdp_click`, `wait_for`, `get_text`, `get_content`, `save_session` endpoint'leri eklendi. Artık tüm DOM-based akışlar `browser_router` üzerinden çalışır.

## Planlanan İyileştirmeler

- Selector'ların `.claude-routes.json` benzeri bir site-özel haritayla saklanması (ör. `hepsiburada.com` → login selector'ları).
