#!/bin/sh
# ── Bridge container başlangıç scripti ──────────────────────────────────────
# API'nin hazır olmasını bekler, sonra Node.js Bridge'i başlatır.
set -e

OK="[✓]"
WARN="[⚠]"
ERR="[✗]"
INFO="[→]"

# ── 0. root ise: bind-mount'ları chown'la, sonra claude'a düş ────────────────
# Cross-platform fix: Docker Desktop (Windows/Mac) bind-mount'larda host UID'sini
# container'a yansıtmaz; ./data/* dizinleri claude (UID 1001) için yazılamaz olur.
# Çözüm: root olarak chown'la, sonra gosu ile claude:claude'a exec et.
# Claude CLI --permission-mode bypassPermissions root ile çalışmaz — drop zorunlu.
if [ "$(id -u)" = "0" ]; then
  echo ""
  echo "$INFO Root olarak başladı — bind-mount sahiplikleri ayarlanıyor..."
  # Sadece bridge'in yazdığı dizinleri chown'la (API /app/data altına ortak yazmaz).
  # /home/claude — image içinde zaten claude:claude; bind-mount overlay'de yeniden gerekli.
  # |true: Windows/Mac single-file mount'larda chown sessizce başarısız olabilir.
  chown -R claude:claude \
    /app/data/projects \
    /app/data/media \
    /app/data/claude_sessions \
    /app/data/conv_history \
    /home/claude 2>/dev/null || true
  # .claude.json bind-mount: dosya host'ta ise chown no-op, ama yazılabilir kalır.
  if [ -f /home/claude/.claude.json ]; then
    chown claude:claude /home/claude/.claude.json 2>/dev/null || true
  fi
  echo "  $OK Sahiplikler ayarlandı (chown -> claude:claude)"
  echo "  $INFO claude user'a düşülüyor (gosu)..."
  exec gosu claude:claude "$0" "$@"
fi

echo ""
echo "=================================================="
echo "  personal-agent Bridge — başlatılıyor (UID $(id -u))"
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

# ── 1b. Yazma izinleri kontrolü ──────────────────────────────────
# Root prelude chown'ladıktan sonra burası geçmeli. Geçmezse mount yapısı
# beklenmedik (read-only mount, full-disk vs.) — fail-fast ile erken uyar.
echo ""
echo "$INFO Yazma izinleri kontrol ediliyor..."
WRITE_OK=true
for dir in /app/data/claude_sessions /app/data/conv_history /home/claude/.claude; do
  if ! touch "$dir/.writetest" 2>/dev/null; then
    echo "  $ERR $dir yazılabilir değil — beklenmedik durum (root chown başarısız oldu?)"
    echo "  $INFO Container'ı root olarak başlatın veya mount'ları kontrol edin:"
    echo "    docker compose down && docker compose up -d --build"
    WRITE_OK=false
  else
    rm -f "$dir/.writetest"
  fi
done
# .claude.json ayrıca kontrol et — dizin RW olsa bile dosya :ro mount edilmiş olabilir
if [ -f /home/claude/.claude.json ] && [ ! -w /home/claude/.claude.json ]; then
  echo "  $ERR /home/claude/.claude.json yazılabilir değil (:ro mount kaldırılmış olmalı)"
  echo "  $INFO docker-compose.yml'de :ro flag'ini kaldırın ve container'ı yeniden başlatın"
  WRITE_OK=false
elif [ -f /home/claude/.claude.json ]; then
  echo "  $OK /home/claude/.claude.json yazılabilir"
fi
if [ "$WRITE_OK" = "false" ]; then
  echo "  $ERR Bridge yazma izinleri eksik — Claude CLI session yazamayacak, sorgular askıda kalacak"
  exit 1
fi
echo "  $OK Tüm yazma izinleri tamam"

# ── 2. Claude CLI kimlik doğrulaması ─────────────────────────────
echo ""
echo "$INFO Claude kimlik bilgileri kontrol ediliyor..."
CLAUDE_JSON="/home/claude/.claude.json"
CRED_FILE="/home/claude/.claude/.credentials.json"

if [ -n "$ANTHROPIC_API_KEY" ]; then
  echo "  $OK ANTHROPIC_API_KEY mevcut — OAuth gerekmez"
else
  if [ ! -f "$CLAUDE_JSON" ] || [ ! -r "$CLAUDE_JSON" ]; then
    echo "  $ERR $CLAUDE_JSON mount edilmemiş veya okunamıyor."
    echo "  $INFO Host'ta 'claude auth login' çalıştır ve container'ı yeniden başlat."
    exit 1
  fi
  echo "  $OK .claude.json mevcut ve okunabilir"

  if [ ! -f "$CRED_FILE" ] || [ ! -r "$CRED_FILE" ]; then
    echo "  $ERR $CRED_FILE mount edilmemiş veya okunamıyor."
    echo "  $INFO Host'ta 'claude auth login' çalıştır ve container'ı yeniden başlat."
    exit 1
  fi
  echo "  $OK .credentials.json mevcut ve okunabilir"
  echo "  $OK Claude OAuth kimlik bilgileri hazır"
fi

# ── 3. CLAUDE.md ve GUARDRAILS.md kontrolü ───────────────────────
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

# ── 4. API hazır mı? (kısa retry) ───────────────────────────────
# Docker compose bağımlılığı: 99-api depends_on: 99-bridge: healthy
# Bu yüzden API henüz başlamamış olabilir; bekleme çok kısa tutulur.
# Bridge başladıktan sonra API ayağa kalkar; bağlantı sorunları server.js'de handle edilir.
API_URL="${FASTAPI_URL:-http://99-api:8010}"
echo ""
echo "$INFO API kontrol ediliyor: $API_URL/health"

MAX_RETRIES=5   # 5 × 2s = 10s maksimum bekleme (API daha sonra başlayacak)
RETRY=0
until curl -sf "${API_URL}/health" > /dev/null 2>&1; do
  RETRY=$((RETRY + 1))
  if [ "$RETRY" -ge "$MAX_RETRIES" ]; then
    echo "  $WARN API henüz hazır değil — Bridge başlatılıyor (API sonra bağlanır)"
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
