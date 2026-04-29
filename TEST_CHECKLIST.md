# Test Checklist — 99-root Kişisel AI Ajan

> Durum: `[ ]` bekliyor · `[x]` geçti · `[!]` hata var

---

## 1. Servis Sağlığı

| # | Test | Durum | Not |
|---|------|-------|-----|
| S-1 | `curl http://localhost:8010/health` → 200 | [ ] | |
| S-2 | `curl http://localhost:8013/health` → 200 | [ ] | |
| S-3 | `journalctl -u personal-agent.service` — hata yok | [ ] | |
| S-4 | `journalctl -u personal-agent-bridge.service` — hata yok | [ ] | |

---

## 2. Temel Sohbet

| # | Test | Durum | Not |
|---|------|-------|-----|
| C-1 | Serbest metin mesajı → Claude yanıtı geliyor | [ ] | |
| C-2 | Yanıt 30 saniye içinde geliyor | [ ] | |
| C-3 | Uzun mesaj (>500 karakter) → yanıt parçalanmıyor | [ ] | |

---

## 3. Komutlar

### !help
| # | Test | Durum | Not |
|---|------|-------|-----|
| H-1 | `!help` → buton menüsü + komut listesi | [ ] | |
| H-2 | `!help` sistem bölümünde "Model Degistir" satırı görünüyor | [ ] | |
| H-3 | `!help` model satırı aktif backend + modeli gösteriyor | [ ] | |
| H-4 | `!help !restart` → yalnızca restart açıklaması | [ ] | |
| H-5 | `!help !bilinmeyen` → hata mesajı | [ ] | |

### !lang
| # | Test | Durum | Not |
|---|------|-------|-----|
| L-1 | `!lang en` → "Language changed: EN" | [ ] | |
| L-2 | `!lang tr` → "Dil değiştirildi: TR" | [ ] | |
| L-3 | `!lang xx` → desteklenmeyen dil hatası | [ ] | |
| L-4 | `!restart` sonrası dil tercihi korunuyor (FEAT-6) | [ ] | |

### !model (FEAT-5)
| # | Test | Durum | Not |
|---|------|-------|-----|
| M-1 | `!model` → aktif model + backend + seçenekler | [ ] | |
| M-2 | `!model haiku` → model değişti mesajı | [ ] | |
| M-3 | `!model sonnet` → model değişti mesajı | [ ] | |
| M-4 | `!model opus` → model değişti mesajı | [ ] | |
| M-5 | `!model haiku` sonrası mesaj gönder → Haiku yanıtlıyor | [ ] | |
| M-6 | `!model haiku` iken `!model haiku` → "zaten aktif" mesajı | [ ] | |
| M-7 | `!restart` sonrası model tercihi korunuyor (FEAT-6) | [ ] | |

### !history
| # | Test | Durum | Not |
|---|------|-------|-----|
| HI-1 | `!history` → son mesajlar geliyor | [ ] | |
| HI-2 | `!history 5` → son 5 mesaj | [ ] | |

### !project
| # | Test | Durum | Not |
|---|------|-------|-----|
| P-1 | `!project` → aktif proje / proje listesi | [ ] | |
| P-2 | `!project <id>` → TOTP isteniyor | [ ] | |
| P-3 | Geçerli TOTP → proje seçildi | [ ] | |
| P-4 | Hatalı TOTP → reddedildi | [ ] | |

### !root-reset
| # | Test | Durum | Not |
|---|------|-------|-----|
| RR-1 | `!root-reset` → Bridge session sıfırlandı | [ ] | |

### !root-project / !root-exit
| # | Test | Durum | Not |
|---|------|-------|-----|
| RP-1 | `!root-project` → aktif bağlam gösteriliyor | [ ] | |
| RP-2 | `!root-exit` → root bağlamdan çıkıldı | [ ] | |

### !root-check
| # | Test | Durum | Not |
|---|------|-------|-----|
| RC-1 | `!root-check` → son 5 log satırı geliyor | [ ] | |

### !schedule
| # | Test | Durum | Not |
|---|------|-------|-----|
| SC-1 | `!schedule` → mevcut görev listesi | [ ] | |
| SC-2 | Doğal dil ile görev oluştur (ör. "Her sabah 9'da...") | [ ] | |
| SC-3 | `!schedule sil <id>` → görev silindi | [ ] | |

### !cancel
| # | Test | Durum | Not |
|---|------|-------|-----|
| CA-1 | TOTP beklerken `!cancel` → akış iptal | [ ] | |

### !restart / !shutdown
| # | Test | Durum | Not |
|---|------|-------|-----|
| RS-1 | `!restart` → matematik sorusu geliyor | [ ] | |
| RS-2 | Matematik cevabı → owner TOTP isteniyor | [ ] | |
| RS-3 | Geçerli TOTP → servis yeniden başlatıldı | [ ] | |
| RS-4 | Restart sonrası servis ayakta (`/health` 200) | [ ] | |

### !lock / !unlock
| # | Test | Durum | Not |
|---|------|-------|-----|
| LK-1 | `!lock` → TOTP isteniyor | [ ] | |
| LK-2 | Geçerli TOTP → uygulama kilitlendi | [ ] | |
| LK-3 | Kilitliyken normal mesaj → reddediliyor | [ ] | |
| LK-4 | `!unlock` + geçerli TOTP → kilit açıldı | [ ] | |

### !terminal
| # | Test | Durum | Not |
|---|------|-------|-----|
| TRM-1 | `!terminal ls -la` → güvenli komut, doğrudan çalışıyor | [ ] | |
| TRM-2 | `!terminal rm -rf /tmp/test` → owner TOTP isteniyor | [ ] | |
| TRM-3 | Geçerli TOTP → tehlikeli komut çalışıyor | [ ] | |

### !timezone
| # | Test | Durum | Not |
|---|------|-------|-----|
| TZ-1 | `!timezone` → mevcut saat dilimi gösteriliyor | [ ] | |
| TZ-2 | `!timezone Europe/London` → saat dilimi değişti, APScheduler güncellendi | [ ] | |
| TZ-3 | Geçersiz timezone → hata mesajı | [ ] | |

### !tokens
| # | Test | Durum | Not |
|---|------|-------|-----|
| TK-1 | `!tokens` → 24 saatlik token istatistiği geliyor | [ ] | |
| TK-2 | `!tokens 7d` → 7 günlük özet | [ ] | |
| TK-3 | `!tokens 30d` → 30 günlük özet, model/backend dağılımı | [ ] | |

---

## 4. Proje Yönetimi

| # | Test | Durum | Not |
|---|------|-------|-----|
| PR-1 | Menü → Yeni Proje → wizard başlıyor | [ ] | |
| PR-2 | Yazılım projesi oluştur → dizin + CLAUDE.md var | [ ] | |
| PR-3 | Görev projesi oluştur → README + outputs/ var | [ ] | |
| PR-4 | PDF gönder → proje wizard başlıyor | [ ] | |
| PR-5 | `!project <id>` ile projeye geçiş | [ ] | |
| PR-6 | Beta modunda mesaj projeye gidiyor | [ ] | |
| PR-7 | `!beta` → root bağlama dönüldü | [ ] | |

---

## 5. Takvim & Zamanlama

| # | Test | Durum | Not |
|---|------|-------|-----|
| CAL-1 | "Yarın saat 10'da toplantı" → takvime eklendi | [ ] | |
| CAL-2 | Menü → Takvim → yaklaşan etkinlikler | [ ] | |
| CAL-3 | Hatırlatıcı zamanında geliyor | [ ] | |

---

## 6. Medya

| # | Test | Durum | Not |
|---|------|-------|-----|
| MED-1 | Görsel gönder → Claude açıklıyor | [ ] | |
| MED-2 | Ses mesajı → Claude yanıtlıyor | [ ] | |
| MED-3 | PDF gönder → proje wizard açılıyor | [ ] | |

---

## 7. Güvenlik

| # | Test | Durum | Not |
|---|------|-------|-----|
| SEC-1 | Bilinmeyen numara → mesaj reddediliyor | [ ] | |
| SEC-2 | Rate limit: kısa aralıkta çok mesaj → kısıtlama | [ ] | |
| SEC-3 | Guardrail tetikleme: "sistemi kapat" → uyarı | [ ] | |

---

## 8. Kullanıcı Ayarları Kalıcılığı (FEAT-6)

| # | Test | Durum | Not |
|---|------|-------|-----|
| US-1 | `!lang en` → `!restart` → dil İngilizce kaldı | [ ] | |
| US-2 | `!model haiku` → `!restart` → model haiku kaldı | [ ] | |

---

## Özet

| Kategori | Toplam | Geçti | Hata |
|----------|--------|-------|------|
| Servis Sağlığı | 4 | | |
| Temel Sohbet | 3 | | |
| Komutlar | 43 | | |
| Proje Yönetimi | 7 | | |
| Takvim & Zamanlama | 3 | | |
| Medya | 3 | | |
| Güvenlik | 3 | | |
| Kullanıcı Ayarları | 2 | | |
| **Toplam** | **68** | | |
