#!/bin/sh
# ── Bridge container başlangıç scripti ──────────────────────────────────────
# API'nin hazır olmasını bekler, sonra Node.js Bridge'i başlatır.
set -e

OK="[✓]"
WARN="[⚠]"
ERR="[✗]"
INFO="[→]"

echo ""
echo "=================================================="
echo "  personal-agent Bridge — başlatılıyor"
echo "=================================================="

# ── 1. Veri dizinleri ─────────────────────────────────────────────
echo ""
echo "$INFO Veri dizinleri kontrol ediliyor..."
for dir in \
    /app/data/projects \
    /app/data/claude_sessions \
    /app/data/conv_history \
    /app/outputs/logs; do
  if [ ! -d "$dir" ]; then
    mkdir -p "$dir"
    echo "  $OK Oluşturuldu: $dir"
  fi
done
echo "  $OK Dizinler hazır"

# ── 2. CLAUDE.md ve GUARDRAILS.md kontrolü ───────────────────────
echo ""
echo "$INFO Kritik dosyalar kontrol ediliyor..."
for f in /app/CLAUDE.md /app/GUARDRAILS.md; do
  if [ -f "$f" ]; then
    echo "  $OK $f mevcut"
  else
    echo "  $WARN $f bulunamadı — volume mount eksik olabilir"
    echo "    Bridge çalışır ama Claude Code context'i kısıtlı olur"
  fi
done

# ── 3. Node syntax kontrolü (+ LLM auto-fix) ─────────────────────
echo ""
echo "$INFO Node.js syntax kontrolü..."
SERVER_JS="/app/scripts/claude-code-bridge/server.js"

NODE_ERROR=$(node --check "$SERVER_JS" 2>&1)
NODE_STATUS=$?

if [ "$NODE_STATUS" -eq 0 ]; then
  echo "  $OK Node syntax OK"
else
  echo "  $ERR Node syntax hatası:"
  echo "$NODE_ERROR" | sed 's/^/    /'

  if [ -n "$ANTHROPIC_API_KEY" ]; then
    echo ""
    echo "  $INFO ANTHROPIC_API_KEY mevcut — LLM ile düzeltme deneniyor..."

    # llm_fix.py Python gerektiriyor; bridge image'ında Python yok.
    # Anthropic API'yi curl ile çağır, jq ile yanıtı ayıkla.
    if command -v python3 > /dev/null 2>&1; then
      FIXER="python3"
    elif command -v python > /dev/null 2>&1; then
      FIXER="python"
    else
      FIXER=""
    fi

    if [ -n "$FIXER" ]; then
      if $FIXER /docker/llm_fix.py \
            --error "$NODE_ERROR" \
            --file "$SERVER_JS" \
            --apply 2>&1; then
        echo ""
        echo "  $INFO Düzeltme uygulandı — syntax tekrar kontrol ediliyor..."
        if node --check "$SERVER_JS" 2>&1; then
          echo "  $OK Node syntax OK (LLM düzeltmesi sonrası)"
        else
          echo "  $ERR LLM düzeltmesi işe yaramadı — manuel inceleme gerekli"
          exit 1
        fi
      else
        echo "  $ERR Otomatik düzeltme uygulanamadı (bkz. yukarıdaki öneri)"
        echo "  $INFO Düzelttikten sonra: docker compose build && docker compose up"
        exit 1
      fi
    else
      # Python yok — curl ile doğrudan API'ye sor, sadece öneri ver
      echo "  $INFO Python bulunamadı; Anthropic API'ye curl ile bağlanılıyor..."
      JS_CONTENT=$(cat "$SERVER_JS")
      RESPONSE=$(curl -sf https://api.anthropic.com/v1/messages \
        -H "x-api-key: $ANTHROPIC_API_KEY" \
        -H "anthropic-version: 2023-06-01" \
        -H "content-type: application/json" \
        -d "{
          \"model\": \"claude-haiku-4-5-20251001\",
          \"max_tokens\": 256,
          \"messages\": [{
            \"role\": \"user\",
            \"content\": \"JavaScript syntax hatası: $NODE_ERROR\\nDosya: server.js\\nTek cümlede nedenini açıkla.\"
          }]
        }" 2>/dev/null || echo "API erişilemedi")
      echo "  $INFO LLM açıklaması: $RESPONSE"
      echo "  $ERR Container başlatılamıyor — kaynak kodu düzelt ve rebuild yap"
      exit 1
    fi
  else
    echo "  $INFO (ANTHROPIC_API_KEY tanımlı olsa LLM ile düzeltme denenirdi)"
    echo "  $ERR Container başlatılamıyor — kaynak kodu incele"
    exit 1
  fi
fi

# ── 4. API hazır mı? (retry loop) ────────────────────────────────
API_URL="${FASTAPI_URL:-http://99-api:8010}"
echo ""
echo "$INFO API bekleniyor: $API_URL/health"

MAX_RETRIES=30   # 30 × 2s = 60s maksimum bekleme
RETRY=0
until curl -sf "${API_URL}/health" > /dev/null 2>&1; do
  RETRY=$((RETRY + 1))
  if [ "$RETRY" -ge "$MAX_RETRIES" ]; then
    echo "  $WARN API 60s içinde yanıt vermedi — Bridge yine de başlatılıyor"
    echo "    API başladığında Bridge otomatik bağlanır"
    break
  fi
  printf "  Bekleniyor... (%d/%d)\r" "$RETRY" "$MAX_RETRIES"
  sleep 2
done

if curl -sf "${API_URL}/health" > /dev/null 2>&1; then
  echo "  $OK API hazır ($API_URL)"
fi

# ── 5. Başlat ────────────────────────────────────────────────────
echo ""
echo "$INFO Node.js Bridge başlatılıyor (port 8013)..."
echo "=================================================="
cd /app/scripts/claude-code-bridge
exec node server.js "$@"
