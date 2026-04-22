# AGENT.md — Kişisel AI Ajan

## Görev
WhatsApp üzerinden erişilebilen, her zaman açık kişisel AI ajan.
Sohbet, iş planlaması, takvim, proje yönetimi ve zamanlanmış görevleri tek yerden yönetir.

## Hedefler & KPI'lar

| Hedef | KPI | Başlangıç | Hedef |
|-------|-----|-----------|-------|
| Yanıt güvenilirliği | Başarılı yanıt / toplam istek | — | >99% |
| Bildirim zamanlaması | Zamanında gelen hatırlatıcı / toplam | — | >95% |
| Proje oluşturma | Başarılı proje init / istek | — | >90% |
| Çalışma süresi | Servis erişilebilirlik | — | >99.5% |

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

## Kapsam Dışı
- Birden fazla kullanıcıya hizmet vermek (tek kullanıcı sistemi)
- Ham verileri dışarıya sızdırmak
- Kullanıcı onayı olmadan dış servislere istek atmak
