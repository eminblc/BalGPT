# Bring Your Own Key / Model (BYOK/BYOM)

Bu ajan üç farklı LLM arka ucu ile çalışabilir. Hangi seçeneği kullanacağına `.env` içindeki `LLM_BACKEND` değişkeni karar verir.

---

## Seçenek A — Anthropic API (varsayılan, GPU gerekmez)

En kolay kurulum. API anahtarı yeterli; yerel GPU şart değil.

```env
LLM_BACKEND=anthropic
ANTHROPIC_API_KEY=sk-ant-...
```

**Maliyet (yaklaşık):**
- Claude Sonnet 4.5: ~$3 / 1M input token, ~$15 / 1M output token
- Claude Haiku 4.5: ~$0.80 / 1M input token, ~$4 / 1M output token

Anahtar almak için: [console.anthropic.com](https://console.anthropic.com)

---

## Seçenek B — Ollama (yerel GPU, ücretsiz)

Tüm işlemler kendi makinende gerçekleşir; dışarıya veri çıkmaz.

**Gereksinimler:**
- NVIDIA / AMD GPU **veya** Apple Silicon (M1/M2/M3)
- Minimum 8 GB VRAM (llama3 8B için), 16 GB+ önerilir

**Kurulum:**

```bash
# Ollama kur
curl -fsSL https://ollama.ai/install.sh | sh

# Model indir (tercihine göre)
ollama pull llama3          # Meta LLaMA 3 8B — dengeli
ollama pull mistral         # Mistral 7B — hız odaklı
ollama pull codestral       # Kod odaklı görevler için
```

```env
LLM_BACKEND=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3
```

> **Not:** Ollama desteği aktif. `OLLAMA_BASE_URL`'in erişilebilir olduğundan emin ol.

---

## Seçenek C — Gemini Free Tier

Google'ın ücretsiz katmanı; belirli bir aylık kota dahilinde ücretsiz.

```env
LLM_BACKEND=gemini
GEMINI_API_KEY=AIza...
GEMINI_MODEL=gemini-2.0-flash
```

Anahtar almak için: [aistudio.google.com](https://aistudio.google.com)

> **Deneysel:** Gemini intent sınıflandırıcı (`_intent_classifier.py`) tarafından kullanılmaz; yönetim niyeti tespiti her zaman Anthropic Haiku ile yapılır. API anahtarı güvenlik nedeniyle URL parametresi değil, `x-goog-api-key` header üzerinden iletilir.

---

## Karşılaştırma Tablosu

| Kriter | Anthropic API | Ollama (yerel) | Gemini Free |
|--------|:---:|:---:|:---:|
| **Gizlilik** | ⚠️ Bulut | ✅ Tam yerel | ⚠️ Bulut |
| **Maliyet** | 💰 Kullanıma göre | ✅ Ücretsiz | ✅ Kota dahilinde |
| **Kurulum kolaylığı** | ✅ Tek API key | ⚙️ GPU + model indirme | ✅ Tek API key |
| **Yanıt hızı** | ✅ Hızlı | ⚙️ Donanıma bağlı | ✅ Hızlı |
| **Yanıt kalitesi** | ✅ En yüksek | ⚙️ Modele göre | 🔶 Orta |
| **Çevrimdışı** | ❌ İnternet şart | ✅ Çevrimdışı çalışır | ❌ İnternet şart |
| **Claude Code CLI** | ✅ Native destek | ⚠️ Bridge gerekli | ⚠️ Bridge gerekli |

### Öneri

| Durum | Seçenek |
|-------|---------|
| Hızlı başlamak istiyorum | **A — Anthropic API** |
| GPU'm var, veri çıkmasın | **B — Ollama** |
| Ücretsiz, bulut kabul | **C — Gemini** |
