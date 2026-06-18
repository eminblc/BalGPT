# BACKLOG.md Format — Backlog Executor Spec

Bu dosya, `scripts/backend/features/backlog_executor/` modülünün BACKLOG.md
dosyalarından **hangi satırları görev olarak okuduğunu** ve bunları nasıl
güncellediğini tanımlar. Tüm projelerin BACKLOG.md dosyaları (99-root dahil)
buradaki kurallara uymak zorundadır; uymayan satırlar `/backlog-execute`
tarafından sessizce atlanır.

Parser kaynak kodu: [`parser.py`](../../scripts/backend/features/backlog_executor/parser.py)
ve [`_formats.py`](../../scripts/backend/features/backlog_executor/_formats.py).

---

## 1. Item ID Kuralı

Regex (parser):

```
[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+
```

ek koşul: ID **en az bir rakam içermeli**.

| Geçerli | Geçersiz | Sebep |
|---|---|---|
| `SEC-001` | `SEC` | Tek segment, tire yok |
| `SCAN-DEPTH-1` | `ABC-DEF` | Hiç rakam yok |
| `BUG-BE-007` | `sec-001` | Lowercase |
| `UIGAP-001` | `001-SEC` | Büyük harfle başlamıyor |
| `VAL-MEDIA-1` | `BUG_042` | Tire yerine alt çizgi |
| `LOG-B001` | | |

ID, satır içinde **ilk geçen geçerli token** olarak yakalanır. Açıklama
metninde geçen başka büyük harfli kelimeler ID gibi görünmemeli (örn.
"REST API" cümlesini ID olarak yakalamaz çünkü iki segment + rakam koşulu yok).

---

## 2. İki Desteklenen Format

Parser, dosyada **ilk hangi format için satır bulursa onu** kullanır.
**İki format aynı dosyada karıştırılamaz** — biri seçilince diğeri okunmaz.

### Format A — Checkbox (my-project + legacy 99-root)

| Durum | Satır deseni |
|---|---|
| pending     | `- [ ] ITEM-001 Açıklama` |
| in_progress | `- [~] ITEM-001 Açıklama` |
| done        | `- [x] ITEM-001 Açıklama` |

Köşeli parantezli ID varyantı da geçerli:

```
- [ ] [UIGAP-001] **Başlık** — açıklama
```

### Format B — Table (güncel 99-root)

Standart Markdown tablosu, ilk hücre item ID olmalı:

```
| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
| ITEM-001 | Başlık | path/to/file.py | Kısa açıklama |
```

| Durum | İlk hücre |
|---|---|
| pending     | `\| ITEM-001 \|` |
| in_progress | `\| 🔄ITEM-001 \|` (🔄 prefix'i parser ekler/kaldırır) |
| done        | Satır tablodan **kaldırılır** veya `✅` bölümüne taşınır |

> 🔄 prefix'ini elle koymayın — `mark_in_progress` ekler, `mark_failed`
> geri alır.

### Format algılama önceliği

1. Dosyada `- [ ]` / `- [~]` / `- [x]` satırı varsa → **Checkbox**
2. Yoksa, `| ID |` satırı varsa → **Table**
3. Hiçbiri yoksa → varsayılan Checkbox (ama hiçbir item bulunmaz)

---

## 3. "Pending Stop" — Parser'ı Durduran Bölüm Başlıkları

Aşağıdaki **case-insensitive** desenlerden birini içeren `## ...` başlığını
gören parser, **dosyanın geri kalanını okumayı tamamen durdurur**:

- `## ... ✅ ...`
- `## ... Tamamlandı ...`
- `## ... Ertelenmiş ...`
- `## ... Deferred ...`
- `## ... Kullanıcı ...` (Kullanıcı Eylemi Gereken)

Yani: tamamlanmış / ertelenmiş / kullanıcı aksiyonu bekleyen item'lar
**dosyanın altında** olmalı. Eğer bu başlıklardan biri dosyanın ortasına
girerse altında kalan **aktif görevler de görünmez**.

---

## 4. Önerilen Bölüm Sırası

```
## 🔴 Kritik
## 🟠 Yüksek
## 🟡 Orta
## 🟢 Düşük
## 🟡 Kullanıcı Eylemi Gereken     ← parser buradan itibaren okumayı durdurur
## 🟠 Ertelenmiş (Deferred)
## ✅ Tamamlanan
```

Her öncelik için **tek bir bölüm** açın; aynı seviyede birden çok bölüm
açmayın ("🟠 Yüksek — Backend" + "🟠 Yüksek — Frontend" gibi
parçalamalar bölüm sırasını bozar).

---

## 5. Durum Geçiş Tablosu

| Olay | Checkbox | Table |
|---|---|---|
| Executor başlar | `- [ ]` → `- [~]` | `\| ID \|` → `\| 🔄ID \|` |
| Bridge cevap verir (≥40 char) | `- [~]` → `- [x]` | Satır silinir |
| Bridge boş/iptal/hata | `- [~]` → `- [ ]` (retry-able) | `\| 🔄ID \|` → `\| ID \|` |

---

## 6. Yaygın Hatalar

- ❌ ID'de rakam unutmak (`SEC-FOO`) → parser yakalamaz
- ❌ ID'yi küçük harfle yazmak (`sec-001`)
- ❌ Aktif bölümün **üstünde** "✅ Tamamlandı" başlığı kullanmak
- ❌ Aynı dosyada hem `- [ ] ...` hem `| ID | ... |` satırları kullanmak
- ❌ Tablo satırının başına 🔄 prefix'i elle koymak (parser bunu zaten yönetir)
- ❌ ID'den önce satıra `> ` blockquote prefix'i koymak (Checkbox satırı `- [ ]` ile başlamalı)

---

## 7. Şablonlar

### Yeni Checkbox formatlı BACKLOG.md

```markdown
# <Proje> — BACKLOG

## 🔴 Kritik

- [ ] BUG-001 Login akışı 500 dönüyor — `src/auth/login.ts`

## 🟠 Yüksek

- [ ] SEC-001 JWT secret env'den okunmuyor — `src/config.ts`
- [ ] [PERF-002] **DB connection pool** — pool size 5'ten 20'ye çıkar

## 🟡 Orta

## 🟢 Düşük

## 🟡 Kullanıcı Eylemi Gereken

- [ ] OPS-001 `.env`'e `API_KEY` eklenmeli

## ✅ Tamamlandı

- [x] INIT-001 Proje iskeleti kuruldu
```

### Yeni Table formatlı BACKLOG.md

```markdown
# <Proje> — BACKLOG

## 🔴 Kritik

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
| BUG-001 | Login akışı 500 dönüyor | `src/auth/login.ts` | Boş Authorization header'da crash |

## 🟠 Yüksek

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|
| SEC-001 | JWT secret env'den okunmuyor | `src/config.ts` | |

## 🟡 Orta

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|

## 🟢 Düşük

| # | Başlık | Dosya | Not |
|---|--------|-------|-----|

## 🟡 Kullanıcı Eylemi Gereken

| # | Başlık | Not |
|---|--------|-----|
| OPS-001 | `.env`'e `API_KEY` eklenmeli | |

## ✅ Tamamlandı

Tamamlanan görevler [DONE.md](DONE.md) dosyasına taşındı.
```
