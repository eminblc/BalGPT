# AGENT.md — Kişisel AI Ajan

## Görev
WhatsApp üzerinden erişilebilen, her zaman açık kişisel AI ajan.
Sohbet, iş planlaması, takvim, proje yönetimi ve zamanlanmış görevleri tek yerden yönetir.

## Hedefler & KPI'lar

| Hedef | KPI | Başlangıç | Hedef |
|-------|-----|-----------|-------|
| Yanıt güvenilirliği | Başarılı yanıt / toplam istek | ~95% (timeout/crash) | >99% |
| Bildirim zamanlaması | Zamanında gelen hatırlatıcı / toplam | ~98% (APScheduler) | >99% |
| Proje oluşturma | Başarılı proje init / istek | ~85% (wizard düzeltme gerekiyordu) | >95% |
| Çalışma süresi | Servis erişilebilirlik | ~99% (BridgeMonitor öncesi) | >99.5% |

## Özellikler

| Özellik | Modül | Durum |
|---------|-------|-------|
| Doğal dil sohbet | `features/chat.py` | ✅ Tamamlandı |
| İş planları | `features/plans.py` | ✅ Tamamlandı |
| Takvim + hatırlatıcı | `features/calendar.py` | ✅ Tamamlandı |
| Proje yönetimi | `features/projects.py` | ✅ Tamamlandı |
| PDF → Proje | `features/pdf_importer.py` | ✅ Tamamlandı |
| Zamanlanmış görevler | `features/scheduler.py` | ✅ Tamamlandı |
| Beta modu | Context Router | ✅ Tamamlandı |
| Çalışma bağlamı | `active_context.json` + Bridge | ✅ Tamamlandı |
| Komut sistemi | `guards/commands/` | ✅ Tamamlandı |
| Konuşma geçmişi köprüsü | `data/conv_history/` + Bridge | ✅ Tamamlandı |
| LLM soyutlama (BYOK/BYOM) | `adapters/llm/` | ✅ Tamamlandı |
| Messenger soyutlama | `adapters/messenger/` | ✅ Tamamlandı |
| Webhook proxy yönetimi | `features/webhook_proxy.py` | ✅ Tamamlandı |
| Arayüz i18n (tr/en) | `backend/i18n.py`, `locales/` | ✅ Tamamlandı |
| Yetenek kısıtlamaları (FEAT-3) | `guards/capability_guard.py` | ✅ Tamamlandı |
| Çalışma zamanı model değişikliği (FEAT-5) | `guards/commands/model_cmd.py` | ✅ Tamamlandı |
| Kullanıcı ayarları kalıcılığı (FEAT-6) | `store/repositories/settings_repo.py` | ✅ Tamamlandı |
| Desktop otomasyon | `features/desktop*.py` (9 modül) | ✅ Tamamlandı |
| Tarayıcı otomasyonu (Playwright) | `features/browser/` paketi | ✅ Tamamlandı |
| Terminal erişimi (!terminal) | `features/terminal.py`, `guards/commands/terminal_cmd.py` | ✅ Tamamlandı |
| Kimlik bilgisi deposu | `features/credential_store.py` | ✅ Tamamlandı |
| Token kullanım istatistikleri | `store/repositories/token_stat_repo.py`, `guards/commands/tokens_cmd.py` | ✅ Tamamlandı |
| Uygulama kilidi / kilit açma | `guards/commands/lock_cmd.py`, `unlock_cmd.py` | ✅ Tamamlandı |
| Çalışma zamanı saat dilimi değiştirme | `guards/commands/timezone_cmd.py` | ✅ Tamamlandı |
| LLM intent sınıflandırıcı | `routers/_intent_classifier.py` | ✅ Tamamlandı |
| Bridge otomatik yeniden başlatma | `services/bridge_monitor.py` | ✅ Tamamlandı |
| Wizard LLM scaffold (proje iskelet üretimi) | `features/wizard_llm_scaffold.py`, `wizard_steps.py` | ✅ Tamamlandı |
| Telegram messenger desteği | `adapters/messenger/telegram_messenger.py`, `routers/telegram_router.py` | ✅ Tamamlandı |

## Kapsam Dışı
- Birden fazla kullanıcıya hizmet vermek (tek kullanıcı sistemi)
- Ham verileri dışarıya sızdırmak
- Kullanıcı onayı olmadan dış servislere istek atmak
