#!/bin/sh
# ── FastAPI container başlangıç scripti ──────────────────────────────────────
# İlk çalışmada eksik dizinleri oluşturur, env var kontrolü yapar,
# isteğe bağlı pytest çalıştırır ve uvicorn'u başlatır.
set -e

OK="[✓]"
WARN="[⚠]"
ERR="[✗]"
INFO="[→]"

echo ""
echo "=================================================="
echo "  personal-agent API — başlatılıyor"
echo "=================================================="

# ── 1. Veri dizinleri ─────────────────────────────────────────────
echo ""
echo "$INFO Veri dizinleri kontrol ediliyor..."
FIXED=0
for dir in \
    /app/data/projects \
    /app/data/media \
    /app/data/claude_sessions \
    /app/data/conv_history \
    /app/outputs/logs \
    /app/reports/done; do
  if [ ! -d "$dir" ]; then
    mkdir -p "$dir"
    echo "  $OK Oluşturuldu: $dir"
    FIXED=$((FIXED + 1))
  fi
done
if [ "$FIXED" -eq 0 ]; then
  echo "  $OK Tüm dizinler mevcut"
fi

# ── 2. active_context.json başlat ────────────────────────────────
CTX_FILE="/app/data/active_context.json"
if [ ! -f "$CTX_FILE" ]; then
  cat > "$CTX_FILE" << 'EOF'
{
  "schema_version": 1,
  "active_project": null,
  "last_actions": [],
  "last_files": [],
  "session_note": ""
}
EOF
  echo "  $OK active_context.json oluşturuldu"
fi

# ── 3. Zorunlu env var kontrolü ──────────────────────────────────
echo ""
echo "$INFO Ortam değişkenleri kontrol ediliyor..."
MISSING=0

check_env() {
  var_name="$1"
  description="$2"
  # Shell'de değişken adından değer okuma
  eval val="\$$var_name"
  if [ -z "$val" ]; then
    echo "  $WARN $var_name boş — $description"
    MISSING=$((MISSING + 1))
  else
    echo "  $OK $var_name ayarlı"
  fi
}

check_env "API_KEY"               "X-Api-Key header'ı için"
check_env "TOTP_SECRET"           "owner TOTP doğrulaması"
check_env "TOTP_SECRET_ADMIN"     "admin TOTP doğrulaması (yıkıcı komutlar)"

LLM_BACKEND="${LLM_BACKEND:-anthropic}"
if [ "$LLM_BACKEND" = "anthropic" ]; then
  check_env "ANTHROPIC_API_KEY" "Claude LLM erişimi (llm_backend=anthropic)"
elif [ -z "$ANTHROPIC_API_KEY" ] && [ "${RESTRICT_INTENT_CLASSIFIER:-false}" != "true" ]; then
  echo "  $INFO ANTHROPIC_API_KEY tanımlı değil — intent classifier devre dışı kalır"
  echo "    (RESTRICT_INTENT_CLASSIFIER=true ile sessize alabilirsin)"
fi

MESSENGER_TYPE="${MESSENGER_TYPE:-whatsapp}"
if [ "$MESSENGER_TYPE" = "whatsapp" ]; then
  check_env "WHATSAPP_OWNER" "alıcı WhatsApp numarası (E.164)"
elif [ "$MESSENGER_TYPE" = "telegram" ]; then
  check_env "TELEGRAM_BOT_TOKEN" "Telegram bot kimlik doğrulaması"
  check_env "TELEGRAM_CHAT_ID"   "Owner'ın Telegram chat_id'si"
fi

if [ "$MISSING" -gt 0 ]; then
  echo ""
  echo "  $WARN $MISSING zorunlu değişken eksik."
  echo "  $INFO Düzeltmek için: scripts/backend/.env dosyasını düzenle"
  echo "  $INFO Şablon: scripts/backend/.env.example"
  echo "  (Eksik değerlerle servis başlamaya devam ediyor — bazı özellikler çalışmaz)"
fi

# ── 4. Python import / syntax kontrolü (+ LLM auto-fix) ─────────
echo ""
echo "$INFO Python import kontrolü..."
cd /app/scripts

IMPORT_ERROR=$(python -c "from backend.main import app" 2>&1)
IMPORT_STATUS=$?

if [ "$IMPORT_STATUS" -eq 0 ]; then
  echo "  $OK Python import OK"
else
  echo "  $ERR Python import BAŞARISIZ:"
  echo "$IMPORT_ERROR" | sed 's/^/    /'

  # Hatalı dosya yolunu çıkar (son "File ..." satırından)
  BROKEN_FILE=$(echo "$IMPORT_ERROR" | grep 'File "' | tail -1 | sed 's/.*File "\([^"]*\)".*/\1/')

  if [ -n "$ANTHROPIC_API_KEY" ] && [ -n "$BROKEN_FILE" ] && [ -f "$BROKEN_FILE" ]; then
    echo ""
    echo "  $INFO ANTHROPIC_API_KEY mevcut — LLM ile düzeltme deneniyor..."
    echo "  $INFO Dosya: $BROKEN_FILE"

    # --apply: volume mount varsa host dosyasını da günceller; yoksa öneri basar
    if python /docker/llm_fix.py \
          --error "$IMPORT_ERROR" \
          --file "$BROKEN_FILE" \
          --apply 2>&1; then
      echo ""
      echo "  $INFO Düzeltme uygulandı — import tekrar deneniyor..."
      if python -c "from backend.main import app" 2>&1; then
        echo "  $OK Python import OK (LLM düzeltmesi sonrası)"
      else
        echo "  $ERR LLM düzeltmesi işe yaramadı — manuel inceleme gerekli"
        exit 1
      fi
    else
      # Çıkış kodu 2 = dosya read-only; öneri log'a basıldı; build gerekli
      echo "  $ERR Otomatik düzeltme uygulanamadı (bkz. yukarıdaki öneri)"
      echo "  $INFO Düzelttikten sonra: docker compose build && docker compose up"
      exit 1
    fi
  else
    if [ -z "$ANTHROPIC_API_KEY" ]; then
      echo "  $INFO (ANTHROPIC_API_KEY tanımlı olsa LLM ile düzeltme denenirdi)"
    fi
    echo "  $ERR Container başlatılamıyor — kaynak kodu incele"
    exit 1
  fi
fi

# ── 5. Unit testler (isteğe bağlı) ───────────────────────────────
if [ "${RUN_TESTS_ON_START:-false}" = "true" ]; then
  echo ""
  echo "$INFO Unit testler çalıştırılıyor (RUN_TESTS_ON_START=true)..."
  if python -m pytest tests/ -q --tb=short 2>&1; then
    echo "  $OK Tüm unit testler geçti"
  else
    echo "  $WARN Bazı unit testler başarısız — servis başlatılıyor ama log incelenmeli"
  fi
fi

# ── 6. Başlat ────────────────────────────────────────────────────
echo ""
echo "$INFO Uvicorn başlatılıyor (port 8010)..."
echo "=================================================="
exec python -m uvicorn backend.main:app \
    --host 0.0.0.0 \
    --port 8010 \
    "$@"
